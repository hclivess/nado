"""The mempool judges a TPM enrolment message at the first height it can land (memserver.merge_transaction).

WHY (2026-10-06, the wallet-challenger walk on a loopback testnet). tpm_challenge / tpm_commit / tpm_reveal each must
land in a LATER block than the message it answers (ops/tpm_enrol). Admission judged them at the tip, so a commit sent
while the last challenge was still the tip was refused ("the commitment must land in a later block than every
challenge") — measured: the client's first commit refused at tip 248, its retry at 249 accepted. The shipped TPM helper
(apps/nado-tpm-attest enrol.rs) treats that refusal as fatal, although the commit (min_block = tip + 8) could only ever
land after the challenge.

Pins: the ordering rule itself (a commit at the challenge's height is refused, one block later accepted — so judging at
the tip refuses what the block accepts); admission judges exactly the three enrolment messages at
max(tip + 1, min_block) and every other recipient at the tip.

Run: python3 tests/test_tpm_messages_admitted_at_landing_height.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-tpmadmit-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import tpm_enrol as te

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


H = 248
rec = {"state": te.STATE_OPEN, "owner": "o" * 50, "challengers": ["a", "b"], "h": 100,
       "blobs": [["a", "00", "00", H - 3], ["b", "00", "00", H]]}
try:
    te.apply_commit(rec, "o" * 50, "ab" * 32, H)
    at_tip = "accepted"
except AssertionError as e:
    at_tip = str(e)
check("a commit judged at the last challenge's height is refused (what judging at the tip did)", "later block" in at_tip, at_tip)
try:
    te.apply_commit(rec, "o" * 50, "ab" * 32, H + 1)
    nxt = "accepted"
except AssertionError as e:
    nxt = str(e)
check("...and accepted one block later, the earliest it can land", nxt == "accepted", nxt)

src = open(os.path.join(ROOT, "memserver.py")).read()
seg = src[src.index("_vh = self.latest_block[\"block_number\"]"):]
seg = seg[:seg.index("except Exception as e:")]
check("admission judges the three enrolment messages at max(tip + 1, min_block)",
      'if transaction.get("recipient") in ("tpm_challenge", "tpm_commit", "tpm_reveal"):' in seg
      and '_vh = max(int(_vh) + 1, int(transaction.get("min_block") or 0))' in seg and "block_height=_vh" in seg)
check("...and nothing else (every other recipient is judged at the tip)", seg.count("recipient") == 1)
print("ALL PASS — enrolment messages are judged where they can land" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
