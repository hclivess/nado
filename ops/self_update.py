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

Triggers: GET /update (remote, cascades to peers), the 15-min in-node timer (nado.py), a PEER HINT —
any peer's status advertising a commit this node does not recognize kicks an immediate check, so one
updated node ripples the whole mesh current within seconds (see peer_hint below) — or the CLI
(`nado_cli.py update`). Opt out with "auto_update": false in private/config.json — that also disables the
/update and /update_peer endpoints entirely (nado.py answers 403 without touching this module), so an
opted-out node cannot be triggered remotely or used as a proxy to trigger others. "auto_heal": false
additionally stops the boot-time installer self-repair (ensure_updatable diagnoses and logs, never heals).

GENESIS REROLLS are fully covered by one /update wave: a reroll commit bumps protocol.CHAIN_GENERATION, and
the post-update boot sees the bump, wipes all chain-derived data (never private/) and regenesis/resyncs
(ops/data_ops.py purge-epoch machinery). No manual purge step on any operator's box.
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

# Service-account installs (install.sh --user) run the node unprivileged, so it cannot call
# `systemctl restart` itself. The installer writes a root-owned path unit (nado-restart.path) that
# watches this flag; the updater writes the flag, root applies the delayed restart of the fixed unit
# list. Root installs keep the direct systemctl path and never need the bridge.
_RESTART_FLAG = "/run/nado/restart-request"
_RESTART_BRIDGE = "/etc/systemd/system/nado-restart.path"

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


_repo_head_cache = [0.0, None]         # (checked_at, short_hash) — git is a subprocess; health polls at 10s


def repo_head(max_age=60.0):
    """Short hash of the commit the CHECKOUT is on right now, cached for `max_age` seconds.

    The pair (repo_head, running_head) is the only way to see the state this module already names one
    comment up — "an applied-but-not-yet-restarted update moves repo HEAD" — and which nothing ever
    actually CHECKED. `update_available` compares against `latest_known()`, i.e. what a FETCH last saw on
    origin, so it says nothing about a fix committed locally: the repo can be correct, the process an hour
    stale, and /status still cheerful. That is not hypothetical — it cost 1.5 hours of frozen finality on
    2026-07-20, when a fix for a per-block exec-summary crash sat committed in the checkout while the
    process that needed it kept running the broken code."""
    now = time.time()
    if now - _repo_head_cache[0] < max_age:
        return _repo_head_cache[1]
    try:
        h = _git("rev-parse", "HEAD")[:12]
    except Exception:
        h = None
    _repo_head_cache[0], _repo_head_cache[1] = now, h
    return h


def code_is_stale():
    """True when the running process predates the checkout — i.e. a restart would change the code.
    False when either hash is unknown (a non-git deploy is a DIFFERENT defect, reported by updatability)."""
    run, repo = running_head(), repo_head()
    return bool(run and repo and run != repo)


# --- Stale-checkout restart -------------------------------------------------------------------------------
# A COMMIT THAT IS NOT RUNNING IS NOT A FIX. The updater only restarts after IT applied a fast-forward, so
# the case where the checkout is already current never restarts anything: the operator commits locally and
# pushes (which is how this fleet is developed), local HEAD already equals origin/main, /update answers
# "up_to_date", and the RUNNING PROCESSES stay on the old code indefinitely. code_is_stale() has detected
# exactly this the whole time and only ever produced a health WARNING — "RESTART to apply" — which is how a
# finality stall once survived 34 minutes past its own fix landing, and how nado-exec ran an hour past the
# row-commit fix that made records proofs 4x cheaper (the exec node is the one that matters here: it is where
# the prover lives, and it is the service an operator is least likely to restart by hand).
#
# THREE GUARDS, each for a failure this could otherwise cause:
#   • DIRTY WORKING TREE -> never restart. The repo dir is a live dev checkout on at least one box; loading a
#     half-finished edit into a money node is far worse than running one commit behind. Same rule the
#     fast-forward path already applies for the same reason.
#   • ONCE PER HEAD -> a restart that does not change the running commit (unit masked, crash loop, exec
#     fail-stopped on a stale native crate) must not re-arm forever. Record the head we acted on.
#   • SETTLE PERIOD -> require the staleness to persist across two observations, so a checkout seen
#     mid-`git merge` (index written, HEAD not yet moved) cannot trigger a restart.
_STALE_MIN_AGE = 90                     # s the checkout must stay ahead before a restart is warranted
_stale_since = [None]                   # (head, first_seen_monotonic) for the head currently observed stale
_stale_acted = [None]                   # the repo head we have already restarted for


