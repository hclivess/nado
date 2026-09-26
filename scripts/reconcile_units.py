#!/usr/bin/env python3
"""Make this machine run every job deploy/units/manifest.json declares for its roles (doc/jobs.md).

WHY (2026-09-26): jobs got lost. The DEX price sampler was started by hand with `&` and died at a reboot unnoticed;
the timers needed someone to remember an install script, which then overwrote an earlier migration and put two jobs
back to running as root; the watchtower unit existed only in /etc on one box. One manifest now declares every job and
this reconciler makes the machine match it after every self-update, with nobody running anything.

THE ROOT BOUNDARY (install.sh: "root never executes anything from the account-owned checkout"). This file is the
SOURCE; root runs only the COPY install.sh places at /usr/local/sbin/nado-reconcile-units (root-owned, refreshed only
by re-running install.sh as root). Everything it reads from the checkout — the manifest and the unit files — is owned
by the node's account and treated as UNTRUSTED DATA. A unit is installed only if:
  * its name is nado-<name>.service / nado-<name>.timer (no system unit can be overwritten);
  * a service runs as the node's own account (User= from the installed nado.service), with no root-escalating Exec
    prefix (+ ! !!), no User=/Group= override to anything else, and no PermissionsStartOnly;
  * a timer triggers only its own validated service (Unit= absent or equal to it).
So the account can at most schedule its own code as itself — which it can already run. Units install.sh generates
per machine (nado, nado-exec, forum, the restart bridge) are never written from here. It installs and enables; it
never disables, stops or removes. Template tokens @USER@ @GROUP@ @HOME@ @REPO@ come from the installed nado.service.
Stdlib only (system python3). Result -> /run/nado/jobs-reconcile.json for /status.

Run: sudo /usr/local/sbin/nado-reconcile-units [--dry-run]     (install.sh installs it and the bridge calls it)
"""
import json
import os
import re
import subprocess
import sys
import time

DEST = "/etc/systemd/system"
RESULT = "/run/nado/jobs-reconcile.json"
NAME_RE = re.compile(r"^nado-[a-z0-9][a-z0-9-]*\.(service|timer)$")
BAD_EXEC = re.compile(r"^\s*Exec[A-Za-z]*\s*=\s*[-@:]*[+!]", re.M)


def node_identity():
    """(user, group, home, repo) from the installed nado.service — root-owned, so trusted."""
    text = open(os.path.join(DEST, "nado.service")).read()
    get = lambda k: (re.search(r"^%s=(.*)$" % k, text, re.M) or [None, None])[1]
    user, repo = get("User"), get("WorkingDirectory")
    home = (re.search(r"^Environment=HOME=(.*)$", text, re.M) or [None, None])[1]
    if not (user and user != "root" and repo and home):
        raise SystemExit("nado.service runs as root or lacks WorkingDirectory/HOME — this reconciler serves "
                         "account installs only (install.sh --service with a service account)")
    return user, get("Group") or user, home, os.path.realpath(repo)


def validate(name, text, user, group, services):
    if not NAME_RE.match(name):
        return f"{name}: only nado-*.service / nado-*.timer are managed"
    if name.endswith(".service"):
        if re.findall(r"^User=(.*)$", text, re.M) != [user]:
            return f"{name}: must run as User={user}, exactly once"
        if any(g != group for g in re.findall(r"^Group=(.*)$", text, re.M)):
            return f"{name}: Group= other than {group}"
        if BAD_EXEC.search(text) or re.search(r"^PermissionsStartOnly\s*=", text, re.M):
            return f"{name}: an Exec line escalates (+, !, !!) or PermissionsStartOnly is set"
    else:
        target = (re.findall(r"^Unit=(.*)$", text, re.M) or [name[:-6] + ".service"])
        if len(target) != 1 or target[0] != name[:-6] + ".service" or target[0] not in services:
            return f"{name}: a timer may only trigger its own validated service"
    return None


def main(dry=False):
    user, group, home, repo = node_identity()
    units_dir = os.path.join(repo, "deploy", "units")
    with open(os.path.join(units_dir, "manifest.json")) as f:
        manifest = json.load(f)
    roles = {"node"}
    if os.path.exists(os.path.join(DEST, "nado-exec.service")):
        roles.add("exec")
    try:
        with open(os.path.join(repo, "private", "config.json")) as f:
            if json.load(f).get("operator_jobs", False) is True:
                roles.add("operator")
    except Exception:
        pass
    todo = [j for j in manifest.get("jobs", []) if j.get("source") == "repo" and j.get("role") in roles]
    rendered, errors = {}, []
    for job in todo:
        for name in job.get("files", []):
            if not NAME_RE.match(name):
                errors.append(f"{name}: only nado-*.service / nado-*.timer are managed")
                continue
            text = open(os.path.join(units_dir, name)).read()
            for tok, val in (("@USER@", user), ("@GROUP@", group), ("@HOME@", home), ("@REPO@", repo)):
                text = text.replace(tok, val)
            rendered[name] = text
    services = {n for n, t in rendered.items() if n.endswith(".service") and not validate(n, t, user, group, set())}
    ok = {}
    for name, text in rendered.items():
        err = validate(name, text, user, group, services)
        if err:
            errors.append(err)
        else:
            ok[name] = text
    written = []
    for name, text in ok.items():
        dst = os.path.join(DEST, name)
        try:
            old = open(dst).read()
        except OSError:
            old = None
        if old != text:
            written.append(name)
            if not dry:
                tmp = dst + ".tmp"
                with open(tmp, "w") as f:
                    f.write(text)
                os.chmod(tmp, 0o644)
                os.replace(tmp, dst)
    if written and not dry:
        subprocess.run(["systemctl", "daemon-reload"], timeout=60)
    enabled = []
    for job in todo:
        unit = job["unit"]
        if unit not in ok:
            continue
        run = lambda *a: subprocess.run(["systemctl", *a], capture_output=True, text=True, timeout=60)
        if run("is-enabled", unit).stdout.strip() != "enabled" or run("is-active", unit).stdout.strip() != "active":
            enabled.append(unit)
            if not dry:
                r = run("enable", "--now", unit)
                if r.returncode != 0:
                    errors.append(f"{unit}: {r.stderr.strip()[:200]}")
    out = {"at": int(time.time()), "roles": sorted(roles), "written": written, "enabled": enabled,
           "errors": errors, "dry_run": dry}
    print(json.dumps(out))
    if not dry:
        try:
            with open(RESULT, "w") as f:
                json.dump(out, f)
            os.chmod(RESULT, 0o644)
        except OSError:
            pass
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(dry="--dry-run" in sys.argv))
