# tests/vmasm.py — the SHARED stackvm assembler + method patterns + test harness for NADO game contracts.
#
# Every game contract test used to re-declare the same opcode helpers, the same bank-table methods
# (open/fund/close), the same PvP skeleton (open/join/resign/abort/cancel) and the same ExecState test
# scaffolding. This module is that common ground, extracted once (from the slots/dice/tictactoe tests —
# the deployed generators of record keep their own inline copies so their committed *.json provenance
# stays byte-stable; NEW games import from here).
#
# Style: every helper returns a LIST of instructions, so bytecode composes with `+`:
#     bet_m = A(0) + P(0) + GT + REQ + ...
# Scratch registers: per-call temporaries live in the "S" map via SETR("x", ops) / R("x").
# Structured control flow: IF(cond, then, els) and WHILE(cond, body) compile to relative JUMP/JUMPI —
# offsets are computed here so no game hand-counts instructions again.
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState  # noqa: E402


# ---- opcodes (each returns a list; compose with +) ------------------------------------------------
def P(v):  return [["PUSH", v]]
def A(i):  return [["ARG", i]]
def LD(m): return [["MLOAD", m]]
def ST(m): return [["MSTORE", m]]
def OP(o): return [[o]]

CALLER = OP("CALLER"); VALUE = OP("VALUE"); CURSOR = OP("CURSOR"); TIME = OP("TIME")
HASH = OP("HASH"); BLOCKHASH = OP("BLOCKHASH"); BEACON = OP("BEACON")
ADD = OP("ADD"); SUB = OP("SUB"); MUL = OP("MUL"); DIV = OP("DIV"); MOD = OP("MOD")
EQ = OP("EQ"); GT = OP("GT"); GTE = OP("GTE"); LT = OP("LT"); LTE = OP("LTE")
NOT = OP("NOT"); AND = OP("AND"); OR = OP("OR"); CONCAT = OP("CONCAT")
DUP = OP("DUP"); SWAP = OP("SWAP"); POP = OP("POP")
REQ = OP("REQUIRE"); PAY = OP("PAY"); RET = OP("RETURN"); HALT = OP("HALT")

# scratch registers: per-call temporaries in the "S" map (persist only within storage — a settled call
# overwrites them next call; keys are register names, so two concurrent calls in one block are fine:
# blobs apply sequentially).
S = "S"
def SETR(r, ops): return P(r) + ops + ST(S)
def R(r):         return P(r) + LD(S)


# ---- structured control flow over relative JUMP/JUMPI ----------------------------------------------
def IF(cond, then, els=None):
    """cond truthy -> run `then` (else `els`). Compiles to NOT + JUMPI with computed relative offsets."""
    if els:
        return cond + NOT + P(len(then) + 3) + OP("JUMPI") + then + P(len(els) + 1) + OP("JUMP") + els
    return cond + NOT + P(len(then) + 1) + OP("JUMPI") + then


def WHILE(cond, body):
    """while cond truthy: run body. Gas-bounded by the VM (every instruction costs 1)."""
    return cond + NOT + P(len(body) + 3) + OP("JUMPI") + body + P(-(len(cond) + len(body) + 4)) + OP("JUMP")


# ---- generalized method patterns --------------------------------------------------------------------
def bank_table_methods(with_round_anchor=False):
    """The peer-banked table lifecycle every house game shares (dice/slots/mines/blackjack):
        open(t)+value  — put up a bankroll, become the table's bank (maps: tk bankroll, tp pool, ta bank)
        fund(t)+value  — bank-only top-up of bankroll + pool
        close(t)       — bank-only, only when every seat settled (tx==tn): reclaim the pool
    with_round_anchor also stores t0=CURSOR at open (auto-rolling round games like dice/roulette).
    Seat methods (bet/settle/...) are game-specific and maintain tc (committed cover), tn, tx themselves."""
    open_m = (
        VALUE + P(0) + GT + REQ
        + A(0) + P(0) + GT + REQ
        + A(0) + LD("ta") + P(0) + EQ + REQ
        + A(0) + VALUE + ST("tk")
        + A(0) + VALUE + ST("tp")
        + A(0) + CALLER + ST("ta")
        + (A(0) + CURSOR + ST("t0") if with_round_anchor else [])
        + HALT)
    fund_m = (
        CALLER + A(0) + LD("ta") + EQ + REQ
        + A(0) + LD("tz") + NOT + REQ
        + VALUE + P(0) + GT + REQ
        + A(0) + A(0) + LD("tk") + VALUE + ADD + ST("tk")
        + A(0) + A(0) + LD("tp") + VALUE + ADD + ST("tp")
        + HALT)
    close_m = (
        CALLER + A(0) + LD("ta") + EQ + REQ
        + A(0) + LD("tz") + NOT + REQ
        + A(0) + LD("tx") + A(0) + LD("tn") + EQ + REQ
        + A(0) + LD("ta") + A(0) + LD("tp") + PAY
        + A(0) + P(1) + ST("tz")
        + A(0) + P(0) + ST("tp")
        + HALT)
    return {"open": open_m, "fund": fund_m, "close": close_m}


