"""THE EXEC TAIL NEVER STALLS FOREVER ON A PROOF NOBODY HOLDS (audit 2026-09-25, HIGH "exec stall").

The exec tail resolves every DA-carried proof of a block BEFORE mutating anything; an unavailable one used to make
_apply_block apply nothing and return False, and the tail retried the same block on every poll, forever. A private_call
was already exempt (refused without its proof, _da_op_refused_at), but a wide `field_transfer` was not, so one
MIN_TX_FEE blob {op: field_transfer, proof_da: <a commitment nobody holds>} froze the exec cursor on every exec node for
good — every game, asset and exit with it. The same stall was reachable with an HONEST proof: DaStore keeps a rolling
COUNT of objects (DA_RETAIN = 24) over an open /da/publish, so junk publishes evicted a transfer's proof before a
lagging exec node had fetched it.

Properties pinned here (no network: the DA fetch is stubbed to fail deterministically, or served from a temp store):
  * REPRODUCTION — below EXEC_DA_DEADLINE_HEIGHT (the live rule until block 29000) the block stalls on every
    retry however far finality runs ahead: cursor frozen, the bridge deposit in the same block never credited;
  * from the gate, a merely SLOW proof still stalls the whole block until finality reaches h + EXEC_DA_WAIT_BLOCKS
    (all-or-nothing is kept — nothing half-applies);
  * at the deadline the unresolvable op is REFUSED and the rest of the block applies: the state equals a node that
    applied the same block without that op (nothing moved, nothing credited or refunded), and the cursor advances;
  * the verdict is the same on a node that reaches the block live at the deadline and on one catching up far past it;
  * the deadline is a function of (h, finalized) only, and the provisional tail (finalized None) never refuses;
  * a refused op is never dispatched — an inline `bundle` riding beside the proof_da does not apply in its place;
  * a HELD proof still applies past the deadline, and is pinned in the DA store;
  * a node catching up does not refuse on its first miss: it retries for its local grace first;
  * the eviction route: a pinned object survives any number of publishes, pins persist across a restart, expire once
    the tail passes their window, and are capped.

Run: python3 tests/test_exec_never_stalls_on_unheld_proof.py
"""
import os
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-da-deadline-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: CWD-relative, see test_tests_never_touch_live_exec_state
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")               # ASSIGN: CWD-relative too
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, json, time, asyncio, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode.state import ExecState
from execnode import execnode as EN
from ops.da_store import DaStore

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


H = 300_000
W = protocol.EXEC_DA_WAIT_BLOCKS
UNHELD = "ab" * 32                      # a well-formed commitment no store holds
ALICE = "a" * 49
_LOOP = asyncio.new_event_loop()


def _state():
    return ExecState(os.path.join(os.environ["HOME"], f"s{os.urandom(4).hex()}.json"))


def _bridge_tx(amount=5000):
    return {"recipient": "bridge", "sender": ALICE, "amount": amount, "txid": "br" + os.urandom(6).hex()}


def _ft_tx(proof_da=UNHELD, **extra):
    return {"recipient": "blob", "sender": ALICE, "txid": "ft" + os.urandom(6).hex(),
            "data": {"op": "field_transfer", "proof_da": proof_da, **extra}}


def _block(h, txs):
    return {"block_number": h, "block_hash": "cd" * 32, "block_timestamp": 0, "block_transactions": txs}


def _apply(st, block, finalized=None):
    return _LOOP.run_until_complete(EN._apply_block(None, {"default": st}, st, block, verbose=False, finalized=finalized))


async def _unavailable(session, commitment):
    return None                          # the whole reachable network cannot supply k shards


class _Gate:
    """Move the (dormant, 2^62) gate for one property, the fetch stub and the local grace with it."""
    def __init__(self, height, fetch=_unavailable, grace=0.0):
        self.height, self.fetch, self.grace = height, fetch, grace

    def __enter__(self):
        self._saved = (protocol.EXEC_DA_DEADLINE_HEIGHT, EN.da_fetch, EN.DA_SKIP_GRACE_S)
        protocol.EXEC_DA_DEADLINE_HEIGHT, EN.da_fetch, EN.DA_SKIP_GRACE_S = self.height, self.fetch, self.grace
        EN._DA_MISS_SINCE.clear()

    def __exit__(self, *a):
        protocol.EXEC_DA_DEADLINE_HEIGHT, EN.da_fetch, EN.DA_SKIP_GRACE_S = self._saved
        EN._DA_MISS_SINCE.clear()


