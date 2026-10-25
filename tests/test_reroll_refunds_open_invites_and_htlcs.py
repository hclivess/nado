"""At a reroll an OPEN invite CARRIES to the new chain, claimable by its link, and an OPEN HTLC lock goes back to whoever
funded it (tools/alphanet6_carryforward.carried_invites / open_escrow_refunds, genesis.py).

Invites used to be refunded with the HTLCs. Operator rule 2026-10-20: everything is carried, never refunded in place of
a carry — and an invite can be: it is an L1-only escrow with an expiry. Its id is blake2b(CHAIN_ID, key), CHAIN_ID
changes at the reroll and the record keeps only the id, so the carry recovers the link key (from the old chain's
invite_lock transactions, or the previous carry file) and genesis re-derives the id under the new CHAIN_ID — exactly
the id the wallet derives from the link. An HTLC still refunds: its expiry races a lock on a foreign chain that keeps
running while this one is rerolled, so a carried lock would hand the secret-holder extra wall-clock time (the operator
decides whether that changes; doc/stwo/g5-carry.md 2c).

Pins:
  1. every open invite carries with its recovered key, sender, amount and the blocks it had left; claimed and refunded
     invites move nothing; an expired one carries refundable (expiry 1), never claimable;
  2. a key carried by the previous reroll is found in its file (an invite crossing two rerolls);
  3. an open invite whose key is nowhere REFUSES (it could not be claimed on the new chain);
  4. an open HTLC goes back to its sender, debited from its escrow; claimed ones move nothing; build() refunds HTLCs
     only, and checks INVITE_ESCROW against the open invites before writing;
  5. L1 genesis seeds each carried invite under invite_id_of(key) on the new chain, open, with its rebased expiry,
     and refuses when INVITE_ESCROW does not hold exactly their coins.

Run: python3 tests/test_reroll_refunds_open_invites_and_htlcs.py
"""
import os, sys, json, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_carry_escrow_")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P

KEY1, KEY2, KEY3 = "a1" * 656, "b2" * 656, "c3" * 656        # ML-DSA-44 public keys are 1312 bytes (hex 2624)

if os.environ.get("NADO_TEST_PHASE") == "l1":
    # 5) L1 genesis in a child process with its own HOME (make_genesis writes the L1 database)
    import logging
    held = int(os.environ["NADO_TEST_ESCROW"])
    os.makedirs(os.path.join(H, "nado", "private"), exist_ok=True)
    json.dump([{"address": P.INVITE_ESCROW, "balance": held, "bonded": 0}],
              open(os.path.join(H, "nado", "private", "genesis_alloc.dat"), "w"))
    json.dump([], open(os.path.join(H, "nado", "private", "genesis_open.dat"), "w"))
    from genesis import make_folders, make_genesis
    from ops import kv_ops
    from ops.transaction_ops import invite_id_of
    make_folders()
    try:
        make_genesis(address=P.GENESIS_ADDRESS, balance=P.TREASURY_GENESIS, ip="127.0.0.1", port=9173,
                     timestamp=P.GENESIS_TIMESTAMP, logger=logging.getLogger("t"))
    except SystemExit as e:
        print("REFUSED", e)
        sys.exit(3)
    print("INVITE", json.dumps(kv_ops.invite_get(invite_id_of(KEY1))))
    sys.exit(0)

import subprocess
from tools.alphanet6_carryforward import carried_invites, open_escrow_refunds
from ops.transaction_ops import invite_id_of

import _harness
_report = _harness.Report()
check = _report.check

TIP = 10_000
i1, i2, i3, i4 = invite_id_of(KEY1), invite_id_of(KEY2), "f" * 64, invite_id_of(KEY3)
inv = {i1: ["alice", 500, TIP + 900, "open", ""], i2: ["alice", 70, TIP - 5, "open", ""],
       i3: ["bob", 999, TIP + 50, "claimed", "carol"], i4: ["bob", 5, TIP + 50, "refunded", ""]}
txs = [{"recipient": "invite_lock", "sender": "alice", "amount": 500, "data": {"key": KEY1, "expiry": TIP + 900}}]
got = carried_invites(inv, txs, [[KEY2, "alice", 70, 3]], TIP)
check("1. every open invite carries: key, sender, amount, the blocks it had left",
      [KEY1, "alice", 500, 900] in got, got)
check("1. an expired invite carries refundable, never claimable (expiry 1)", [KEY2, "alice", 70, 1] in got, got)
check("1. claimed and refunded invites move nothing", len(got) == 2, got)
check("2. a key carried by the previous reroll is found in its file", any(r[0] == KEY2 for r in got), got)
try:
    carried_invites({i1: ["alice", 500, TIP + 900, "open", ""]}, [], [], TIP)
    refused = None
except SystemExit as e:
    refused = str(e)
check("3. an open invite whose key is nowhere refuses", refused is not None and i1[:16] in refused, refused)

htl = {"h1": {"sender": "dave", "claimant": "erin", "amount": 300, "status": "open"},
       "h2": {"sender": "dave", "claimant": "erin", "amount": 40, "status": "claimed"}}
refunds, out = open_escrow_refunds({}, htl)
check("4. an open HTLC goes back to its sender, debited from its escrow; claimed ones move nothing",
      refunds == {"dave": 300} and out == {"invite": 0, "htlc": 300}, (refunds, out))
src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
b = src[src.index("def build():"):src.index("\ndef ", src.index("def build():") + 1)]
check("4. build() refunds HTLCs only, and checks INVITE_ESCROW against the open invites",
      "open_escrow_refunds({}, kv_ops.htlc_all())" in b and "invite escrow holds" in b
      and b.index("invite escrow holds") < b.index("return out"))

# 5) genesis seeds the carried invites under this chain's ids
carry_file = os.path.join(H, "genesis_carry.dat")
json.dump({"generation": P.CHAIN_GENERATION, "invites": [[KEY1, "alice", 500, 900]]}, open(carry_file, "w"))


def l1(escrow):
    env = dict(os.environ, NADO_TEST_PHASE="l1", NADO_TEST_ESCROW=str(escrow), HOME=tempfile.mkdtemp(dir=H),
               NADO_GENESIS_CARRY=carry_file)
    env["NADO_EXEC_STATE"] = os.path.join(env["HOME"], "exec_state.json")
    env["NADO_EXEC_DA"] = os.path.join(env["HOME"], "exec_da")
    env["NADO_EXEC_GENESIS"] = os.path.join(env["HOME"], "none.json")
    return subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True, timeout=600)


ok = l1(500)
line = next((x for x in ok.stdout.splitlines() if x.startswith("INVITE ")), "")
check("5. genesis seeds the carried invite under invite_id_of(key) on this chain, open, with its rebased expiry",
      ok.returncode == 0 and json.loads(line[7:] or "null") == ["alice", 500, 900, "open", ""],
      (ok.returncode, ok.stdout[-300:], ok.stderr[-400:]))
bad = l1(499)
check("5. ...and refuses when INVITE_ESCROW does not hold exactly their coins",
      bad.returncode == 3 and "INVITE_ESCROW" in bad.stdout, (bad.returncode, bad.stdout[-300:]))
print("ALL PASS — open invites carry, open HTLCs go home" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
