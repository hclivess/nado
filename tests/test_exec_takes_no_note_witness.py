"""The exec node routes nothing that takes a spending key or a note witness (security review 2026-09-23, Z7).

/exec/prove_transfer, /exec/prove_transfer2 and /exec/prove_call were delegated provers: the wallet POSTed its
nullifier key and note opening so a server could prove for it. The wallet proves on-device (interface.js
proveTransfer2, WASM), the routes were unrouted in 3eb01c74, and the handlers were deleted in the 2026-09-30
dead-code pass. This pins both halves: no handler of that shape comes back, and no route under /exec/prove_ is
registered — a private key is never sent anywhere (CLAUDE.md rule 8).

Reads the SOURCE only: importing execnode.execnode opens exec state relative to the working directory."""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    src = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
    tree = ast.parse(src)
    handlers = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    check("no delegated-prover handler survives",
          not ({"h_prove_transfer", "h_prove_transfer2", "h_prove_call"} & handlers),
          sorted({"h_prove_transfer", "h_prove_transfer2", "h_prove_call"} & handlers))
    routes = re.findall(r'web\.(?:get|post)\("(/[^"]+)"', src)
    check("the route table was found", len(routes) > 10, routes)
    check("no /exec/prove_* route is registered", not [r for r in routes if r.startswith("/exec/prove")],
          [r for r in routes if r.startswith("/exec/prove")])
    # a handler reading the witness fields a join-split prover needs is the shape that must not come back
    witness = [n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
               and re.search(r'w\["nsk"\]|body\["nsk"\]|\["nsk"\]', ast.get_source_segment(src, n) or "")]
    check("no handler reads a nullifier key from a request", not witness, witness)
    check("the verify-only route stays", "/exec/verify_call" in routes)


if __name__ == "__main__":
    main()
    if _fails:
        print(f"{len(_fails)} FAILED: {_fails}")
        sys.exit(1)
    print("ALL PASS")
