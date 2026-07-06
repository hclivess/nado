"""
Mempool three-buffer transference (ops/pool_ops.py): merge_buffer must promote EVERY due tx (not starve a
low-fee one behind an undue high-fee one), and cull_buffer must never evict a fee-exempt reserved tx.

Run: python3 tests/test_pool_buffers.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.pool_ops import merge_buffer, cull_buffer, FEE_EXEMPT_RECIPIENTS
from ops.data_ops import get_byte_size

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print("PASS  " + name)
    except Exception as e:
        fails += 1; print("FAIL  " + name + ": " + str(e)); traceback.print_exc()

def tx(txid, target, fee=0, recipient="ndoRECIPIENT"):
    """Build a minimal tx dict with the given txid, target_block, fee and recipient."""
    return {"txid": txid, "target_block": target, "fee": fee, "recipient": recipient, "amount": 1}

def t1_due_low_fee_not_starved_by_undue_high_fee():
    """Prove merge_buffer promotes a due fee-0 tx even when an undue high-fee tx sits ahead of it."""
    # the exact bug: a fee-0 due tx (target==5) behind a high-fee undue tx (target==100). Window (4,5].
    frm = [tx("high", 100, fee=10, recipient="ndoX"), tx("reg", 5, fee=0, recipient="register")]
    out = merge_buffer(list(frm), [], block_max=5, block_min=4)
    moved = {t["txid"] for t in out["to_buffer"]}
    assert "reg" in moved, "the due fee-0 register MUST promote"
    assert "high" not in moved, "the undue high-fee tx must stay behind"
    assert {t["txid"] for t in out["from_buffer"]} == {"high"}

def t2_promotes_all_in_window():
    """Prove merge_buffer promotes exactly the txs whose target_block falls in (block_min, block_max]."""
    frm = [tx("a", 5), tx("b", 5), tx("c", 9), tx("d", 4)]
    out = merge_buffer(frm, [], block_max=5, block_min=4)   # window (4,5] -> a,b only
    assert {t["txid"] for t in out["to_buffer"]} == {"a", "b"}
    assert {t["txid"] for t in out["from_buffer"]} == {"c", "d"}

def t3_dedup_against_to_buffer():
    """Prove merge_buffer drops a txid already present in to_buffer instead of adding it twice."""
    existing = [tx("a", 5)]
    out = merge_buffer([tx("a", 5), tx("b", 5)], list(existing), block_max=5, block_min=4)
    ids = [t["txid"] for t in out["to_buffer"]]
    assert ids.count("a") == 1 and "b" in ids, "a duplicate must not be added twice"
    assert all(t["txid"] != "a" for t in out["from_buffer"]), "the duplicate is dropped from from_buffer"

def t4_cull_never_drops_fee_exempt():
    """Prove cull_buffer keeps a fee-exempt register while evicting fee-paying spam to fit the byte limit."""
    # a fat fee-0 register + many tiny fee-1 ordinary txs; cull under a small limit must keep the register.
    reg = tx("reg", 5, fee=0, recipient="register")
    spam = [tx("s%d" % i, 5, fee=1, recipient="ndoSPAM") for i in range(200)]
    buf = [reg] + spam
    limit = get_byte_size([reg] + spam[:20])   # force eviction of most spam
    kept = cull_buffer(list(buf), limit)
    assert any(t["txid"] == "reg" for t in kept), "the fee-exempt register must survive the cull"
    assert get_byte_size(kept) <= limit, "cull must bring the buffer under the limit"

def t5_fee_exempt_set_covers_the_gated_txs():
    """Prove FEE_EXEMPT_RECIPIENTS covers every reserved fee-gated tx type."""
    for r in ("register", "unbond", "withdraw", "attest", "reveal", "commit", "settle", "heartbeat",
              "bridge_withdraw", "dividend_withdraw"):
        assert r in FEE_EXEMPT_RECIPIENTS, r + " should be protected from culling"

for n, f in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(n, f)
print("\n" + ("ALL PASSED" if not fails else str(fails) + " FAILED"))
sys.exit(1 if fails else 0)
