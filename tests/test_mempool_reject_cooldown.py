"""Refused gossip txs must cool by what the refusal MEANS — a flat cooldown was a fork driver.

"Empty account" is a spend from a fresh address whose funding tx is still in the mempool: the account
exists only once the funding MINES, so nodes that saw the spend early refused it and cooled it a flat
60 s while late nodes admitted it. Deterministic production turns that divergent pool straight into a
same-height split (the 62655/62895 class). Terminal refusals keep the long cooldown (re-fetching them is
waste); transient ones cool ~2 block times; an "Empty account" whose funder is visible in OUR OWN pool
does not cool at all — the first reconcile after the funding mines admits it, the earliest any node can.

Run: python3 tests/test_mempool_reject_cooldown.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def cooldown(message, funder=False):
    # import lazily so a syntax error in memserver fails one test, not the harness
    from memserver import MemServer
    return MemServer.reject_cooldown_s(message, funder)


def t_terminal_refusals_cool_long():
    for m in ("Malformed transaction", "Invalid txid", "Invalid signature", "Already mined",
              "Superseded by the merged `duty` tx", "Target block too high", "Target block too low"):
        assert cooldown(m) == 60, f"{m!r} must cool 60s — it can never become valid"
        assert cooldown(m, funder=True) == 60, f"{m!r} is terminal regardless of a pool funder"


def t_transient_refusals_cool_briefly():
    """Two block times: the pool must re-converge within the window the funding tx needs to mine."""
    assert cooldown("Empty account") == 12
    assert cooldown("Mempool full") == 12
    assert cooldown("some future unknown reason") == 12, "unknown refusals must default TRANSIENT — " \
        "defaulting terminal would re-create the fork driver for every new message"


def t_a_spend_whose_funder_we_hold_never_cools():
    """The fork-driver case exactly: funding in the pool, spend refused until it mines. The next 1 s
    reconcile pass after the funding mines must be able to admit it immediately."""
    assert cooldown("Empty account", funder=True) == 0


def t_the_caching_site_uses_the_grading():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "memserver.py"), encoding="utf8").read()
    site = src[src.index("def merge_remote_transactions"):]
    site = site[:site.index("def _fetch_missing_remote_txs")]
    assert "self.reject_cooldown_s(result.get(\"message\")" in site, "the flat 60s cooldown is back"
    assert "now + 60" not in site, "a hardcoded 60s survives at the caching site"
    assert "if _cool:" in site, "a zero cooldown must mean NO cache entry, not an instantly-expired one"
    assert 't.get("recipient") == tx.get("sender")' in site, "the funder-in-pool check is gone"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "REJECT COOLDOWNS ARE GRADED BY MEANING")
sys.exit(1 if FAILS else 0)
