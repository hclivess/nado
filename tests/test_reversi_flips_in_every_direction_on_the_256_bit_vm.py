"""Reversi flips in every one of the 8 directions on the 256-bit VM, and a whole game played on the contract ends on
the reference board with the reference payout.

The 2026-10-28 bug: execnode/games/reversi.py wrote a negative direction d into the contract source as `d % P` with P
the Goldilocks prime — the field VM's spelling of -|d|. Generation 29 runs zkvm2, whose word wraps at 2^256, so that
literal was a huge positive number and every walk along -16, -1, -15 or -17 read a garbage board index: those
directions never flipped, and a move legal only through one of them was refused (black's opening move at cell 44,
which flips 85 along -16, reverted). tests/test_every_contract_builds_byte_identical_for_the_256_bit_vm.py had pinned
that bytecode. Pinned here on the real ExecState (the path the live exec node runs) against the in-clear reference
reversi.flips_for:
  1. each of the four opening moves (one per negative-or-positive axis) applies and flips exactly the reference cells;
  2. for EVERY direction, a move whose only flips lie along that direction is accepted and matches the reference;
  3. several full random legal games (passes included) agree with the reference board after every move, and the
     payout at the double pass is the reference disc count's (winner takes the pot, a draw refunds both);
  4. an illegal move — no flip, an occupied cell, the wrong ply, the wrong player — is refused and changes nothing.

Run: python3 tests/test_reversi_flips_in_every_direction_on_the_256_bit_vm.py
"""
import _harness
HOME = _harness.isolate("nado-test-reversi-dirs-")
import os
import random
import tempfile

from execnode.state import ExecState
from execnode.games import reversi as rv

T = _harness.Report()
A, B = "ndoAAAA" + "A" * 41, "ndoBBBB" + "B" * 41
STAKE = 100_000
SEED_BOARD = dict(rv.SEED)


