"""Every collected fork seed was an "only_ours" SYSTEM tx — the node that created it included it
before gossip delivered it anywhere. Three classes, two mechanisms, pinned here:

  dividend_withdraw (h66894)  FLEXIBLY-landing -> min_block is the propagation guard; the constructor
                              now takes it and the auto-collector passes tip + TX_INCLUSION_DELAY.
  settle            (h66830)  EXACT-landing -> the target IS the deadline; tip+2 (12 s) was the whole
                              race, now tip+12.
  duty              (h66680)  EXACT-landing -> DUTY_TX_MARGIN 12 -> 20, deadline clamps still bound it.

Run: python3 tests/test_fork_seed_landing_margins.py
"""
import os
import re
import subprocess
import sys
import tempfile

if os.environ.get("_LM_CHILD") != "1":
    tmp = tempfile.mkdtemp(prefix="lm_")
    env = dict(os.environ, HOME=tmp, _LM_CHILD="1", NADO_ALLOW_PYTHON_KERNELS="1",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env)
    sys.exit(r.returncode)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.expanduser("~/nado"), exist_ok=True)

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


def t_dividend_withdraw_carries_a_verified_min_block():
    """min_block must be inside the SIGNED body (txid + signature) and enforced by the window check."""
    from ops.key_ops import generate_keys
    from ops.transaction_ops import construct_dividend_withdraw_tx
    from ops.block_ops import check_target_match
    keys = generate_keys()
    tx = construct_dividend_withdraw_tx(keys, 5, "n1", {"p": 1}, max_block=1000, min_block=108)
    assert tx.get("min_block") == 108, "min_block did not make it into the tx"
    from ops.transaction_ops import create_txid
    body = {k: v for k, v in tx.items() if k not in ("txid", "signature")}
    assert create_txid(body) == tx["txid"], "min_block is OUTSIDE the txid — strippable in flight"
    class _L:
        def __getattr__(self, _n):
            return lambda *a, **k: None
    _log = _L()
    assert not check_target_match([tx], 100, _log), "landed BELOW min_block — the h66894 fork exactly"
    assert check_target_match([tx], 108, _log) and check_target_match([tx], 500, _log), \
        "the window itself broke"
    legacy = construct_dividend_withdraw_tx(keys, 5, "n1", {"p": 1}, max_block=1000)
    assert "min_block" not in legacy and check_target_match([legacy], 100, _log), \
        "legacy (no min_block) txs must keep landing anywhere up to max_block"


def t_the_auto_collector_passes_the_guard():
    s = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf8").read()
    site = s[s.index("construct_dividend_withdraw_tx("):]
    site = site[:site.index(")") + 200]
    assert "TX_INCLUSION_DELAY" in site.split("construct_dividend_withdraw_tx(", 1)[0] or \
           "min_block=" in site, "the auto-collector builds unguarded claims again"


def t_settle_targets_give_propagation_headroom():
    """No settle submission path may aim closer than 12 blocks ahead of the tip it read."""
    s = open(os.path.join(ROOT, "execnode", "execnode.py"), encoding="utf8").read()
    bad = re.findall(r'block_number"\]\)\s*\+\s*[2-9]\b', s)
    assert not bad, f"a settle target aims < 12 blocks ahead again: {bad}"
    assert s.count('block_number"]) + 12') >= 3, "the widened targets are gone"
    assert "else 12)" in s, "the no-proof fallback margin regressed"


def t_duty_margin_is_widened_but_still_clamped():
    from protocol import DUTY_TX_MARGIN, EPOCH_LENGTH
    assert DUTY_TX_MARGIN >= 20, f"DUTY_TX_MARGIN regressed to {DUTY_TX_MARGIN}"
    assert DUTY_TX_MARGIN < EPOCH_LENGTH, "a margin >= an epoch would defeat the deadline clamps"
    s = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf8").read()
    assert "reveal_hi" in s and "epoch_hi" in s, "the deadline clamps the margin relies on are gone"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "SYSTEM TXS NOW OUTRUN THEIR OWN INCLUSION")
sys.exit(1 if FAILS else 0)
