"""
END-TO-END settle-prove benchmark across FRI blowups — the measurement doc/fri-parameters.md §4 was
missing.

`tools/bench_fri_blowup.py` proves a ONE-COLUMN toy trace (x' = x^2 + 7). It sizes the FRI term in
isolation and nothing else: no LogUp, no periodic columns, no sparse projection, no recursion fold, and a
trace 1/100th the width of the real exec AIR. Its ratios (2.35x prove, 0.30x verify, 0.36x size at blowup
8) therefore say what happens to FRI, NOT what happens to a settle proof — and extrapolating the size
ratio onto the real ~97 MiB proof is not a measurement.

This script proves a REAL span with the REAL prover entry point the exec node uses:

    SS.prove_settlement_sparse(pre_contracts, calls, cursor, rec_hex, beacons, block_hashes,
                               pre_bridge, depth=EXEC_TREE_DEPTH)

with `pre_contracts` read from an actual settle STASH written by the live node
(`exec_state.json~stash~<ns>~<cursor>.json` — the exact pre-state the real prover would have used) and
`calls` rebuilt from the real on-chain DA calldata via `calls_commit.block_calls`, exactly as
`execnode._build_settlement_proof` does. Every proof produced is then VERIFIED with
`verify_settlement_sparse` at the protocol depth — an unverified proof is not a benchmark.

WHAT IT REPORTS, and why the breakdown is the point: total prove seconds are split into the sparse half
(`sparse_projection` + `SparseStore.root`, which scale with the state tree and are INDIFFERENT to the FRI
blowup) and everything else. The blowup multiplier only applies to the second term, so the breakdown is
what turns "2.35x on the FRI term" into a defensible statement about the settle path.

    HOME=<throwaway> PYTHONPATH=. python3 tools/bench_settle_fri.py \
        --stash /path/to/exec_state.json~stash~default~16920.json --to 16950

HOME must be a throwaway directory: importing execnode pulls in modules that open the node's LMDB, and
doing that against the live chain wedges it. The script never writes to the live data directory; it only
reads the stash file you point it at, over HTTP from the node's read-only block endpoint.

Native kernels are REQUIRED (do not set NADO_ALLOW_PYTHON_KERNELS): the whole question is what a real
prove costs, and the Python fallback is ~146x off on the fold's inner loop.
"""
import argparse
import json
import os
import resource
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# fri_blowup, num_queries — the rows doc/fri-parameters.md §2 puts on the table. k scales the LDE domain,
# so fri_blowup == 2 * k; queries follow the soundness table at roughly constant provable bits.
CONFIGS = ((1, 320), (2, 192), (4, 96))


def peak_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def fetch_block(node, n):
    with urllib.request.urlopen(f"{node}/get_block_number?number={n}", timeout=15) as r:
        return json.load(r)


def load_span(stash_path, node, ns, to_height):
    """(pre_contracts, pre_bridge, calls, cursor, rec_hex, beacons, bhashes) for a real settle span.

    Mirrors execnode._build_settlement_proof steps 2 and 4: pre-state from the stash at the justified
    cursor, calls rebuilt per block from on-chain DA calldata over (stash_cursor, to_height]."""
    from execnode.stark import calls_commit as CC, storage_tree as SST
    from execnode.stark import field as _F
    from execnode.state import ExecState

    snap = json.loads(open(stash_path).read())
    sc = int(snap["cursor"])
    st = snap.get("state") or {}
    pre_contracts = st.get("contracts") or {}
    pre_bridge = st.get("bridge")
    # rec_hex is the records-half root AT the justified cursor — the proof pins it (this span must not
    # move records, which is what the caller checks by picking a span that does not cross a boundary).
    rec_hex = SST.digest_hex(ExecState.records_root_from_snapshot(st))
    beacons = {int(e): int(v) % _F.P for e, v in (st.get("beacons") or {}).items()}
    bhashes = {int(h): int(v) % _F.P for h, v in (st.get("block_hashes") or {}).items()}

    calls = []
    for h in range(sc + 1, to_height + 1):
        blk = fetch_block(node, h)
        if not blk or not blk.get("block_hash"):
            raise SystemExit(f"block {h} missing from {node}")
        calls += CC.block_calls(blk, ns)
    return pre_contracts, pre_bridge, calls, to_height, rec_hex, beacons, bhashes, sc


