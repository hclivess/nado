"""Out-of-process settle-proof verification (2026-09-07).

The KV-half STARK verification (execnode.stark.settlement_sparse.verify_settlement_sparse) is a pure function
of the proof and the protocol tree depth, but it runs 70-780 s of Python-orchestrated hashing — measured on
the relay: every API request and the block loop crawled for the whole time because the verifier held the
GIL. The parent hands the proof to a fresh interpreter over a pipe and blocks on the result with the GIL
RELEASED; the verdict is bit-identical (same code, same inputs). The child imports ONLY the verifier
package: never nado/memserver/kv_ops (importing the node opens the live LMDB — see memory
never-import-node-modules-against-live-db). Any child failure falls back to in-process verification and is
NEVER cached as a verdict.

Protocol: stdin = codec.pack({"proof": ..., "depth": int}); stdout = codec.pack([ok, reason, kv_pre, kv_post]).
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
    req = codec.unpack(sys.stdin.buffer.read())
    res = SS.verify_settlement_sparse(req["proof"], depth=req["depth"])
    payload = codec.pack(list(res))
    view = memoryview(payload)
    while view:
        n = os.write(verdict_fd, view)
        view = view[n:]
    os.close(verdict_fd)


def verify_sparse_out_of_process(proof, depth):
    """(ok, reason, kv_pre_hex, kv_post_hex) from a child interpreter, or None when the child could not
    produce a verdict (caller falls back in-process; a None is never a verdict)."""
    from ops import codec
    env = dict(os.environ)
    env.pop("NADO_PROOF_VERIFY_INPROC", None)
    try:
        p = subprocess.Popen([sys.executable, "-c", "from ops.proof_child import main; main()"],
                             cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env)
        out, err = p.communicate(codec.pack({"proof": proof, "depth": int(depth)}), timeout=VERIFY_TIMEOUT_S)
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
