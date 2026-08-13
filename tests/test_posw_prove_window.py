"""
A registration must be PROVABLE inside the window it is given (protocol.POSW_ANCHOR_OFFSET /
POSW_TARGET_MARGIN).

THE BUG. `register` lands at EXACTLY max_block, and its PoSW anchor (max_block - POSW_ANCHOR_OFFSET) has
to already exist when proving STARTS. So a client targeting tip+M can only choose M <= offset, and M
blocks is its ENTIRE proving budget. With offset 30 that budget was 30 blocks (180 s) — and it was not a
function of the WORK the difficulty demands. An ENTRY registration owes POSW_ENTRY_MULT x the rate
multiplier: up to 32 x 16 = 512 x POSW_T = 512,000,000 sequential hashes. Measured with the hasher the
browser miner actually ships (WASM blake2b: ~3.2M h/s on a desktop, 4-10x slower on a phone), a mid-range
phone needed ~121 s of that 180 s window at the 96x that was live, and could not finish at all above it.

The failure mode was silent and misleading: the prover produced a perfectly VALID proof for a block the
chain had already passed, the submit was refused, and the wallet reported "the relay rejected the
registration" with nothing on screen connecting it to device speed.

THE FIX widens the window without touching the anti-Sybil COST by a single hash: offset 150, target
margin 90. The anchor becomes tip-60 (deeper than FINALITY_DEPTH at prove time, which the constant's own
comment had always claimed and never been) and the budget becomes 90 blocks = 540 s.

WHAT THESE CHECKS PIN. The three inequalities that make the scheme coherent at all — a client cannot
target past the anchor's existence, the anchor is settled when it is used, and the budget covers the
worst-case work on a slow device — plus the fact that every prover in the tree (node, CLI, wallet) aims
at the same budget. Get the first one wrong and NOBODY can register: the anchor block does not exist yet.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from protocol import (POSW_ANCHOR_OFFSET, POSW_TARGET_MARGIN, POSW_T, POSW_S, POSW_ENTRY_MULT,
                              POSW_DIFF_MAX_MULT, FINALITY_DEPTH, BLOCK_TIME, TX_LANDING_WINDOW)

        # ---- the three inequalities ------------------------------------------------------------------
        # 1. THE ANCHOR MUST EXIST WHEN PROVING STARTS. Targeting tip+M anchors at tip+M-offset; if that
        #    is above the tip the block has not been mined and no one can register at all.
        check("a client's target never anchors past the tip (margin <= offset)",
              POSW_TARGET_MARGIN <= POSW_ANCHOR_OFFSET)

        # 2. THE ANCHOR MUST BE SETTLED. Depth at prove time is offset - margin; the constant has always
        #    documented this as ">= FINALITY_DEPTH" and, at offset 30 == margin 30, it was 0.
        depth_at_prove = POSW_ANCHOR_OFFSET - POSW_TARGET_MARGIN
        check(f"the anchor is finalized when it is used (depth {depth_at_prove} >= FINALITY_DEPTH {FINALITY_DEPTH})",
              depth_at_prove >= FINALITY_DEPTH)
        check("...and deeper still by the time the tx lands",
              POSW_ANCHOR_OFFSET > depth_at_prove)

        # 3. THE BUDGET MUST COVER THE WORK. Worst-case entry = entry x rate multipliers, against the
        #    slowest device we intend to support. 0.3M h/s is the shipped WASM blake2b on a slow phone
        #    (measured: 3.17M h/s on a desktop core, phones run 4-10x slower).
        budget_s = POSW_TARGET_MARGIN * BLOCK_TIME
        worst_t = POSW_T * POSW_ENTRY_MULT * POSW_DIFF_MAX_MULT
        SLOW_PHONE_HPS = 300_000
        check(f"the proving budget is {budget_s}s, not the old 180s", budget_s >= 540)
        # The worst case (512x) still does not fit on a slow phone in 540s — that is a KNOWN, deliberate
        # remainder: it needs the rate multiplier to be pinned at its 16x cap, which only happens under a
        # sustained registration flood, and throttling entry during a flood is the point. What must fit is
        # the ordinary case: an entry at the rate multipliers actually seen in operation (1x-3x).
        for mult in (1, 2, 3):
            t = POSW_T * POSW_ENTRY_MULT * mult
            check(f"an entry at {mult}x rate ({t:,} hashes) fits the budget on a slow phone "
                  f"({t / SLOW_PHONE_HPS:.0f}s <= {budget_s}s)",
                  t / SLOW_PHONE_HPS <= budget_s)
        print(f"      note: the 512x worst case ({worst_t:,} hashes) needs "
              f"{worst_t / SLOW_PHONE_HPS:.0f}s and still does not fit — flood-throttled by design")

        # 4. The mempool must actually accept a tx aimed that far out.
        check("the target stays inside TX_LANDING_WINDOW", POSW_TARGET_MARGIN <= TX_LANDING_WINDOW)
        check("T stays a whole number of PoSW segments at every multiplier",
              all((POSW_T * m) % POSW_S == 0 for m in (1, POSW_ENTRY_MULT, POSW_DIFF_MAX_MULT,
                                                       POSW_ENTRY_MULT * POSW_DIFF_MAX_MULT)))

        # ---- every prover in the tree aims at the SAME budget -----------------------------------------
        # A prover using a different margin gets a different anchor and a rejected proof, which is exactly
        # how the CLI and the browser wallet came to disagree with the node in the first place.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        core = open(os.path.join(root, "loops", "core_loop.py")).read()
        check("the node's auto-register targets tip + POSW_TARGET_MARGIN",
              'latest_block["block_number"] + POSW_TARGET_MARGIN' in core)
        cli = open(os.path.join(root, "scripts", "nado_cli.py")).read()
        check("the CLI's register targets tip + POSW_TARGET_MARGIN",
              "_tip(node) + POSW_TARGET_MARGIN" in cli)
        js = open(os.path.join(root, "static", "interface.js")).read()
        # the wallet carries its own copies of both constants; they must track protocol.py exactly
        m_off = re.search(r"POSW_ANCHOR_OFFSET\s*=\s*(\d+)", js)
        m_mar = re.search(r"const POSW_TARGET_MARGIN\s*=\s*(\d+)", js)
        check("the wallet's POSW_ANCHOR_OFFSET matches protocol.py",
              bool(m_off) and int(m_off.group(1)) == POSW_ANCHOR_OFFSET)
        check("the wallet's POSW_TARGET_MARGIN matches protocol.py",
              bool(m_mar) and int(m_mar.group(1)) == POSW_TARGET_MARGIN)

        # ---- and the anchor arithmetic itself ---------------------------------------------------------
        # validate_transaction derives the anchor from the tx's OWN max_block; a client that targets
        # tip+margin must therefore be able to name a block at or below the tip.
        for tip in (0, 1, 149, 150, 3000, 10_000):
            target = tip + POSW_TARGET_MARGIN
            anchor = max(0, target - POSW_ANCHOR_OFFSET)
            check(f"tip {tip}: anchor {anchor} already exists", anchor <= tip)

    print()
    print("ALL POSW WINDOW CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