class PhaseTimer:
    """Attribute prove seconds to the FRI-indifferent sparse half vs everything else.

    sparse_projection and SparseStore.root are driven by the state tree, not by the FRI blowup, so their
    cost is CONSTANT across the configs below. Isolating them is what makes the blowup multiplier on the
    real settle path computable rather than assumed."""

    def __init__(self):
        self.sparse = 0.0
        self._orig = {}

    def __enter__(self):
        from execnode.stark import settlement_sparse as SS, storage_tree as STT
        self._orig["proj"] = SS.sparse_projection
        self._orig["root"] = STT.SparseStore.root

        def _proj(*a, _o=self._orig["proj"], **kw):
            t = time.perf_counter()
            try:
                return _o(*a, **kw)
            finally:
                self.sparse += time.perf_counter() - t

        def _root(inner, *a, _o=self._orig["root"], **kw):
            t = time.perf_counter()
            try:
                return _o(inner, *a, **kw)
            finally:
                self.sparse += time.perf_counter() - t

        SS.sparse_projection = _proj
        STT.SparseStore.root = _root
        return self

    def __exit__(self, *e):
        from execnode.stark import settlement_sparse as SS, storage_tree as STT
        SS.sparse_projection = self._orig["proj"]
        STT.SparseStore.root = self._orig["root"]
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stash", required=True, help="exec_state.json~stash~<ns>~<cursor>.json (the pre-state)")
    ap.add_argument("--to", type=int, required=True, help="span end height (the settle cursor to prove)")
    ap.add_argument("--ns", default="default")
    ap.add_argument("--node", default="http://127.0.0.1:9173")
    ap.add_argument("--out", default=None, help="write the result rows here as JSON")
    ap.add_argument("--k", type=int, default=None,
                    help="run ONE config (k=1,2,4 -> fri_blowup 2,4,8) and print one JSON row. The driver "
                         "uses this to give each config a FRESH PROCESS; see _drive().")
    args = ap.parse_args()

    # PROCESS ISOLATION IS NOT OPTIONAL HERE. settlement_sparse keeps two module-level caches that
    # survive between proves — _E_CACHE (empty-subtree hashes per depth) and _FOLD_CACHE (~131k Merkle
    # fold entries). The FIRST prove in a process pays to build them and every later one does not, so
    # three configs in one process measure cache warmth, not the FRI blowup. Measured that way once:
    # sparse_projection came out 50.3 s, then 0.8 s, then 0.7 s, which made blowup 8 look 8x FASTER than
    # blowup 2. It is not. Each config now runs in its own interpreter.
    if args.k is None:
        return _drive(args)

    if os.path.realpath(os.environ.get("HOME", "")) in ("/root", "/srv/nado-home"):
        raise SystemExit("refusing to run with HOME pointing at the live node — set a throwaway HOME")

    from execnode.stark import settlement_sparse as SS, stark, fri
    from protocol import EXEC_TREE_DEPTH

    pre, bridge, calls, cur, rec_hex, beacons, bhashes, sc = load_span(
        args.stash, args.node, args.ns, args.to)
    print(f"span {sc} -> {cur} ({cur - sc} blocks), {len(calls)} exec calls, "
          f"{len(pre)} contracts, depth={EXEC_TREE_DEPTH}")
    if not calls:
        print("WARNING: the span carries NO exec calls. The trace is minimal, so the FRI term is "
              "atypically small and the blowup multiplier below will be UNDERSTATED. Pick a busier span.")

    orig_blowup, orig_fri_blowup, orig_fri_verify = stark._blowup, fri.FRI_BLOWUP, fri.verify
    rows = []
    for k, queries in [c for c in CONFIGS if c[0] == args.k]:
        stark._blowup = (lambda md, _k=k: orig_blowup(md) * _k)
        fri.FRI_BLOWUP = orig_fri_blowup * k
        # stark.verify passes expected_blowup as a literal, so the constant above does not reach it.
        # Shim only that argument; every other verifier check runs untouched, so verify timing is real.
        fri.verify = (lambda pr, *a, _k=k, **kw: orig_fri_verify(
            pr, *a, **{**kw, "expected_blowup": (kw.get("expected_blowup") or 2) * _k}))
        try:
            with PhaseTimer() as pt:
                t0 = time.perf_counter()
                proof = SS.prove_settlement_sparse(
                    pre, calls, cursor=cur, rec_hex=rec_hex, beacons=beacons, block_hashes=bhashes,
                    pre_bridge=bridge, depth=EXEC_TREE_DEPTH, num_queries=queries)
                t_prove = time.perf_counter() - t0
            size = len(json.dumps(proof, default=str)) / (1024 * 1024)
            t1 = time.perf_counter()
            ok, why, _pre, _post = SS.verify_settlement_sparse(
                proof, num_queries=queries, depth=EXEC_TREE_DEPTH)
            t_verify = time.perf_counter() - t1
            if not ok:
                print(f"VERIFY FAILED: {why}", file=sys.stderr)
            rows.append({"fri_blowup": 2 * k, "queries": queries, "prove_s": t_prove,
                         "sparse_s": pt.sparse, "rest_s": t_prove - pt.sparse, "verify_s": t_verify,
                         "proof_mib": size, "peak_rss_mib": peak_mib(), "ok": bool(ok),
                         "calls": len(calls), "span": cur - sc})
        except Exception as e:
            rows.append({"fri_blowup": 2 * k, "queries": queries,
                         "error": f"{type(e).__name__}: {str(e)[:160]}"})
        finally:
            stark._blowup, fri.FRI_BLOWUP, fri.verify = orig_blowup, orig_fri_blowup, orig_fri_verify
    print("ROW " + json.dumps(rows[0]))


