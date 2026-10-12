"""The push host builds the Stwo verifier before it restarts into the commit that makes it required.

REVIEW 2026-10-12 (pre-push, stwo-on), reproduced here and MEASURED on the push host. The node a push is made FROM never
fast-forwards (its checkout already moved), so it reaches new code only through ops/self_update.apply_stale_checkout.
On main that path builds the OPTIONAL crates first (4084c337) — native/stwo_js was one. stwo-on moves native/stwo_js to
_CRATES (required) and empties _OPTIONAL_CRATES, and apply_stale_checkout still builds only optional crates ("Required
crates are left as before on this path"), so from stwo-on onward a stale-checkout restart never builds a MISSING
verifier. Nothing else does automatically either: loops/message_loop rebuilds only STALE required libraries, and
_missing_required_libs runs only when someone calls /update on this host.

MEASURED 2026-10-12 15:5x on the push host (GET /status, native): every required crate "ok" and native/stwo_js
"missing" — the node restarted onto 1d2ca48c at 13:50:57 from 9cfd117e, i.e. from code older than 4084c337, so the
optional build never ran. The gate comment in protocol.py says the height was "chosen ... with every node reporting
native/stwo_js ok"; the relay is not. A node without the library refuses every relayed spend (/stwo/relay_info "no Stwo
verifier") and its exec layer STALLS at the first block that carries a Stwo spend (execnode._apply_block).

The property: a stale-checkout restart into a tree whose required crate has no library builds that crate first.
Run: python3 tests/test_the_push_host_builds_the_stwo_verifier_before_it_restarts_into_the_gate.py
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import self_update as SU  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


check("setup: native/stwo_js is a REQUIRED crate on this tree", "native/stwo_js" in SU._CRATES, SU._CRATES)

# a synthetic repo: every crate directory exists, every required library is built EXCEPT native/stwo_js
repo = _tempfile.mkdtemp(prefix="nado-test-repo-")
for crate in SU._CRATES:
    os.makedirs(os.path.join(repo, crate), exist_ok=True)
    if crate != "native/stwo_js":
        lib = SU._loader_lib(crate).replace(SU._REPO_DIR, repo, 1)
        os.makedirs(os.path.dirname(lib), exist_ok=True)
        open(lib, "wb").close()
SU._REPO_DIR = repo
check("setup: the synthetic node is missing exactly the Stwo verifier", SU._missing_required_libs() == ["native/stwo_js"],
      SU._missing_required_libs())

events = []
SU.running_head = lambda: "a" * 40
SU.repo_head = lambda: "b" * 40
SU.working_tree_dirty = lambda: False
SU._git = lambda *a, **k: "protocol.py\nops/self_update.py\n"      # the push: no native/ source changed
SU._schedule_restart = lambda: (events.append(("restart",)) or ["nado", "nado-exec"])
SU._build_crates = lambda crates: (events.append(("build", tuple(crates))) or {c: "built" for c in crates})
_real_which = shutil.which
shutil.which = lambda name, *a, **k: "/usr/bin/cargo" if name == "cargo" else _real_which(name, *a, **k)
SU._stale_since[0] = None
SU._stale_acted[0] = None

first = SU.apply_stale_checkout(now=1000.0)
out = SU.apply_stale_checkout(now=1000.0 + SU._STALE_MIN_AGE + 1)
check("setup: the stale checkout is restarted into", out.get("status") == "restarting", out)
built = [c for e in events if e[0] == "build" for c in e[1]]
order = [e[0] for e in events]
check("the stale-checkout restart builds the missing required Stwo verifier BEFORE it restarts",
      "native/stwo_js" in built and order.index("build") < order.index("restart") if "build" in order else False,
      f"events {events}; apply_stale_checkout -> {out}")

shutil.which = _real_which
shutil.rmtree(repo, ignore_errors=True)
print("ALL PASS — the push host builds the Stwo verifier before it restarts into the gate" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
