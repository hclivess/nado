"""Peer CONTROL messages are read under a control-sized cap, not the 200 MiB body cap (audit 2026-09-25, MEDIUM).

/status, /peers, /transaction_ids and /next_block_txids are kilobytes (measured 2026-09-27: 6.5 KB, 215 B, 252 B,
307 B) but were read — and zstd-decompressed — under MAX_PEER_BODY (~200 MiB), so any peer could make every status
pass buffer that much per request. Pins: MAX_CONTROL_BODY is small and below MAX_PEER_BODY; each control reader in
compounder.py and peer_ops' status fetch caps BOTH the read and the decompression at it; and the readers that carry
real payloads (tx bodies, blocks, snapshots) keep MAX_PEER_BODY, so nothing honest is clipped.
Source is read, not imported (these modules sit next to node state).

Run: python3 tests/test_control_reads_capped.py
"""
import ast, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def funcs(path):
    src = open(os.path.join(ROOT, path)).read()
    return src, {n.name: ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src))
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


net = open(os.path.join(ROOT, "ops", "net_ops.py")).read()
m = re.search(r"^MAX_CONTROL_BODY = (\d+) << (\d+)", net, re.M)
check("MAX_CONTROL_BODY is defined as a small fixed size", bool(m) and (int(m.group(1)) << int(m.group(2))) <= 16 << 20)

_, comp = funcs("compounder.py")
for fn in ("get_list_of", "get_tx_ids_of", "get_next_block_txids_of", "get_status"):
    body = comp.get(fn, "")
    reads = re.findall(r"read_capped\(response, (\w+)\)", body)
    unpacks = re.findall(r"unpack_zstd_peer\(body(?:, cap=(\w+))?\)", body)
    check(f"{fn}: every read is capped at MAX_CONTROL_BODY", reads and all(r == "MAX_CONTROL_BODY" for r in reads), reads)
    check(f"{fn}: every decompression is capped at MAX_CONTROL_BODY", all(u == "MAX_CONTROL_BODY" for u in unpacks), unpacks)
check("post_txs_by_id (transaction BODIES) keeps MAX_PEER_BODY",
      "read_capped(response, MAX_PEER_BODY)" in comp.get("post_txs_by_id", ""))

psrc, _ = funcs(os.path.join("ops", "peer_ops.py"))
check("peer_ops' status fetch caps read and decompression at MAX_CONTROL_BODY",
      "unpack_zstd_peer(await read_capped(response, MAX_CONTROL_BODY), cap=MAX_CONTROL_BODY)" in psrc)
check("peer_ops' block fetch keeps MAX_PEER_BODY (a block may carry an inline proof)",
      "r.read(MAX_PEER_BODY)" in psrc)

print("ALL PASS — control messages are read under a control-sized cap" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
