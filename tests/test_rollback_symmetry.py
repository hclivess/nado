"""
ROLLBACK MUST BE THE EXACT INVERSE OF APPLY — asserted against the REAL functions.

WHY THIS FILE EXISTS. A round-trip check already lived in test_s2b_atomic.py (t9, "atomic incorporate ->
rollback returns env BYTE-IDENTICAL") and it has passed continuously while production wedged on this exact
class of bug at least three times (h4260 meta corruption, the betanet-8 meta wedge, and the 2026-08-14
stall at h10047). The reason is in its own comments: it "mirrors loops/core_loop.incorporate_block's atomic
window" and "mirrors rollback.rollback_one_block's atomic window" — it HAND-COPIES both sequences instead
of calling them.

So it tests a replica. Every step the real incorporate_block gained since that replica was written — the
exec-summary put and its retention delete, records effects, the presence-dividend accrual, the block-index
write — is simply absent from the copy. The replica is symmetric by construction; the code it stands in for
need not be. The test cannot fail, which is worse than not existing, because it reads as coverage.

THIS file calls loops.core_loop.CoreClient.incorporate_block and rollback.rollback_one_block themselves. If
a future step adds state without an inverse, this goes red and that one does not.

WHY THE INVARIANT MATTERS AT ALL. Every node rolls back constantly — any reorg, any emergency-mode churn.
If rollback leaves residue, the node's state silently stops matching the chain it agrees with, and the next
block it tries to produce trips the (fatal, correct) state-root gate:

    STATE DIVERGENCE (L1) @block N (ours <x> vs producer <y>) — refusing to extend

The node then cannot extend and cannot roll back below its finality floor, so it wedges. Worse, the
standing repair for that wedge is a snapshot re-anchor — which is how a broken rollback quietly turns
snapshots into the routine recovery path for something a rollback should have handled, and on an ARCHIVE
node destroys the history it exists to keep.

WHAT IS COVERED: a plain transfer, a registration (recert + fidelity + the recert indexes), the block
reward and totals, an epoch-boundary block, and an empty block — the shape that actually wedged the fleet,
where the ONLY state movement is the reward and the per-height bookkeeping.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        _fails.append(name)


class L:
    def warning(self, *a): pass
    def info(self, *a): pass
    def error(self, *a): pass
    def debug(self, *a): pass


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        import genesis as _g
        _g.make_folders(); _g.create_indexers()
        from ops.key_ops import save_keys, generate_keys, keyfile_found
        if not keyfile_found():
            save_keys(generate_keys())
        from ops.key_ops import load_keys
        _kd = load_keys()
        # a REAL genesis block, so every rollback has a loadable parent — rollback_one_block reads
        # block["parent_hash"] and loads that body, which isolated synthetic blocks cannot satisfy
        _g.make_genesis(address=_kd["address"], balance=0, ip="127.0.0.1", port=9173,
                        timestamp=1786600000, logger=L())

        from ops import kv_ops
        from ops.account_ops import create_account
        from ops.data_ops import sort_list_dict
        from ops.snapshot_ops import state_fingerprint
        from protocol import TREASURY_ADDRESS, EPOCH_LENGTH
        from loops.core_loop import CoreClient
        import rollback

        log = L()

        # A real CoreClient, with only the collaborators incorporate_block reaches for stubbed. Stubbing
        # these does not weaken the test: none of them writes consensus state (they are a corroboration
        # gate, a checkpoint writer and the exec-accrual hook), and the point is to exercise the REAL
        # apply/rollback sequences rather than a paraphrase of them.
        core = CoreClient.__new__(CoreClient)
        core.logger = log
        from protocol import FINALITY_DEPTH
        class _Mem:
            """Only the fields incorporate_block reads. finalized_height mirrors the real monotonic floor
            so the finality advance (and its rollback) is exercised, not stubbed away."""
            address = "prod"
            finality_depth = FINALITY_DEPTH
            archive = True
            def __init__(self):
                self.latest_block = {"block_number": 0}
                self.finalized_height = 0
                self.ffg_finalized = 0
        core.memserver = _Mem()
        core._depth_floor_corroborated = lambda *a, **k: True
        core.maybe_checkpoint_state = lambda *a, **k: None
        core._accrual_effects = lambda *a, **k: (None, None, None)

        for name, bal in (("snd", 100_000), ("rcv", 500), ("reg", 0), ("prod", 0), (TREASURY_ADDRESS, 0)):
            create_account(name, balance=bal)

        from ops.block_ops import get_block_ends_info
        _ends = get_block_ends_info(logger=log)
        _tip = dict((_ends or {}).get("latest_block") or {})
        chain = [_tip]

        def mk(txs, reward, number=None):
            """A block that really links to the current tip — parent_hash is what rollback loads."""
            parent = chain[-1]
            n = number if number is not None else int(parent["block_number"]) + 1
            return {"block_number": n,
                    "block_hash": f"{n:064x}",
                    "parent_hash": parent["block_hash"],
                    "block_creator": "prod",
                    "block_reward": reward,
                    "block_timestamp": 1786600000 + n * 6,
                    "block_transactions": txs}

        def roundtrip(label, block):
            """fingerprint -> real apply -> real rollback -> fingerprint."""
            before_root, before_per = state_fingerprint()
            txs = sort_list_dict(block.get("block_transactions", []))
            core.memserver.latest_block = {"block_number": block["block_number"] - 1}
            CoreClient.incorporate_block(core, block, txs)
            mid_root, _ = state_fingerprint()
            if mid_root == before_root and block.get("block_reward"):
                check(f"{label}: apply actually changed state", False, "apply was a no-op")
                return
            rollback.rollback_one_block(log, block)
            after_root, after_per = state_fingerprint()
            ok = after_root == before_root
            check(f"{label}: rollback restores the exact state root", ok,
                  f"{before_root[:16]} -> {after_root[:16]}")
            if not ok:
                for k in sorted(set(before_per) | set(after_per)):
                    if before_per.get(k) != after_per.get(k):
                        print(f"        DIVERGED SUB-DB {k}: before={before_per.get(k)} after={after_per.get(k)}")

        # ---- the shape that actually wedged the fleet: an EMPTY block -------------------------------
        # h10047 on betanet-3 carried ZERO transactions. Its only state movement is the block reward and
        # the per-height bookkeeping, so an asymmetry here is invisible to any tx-shaped test.
        roundtrip("empty block", mk([], 274_600_000))

        # ---- a plain transfer ------------------------------------------------------------------------
        roundtrip("transfer", mk(
            [{"txid": "t_xfer", "sender": "snd", "recipient": "rcv", "amount": 1000, "fee": 7}], 4000))

        # ---- a registration: recert + fidelity + both recert indexes ---------------------------------
        roundtrip("registration", mk(
            [{"txid": "t_reg", "sender": "reg", "recipient": "register", "amount": 0, "fee": 0}], 4000))

        # ---- an EPOCH BOUNDARY block -----------------------------------------------------------------
        # Boundaries move state no transaction can account for (beacon anchoring, dividend accrual), which
        # is exactly where a hand-copied replica of the apply sequence stops resembling it. The chain has
        # to be BUILT to the boundary — jumping there trips the finality floor, which is itself correct.
        def advance_to(target):
            while int(chain[-1]["block_number"]) < target:
                b = mk([], 274_600_000)
                core.memserver.latest_block = {"block_number": b["block_number"] - 1}
                CoreClient.incorporate_block(core, b, [])
                core.memserver.finalized_height = max(
                    core.memserver.finalized_height, b["block_number"] - FINALITY_DEPTH)
                chain.append(b)

        advance_to(EPOCH_LENGTH - 1)
        roundtrip("epoch-boundary block", mk([], 274_600_000))

        # ---- REPEATED churn, which is what an emergency-mode storm actually does ----------------------
        # One clean round trip proves little: the wedge appears after a node applies and reverts the same
        # height repeatedly. Residue that is invisible once compounds here.
        from ops.snapshot_ops import read_state, _root_triples
        advance_to(EPOCH_LENGTH + 5)
        # BASELINE AFTER the advance. Taking it before puts the advance's own blocks inside the
        # comparison window and reports them as rollback residue — a false positive that costs more
        # than the bug would, because it points at consensus code when the harness is at fault.
        rows_before = {(n, k): v for n, k, v in _root_triples(read_state())}
        root_before_churn, per_before_churn = state_fingerprint()
        blk = mk([], 274_600_000)
        for _ in range(5):
            core.memserver.latest_block = {"block_number": blk["block_number"] - 1}
            CoreClient.incorporate_block(core, blk, [])
            rollback.rollback_one_block(log, blk)
        root_after_churn, per_after_churn = state_fingerprint()
        ok_churn = root_after_churn == root_before_churn
        check("5x apply/rollback of the same height leaves no residue", ok_churn,
              f"{root_before_churn[:16]} -> {root_after_churn[:16]}")
        if not ok_churn:
            # Name the exact ROWS, not just the sub-DB. "meta diverged" is where the previous
            # investigations stalled; the key is what identifies the missing inverse.
            rows_after = {(n, k): v for n, k, v in _root_triples(read_state())}
            for key in sorted(set(rows_before) | set(rows_after), key=lambda t: (t[0], t[1])):
                b, a = rows_before.get(key), rows_after.get(key)
                if b != a:
                    kk = key[1][:48]
                    print(f"        ROW {key[0]}/{kk!r}")
                    print(f"            before={str(b)[:70]}")
                    print(f"            after ={str(a)[:70]}")

        # ---- and the guard against this file rotting the way its predecessor did ----------------------
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tests", "test_rollback_symmetry.py")).read()
        check("this test calls the REAL apply (not a copy of it)",
              "CoreClient.incorporate_block(core" in src)
        check("...and the REAL rollback", "rollback.rollback_one_block(log" in src)

    print()
    print("ALL ROLLBACK-SYMMETRY CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