def working_tree_dirty():
    """True when tracked files have uncommitted changes. Any error answers True — 'I could not tell' must
    behave like 'do not touch it'."""
    try:
        _git("diff", "--quiet")
        _git("diff", "--cached", "--quiet")
        return False
    except Exception:
        return True


def apply_stale_checkout(now=None):
    """Restart the services when the checkout is ahead of the running process, so a pushed fix actually runs.

    Returns a dict describing what happened; the caller logs it. Never raises — this is called from the
    health loop, and observability must not be able to take the node down."""
    try:
        run, repo = running_head(), repo_head()
        if not (run and repo) or run == repo:
            _stale_since[0] = None
            return {"status": "current", "running": run, "repo": repo}
        try:
            from config import get_config
            if get_config().get("auto_update", True) is False:
                return {"status": "disabled", "reason": "auto_update=false in config"}
        except Exception:
            pass                                    # config unreadable: fall through to the safety guards
        if _stale_acted[0] == repo:
            return {"status": "already_restarted", "repo": repo}
        if working_tree_dirty():
            return {"status": "dirty", "reason": "uncommitted changes — refusing to load a half-finished edit",
                    "running": run, "repo": repo}
        t = time.monotonic() if now is None else now
        seen = _stale_since[0]
        if not seen or seen[0] != repo:
            _stale_since[0] = (repo, t)
            return {"status": "observing", "running": run, "repo": repo}
        if t - seen[1] < _STALE_MIN_AGE:
            return {"status": "observing", "running": run, "repo": repo,
                    "for_s": round(t - seen[1], 1)}
        # _schedule_restart, not _restart_services — the latter has never existed, so this raised
        # NameError and the outer handler reported {"status": "error"} instead of restarting. The
        # self-heal was dead in a way that HID itself: _stale_acted[0] is set on the line above, so
        # after the first failure every later pass short-circuits to "already_restarted" for a restart
        # that never happened. Found by test_no_undefined_names.
        _stale_acted[0] = repo
        services = _schedule_restart()
        return {"status": "restarting", "running": run, "repo": repo, "services": services}
    except Exception as e:
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}


class GitError(RuntimeError):
    """A git command failed, carrying git's ACTUAL stderr rather than a guess about why."""


def _git(*args, timeout=15):
    """Run a git command in the repo root; returns stripped stdout, raises GitError on failure.

    stderr is CAPTURED, not discarded. It used to go to DEVNULL, so every failure reached the caller as a
    bare exception with nothing in it, and the caller had to GUESS — /update answered "could not reach
    origin (offline?)" for a node whose network was fine, which sends an operator chasing connectivity for
    something else entirely. This module exists so a node can SAY why it cannot update; throwing away the
    one sentence that says so defeated it. (Same lesson as the dead-fork probe: instrument first.)"""
    try:
        p = subprocess.run(["git", *args], cwd=_REPO_DIR, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]}: timed out after {timeout}s")
    except Exception as e:
        raise GitError(f"git {args[0]}: {type(e).__name__}: {e}")
    if p.returncode != 0:
        tail = [ln for ln in (p.stderr or "").strip().splitlines() if ln.strip()]
        raise GitError(f"git {args[0]}: exit {p.returncode}" + (f" — {tail[-1][:200]}" if tail else ""))
    return (p.stdout or "").strip()


# --- NEAR-REAL-TIME UPDATE CASCADE (peer hints) ----------------------------------------------------
#
# The periodic origin check (15 min, nado.py) only bounds how long the FIRST node lags a push. Every
# other node gets there much faster: an updated peer restarts, advertises the new commit in its status,
# and every current-code node sees it within one status pass (~1s). A commit we do not RECOGNIZE is
# therefore the freshest possible "origin moved" signal — kick an async check on it. The hint decides
# only WHEN we look at the PINNED official repo (ff-only), never WHAT we pull, so a hostile peer gets
# nothing beyond making us glance at GitHub (bounded below + by check_and_update's _MIN_INTERVAL).