def pvp_methods(window):
    """The 2-player staked board-game skeleton (tictactoe lineage). Maps: p1 opener, p2 joiner,
    st stake, pt pot, nn player count, sd settled, dl move deadline (cursor+window), mc ply counter,
    wr result (1=p1 wins, 2=p2 wins, 3=draw/void). The game supplies its own move() (which must
    ply-bind on mc, referee, PAY the pot on a win and refund on a draw)."""
    open_m = (
        VALUE + P(0) + GT + REQ
        + A(0) + P(0) + GT + REQ
        + A(0) + LD("nn") + P(0) + EQ + REQ
        + A(0) + VALUE + ST("st")
        + A(0) + VALUE + ST("pt")
        + A(0) + CALLER + ST("p1")
        + A(0) + P(1) + ST("nn")
        + HALT)
    join_m = (
        A(0) + LD("nn") + P(1) + EQ + REQ
        + A(0) + LD("sd") + NOT + REQ
        + VALUE + A(0) + LD("st") + EQ + REQ
        + CALLER + A(0) + LD("p1") + EQ + NOT + REQ
        + A(0) + A(0) + LD("pt") + VALUE + ADD + ST("pt")
        + A(0) + CALLER + ST("p2")
        + A(0) + P(2) + ST("nn")
        + A(0) + CURSOR + P(window) + ADD + ST("dl")
        + HALT)
    resign_m = (
        A(0) + LD("nn") + P(2) + EQ + REQ
        + A(0) + LD("sd") + NOT + REQ
        + CALLER + A(0) + LD("p1") + EQ + CALLER + A(0) + LD("p2") + EQ + OR + REQ
        + A(0) + LD("p2") + A(0) + LD("pt") + CALLER + A(0) + LD("p1") + EQ + MUL + PAY
        + A(0) + LD("p1") + A(0) + LD("pt") + CALLER + A(0) + LD("p2") + EQ + MUL + PAY
        + A(0) + P(2) + CALLER + A(0) + LD("p1") + EQ + MUL + P(1) + CALLER + A(0) + LD("p2") + EQ + MUL + ADD + ST("wr")
        + A(0) + P(1) + ST("sd")
        + A(0) + P(0) + ST("pt")
        + HALT)
    abort_m = (
        A(0) + LD("nn") + P(2) + EQ + REQ
        + A(0) + LD("sd") + NOT + REQ
        + CURSOR + A(0) + LD("dl") + GT + REQ
        + A(0) + LD("p1") + A(0) + LD("st") + PAY
        + A(0) + LD("p2") + A(0) + LD("st") + PAY
        + A(0) + P(3) + ST("wr")
        + A(0) + P(1) + ST("sd")
        + A(0) + P(0) + ST("pt")
        + HALT)
    cancel_m = (
        A(0) + LD("nn") + P(1) + EQ + REQ
        + CALLER + A(0) + LD("p1") + EQ + REQ
        + A(0) + LD("sd") + NOT + REQ
        + A(0) + LD("p1") + A(0) + LD("pt") + PAY
        + A(0) + P(1) + ST("sd")
        + A(0) + P(0) + ST("pt")
        + HALT)
    return {"open": open_m, "join": join_m, "resign": resign_m, "abort": abort_m, "cancel": cancel_m}


# ---- the VM's HASH, for python reference implementations -------------------------------------------
def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")


# ---- test harness -----------------------------------------------------------------------------------
class Harness:
    """ExecState wrapper with the idioms every contract test repeats: deploy, call, balances, storage
    reads, block-hash seeding, the ok/FAIL checker, and the committed-json write-or-verify footer."""

    def __init__(self, code, deployer="BANK", accounts=("BANK", "B1", "B2", "EVE"),
                 cursor=100, credit=10**14, nonce="t"):
        self.code = code
        self.st = ExecState(tempfile.mktemp())
        self.st.cursor = cursor
        for a in set(accounts) | {deployer}:
            self.st.credit_deposit(a, credit)
        self.st.apply_blob({"op": "deploy", "code": code, "runtime": "stackvm", "nonce": nonce}, deployer, "d0")
        self.cid = list(self.st.contracts)[0]
        self.fails = []
        self._n = 0

    # -- chain plumbing --
    @property
    def cursor(self): return self.st.cursor

    @cursor.setter
    def cursor(self, v): self.st.cursor = v

    def call(self, method, args, value, who):
        self._n += 1
        return self.st.apply_blob({"op": "call", "contract": self.cid, "method": method,
                                   "args": args, "value": value}, who, f"{method}{args}#{self._n}")

    def bal(self, a): return self.st.bridge.get(a, 0)

    def M(self, m, k): return self.st.contracts[self.cid]["storage"].get(m, {}).get(str(k), 0)

    def seed(self, lo, hi, tag="s"):
        for h in range(lo, hi + 1):
            self.st.block_hashes[h] = vm_hash([tag, h])

    @staticmethod
    def rv(r): return "revert" in r or "skip" in r

    # -- checks + the standard footer --
    def ck(self, name, cond):
        print(("  ok  " if cond else " FAIL ") + name)
        if not cond:
            self.fails.append(name)

    def finish(self, json_name, extra=""):
        """Print the verdict; on success WRITE=1 regenerates execnode/contracts/<json_name>, otherwise
        assert the committed file matches this test's CODE (the stale-guard every game test carries)."""
        print("\n" + ("ALL PASS" if not self.fails else f"{len(self.fails)} FAILED: {self.fails}"))
        if not self.fails:
            outp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "execnode", "contracts", json_name)
            blob = json.dumps(self.code)
            print(f"deploy blob = {len(blob)} bytes{(' ; ' + extra) if extra else ''}")
            if os.environ.get("WRITE"):
                json.dump(self.code, open(outp, "w"))
                print("WROTE", outp)
            else:
                committed = json.load(open(outp)) if os.path.exists(outp) else None
                assert committed == self.code, f"execnode/contracts/{json_name} is STALE — re-run with WRITE=1"
                print(f"committed {json_name} matches")
        sys.exit(1 if self.fails else 0)