def bi(cell):
    return (cell // 8 + 1) * 16 + (cell % 8 + 1)


def runs_by_dir(board, cell, k):
    """{d: [bidx...]} — the reference flips split per direction (flips_for's own walk, kept per d)."""
    base, opp, out = bi(cell), 3 - k, {}
    for d in rv.DIRS:
        run, p = [], base + d
        while board.get(p, 0) == opp:
            run.append(p); p += d
        if run and board.get(p, 0) == k:
            out[d] = run
    return out


class Game:
    def __init__(self, g=7):
        self.st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json")); self.st.cursor = 100
        code = rv.build()
        self.st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": rv.ABI, "nonce": "n"}, A, "d")
        self.cid = self.st.contract_id(A, code, "n")
        for who in (A, B):
            self.st.credit_deposit(who, 10_000_000)
        self.g, self.n, self.mc, self.board = g, 0, 0, dict(SEED_BOARD)
        assert self.call(A, "open", [g], STAKE).endswith("-> ok")
        assert self.call(B, "join", [g], STAKE).endswith("-> ok")

    def call(self, who, method, args, value=0):
        self.n += 1
        return self.st.apply_blob({"op": "call", "contract": self.cid, "method": method, "args": args,
                                   **({"value": value} if value else {})}, who, f"t{self.n}")

    def slots(self):
        return self.st.contracts[self.cid]["storage"].get("slots") or {}

    def rd(self, f):
        return int(self.slots().get(str(f * (1 << 32) + self.g), 0))

    def chain_board(self):
        s = self.slots()
        return {b: int(s.get(str((rv.BD_BASE + b) * (1 << 32) + self.g), 0)) for b in range(160)}

    def matches(self):
        cb = self.chain_board()
        return all(cb[b] == self.board.get(b, 0) for b in range(160))

    def legal(self, k):
        return [c for c in range(64) if self.board.get(bi(c), 0) == 0 and rv.flips_for(self.board, c, k)]

    def play(self, cell):
        """Play `cell` (or rv.PASS) for the side to move; apply the reference; return the contract's result line."""
        k = 1 + self.mc % 2
        r = self.call(A if k == 1 else B, "move", [self.g, cell, self.mc])
        if r.endswith("-> ok"):
            if cell != rv.PASS:
                for p in rv.flips_for(self.board, cell, k):
                    self.board[p] = k
                self.board[bi(cell)] = k
            self.mc += 1
        return r


# 1. the four opening moves — black's 44 is the measured refusal (flips 85 along -16)
for cell in (19, 26, 37, 44):
    gm = Game()
    ref = rv.flips_for(gm.board, cell, 1)
    r = gm.play(cell)
    T.check(f"1. black's opening move at {cell} (flips {ref} along {list(runs_by_dir(SEED_BOARD, cell, 1))}) "
            f"applies and the board is the reference", r.endswith("-> ok") and gm.matches(), (r, ref))

# 2 + 3. full random games; record, per direction, a move whose ONLY flips lie along that direction
only_dir = {d: 0 for d in rv.DIRS}
flipped_dir = {d: 0 for d in rv.DIRS}
outcomes = {"p1": 0, "p2": 0, "draw": 0}
bad_moves, bad_pay = [], []
for seed in range(12):
    rnd = random.Random(0xA11CE + seed)
    gm = Game(g=100 + seed)
    a0, b0 = gm.st.bridge[A], gm.st.bridge[B]
    passes, moves = 0, 0
    while passes < 2:
        k = 1 + gm.mc % 2
        lg = gm.legal(k)
        if lg:
            cell = rnd.choice(lg)
            per = runs_by_dir(gm.board, cell, k)
            r = gm.play(cell)
            if not (r.endswith("-> ok") and gm.matches()):
                bad_moves.append((seed, moves, cell, per, r)); break
            for d in per:
                flipped_dir[d] += 1
            if len(per) == 1:
                only_dir[next(iter(per))] += 1
            passes, moves = 0, moves + 1
        else:
            r = gm.play(rv.PASS)
            if not (r.endswith("-> ok") and gm.matches()):
                bad_moves.append((seed, moves, "PASS", r)); break
            passes += 1
    else:
        n1 = sum(1 for v in gm.board.values() if v == 1); n2 = sum(1 for v in gm.board.values() if v == 2)
        da, db = gm.st.bridge[A] - a0, gm.st.bridge[B] - b0
        if n1 > n2:
            want, wr, tag = (2 * STAKE, 0), 1, "p1"
        elif n2 > n1:
            want, wr, tag = (0, 2 * STAKE), 2, "p2"
        else:
            want, wr, tag = (STAKE, STAKE), 3, "draw"
        outcomes[tag] += 1
        if (da, db) != want or gm.rd(rv.SD) != 1 or gm.rd(rv.WR) != wr or gm.st.bridge.get(gm.cid, 0) != 0:
            bad_pay.append((seed, n1, n2, (da, db), want, gm.rd(rv.WR), gm.st.bridge.get(gm.cid, 0)))

T.check("3. every move of 12 full random games is accepted and leaves the reference board", not bad_moves, bad_moves[:3])
T.check("3. ...and the double pass pays the reference disc count (winner takes the pot, a draw refunds both), "
        "leaving the contract empty", not bad_pay, bad_pay)
T.check("3. ...the games end both ways (p1 wins and p2 wins both occur)", outcomes["p1"] and outcomes["p2"], outcomes)
T.check("2. every one of the 8 directions flipped discs in those games", all(flipped_dir.values()), flipped_dir)
T.check("2. for every direction, a move whose ONLY flips lie along it was accepted and matched the reference",
        all(only_dir.values()), only_dir)

# 4. illegal moves are refused and change nothing
gm = Game()
before = gm.chain_board()
nofl = next(c for c in range(64) if gm.board.get(bi(c), 0) == 0 and not rv.flips_for(gm.board, c, 1))
cases = [("a placement that flips nothing", A, [gm.g, nofl, 0]),
         ("an occupied cell", A, [gm.g, 27, 0]),
         ("the wrong ply", A, [gm.g, 44, 1]),
         ("the wrong player (white on black's turn)", B, [gm.g, 44, 0]),
         ("a cell past PASS", A, [gm.g, 65, 0])]
for name, who, args in cases:
    r = gm.call(who, "move", args)
    T.check(f"4. an illegal move is refused: {name}", "revert" in r and gm.chain_board() == before
            and gm.rd(rv.MC) == 0, r)
T.check("4. ...and the legal move is still accepted afterwards", gm.play(44).endswith("-> ok") and gm.matches())

T.done("ALL PASS — reversi flips in every direction on the 256-bit VM and pays the reference count")