_HINT_COOLDOWN = 3600                  # s per distinct advertised value — a stale or lying peer cannot loop us
_hints = {}                            # advertised short-commit -> monotonic ts of its last evaluation


def peer_hint(commit):
    """A peer's status advertised `commit` (its running_commit or its view of origin/main). If it is not
    one we recognize — not our HEAD, not the origin head we last saw, and not an ancestor already in our
    history (that is just a LAGGING peer) — start an async check_and_update. Returns True when a check
    was kicked; False for recognized/cooled-down/empty values. Never raises (runs in the peer loop)."""
    try:
        if not commit:
            return False
        c = str(commit)[:12]
        known = {k for k in (latest_known(), running_head(), repo_head()) if k}
        if any(c == k or c.startswith(k) or k.startswith(c) for k in known):
            return False
        now = time.monotonic()
        if now - _hints.get(c, -_HINT_COOLDOWN) < _HINT_COOLDOWN:
            return False
        if len(_hints) > 64:           # bounded: rotating fake values cannot grow this forever
            _hints.clear()
        _hints[c] = now
        try:
            # an OLD commit is recognizable LOCALLY: it exists in our history as an ancestor of HEAD, so
            # origin has not moved and no fetch is needed. (Unknown-to-git or diverged -> fall through.)
            _git("merge-base", "--is-ancestor", c, "HEAD")
            return False
        except Exception:
            pass
        threading.Thread(target=check_and_update, args=("peer-hint",), daemon=True,
                         name="peer_hint_update").start()
        return True
    except Exception:
        return False


def _blocked(why):
    return {"status": "blocked", "reason": why}


# --- SELF-DIAGNOSIS: can this node update itself AT ALL? -------------------------------------------
#
# The refusal reasons in check_and_update ("not a git checkout", "no 'origin' remote", …) were only ever
# discovered when somebody called /update. A node laid down by an old installer could therefore sit
# un-updatable for months with nobody aware — which is exactly what happened: 21 of 25 peers answer
# `running_commit: null` because they have no git metadata, so the fleet cannot even be VERSION-CHECKED,
# let alone updated. Consensus changes ship strictly with no backward compatibility, so an un-updatable
# node does not merely go stale: it eventually diverges and forks the network.
#
# So the node now diagnoses its OWN updatability at startup, advertises the verdict in /status, and can
# repair itself. The repair is deliberately "run scripts/install.sh" and nothing else: the installer is the
# single supported fixer (it converts a git-less directory into a real checkout in place, and writes the
# systemd unit), so there is exactly ONE definition of a correct install and no second, drifting copy of
# that logic living here.
#
# DEFECTS ARE SPLIT BY KIND, because the response differs:
#   BLOCKING  local + permanent (no git binary, not a checkout, wrong origin, nothing to restart). The node
#             cannot ever update until a human or the installer fixes it. Healable.
#   WARNING   transient (origin unreachable). A node that was updatable yesterday and is offline today is
#             FINE — it will update when connectivity returns. Never treated as fatal, because doing so
#             would let one GitHub outage take down the entire fleet at once.