def _drive(args):
    """Run every config in a FRESH interpreter and collate. See the cache note in main()."""
    import subprocess
    rows = []
    for k, _q in CONFIGS:
        cmd = [sys.executable, os.path.abspath(__file__), "--stash", args.stash, "--to", str(args.to),
               "--ns", args.ns, "--node", args.node, "--k", str(k)]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": os.path.dirname(
                               os.path.dirname(os.path.abspath(__file__)))})
        line = next((l for l in p.stdout.splitlines() if l.startswith("ROW ")), None)
        if not line:
            print(f"k={k} produced no row:\n{p.stdout[-600:]}\n{p.stderr[-600:]}")
            continue
        rows.append(json.loads(line[4:]))

    print(f"{'fri_blowup':>10} {'queries':>8} {'prove s':>9} {'sparse s':>9} {'non-sparse s':>13} "
          f"{'verify s':>9} {'proof MiB':>10} {'peak RSS':>9} {'ok':>4}")
    for r in rows:
        if "error" in r:
            print(f"{r['fri_blowup']:>10} {r['queries']:>8}   FAILED: {r['error']}")
            continue
        print(f"{r['fri_blowup']:>10} {r['queries']:>8} {r['prove_s']:>9.1f} {r['sparse_s']:>9.1f} "
              f"{r['rest_s']:>13.1f} {r['verify_s']:>9.1f} {r['proof_mib']:>10.2f} "
              f"{r['peak_rss_mib']:>9.0f} {'yes' if r['ok'] else 'NO':>4}")
    good = [r for r in rows if "error" not in r]
    if len(good) > 1:
        b = good[0]
        print(f"\nspan {b['span']} blocks, {b['calls']} exec calls — "
              f"relative to fri_blowup 2 / 320 queries (today), each in a fresh process:")
        for r in good[1:]:
            print(f"  blowup {r['fri_blowup']:>2} / {r['queries']:>3}q: "
                  f"prove {r['prove_s']/b['prove_s']:.2f}x   verify {r['verify_s']/b['verify_s']:.2f}x   "
                  f"proof {r['proof_mib']/b['proof_mib']:.2f}x")
        print(f"\n  the blowup-indifferent sparse half is {b['sparse_s']/b['prove_s']*100:.0f}% of today's "
              f"prove at this call load.")
        if b["calls"] == 0:
            print("  CAVEAT: zero exec calls — the exec AIR trace is minimal, so this understates both "
                  "the FRI share and the blowup multiplier. Not a substitute for a busy span.")
    if args.out and rows:
        open(args.out, "w").write(json.dumps(rows, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
