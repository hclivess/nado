"""
Detached winner block-signature unit checks (#15, security step 5).

The signature is OPTIONAL and OUTSIDE the hash preimage: absent -> valid (win-offline); present ->
the signer must BE the winner (pubkey hashes to block_creator) and the ML-DSA sig must verify; a
forged/tampered or wrong-signer sig is rejected; and signing never changes the block hash.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_bsig_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signatures import generate_keydict
from ops.block_ops import construct_block, sign_block, verify_block_signature

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

kd = generate_keydict()
winner = kd["address"]

def mkblock(creator):
    """Construct a minimal block (number 5, empty tx pool) with the given creator."""
    return construct_block(block_timestamp=10, block_number=5, parent_hash="0" * 64, creator=creator,
                           transaction_pool=[],
                           block_reward=1_000_000_000, parent_cumulative_weight=4, block_weight=1)


def t1():
    """Prove a block with no block_signature is valid (the signature is optional: win-offline)."""
    b = mkblock(winner)
    assert "block_signature" not in b
    assert verify_block_signature(b) is True, "an unsigned block must be valid (win-offline)"
check("absent signature -> valid (optional, win-offline)", t1)


def t2():
    """Prove the winner's own signature verifies and, being detached/off-preimage, leaves the block hash unchanged."""
    b = mkblock(winner)
    h_before = b["block_hash"]
    sign_block(b, kd["private_key"], kd["public_key"])
    assert "block_signature" in b
    assert b["block_hash"] == h_before, "signing must NOT change the block hash (detached, off-preimage)"
    assert verify_block_signature(b) is True, "the winner's own valid signature must verify"
check("winner signs -> verifies, and block hash is unchanged", t2)


def t3():
    """Prove a tampered (bit-flipped) signature is rejected."""
    b = mkblock(winner)
    sign_block(b, kd["private_key"], kd["public_key"])
    sig = b["block_signature"]["signature"]
    b["block_signature"]["signature"] = sig[:-4] + ("1111" if sig[-4:] != "1111" else "2222")
    assert verify_block_signature(b) is False, "a tampered signature must be rejected"
check("tampered signature -> rejected", t3)


def t4():
    """Prove a valid signature from a non-winner identity is rejected (signer must BE block_creator)."""
    other = generate_keydict()  # a different identity (address != winner)
    b = mkblock(winner)         # block_creator stays the winner, but `other` signs it
    sign_block(b, other["private_key"], other["public_key"])
    assert verify_block_signature(b) is False, "a signature by a non-winner must be rejected (proof_sender)"
check("wrong signer (not the winner) -> rejected", t4)


print(f"\n{'ALL BLOCK-SIGNATURE CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