def _has_restart_capability():
    """True if at least one repo-running systemd unit exists AND this process has a way to actually invoke
    the restart: directly (root) or via the nado-restart bridge (service-account installs). Without the
    unit, /update fast-forwards the repo and the OLD process keeps running forever, which is the state
    three peers were in (repo current, running_commit stale); without restart access the failure is the
    same but QUIETER — systemctl exits non-zero into a discarded pipe — so it must count as incapable."""
    if os.geteuid() != 0 and not os.path.isfile(_RESTART_BRIDGE):
        return False
    for svc in _SERVICES:
        try:
            subprocess.run(["systemctl", "cat", f"{svc}.service"], timeout=10, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


def updatability(probe_remote=True) -> dict:
    """Diagnose whether this node can self-update. Pure inspection — never mutates anything. Returns
    {capable, blocking[], warnings[], checks{}} where `capable` is False ONLY for local permanent defects."""
    checks, blocking, warnings = {}, [], []

    try:
        subprocess.check_output(["git", "--version"], timeout=10, stderr=subprocess.DEVNULL)
        checks["git_binary"] = True
    except Exception:
        checks["git_binary"] = False
        blocking.append("git is not installed")

    if checks.get("git_binary"):
        try:
            branch = _git("rev-parse", "--abbrev-ref", "HEAD")
            checks["git_checkout"] = True
            checks["branch"] = branch
            if branch != _BRANCH:
                blocking.append(f"checkout is on '{branch}', not '{_BRANCH}'")
        except Exception:
            checks["git_checkout"] = False
            blocking.append("not a git checkout (installed by hand or by an old installer)")
        if checks.get("git_checkout"):
            try:
                url = _git("remote", "get-url", "origin")
                checks["origin"] = url
                if not _OFFICIAL_REPO_RE.search(url):
                    blocking.append(f"origin is '{url}', not the official repo")
            except Exception:
                checks["origin"] = None
                blocking.append("no 'origin' remote")

    checks["restart_capable"] = _has_restart_capability()
    checks["restart_bridge"] = os.path.isfile(_RESTART_BRIDGE)
    if not checks["restart_capable"]:
        if os.geteuid() != 0 and not checks["restart_bridge"]:
            blocking.append("running unprivileged without the nado-restart bridge — an update could apply to "
                            "the repo but never restart the process; re-run: sudo scripts/install.sh --service "
                            "--user <account>")
        else:
            blocking.append("no systemd unit — an update would apply to the repo but never restart the process")

    if probe_remote and checks.get("git_checkout") and not blocking:
        try:
            _git("ls-remote", "--exit-code", "origin", _BRANCH, timeout=30)
            checks["remote_reachable"] = True
        except Exception as e:
            checks["remote_reachable"] = False
            warnings.append(f"origin unreachable right now: {e}")

    return {"capable": not blocking, "blocking": blocking, "warnings": warnings, "checks": checks}


_heal_attempted = [False]


def heal(logger=None, force=False) -> dict:
    """Repair an un-updatable node by running THE INSTALLER — the only supported fixer. scripts/install.sh
    is idempotent, converts a git-less directory into a real checkout in place (keys and chain data are
    gitignored and untracked, so a hard reset cannot touch them), reuses the existing venv, and writes the
    systemd unit. Detached, because the installer restarts the very services this process belongs to.

    Attempted at most ONCE per process (a heal that does not take must not become a restart loop), and only
    as root — writing a systemd unit needs it."""
    if _heal_attempted[0] and not force:
        return {"status": "already_attempted"}
    script = os.path.join(_REPO_DIR, "scripts", "install.sh")
    if not os.path.isfile(script):
        return {"status": "unavailable", "reason": "scripts/install.sh is missing from this directory"}
    if os.geteuid() != 0:
        return {"status": "needs_root",
                "reason": "run: sudo scripts/install.sh --service   (writing a systemd unit needs root)"}
    _heal_attempted[0] = True
    args = ["bash", script, "--service"]
    if os.path.isfile("/etc/systemd/system/nado-exec.service"):
        args.append("--exec")                             # preserve an exec node this box already runs
    if logger:
        logger.warning(f"SELF-HEAL: running the installer to restore updatability: {' '.join(args)}")
    try:
        subprocess.Popen(args, cwd=_REPO_DIR, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "healing", "cmd": " ".join(args)}
    except Exception as e:
        return {"status": "failed", "reason": repr(e)}


def ensure_updatable(logger=None, auto_heal=True) -> dict:
    """Startup gate: diagnose, shout, and (optionally) repair. Returns the report so /status can serve it.
    The repair is skippable two ways: the auto_heal param (tests / callers that only want the diagnosis)
    and "auto_heal": false in private/config.json (the operator opt-out) — either alone disables it; the
    diagnosis itself always runs, so an opted-out broken node still shouts in the journal and /status.

    NOTE ON WHAT THIS CAN AND CANNOT FIX: a node already in the broken state cannot receive this code — it
    is un-updatable, that is the defect. So this does NOT rescue the existing stranded peers; a human runs
    the installer once for those. What it does is stop the fleet from silently rotting into that state
    again, and make the condition VISIBLE (in /status, so peers and the operator can see it) instead of
    discoverable only by calling /update."""
    try:
        report = updatability()
    except Exception as e:
        return {"capable": None, "error": repr(e)}
    if report["capable"]:
        for w in report["warnings"]:
            if logger:
                logger.warning(f"self-update: {w}")
        return report
    if logger:
        logger.error("=" * 78)
        logger.error("THIS NODE CANNOT UPDATE ITSELF — it will drift out of consensus and fork.")
        for b in report["blocking"]:
            logger.error(f"  - {b}")
        logger.error("  FIX: curl -sSfL https://raw.githubusercontent.com/hclivess/nado/main/scripts/"
                     "install.sh | sudo bash -s -- --service")
        logger.error("=" * 78)
    try:
        from config import get_config
        if get_config().get("auto_heal", True) is False:
            auto_heal = False
            report["heal"] = {"status": "disabled", "reason": "auto_heal=false in config"}
    except Exception:
        pass                                            # no config -> still heal (the default posture)
    if auto_heal:
        report["heal"] = heal(logger=logger)
        if logger:
            logger.error(f"self-heal: {report['heal']}")
    return report


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
            # --tags is REQUIRED, not cosmetic: the reported version is `git describe --tags`, so a node that
            # fast-forwards the branch without fetching tags keeps naming whatever stale tag it happens to
            # hold. The fleet then reports DIVERGENT versions (alpha.11 / alpha.12 / a bare hash) while every
            # node runs the identical commit — which reads as a broken/partial rollout and makes the version
            # column useless for spotting a genuinely un-updated node.
            _git("fetch", "--quiet", "--tags", "--force", "origin", _BRANCH, timeout=60)
        except Exception as e:
            # git's OWN words. "offline?" was a guess, and it was usually wrong — the failures this actually
            # reports are auth prompts, DNS hiccups, a stale index.lock, and genuine timeouts, which need
            # completely different fixes from each other.
            return {"status": "fetch_failed", "reason": f"git fetch failed: {e}"}

        local, remote = _git("rev-parse", "HEAD"), _git("rev-parse", f"origin/{_BRANCH}")
        _latest_remote[0] = remote[:12]
        if local == remote:
            # UP TO DATE IN GIT IS NOT THE SAME AS ABLE TO RUN. A node can sit on the right commit and still
            # be missing a REQUIRED native library, and then it silently cannot do its job: measured
            # 2026-08-06, peers on the correct HEAD lacked libgoldilocks.so and rejected every settle proof
            # with "NativeMissing: native crate 'goldilocks' is REQUIRED but its library is missing". Since
            # betanet-14 there is no Python fallback, so those nodes could never verify a proof at all.
            # The rebuild used to run ONLY on the update path, so a node that was already current never
            # built the missing library no matter how many times /update was called — which is exactly the
            # state .141 was left in after it happened to be mid-cascade during the wave that built it.
            # Building here costs nothing when everything is present (_missing_required_libs returns []).
            miss = _missing_required_libs()
            if miss:
                built = _build_crates(miss)
                return {"status": "up_to_date", "head": local[:12], "trigger": trigger, "native": built,
                        "note": "rebuilt required native libraries that were missing"}
            # ...AND A PRESENT LIBRARY IS NOT NECESSARILY A USABLE ONE. A node that fast-forwarded across a
            # commit touching native/*.rs keeps a .so that is now older than its sources; native_guard
            # refuses it and BLOCK PRODUCTION STOPS, while this function kept answering "up_to_date" because
            # in git it was. See _stale_required_libs for the live failure this repairs.
            stale = _stale_required_libs()
            if stale:
                # REFUSE ON LOCAL EDITS. A rebuild here compiles whatever is in the working tree, so on a box
                # where someone is mid-edit it would build and then RESTART INTO their unfinished work. The
                # same reason the update path refuses to fast-forward over a dirty tree; the check belongs on
                # both, because this branch never reaches that one.
                try:
                    _git("diff", "--quiet"); _git("diff", "--cached", "--quiet")
                except Exception:
                    return {"status": "up_to_date", "head": local[:12], "trigger": trigger,
                            "native_stale": stale,
                            "note": "native libraries are STALE but the working tree has uncommitted "
                                    "changes — refusing to rebuild; commit or stash, then retry"}
                before = _lib_digests(stale)
                built = _build_crates(stale)
                # VERIFY, DO NOT ASSUME. cargo can exit 0 and leave the artifact untouched, so re-ask the
                # guard: it is the only evidence that the thing which refused to load now loads, and
                # restarting while it is still stale would just fail-stop again.
                still = _stale_required_libs()
                if still:
                    return {"status": "up_to_date", "head": local[:12], "trigger": trigger, "native": built,
                            "native_stale": still,
                            "note": "rebuild did not clear the staleness — this node needs cargo and a "
                                    "manual `cargo build --release` in the listed crates"}
                # RESTART ONLY IF THE LIBRARY ACTUALLY CHANGED. Staleness is an MTIME question, so a crate
                # goes stale when a manifest is merely TOUCHED — on this box native/mldsa44 read stale
                # because a thin-LTO commit rewrote Cargo.toml, while the node was serving happily on a
                # library whose BYTES were correct. Bouncing a healthy validator to install an identical
                # .so is a self-inflicted outage; the rebuild silences the guard either way.
                after = _lib_digests(stale)
                changed = [c for c in stale if before.get(c) != after.get(c)]
                if not changed:
                    return {"status": "up_to_date", "head": local[:12], "trigger": trigger, "native": built,
                            "native_rebuilt": stale, "restarting": False,
                            "note": "rebuilt STALE native libraries; bytes unchanged, so no restart"}
                restarting = _schedule_restart()
                return {"status": "up_to_date", "head": local[:12], "trigger": trigger, "native": built,
                        "restarting": restarting, "native_rebuilt": changed,
                        "note": "rebuilt STALE native libraries and restarted" if restarting else
                                "rebuilt STALE native libraries — restart the node manually"}
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

        native = _rebuild_native_if_changed(local, remote)
        restarting = _schedule_restart()
        out = {"status": "updated", "from": local[:12], "to": remote[:12], "trigger": trigger,
               "restarting": restarting,
               "note": None if restarting else "no systemd services found — restart the node manually"}
        if native:
            out["native"] = native                      # per-crate build outcome; "purged-stale" ⇒ fell back to pure-Python
        return out
    finally:
        _lock.release()


def _shared_libs(crate_path):
    """Every compiled shared library a crate's loader could pick up: target/release artifacts AND any dropped
    in the crate root (build_pq_native.sh copies libnado_mldsa44.so there)."""
    out = []
    for d in (os.path.join(crate_path, "target", "release"), crate_path):
        try:
            for fn in os.listdir(d):
                if fn.endswith((".so", ".dylib", ".dll")):
                    out.append(os.path.join(d, fn))
        except Exception:
            pass
    return out


def _missing_required_libs():
    """Crates from _CRATES that exist in the tree but have NO compiled shared library. These are the ones a
    node cannot run without (there is no Python fallback since betanet-14), so an /update should build them
    even when git is already current."""
    out = []
    for crate in _CRATES:
        path = os.path.join(_REPO_DIR, crate)
        if os.path.isdir(path) and not _shared_libs(path):
            out.append(crate)
    return out


def _stale_required_libs():
    """Crates whose .so EXISTS but was built before the Rust sources it claims to implement.

    PRESENT IS NOT THE SAME AS USABLE, and this is the gap that stopped a node dead. `_missing_required_libs`
    only notices an ABSENT library, so a node that fast-forwarded across a commit touching native/*.rs kept a
    perfectly present — and now older — .so. native_guard then refuses it, correctly and loudly, and the node
    cannot produce blocks at all:

        ERROR Failed to validate transaction during block preparation: native crate 'alghash2' library …
        is STALE — its Rust sources are newer than the built library … Rebuild it.
        WARNING Block production skipped due to: …

    Observed on a peer 2026-08-08 after commits 6af13f71 and 5f372758 (both 2026-08-04) changed
    native/alghash2. The updater reported "up_to_date" the whole time, because in GIT it was.

    Uses native_guard.is_stale so the updater and the loader agree on the definition by construction — a
    second mtime comparison here would be one more thing to drift.

    ONLY THE ARTIFACT THE LOADER RESOLVES COUNTS. The first version of this walked every .so under the crate
    and flagged the crate if ANY was stale, which on this very box flagged native/mldsa44 because of
    `_thin_test.so` and an old copy left in the crate root — neither of which anything loads. The loader
    always uses target/release/libnado_<name>.so (stark_native.py), so that is the only file worth asking
    about; a stray build artifact must never be able to trigger a rebuild and a RESTART of a healthy node.
    """
    try:
        from execnode.stark import native_guard as _ng
    except Exception:
        return []                                   # no guard ⇒ nothing refuses a stale lib ⇒ nothing to fix
    out = []
    for crate in _CRATES:
        path = os.path.join(_REPO_DIR, crate)
        if not os.path.isdir(path):
            continue
        so = os.path.join(path, "target", "release", f"libnado_{os.path.basename(crate)}.so")
        if not os.path.exists(so):
            continue                                # absent is _missing_required_libs' job, not ours
        try:
            if _ng.is_stale(so, path):
                out.append(crate)
        except Exception:
            pass
    return out


def _lib_digests(crates):
    """sha256 of each crate's loader-resolved library, for deciding whether a rebuild CHANGED anything."""
    import hashlib
    out = {}
    for crate in crates:
        so = os.path.join(_REPO_DIR, crate, "target", "release", f"libnado_{os.path.basename(crate)}.so")
        try:
            with open(so, "rb") as fh:
                out[crate] = hashlib.sha256(fh.read()).hexdigest()
        except Exception:
            out[crate] = None
    return out


def _build_crates(crates):
    """cargo build --release each named crate. Returns {crate: "built"|"build-failed"|"no-cargo"} — the same
    shape _rebuild_native_if_changed reports, so /update responses stay uniform. Never raises."""
    cargo = shutil.which("cargo") or os.path.expanduser("~/.cargo/bin/cargo")
    have_cargo = bool(shutil.which("cargo")) or os.access(cargo, os.X_OK)
    report = {}
    for crate in crates:
        path = os.path.join(_REPO_DIR, crate)
        if not have_cargo:
            report[crate] = "no-cargo"
            continue
        try:
            r = subprocess.run([cargo, "build", "--release"], cwd=path, timeout=600,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report[crate] = "built" if r.returncode == 0 else "build-failed"
        except Exception:
            report[crate] = "build-failed"
    return report


def _has_shared_lib(crate_path):
    """True if this crate already has a compiled shared library. Used to tell "unchanged, already built"
    (skip) apart from "unchanged, NEVER built" (must build) — see _rebuild_native_if_changed."""
    return bool(_shared_libs(crate_path))


def _purge_shared_libs(crate_path):
    """Delete a crate's compiled shared libs so its loader sees an ABSENT (not STALE) artifact and takes the
    pure-Python path. Returns True if anything was removed."""
    removed = False
    for p in _shared_libs(crate_path):
        try:
            os.remove(p); removed = True
        except Exception:
            pass
    return removed


def _rebuild_native_if_changed(old, new):
    """Rebuild the Rust accelerator crates whose sources changed in this update, BEFORE the restart, so the
    node never runs the new Python against a STALE binary.

    Correctness hinges on one fact: a STALE .so is NOT the same as an ABSENT one. A stale one is loaded and
    TRUSTED, so e.g. an old 8-round alghash2 .so against new 54-round Python silently diverges. Therefore a
    crate whose source changed but that we CANNOT rebuild (no cargo, or the build fails) has its stale .so
    DELETED — purging is still the right call, because a wrong answer is worse than no answer.

    WHAT PURGING NO LONGER BUYS YOU, and this paragraph is the correction: it used to force "the pure-Python
    fallback (slower, but bit-identical and consensus-safe)". Since BETANET-14 there is no Python fallback.
    execnode/stark/native_guard.require() raises NativeMissing for an ABSENT library exactly as loudly as for
    a stale one ("There is no Python fallback: since betanet-14 the Rust kernel is the only production
    implementation"), unless NADO_ALLOW_ABSENT_NATIVE is set. So on a box without cargo, a crate whose sources
    changed ends with a purged .so and an exec node that REFUSES TO START — not a slow one.

    That failure is silent from the outside: L1 keeps producing blocks and /status stays 200 while
    nado-exec restart-loops, and the only user-visible symptom is the wallet reporting "exec node
    unreachable". It cost this fleet two days once already. An update wave that reports
    "no-cargo-stale-purged" for any crate means that box needs cargo and a rebuild before its exec layer
    comes back; treat it as an outage, not a degradation.

    A crate with no prior .so and no cargo is reported "pure-python" for historical reasons — that name is
    now only accurate for crates nothing mandatory loads.
    (mldsa44 additionally self-guards via a startup interop self-test, and every STARK loader now runs the same
    known-answer self-test at load, so a stale binary is rejected even outside this path — belt and suspenders.)

    Returns {crate: "built" | "no-cargo-stale-purged" | "build-failed-purged" | "pure-python"} for the /update
    response, so an operator (and the update wave) can SEE that a box fell back. Never raises — this runs on a
    live money node right before the restart."""
    report = {}
    try:
        changed = _git("diff", "--name-only", old, new, timeout=30)
    except Exception:
        changed = None                                   # diff unavailable → be conservative, treat all as touched
    # service-account installs get a per-user rustup under $HOME/.cargo which is NOT on systemd's PATH
    cargo = shutil.which("cargo") or os.path.expanduser("~/.cargo/bin/cargo")
    have_cargo = bool(shutil.which("cargo")) or os.access(cargo, os.X_OK)
    for crate in _CRATES:
      try:
        path = os.path.join(_REPO_DIR, crate)
        if not os.path.isdir(path):
            continue
        touched = changed is None or re.search(rf"^{re.escape(crate)}/.*\.(rs|toml|lock)$", changed, re.M)
        # MISSING IS NOT THE SAME AS UNCHANGED. "sources unchanged → its .so is still valid" only holds if a
        # .so was ever built here. A box that has NEVER built a crate has unchanged sources forever, so this
        # loop skipped it on every update and the library never appeared.
        #
        # That is not hypothetical. Measured 2026-08-06: all three peers were missing libgoldilocks.so, so
        # every proof-carrying settle they were offered was rejected outright —
        #     "Settle proof invalid: segment 0: epoch proof invalid: malformed proof: NativeMissing:
        #      native crate 'goldilocks' is REQUIRED but its library is missing"
        # — and since there is no Python fallback since betanet-14, NO settle proof could EVER have been
        # verified anywhere on this fleet, at any size, through DA or inline. It is the deepest reason no
        # proof has ever landed on betanet-15, underneath every transport problem.
        if not touched and _has_shared_lib(path):
            continue                                     # unchanged AND already built → its .so is still valid
        ok = False
        if have_cargo:
            try:
                r = subprocess.run([cargo, "build", "--release"], cwd=path, timeout=600,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ok = (r.returncode == 0)
            except Exception:
                ok = False
        if ok:
            report[crate] = "built"
        elif _purge_shared_libs(path):
            report[crate] = "no-cargo-stale-purged" if not have_cargo else "build-failed-purged"
        else:
            report[crate] = "pure-python"                # no cargo / build failed, but no stale .so existed anyway
      except Exception:
        continue                                         # one crate's trouble never aborts the others (or the update)
    return report


def _schedule_restart():
    """Restart the node services DETACHED and DELAYED so this process can still flush its HTTP response
    (and forward the update wave to peers) before systemd tears it down. Returns the service list, or []
    when there is nothing systemd-managed to restart (manual runs: new code applies on next start).

    Unprivileged (service-account) installs cannot call systemctl restart; they signal the root-owned
    nado-restart.path bridge by writing the flag file instead — the bridge sleeps, then restarts the
    fixed unit list, so the delayed/detached semantics are identical."""
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
    if os.geteuid() != 0 and os.path.isfile(_RESTART_BRIDGE):
        try:
            with open(_RESTART_FLAG, "w") as fh:
                fh.write(str(int(time.time())))
            return services
        except Exception:
            pass                                         # bridge present but flag unwritable — try systemctl anyway
    cmd = ["systemctl", "restart", *services]
    try:
        subprocess.run(["systemd-run", f"--on-active={_RESTART_DELAY}", "--collect", *cmd],
                       timeout=10, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:                                    # no systemd-run: detached shell sleep fallback
        subprocess.Popen(["/bin/sh", "-c", f"sleep {_RESTART_DELAY} && {' '.join(cmd)}"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return services
