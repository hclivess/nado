"""Out-of-process settle-proof verification (2026-09-07).

The KV-half STARK verification (execnode.stark.settlement_sparse.verify_settlement_sparse) is a pure function
of the proof and the protocol tree depth, but it runs 70-780 s of Python-orchestrated hashing — measured on
the relay: every API request and the block loop crawled for the whole time because the verifier held the
GIL. The parent hands the proof to a fresh interpreter over a pipe and blocks on the result with the GIL
RELEASED; the verdict is bit-identical (same code, same inputs). The child imports ONLY the verifier
package: never nado/memserver/kv_ops (importing the node opens the live LMDB — see memory
never-import-node-modules-against-live-db). Any child failure falls back to in-process verification and is
NEVER cached as a verdict.

Protocol: stdin = codec.pack({"proof": ..., "depth": int, "rules": [pin_fri_domain, bind_statement]});
stdout = codec.pack([ok, reason, kv_pre, kv_post]). `rules` (2026-09-23) are the verification rules for the
block being judged (stark.rules_for_height in the parent): a fresh interpreter has no context, and an unset
context means STRICT — which below PROOF_BIND_HEIGHT would refuse every honest legacy proof.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_TIMEOUT_S = 3 * 3600


def main():
    """child entry. Imported modules print to stdout at import time (the ML-DSA backend self-test line, for
    one), which corrupted the verdict frame on the first live run — so stdout is redirected to stderr for the
    whole child and the verdict goes to the ORIGINAL stdout descriptor saved before any import."""
    verdict_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    sys.path.insert(0, REPO)
    from ops import codec
    from execnode.stark import settlement_sparse as SS
    from execnode.stark import stark as _stk
    req = codec.unpack(sys.stdin.buffer.read())
    _r = req.get("rules")
    # A WARM FOLD CACHE, CARRIED ACROSS CHILDREN (2026-09-24). Every child is a fresh interpreter, so the pre-state
    # pin in verify_bound_epoch (sparse_root over the WHOLE pre_contracts) rebuilt the depth-256 tree cold on every
    # verify. MEASURED on the live settle stash (27 contracts, 15,078 slots): 112.4 s total, 107.8 s of it the pin;
    # the same verify warm is 6.1 s. That cold rebuild is the 107-179 s "[settle-verify] KV half" every proof has
    # logged since at least Sep 14, and it is what kept peers from admitting an inline settle proof in time. The
    # storage_tree comment saying "a sparse verifier never rebuilds the tree" predates the pin and was wrong.
    # Safe for consensus by construction: the cache memoizes a PURE function and load_fold_cache validates the file
    # (fingerprint + spot-recompute), so a verdict is bit-identical cold, warm or with the file missing.
    from execnode.stark import storage_tree as _ST
    _fold_path = _fold_cache_path()
    if _fold_path:
        try:
            _ST.load_fold_cache(_fold_path, int(req["depth"]))
        except Exception:
            pass                                   # a cache problem costs the cold rebuild, never the verdict
    with _stk.with_rules(_stk.Rules(*[bool(x) for x in _r]) if _r is not None else _stk.RULES_STRICT):
        # A node-local failure (native_guard.NODE_LOCAL_ERRORS) raises out of the verifier and ends this child with a
        # non-zero status and no frame, which the parent reads as "no verdict" — never as "invalid".
        res = SS.verify_settlement_sparse(req["proof"], depth=req["depth"])
    # Saved only after an ACCEPTED proof: a refused one may carry an arbitrary pre_contracts, and letting it fill
    # the file would let anyone who can submit a settle crowd the real state's folds out of it (bounded by
    # _FOLD_CACHE_MAX either way, but there is no reason to keep a stranger's garbage).
    if _fold_path and res and res[0] is True:
        try:
            _ST.save_fold_cache(_fold_path, int(req["depth"]))
        except Exception:
            pass
    payload = codec.pack(list(res))
    view = memoryview(payload)
    while view:
        n = os.write(verdict_fd, view)
        view = view[n:]
    os.close(verdict_fd)


def _fold_cache_path():
    """Where the verify child keeps its fold cache: beside the node's data (~/nado), never beside the exec node's own
    file (a second writer would race it). None when the data dir does not exist, e.g. a bare test HOME."""
    d = os.path.join(os.path.expanduser("~"), "nado")
    return os.path.join(d, "settle_verify_folds.json") if os.path.isdir(d) else None


def verify_sparse_out_of_process(proof, depth, rules=None):
    """(ok, reason, kv_pre_hex, kv_post_hex) from a child interpreter, or None when the child could not
    produce a verdict (caller falls back in-process; a None is never a verdict)."""
    from ops import codec
    env = dict(os.environ)
    env.pop("NADO_PROOF_VERIFY_INPROC", None)
    try:
        p = subprocess.Popen([sys.executable, "-c", "from ops.proof_child import main; main()"],
                             cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env)
        from execnode.stark import stark as _stk
        _r = list(_stk.current_rules() if rules is None else rules)
        out, err = p.communicate(codec.pack({"proof": proof, "depth": int(depth), "rules": _r}),
                                 timeout=VERIFY_TIMEOUT_S)
        if p.returncode != 0 or not out:
            print(f"[settle-verify] child failed rc={p.returncode}: {err[-300:]!r} — verifying in-process", flush=True)
            return None
        res = codec.unpack(out)
        if not (isinstance(res, list) and len(res) == 4 and isinstance(res[0], bool)):
            print("[settle-verify] child returned a malformed verdict — verifying in-process", flush=True)
            return None
        return tuple(res)
    except Exception as e:
        try:
            p.kill()
        except Exception:
            pass
        print(f"[settle-verify] child error {e!r} — verifying in-process", flush=True)
        return None


if __name__ == "__main__":
    main()
