"""Rolling back an enrolment restores the chip's open-enrolment marker to the enrolment it named before, not to
nothing (ops/account_ops.apply_tpm_enrol_tx revert, ops/kv_ops.tpm_enrol_open_revert_put).

The marker "tpmek:<endorsement identity>" lives in devbind, so it is CONSENSUS STATE and in the L1 root. A tpm_enrol
overwrites it with the new enrolment's id, and the revert used to DELETE it — right only for a chip's first enrolment.
Once a chip's earlier attempt had expired, opening a second one and rolling that block back left the chip with no
marker while every node that never applied the block still named the first attempt: a state-root split from an
ordinary one-block reorg (audit 2026-09-25, HIGH). Superseding an expired record under the SAME id left the marker on
the superseding id instead of the one it replaced. Rollback must be the exact inverse, so the marker's prior value is
journaled like the record's (node-local devbind_revert) and restored from the journal.

Pins, with real kv tables under a throwaway HOME and only the native certificate kernel stubbed: every block of
  open A for chip X -> challenge A -> (A expires) open B for X -> challenge B -> (B expires) re-open A's key,
  superseding A's expired record -> two enrolments of X in ONE block
is rolled back last-to-first, and after each rollback every row of devbind (records + marker) AND of devbind_revert
(the journals) is byte-identical to what it was before that block applied; and each rolled-back block re-applies.

Run: python3 tests/test_tpm_enrol_revert_exact.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-enrol-revert-exact-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(os.environ["HOME"], "nado", "index"), exist_ok=True)

from ops import kv_ops, tpm_enrol as te, attest_native, account_ops
import protocol as _P
# THE IMMEDIATE-DRAW REGIME, pinned at gen 27's gate: this test's heights (100..) and its challenge one block after the
# open are the pre-TPM_DRAW_UNGRINDABLE_HEIGHT shape. On gen 28 the gate is 1 and challengers are drawn two epochs after
# the open; that path's exact rollback (the materialising challenge) is pinned by tests/test_tpm_draw_is_not_grindable.py.
# The marker journal this test is about is the same code in both regimes (gen-28 rehearsal).
_P.TPM_DRAW_UNGRINDABLE_HEIGHT = max(_P.TPM_DRAW_UNGRINDABLE_HEIGHT, 28500)
from ops.account_ops import apply_tpm_enrol_tx
from protocol import CHAIN_ID

kv_ops.init_env()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# --- stubs: only what needs the native certificate kernel or the chain's block history. Every kv write is real. ---
def _identity(cert: bytes) -> str:
    return hashlib.sha256(cert).hexdigest()


attest_native.verify_ek = lambda chain, now, roots=None, height=None: {"ok": True, "identity": _identity(chain[0])}
attest_native.ek_public_der = lambda der: b"\x30\x03" + der[:3]
A, B, C = "a" * 46, "b" * 46, "c" * 46
account_ops._tpm_anchor_time = lambda h: 0
account_ops._tpm_challengers_for = lambda eid, h: [A, B, C]

CERT_X = b"chip-X-endorsement-certificate"
X = _identity(CERT_X)
AIK1, AIK2, AIK3, AIK4 = (b"\x00\x01aik-" + bytes([i]) for i in (1, 2, 3, 4))
OWNER = "o" * 46
W = te.enrol_window(1)


def eid_of(aik):
    return te.enrol_id(CHAIN_ID, X, te.aik_name_hex(aik))


def enrol(aik):
    return {"recipient": "tpm_enrol", "sender": OWNER, "data": {"ek": [CERT_X.hex()], "pub": aik.hex()}}


def challenge(sender, eid):
    return {"recipient": "tpm_challenge", "sender": sender, "data": {"id": eid, "blob": "aa", "enc": "bb"}}


def dump():
    """Every row of the enrolment's consensus table (records + per-chip marker) and of its rollback journal."""
    out = {}

    def _do(txn):
        for name in ("devbind", "devbind_revert"):
            with txn.cursor(db=kv_ops._dbs()[name]) as cur:
                for k, v in cur:
                    out[(name, bytes(k))] = bytes(v)
    kv_ops._read(_do)
    return out


def block(h, txs, revert=False):
    with kv_ops.write_txn():
        for tx in (reversed(txs) if revert else txs):     # rollback_one_block reverts last-to-first
            apply_tpm_enrol_tx(tx, h, revert=revert)


def diff(a, b):
    keys = sorted(set(a) | set(b))
    return [(n, k, a.get((n, k)), b.get((n, k))) for (n, k) in keys if a.get((n, k)) != b.get((n, k))]


EA, EB, E3, E4 = eid_of(AIK1), eid_of(AIK2), eid_of(AIK3), eid_of(AIK4)
H1 = 100
H2 = H1 + W          # A expired: B may open for the same chip
H3 = H2 + W          # B expired: the chip re-publishes AIK1, superseding A's expired record under the SAME id
H4 = H3 + W          # the re-opened A expired: two enrolments of X land in ONE block (each validates vs the parent)
blocks = [
    ("open A for chip X", H1, [enrol(AIK1)]),
    ("challenge A", H1 + 1, [challenge(A, EA)]),
    ("open B for chip X after A expired", H2, [enrol(AIK2)]),
    ("challenge B", H2 + 1, [challenge(B, EB)]),
    ("re-open A's key, superseding A's expired record", H3, [enrol(AIK1)]),
    ("two enrolments of chip X in one block", H4, [enrol(AIK3), enrol(AIK4)]),
]

before = []
for name, h, txs in blocks:
    before.append(dump())
    block(h, txs)
    check(f"applies: {name}", True)

check("forward: after the last block the marker names the last enrolment applied",
      kv_ops.tpm_enrol_open_for_ek(X) == E4, kv_ops.tpm_enrol_open_for_ek(X))

expected_marker_before = [None, EA, EA, EB, EB, EA]
for i in range(len(blocks) - 1, -1, -1):
    name, h, txs = blocks[i]
    after = dump()
    block(h, txs, revert=True)
    d = diff(before[i], dump())
    check(f"rollback of '{name}' leaves devbind + devbind_revert byte-identical to before it", not d, d)
    check(f"rollback of '{name}' restores the chip's marker to {expected_marker_before[i]}",
          kv_ops.tpm_enrol_open_for_ek(X) == expected_marker_before[i], kv_ops.tpm_enrol_open_for_ek(X))
    # the block re-applies onto the restored state and lands exactly where it did, then roll it back again
    block(h, txs)
    d2 = diff(after, dump())
    check(f"'{name}' re-applies after the rollback to the identical state", not d2, d2)
    block(h, txs, revert=True)

check("everything rolled back: no enrolment row, no marker, no journal left", dump() == before[0], diff(before[0], dump()))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
