"""What this node is supposed to be running, and whether it is (deploy/units/manifest.json, doc/jobs.md).

WHY (2026-09-26): a job that stops must be SEEN. The DEX price sampler died at a reboot and the chart froze for two
days with nothing anywhere saying so. /status now carries `jobs` — every declared unit this machine should run, its
systemd state, and the in-node samplers' last success — and peers pass /status around (status_pool), so a dead job on
any node is visible from any other. Read-only: `systemctl show` works for the unprivileged node user; writing units is
scripts/reconcile_units.py's job, as root, never this module's.
"""
import json
import os
import subprocess
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(_HERE, "deploy", "units", "manifest.json")
RECONCILE_RESULT = "/run/nado/jobs-reconcile.json"

# In-node jobs report here: {name: {"role": which machines should run it, "since": loop start, "last_ok": unix of the
# last success, ...}} — set by the loops in nado.py. A job past STALE_S without a success is listed under `problems`.
inner = {}
STALE_S = 300
_cache = {"at": 0.0, "value": None}


def roles(config):
    r = {"node"}
    if os.path.exists("/etc/systemd/system/nado-exec.service"):
        r.add("exec")
    if (config or {}).get("operator_jobs", False) is True:       # default in the CODE: get_config merges nothing
        r.add("operator")
    return r


def _show(unit):
    props = ["LoadState", "ActiveState", "SubState", "Result", "UnitFileState"]
    if unit.endswith(".timer"):
        props.append("LastTriggerUSec")
    try:
        out = subprocess.run(["systemctl", "show", "--timestamp=unix", unit, *[f"-p{p}" for p in props]],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    last = d.get("LastTriggerUSec", "")
    return {"load": d.get("LoadState"), "state": d.get("ActiveState"), "sub": d.get("SubState"),
            "result": d.get("Result"), "enabled": d.get("UnitFileState"),
            "last": int(last.lstrip("@")) if last.startswith("@") and last.lstrip("@").isdigit() else None}


def refresh(config):
    """Recompute the report (blocking: call from a worker thread). Cheap: a handful of `systemctl show`."""
    try:
        with open(MANIFEST) as f:
            jobs = json.load(f)["jobs"]
    except Exception as e:
        _cache.update(at=time.time(), value={"error": f"manifest unreadable: {e}"})
        return
    mine = roles(config)
    units, problems = {}, []
    for job in jobs:
        if job.get("role") not in mine:
            continue
        s = _show(job["unit"])
        if s is None:
            continue
        runs = _show(job["runs"]) if job.get("runs") else None
        if s["load"] != "loaded":
            problems.append(f"{job['unit']} not installed")
        elif s["state"] != "active":
            problems.append(f"{job['unit']} {s['state']}")
        elif runs and runs.get("result") not in (None, "", "success"):
            problems.append(f"{job['runs']} last run {runs['result']}")
        units[job["unit"]] = {k: v for k, v in s.items() if v not in (None, "")}
        if runs and runs.get("result"):
            units[job["unit"]]["last_result"] = runs["result"]
    # in-node jobs: one that should succeed here and has not for STALE_S is as dead as a failed unit
    for name, v in inner.items():
        if v.get("role") in mine and time.time() - float(v.get("since", time.time())) > STALE_S \
                and time.time() - float(v.get("last_ok") or 0) > STALE_S:
            problems.append(f"{name} has not succeeded for {int(time.time() - float(v.get('last_ok') or v['since']))} s")
    try:
        with open(RECONCILE_RESULT) as f:
            rec = json.load(f)
    except Exception:
        rec = None
    _cache.update(at=time.time(), value={"roles": sorted(mine), "units": units, "inner": dict(inner),
                                          "problems": problems, "reconcile": rec})


def report():
    """The last computed report (never blocks the /status handler)."""
    return _cache["value"]