def t_reproduction_below_the_gate_an_unheld_proof_freezes_the_tail_forever():
    # The finding, reproduced on the code path the live chain runs while the gate is dormant: no retry and no amount
    # of finality ever gets past the block, and the honest deposit sharing it is never credited.
    with _Gate(H + 1):
        st = _state()
        st.cursor = H - 1
        before = st.state_root()
        blk = _block(H, [_bridge_tx(), _ft_tx()])
        for fin in (H, H + W, H + 10 * W, H + 10 ** 6):
            for _ in range(5):
                assert _apply(st, blk, finalized=fin) is False, "the block applied although its proof is unavailable"
        assert st.cursor == H - 1, f"cursor moved to {st.cursor} on a stalled block"
        assert st.bridge.get(ALICE) is None, "the deposit in the stalled block was credited"
        assert st.state_root() == before, "a stalled block changed the state"


def t_before_the_deadline_a_slow_proof_still_stalls_the_whole_block():
    with _Gate(H):
        st = _state()
        st.cursor = H - 1
        before = st.state_root()
        blk = _block(H, [_bridge_tx(), _ft_tx()])
        for fin in (H, H + 1, H + W - 1):
            assert _apply(st, blk, finalized=fin) is False, f"refused before the deadline (finalized {fin})"
        assert st.cursor == H - 1 and st.state_root() == before and st.bridge.get(ALICE) is None, \
            "a waiting block half-applied"


def t_at_the_deadline_the_op_is_refused_and_the_rest_of_the_block_applies():
    with _Gate(H):
        st, ref = _state(), _state()
        st.cursor = ref.cursor = H - 1
        dep = _bridge_tx()
        assert _apply(st, _block(H, [dep, _ft_tx()]), finalized=H + W) is True, "the block still stalls at the deadline"
        assert _apply(ref, _block(H, [dep]), finalized=H + W) is True
        assert st.cursor == H, f"cursor {st.cursor} != {H}"
        assert st.bridge.get(ALICE) == 5000, f"the deposit beside the refused op was credited {st.bridge.get(ALICE)}"
        assert st.state_root() == ref.state_root(), \
            "the refused op changed the state (a node that never saw it must land on the same root)"
        # the tail moves on: the next block applies normally
        assert _apply(st, _block(H + 1, [_bridge_tx(1)]), finalized=H + W) is True and st.cursor == H + 1


def t_a_live_node_and_a_catching_up_node_reach_the_same_verdict():
    with _Gate(H):
        live, late = _state(), _state()
        live.cursor = late.cursor = H - 1
        blk = _block(H, [_bridge_tx(), _ft_tx(), _bridge_tx(7)])
        # the live node waited through the whole window, then refused
        for fin in range(H, H + W):
            assert _apply(live, blk, finalized=fin) is False
        assert _apply(live, blk, finalized=H + W) is True
        # the late node first sees the block with finality far ahead
        EN._DA_MISS_SINCE.clear()
        assert _apply(late, blk, finalized=H + 10 ** 6) is True
        assert live.state_root() == late.state_root(), "two nodes disagree on the same unheld proof"


def t_the_deadline_is_a_function_of_height_and_finality_only():
    with _Gate(H):
        assert not EN._da_deadline_passed(H - 1, 10 ** 9), "a block below the gate was refused"
        assert not EN._da_deadline_passed(H, H + W - 1)
        assert EN._da_deadline_passed(H, H + W)
        assert EN._da_deadline_passed(H + 5, H + 5 + W) and not EN._da_deadline_passed(H + 5, H + 4 + W)
        assert not EN._da_deadline_passed(H, None), "the provisional tail (no finalized height) refused"
    with _Gate(H):
        st = _state()
        st.cursor = H - 1
        assert _apply(st, _block(H, [_ft_tx()]), finalized=None) is False, "a provisional view refused the op"


def t_a_refused_op_is_never_dispatched_even_with_an_inline_bundle():
    seen = []
    orig = ExecState.apply_field_transfer
    ExecState.apply_field_transfer = lambda self, bundle: seen.append(bundle) or "applied"
    try:
        with _Gate(H):
            st = _state()
            st.cursor = H - 1
            assert _apply(st, _block(H, [_ft_tx(bundle={"x": 1})]), finalized=H + W) is True
            assert seen == [], f"the refused op reached apply_field_transfer with {seen}"
    finally:
        ExecState.apply_field_transfer = orig


def t_a_held_proof_still_applies_past_the_deadline_and_is_pinned():
    seen = []
    orig = ExecState.apply_field_transfer
    ExecState.apply_field_transfer = lambda self, bundle: seen.append(bundle) or "applied"
    saved_da = EN.DA
    EN.DA = DaStore(tempfile.mkdtemp(prefix="da_", dir=os.environ["HOME"]), retain=2)
    try:
        meta = EN.DA.put(json.dumps({"proof": "p", "n": 1}).encode(), 2, 4)
        c = meta["commitment"]
        with _Gate(H, fetch=EN.da_fetch):              # the real resolver: local store first, no network needed
            st = _state()
            st.cursor = H - 1
            assert _apply(st, _block(H, [_ft_tx(proof_da=c)]), finalized=H + 10 * W) is True
            assert seen == [{"proof": "p", "n": 1}], f"the held proof was not injected and applied: {seen}"
            assert c in EN.DA.pinned(), "a proof an on-chain op used was not pinned"
    finally:
        ExecState.apply_field_transfer = orig
        EN.DA = saved_da


