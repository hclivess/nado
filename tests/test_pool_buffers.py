"""
Mempool buffer culling (ops/pool_ops.py): cull_buffer must never evict a fee-exempt reserved tx, and the
fee-exempt set must cover every reserved fee-gated tx type. (The three-buffer merge_buffer it used to pin
was deleted as unreachable; its starvation tests went with it.)

Run: python3 tests/test_pool_buffers.py
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.pool_ops import cull_buffer, FEE_EXEMPT_RECIPIENTS
from ops.data_ops import get_byte_size

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print("PASS  " + name)
    except Exception as e:
        fails += 1; print("FAIL  " + name + ": " + str(e)); traceback.print_exc()

def tx(txid, target, fee=0, recipient="ndoRECIPIENT"):
    """Build a minimal tx dict with the given txid, max_block, fee and recipient."""
    return {"txid": txid, "max_block": target, "fee": fee, "recipient": recipient, "amount": 1}

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
