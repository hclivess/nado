"""
Integrated node self-updater (replaces scripts/nado_autoupdate.sh + its systemd timer).

Anyone may trigger an update check (GET /update) because the caller controls only the WHEN, never the
WHAT: the node advances EXCLUSIVELY along origin/main of the OFFICIAL repo (github.com/hclivess/nado),
fast-forward only — the code that lands is exactly the code the operator already chose to trust by
running the node. A node that is current answers "up_to_date" and does nothing, so spamming the endpoint
is harmless; an actual update is followed by a clean systemd restart (SIGTERM shutdown is crash-safe).

SAFE BY DESIGN (this runs unattended on a live money node whose repo dir IS the data dir):
  • FAST-FORWARD ONLY — never a hard reset, never a merge. A diverged HEAD (local commits) or a dirty
    working tree REFUSES and leaves the node running the current code.
  • PINNED to origin/main of the official repo — a checkout on another branch, or with origin pointed at
    a fork, refuses (the operator has deliberately left the release channel; we never yank them back).
  • Touches only TRACKED files — chain DB / index / peers / private keys are gitignored runtime data.
  • Restart is DETACHED and DELAYED (systemd-run) so the HTTP response and the peer-wave forwarding get
    out before this process dies; systemd waits for the node's graceful shutdown.

Triggers: GET /update (remote, cascades to peers), the 24h in-node timer (nado.py), or the CLI
(`nado_cli.py update`). Opt out with "auto_update": false in private/config.json.
"""
import os
import re
import shutil
import subprocess
import threading
import time

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OFFICIAL_REPO_RE = re.compile(r"github\.com[:/]hclivess/nado(?:\.git)?/?$", re.I)
_BRANCH = "main"                      # the single release channel this updater will ever advance
_MIN_INTERVAL = 30                    # s between checks — spam does at most one fetch per this window
_RESTART_DELAY = 5                    # s between "updated" and the service restart (lets the wave out)
_SERVICES = ("nado", "nado-exec", "forum")   # every service that runs repo code (only installed ones restart)
_CRATES = ("native/mldsa44", "native/alghash2", "native/starkcompose", "native/starkprove", "wasm/goldilocks")

_lock = threading.Lock()
_last_check = [0.0]
_latest_remote = [None]               # origin/main head seen by the LAST fetch — /status advertises it


def latest_known():
    """The most recent origin/main commit this node has SEEN (short hash), or None before the first
    fetch. Served from cache — /status is hot and must never fetch inline; the daily timer and /update
    triggers keep it fresh."""
    return _latest_remote[0]


try:                                   # the commit THIS PROCESS runs — captured at import (process start),
    _RUNNING_HEAD = None               # because an applied-but-not-yet-restarted update moves repo HEAD
    _RUNNING_HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_REPO_DIR,
                                            stderr=subprocess.DEVNULL, text=True, timeout=10).strip()[:12]
except Exception:
    pass


def running_head():
    """Short hash of the commit this PROCESS was started from (None outside a git checkout)."""
    return _RUNNING_HEAD


def _git(*args, timeout=15):
    """Run a git command in the repo root; returns stripped stdout, raises on non-zero exit."""
    return subprocess.check_output(["git", *args], cwd=_REPO_DIR, stderr=subprocess.DEVNULL,
                                   text=True, timeout=timeout).strip()


def _blocked(why):
    return {"status": "blocked", "reason": why}


def check_and_update(trigger: str) -> dict:
    """One update check: fetch origin/main of the official repo and fast-forward onto it if it is
    strictly ahead; schedule a detached service restart when code actually changed. Every refusal is a
    normal, reported outcome — never an exception. Thread-safe (HTTP handler + daily timer)."""
    from config import get_config
    try:
        if get_config().get("auto_update", True) is False:
            return {"status": "disabled", "reason": "auto_update=false in config"}
    except Exception:
        pass                                            # no config -> still allow (dev checkouts)
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "reason": "another update check is already running"}
    try:
        now = time.time()
        if now - _last_check[0] < _MIN_INTERVAL:
            return {"status": "rate_limited", "retry_in_s": int(_MIN_INTERVAL - (now - _last_check[0]))}
        _last_check[0] = now

        try:
            branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        except Exception:
            return _blocked("not a git checkout")
        if branch != _BRANCH:
            return _blocked(f"checkout is on '{branch}', not '{_BRANCH}' — refusing to switch branches")
        try:
            url = _git("remote", "get-url", "origin")
        except Exception:
            return _blocked("no 'origin' remote")
        if not _OFFICIAL_REPO_RE.search(url):
            return _blocked(f"origin is '{url}', not the official repo — refusing to pull from it")

        try:
            _git("fetch", "--quiet", "origin", _BRANCH, timeout=60)
        except Exception:
            return {"status": "fetch_failed", "reason": "could not reach origin (offline?) — will retry later"}

        local, remote = _git("rev-parse", "HEAD"), _git("rev-parse", f"origin/{_BRANCH}")
        _latest_remote[0] = remote[:12]
        if local == remote:
            return {"status": "up_to_date", "head": local[:12], "trigger": trigger}
        try:                                            # only advance if remote is strictly AHEAD of us
            _git("merge-base", "--is-ancestor", local, remote)
        except Exception:
            return _blocked(f"local HEAD {local[:12]} diverged from origin/{_BRANCH} (local commits) — update manually")
        try:
            _git("diff", "--quiet"); _git("diff", "--cached", "--quiet")
        except Exception:
            return _blocked("working tree has uncommitted changes — refusing to touch local edits")
        try:
            _git("merge", "--ff-only", "--quiet", f"origin/{_BRANCH}", timeout=60)
        except Exception:
            return _blocked(f"fast-forward to {remote[:12]} failed — left on {local[:12]}")

        _rebuild_native_if_changed(local, remote)
        restarting = _schedule_restart()
        return {"status": "updated", "from": local[:12], "to": remote[:12], "trigger": trigger,
                "restarting": restarting,
                "note": None if restarting else "no systemd services found — restart the node manually"}
    finally:
        _lock.release()


def _rebuild_native_if_changed(old, new):
    """Rebuild the optional Rust accelerator crates when their sources changed in the update. Best-effort:
    a failed build is non-fatal (the node falls back to pure Python, still correct)."""
    try:
        if not shutil.which("cargo"):
            return
        changed = _git("diff", "--name-only", old, new, timeout=30)
        if not re.search(r"^(native|wasm)/.*\.rs$", changed, re.M):
            return
        for crate in _CRATES:
            path = os.path.join(_REPO_DIR, crate)
            if os.path.isdir(path):
                subprocess.run(["cargo", "build", "--release"], cwd=path, timeout=600,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass


def _schedule_restart():
    """Restart the node services DETACHED and DELAYED so this process can still flush its HTTP response
    (and forward the update wave to peers) before systemd tears it down. Returns the service list, or []
    when there is nothing systemd-managed to restart (manual runs: new code applies on next start)."""
    services = []
    for svc in _SERVICES:
        try:
            subprocess.run(["systemctl", "cat", f"{svc}.service"], timeout=10, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            services.append(svc)
        except Exception:
            pass
    if not services:
        return []
    cmd = ["systemctl", "restart", *services]
    try:
        subprocess.run(["systemd-run", f"--on-active={_RESTART_DELAY}", "--collect", *cmd],
                       timeout=10, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:                                    # no systemd-run: detached shell sleep fallback
        subprocess.Popen(["/bin/sh", "-c", f"sleep {_RESTART_DELAY} && {' '.join(cmd)}"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return services