def t_a_catching_up_node_retries_for_its_grace_before_refusing():
    with _Gate(H, grace=3600.0):
        st = _state()
        st.cursor = H - 1
        blk = _block(H, [_ft_tx()])
        assert _apply(st, blk, finalized=H + 10 ** 6) is False, "refused on the first miss, with no retry at all"
        assert UNHELD in EN._DA_MISS_SINCE, "the first miss was not recorded"
        EN._DA_MISS_SINCE[UNHELD] = time.monotonic() - 3601
        assert _apply(st, blk, finalized=H + 10 ** 6) is True, "still stalled after the grace"
        assert UNHELD not in EN._DA_MISS_SINCE, "the miss record outlived the verdict"


def t_a_private_call_is_still_refused_without_any_fetch():
    calls = []

    async def _count(session, c):
        calls.append(c)
        return None
    with _Gate(1 << 62, fetch=_count):
        st = _state()
        st.cursor = H - 1
        tx = {"recipient": "blob", "sender": ALICE, "txid": "pc1", "data": {"op": "private_call", "proof_da": UNHELD}}
        assert _apply(st, _block(H, [tx]), finalized=H) is True and calls == [], "private_call fetched or stalled"


def t_a_pinned_proof_survives_a_publish_flood():
    root = tempfile.mkdtemp(prefix="da_pin_", dir=os.environ["HOME"])
    s = DaStore(root, retain=3)
    keep = s.put(b"honest transfer proof" + b"x" * 200, 2, 4)["commitment"]
    s.pin(keep, H + 100)
    for i in range(30):                                            # the flood: far past the rolling window
        s.put(b"junk-%04d" % i + b"y" * 200, 2, 4)
        time.sleep(0.002)
    objs = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    assert keep in objs and s.get(keep) is not None, "the pinned proof was evicted by the flood"
    assert len(objs) == 4, f"the window no longer bounds the unpinned objects ({len(objs)} kept)"
    # a restart reads the pins back
    s2 = DaStore(root, retain=3)
    assert keep in s2.pinned(), "pins were lost across a restart"
    # expiry: once the tail passes the window the object is an ordinary one again
    assert s2.expire_pins(H + 100) == 0, "a pin expired on its last block"
    assert s2.expire_pins(H + 101) == 1 and keep not in s2.pinned()
    for i in range(4):
        s2.put(b"later-%04d" % i + b"z" * 200, 2, 4)
        time.sleep(0.002)
    assert s2.get(keep) is None, "an expired pin still held its object"


def t_pins_are_capped_oldest_window_first():
    s = DaStore(tempfile.mkdtemp(prefix="da_cap_", dir=os.environ["HOME"]), retain=2)
    for i in range(10):
        s.pin(f"{i:064x}", H + i, cap=4)
    assert s.pinned() == {f"{i:064x}" for i in range(6, 10)}, f"cap kept {sorted(s.pinned())}"
    s.pin(f"{9:064x}", H, cap=4)                                    # a re-pin never shortens a window
    assert f"{9:064x}" in s.pinned() and s._load_pins()[f"{9:064x}"] == H + 9
    s.pin("../escape", H + 50, cap=4)                               # the path guard applies to pins too
    assert "../escape" not in s.pinned()


def t_the_finalized_tail_bounds_the_stall_and_the_provisional_one_does_not():
    src = open(EN.__file__, encoding="utf-8").read()
    tail = src[src.index("async def tail_loop"):]
    assert "await _apply_block(session, states, state, block, verbose=True, finalized=finalized)" in tail, \
        "the finalized tail no longer passes its finalized height — the DA stall is unbounded again"
    prov = src[src.index("async def _refresh_provisional"):src.index("async def tail_loop")]
    assert "finalized=" not in "".join(l for l in prov.splitlines() if "_apply_block(" in l), \
        "a provisional tail passes finalized — a speculative view would refuse ahead of the finalized verdict"
    assert "EXEC_DA_DEADLINE_HEIGHT = 29000 if CHAIN_GENERATION == 27 else 1" in open(protocol.__file__).read()   # activated 2026-09-27


for _name, _fn in list(globals().items()):
    if _name.startswith("t_") and callable(_fn):
        check(_name[2:].replace("_", " "), _fn)
print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
