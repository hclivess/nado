"""The node runs its exec node itself while nado-exec.service is down (and hands it back when the service returns).

WHY (2026-09-27). After the update waves to 7709680c and 56af9d58, 185.100.232.5 and 185.238.249.208 were left with
nado-exec "inactive (dead), result success": nado-exec has Requires=nado.service, so restarting nado stops it, and the
fleet's root restart bridge only runs `systemctl try-restart`, which restarts RUNNING units. Every root-side fix (the bridge
in scripts/install.sh, the nado-exec-keeper unit the jobs reconciler installs) reaches a machine only when its root re-runs
install.sh, and the community operators of the fleet do not. The node process is the one thing every machine updates, and
it runs as the same account nado-exec.service does, so it can run the same program itself.

WHAT IT DOES, each pass of the node's job loop (nado.py _node_jobs_loop):
  * only on an exec machine (the install.sh unit /etc/systemd/system/nado-exec.service exists) whose unit runs as THIS
    account, and only when systemd's state is readable (unknown is never read as "down");
  * the unit ENABLED and not active -> start the unit's own ExecStart (its argv, Environment= and WorkingDirectory=, read
    from the root-owned unit file) as a child of the node, unless one is already running;
  * the unit active or starting -> stop the child, so the service takes over (the exec node's state lock makes a second
    instance exit instead of running beside the first: execnode.acquire_state_lock);
  * the unit DISABLED -> never run it: an operator turns the exec node off by disabling it.
The child lives in nado.service's cgroup, so a node restart ends it and the next pass starts it again — exactly what the
service did under Requires=. Nothing here touches consensus."""
import os
import shlex
import subprocess
import time

UNIT_PATH = "/etc/systemd/system/nado-exec.service"
UNIT = "nado-exec.service"
_child = {"proc": None, "since": None, "starts": 0, "last": None}


def _unit_config(text):
    """(argv, env, cwd, user) from the unit file text; argv None when the unit is not the exec node."""
    argv, env, cwd, user = None, {}, None, None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("ExecStart="):
            argv = shlex.split(line[len("ExecStart="):].lstrip("-@:+!"))
        elif line.startswith("Environment="):
            for part in shlex.split(line[len("Environment="):]):
                if "=" in part:
                    k, v = part.split("=", 1)
                    env[k] = v
        elif line.startswith("WorkingDirectory="):
            cwd = line.split("=", 1)[1].strip()
        elif line.startswith("User="):
            user = line.split("=", 1)[1].strip()
    # only ever the exec node itself: a python interpreter running execnode/execnode.py
    if not argv or len(argv) < 2 or not argv[1].endswith("execnode/execnode.py"):
        argv = None
    return argv, env, cwd, user


def _state():
    """(ActiveState, UnitFileState) of nado-exec, or None when systemd will not say (never read as "down")."""
    try:
        out = subprocess.run(["systemctl", "show", UNIT, "-pActiveState", "-pUnitFileState"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if not d.get("ActiveState"):
        return None
    return d.get("ActiveState"), d.get("UnitFileState")


def _alive():
    p = _child["proc"]
    return p is not None and p.poll() is None


def _stop_child(why, log):
    p = _child["proc"]
    if p is None:
        return
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=60)
        except Exception:
            p.kill()
    log(f"exec supervisor: stopped the node's own exec node ({why})")
    _child.update(proc=None, since=None)


def supervise(log=print, unit_path=UNIT_PATH, current_user=None):
    """One pass. Returns what it decided, for the job report."""
    if not os.path.exists(unit_path):
        return "not an exec machine"
    try:
        argv, env, cwd, user = _unit_config(open(unit_path).read())
    except Exception as e:
        return f"unit unreadable: {e}"
    if argv is None:
        return "the unit does not run the exec node"
    me = current_user or _whoami()
    if user != me:
        return f"the unit runs as {user!r}, not as this node's account {me!r}"
    st = _state()
    if st is None:
        return "systemd state unknown"
    active, enabled = st
    if enabled != "enabled":
        _stop_child("the operator disabled nado-exec", log)
        return "disabled by the operator"
    if active in ("active", "activating", "reloading", "deactivating"):
        if _alive():
            _stop_child("nado-exec.service is back", log)
        return "the service runs it"
    if _alive():
        return f"running it (pid {_child['proc'].pid}) while nado-exec.service is {active}"
    full_env = dict(os.environ)
    full_env.update(env)
    try:
        _child["proc"] = subprocess.Popen(argv, env=full_env, cwd=cwd or None)
    except Exception as e:
        return f"could not start it: {e}"
    _child.update(since=time.time(), starts=_child["starts"] + 1, last=time.time())
    log(f"exec supervisor: nado-exec.service is {active} but enabled — running the exec node here "
        f"(pid {_child['proc'].pid}) until the service is back")
    return f"started it (pid {_child['proc'].pid}) while nado-exec.service is {active}"


def status():
    return {"child_pid": _child["proc"].pid if _alive() else None, "starts": _child["starts"], "since": _child["since"]}


def _whoami():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name
