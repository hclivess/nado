"""THE SHADOW SETTLEMENT RUN (G8's two weeks of off-chain proofs, doc/stwo-migration.md 9.5): prove every span the exec node
settled, verify each proof as L1 would, and check the verified root against the exec node's own. READ-ONLY: it reads the
exec node's settled snapshots (exec_state.json~stash~<ns>~<cursor>.json) and GETs blocks and accrual inputs from L1; it
writes only --out. Nothing it finds changes anything on the chain.

    python3 tools/settle_b2_shadow.py (--bin <vm_settle> | --build) --out <results.jsonl> [--state-dir DIR] [--l1 URL]
                                      [--last N]

One JSON line per span (execnode/settle_b2.shadow_span): "proven" (the verifier accepted, on the exec node's root),
"chain_eq" (G8: the Chain L1 derives from its own state, GET /settle_chain_inputs, equals the exec node's for every read
the span could make, the carry and the accruals; "chain_diff" names any difference, which is a bug in ops/settle_chain.py),
"unprovable" (with the reason the witness cannot carry it yet), "refused" or "mismatch" (a bug: the prover's own bundle
must verify and land on the exec node's root), "error", "skipped" (a stash not at its own cursor and root, from before
execnode._stash_payload). Spans already in --out are skipped, so reruns continue.

`vm_settle` is native/stwo_settle's prover binary (nightly + the `prover` feature). `--build` builds it with the
account's own nightly (tests/_stwo_settle_build.py: a copy of the crate in ~/.cache, never in the checkout); the operator
job deploy/units/nado-settle-shadow.service runs it that way every 30 minutes.
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")    # BEFORE the reassignment below: the toolchain and the build cache live there
# NEVER the live node's state (CLAUDE.md rule 4): HOME and both exec paths are assigned before any node import, so the
# imports below open throwaway directories; the snapshots are read by path, as files.
_TMP = tempfile.mkdtemp(prefix="nado-settle-shadow-")
os.environ["HOME"] = _TMP
os.environ["NADO_EXEC_STATE"] = os.path.join(_TMP, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_TMP, "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import urllib.request  # noqa: E402


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def stashes(state_dir, ns):
    """{cursor: path} of the exec node's settled snapshots"""
    out = {}
    for p in glob.glob(os.path.join(state_dir, f"exec_state.json~stash~{ns}~*.json")):
        m = re.search(r"~(\d+)\.json$", p)
        if m:
            out[int(m.group(1))] = p
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bin", help="native/stwo_settle's vm_settle binary")
    ap.add_argument("--build", action="store_true", help="build vm_settle with this account's nightly toolchain")
    ap.add_argument("--out", required=True, help="results, JSON lines (appended)")
    ap.add_argument("--state-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="where the exec node keeps exec_state.json and its stashes (default: this checkout)")
    ap.add_argument("--l1", default="http://127.0.0.1:9173", help="an L1 node's HTTP base")
    ap.add_argument("--ns", default="default")
    ap.add_argument("--last", type=int, default=0, help="only the last N spans (0: all)")
    a = ap.parse_args()
    if not a.bin:
        if not a.build:
            ap.error("give --bin or --build")
        from tests._stwo_settle_build import build
        a.bin, log = build(_REAL_HOME, "vm_settle")
        if a.bin is None:
            sys.exit(f"cannot build vm_settle: {log or 'no nightly toolchain for this account'}")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    from execnode import settle_b2 as S
    from execnode.state import ExecState

    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            try:
                r = json.loads(line)
                done.add((r["from"], r["to"]))
            except (ValueError, KeyError):
                pass
    st = stashes(a.state_dir, a.ns)
    cursors = sorted(st)
    pairs = list(zip(cursors, cursors[1:]))
    if a.last:
        pairs = pairs[-a.last:]

    accrual_cache = {}

    def accrual(E):
        if E not in accrual_cache:
            inflow = get_json(f"{a.l1}/get_dividend_inflow?epoch={E}")["inflow"]
            weights = get_json(f"{a.l1}/get_open_weights?epoch={E}")["weights"]
            accrual_cache[E] = (int(inflow), dict(weights))
        return accrual_cache[E]

    for c0, c1 in pairs:
        if (c0, c1) in done:
            continue
        pre_doc, post_doc = json.load(open(st[c0])), json.load(open(st[c1]))
        pre = ExecState.snapshot_view(pre_doc["state"])
        post_cur = int(post_doc["state"].get("cursor", -1))
        if int(pre.cursor) != c0 or pre.state_root() != pre_doc["state_root"] or post_cur != c1:
            # a stash serialized after the live state moved on (fixed 2026-10-27, execnode._stash_payload): its label
            # is not its state, so it is no span's pre- or post-state; reported, not proven
            rec = {"from": c0, "to": c1, "result": "skipped",
                   "reason": f"a stash is not at its own (cursor, root): pre cursor {pre.cursor}, post cursor {post_cur}"}
        else:
            blocks = [get_json(f"{a.l1}/get_block?number={h}") for h in range(c0 + 1, c1 + 1)]
            # L1'S OWN CHAIN INPUTS (G8): what the settle branch would judge this span with, so `chain_eq` checks the
            # derivation (ops/settle_chain.py) against the exec node's bookkeeping on every live span. A node without the
            # endpoint (older code) leaves chain_eq None: not checked, never "equal".
            try:
                l1_inputs = get_json(f"{a.l1}/settle_chain_inputs?sc={c0}&cursor={c1}")
                if not isinstance(l1_inputs, dict) or "hashes" not in l1_inputs:
                    l1_inputs = None
            except Exception:
                l1_inputs = None
            rec = S.shadow_span(pre, blocks, post_doc["state_root"], accrual, a.bin, l1_inputs=l1_inputs)
        with open(a.out, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        print(json.dumps(rec, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
