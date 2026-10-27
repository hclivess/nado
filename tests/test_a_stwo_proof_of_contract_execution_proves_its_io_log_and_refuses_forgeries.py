"""A Stwo proof of contract execution proves exactly the io log each call produced, and refuses forgeries and dishonest
provers (Goldilocks retirement G4, doc/stwo/g4-settlement-statement.md section 4 step 3).

native/stwo_settle's VM component (src/blake/vm_air.rs; the reference interpreter is src/vm.rs) proves that each call of
a statement, run on zkvm2 (the gen-29 VM), produces the stated io log and ends in RET. Inputs:
  * REAL calls: every successful zkvm2 run while four gen-29 contract tests play the real contracts (tictactoe, bet,
    pets, dex, reserve), recorded by tests/_vm_record.py;
  * SYNTHETIC calls that cover what the games do not: every one of the 34 opcodes (NOP, RANGE, BEACON, AMINT, ABAL and
    ARENOUNCE appear in no game flow), each arithmetic op on the word's edges (0, 1, 2^16, 2^62 - 1, 2^255, 2^256 - 1,
    ...), and random programs; every result is SSTOREd, so the io log carries it.
Checks:
  1. the Rust reference agrees with zkvm2 on every call (vm::run replays each call io-driven and refuses on the first io
     entry or step count that differs), and every CPU constraint holds on every row of the honest witness;
  2. the honest proof of the real calls, and of the synthetic ones, verifies, and the proof's table multiplicities (the
     statement's table is public LogUp terms, not a column: vm_air.rs preprocessed_ids) are bound: a mutated vector is
     refused;
  3. every forged statement is refused: each io entry's value, key and kind, an io entry dropped / added / swapped, each
     arg, an appended arg, each CTX and ACTX value, the step count +-1, another program, a MOVI immediate or a
     destination register changed in the code, two calls swapped, io logs moved between calls, a call dropped;
  4. a DISHONEST PROVER is refused (vm_air::Tamper): a MUL result off by one, a taken JNZ falling through, an ADD that
     also writes another register, a HABS whose new hash state is not the compression's digest, an LT that answers the
     opposite;
  5. the FREE-CELL PROBE: every cell of sampled rows (each opcode) perturbed by +-1, +2, +256, +65536 — no perturbation
     the row's constraints and lookups accept changes the row's state, io or table tuples, and the cells that are free
     are only the ones that row never reads (the by-design classes below). A circuit that drops a binding (say MUL's
     operand bytes) shows up here as a new free class and fails.
Prints the prove / verify time and the proof size.

Needs the nightly toolchain to build the crate; skips with the reason when it is not installed.
Run: python3 tests/test_a_stwo_proof_of_contract_execution_proves_its_io_log_and_refuses_forgeries.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchain lives under the real HOME
import _harness
HOME = _harness.isolate("nado-test-stwo-vm-")
import json
import random
import subprocess
import sys

from execnode import zkvm2
from tests._stwo_settle_build import NIGHTLY, build

T = _harness.Report()
ROOT = _harness.ROOT
W = 1 << 256
M = W - 1
EDGE = [0, 1, 2, 3, 0xffff, 0x10000, (1 << 62) - 1, 1 << 64, (1 << 128) + 7, 1 << 255, M - 1, M]
REAL_TESTS = [
    "tests/test_contracts_run_on_the_256_bit_vm_from_the_exec_gate.py",
    # the bet market, the dex and the reserve vaults on zkvm2: they were recorded from the gen-28 -> gen-29 carry tests,
    # retired in G9 with BLAKE_EXEC_HEIGHT (no gen-28 exec state can be staged any more)
    "tests/test_bet_book_beside_the_tote.py",
    "tests/test_dex.py",
    "tests/test_reserve.py",
    "tests/test_a_gen29_pet_previews_the_combine_the_contract_rolls.py",
]


def record_real():
    out = os.path.join(HOME, "real.jsonl")
    env = dict(os.environ, HOME=os.path.join(HOME, "rec"), NADO_ALLOW_PYTHON_KERNELS="1")
    os.makedirs(env["HOME"], exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "_vm_record.py"), out, *REAL_TESTS], cwd=ROOT,
                       env=env, capture_output=True, text=True, timeout=1800)
    recs = [json.loads(l) for l in open(out)] if os.path.exists(out) else []
    return recs, r.stdout[-400:] + r.stderr[-1500:]


def rec(code, method, args, ctx, actx, beacons=None, block_hashes=None, abal=None, storage=None, reverts=False):
    zkvm2.validate_code(code)
    m = {}
    ok, ret, st, io = zkvm2.run(code, method, ctx[0], args, storage or {}, value=ctx[1], cursor=ctx[2], timestamp=ctx[3],
                                beacons=beacons, block_hashes=block_hashes, asset=actx[0], selfd=actx[1], abal=abal,
                                meter=m)
    assert ok != reverts, (method, "reverted" if not ok else "returned")
    rv = m.get("revert") if not ok else None
    return {"method": method, "code": [[zkvm2.OP[i[0]], i[1], i[2], i[3]] for i in code[method]], "args": args,
            "ctx": ctx, "actx": actx, "io": [list(e) for e in (rv["io"] if rv else io)], "gas": m["gas"],
            "revert": rv["kind"] if rv else None}


# ONE REVERTING CALL PER REVERT KIND (zkvm2.REVERT_KINDS, native/stwo_settle vm::revert), the "outside a small range"
# ones from both sides (a low limb past the bound, a high limb set): each is the program's last step but the OOB
# fall-through and the out-of-gas loop (131,070 steps: its own statement, it is the expensive one)
SELF = 0xabc
REVERTING = {
    "REQUIRE": [["MOVI", 1, 0, 5], ["SSTORE", 1, 1, 0], ["MOVI", 2, 0, 0], ["REQUIRE", 0, 2, 0], ["RET", 0, 0, 0]],
    "DIVMOD": [["MOVI", 1, 0, 9], ["MOVI", 2, 0, 0], ["DIVMOD", 1, 2, 0], ["RET", 0, 0, 0]],
    "DIVMODW": [["MOVI", 1, 0, 9], ["MOVI", 2, 0, 0], ["DIVMODW", 1, 2, 0], ["RET", 0, 0, 0]],
    "NOTB (2..)": [["MOVI", 1, 0, 7], ["NOTB", 1, 1, 0], ["RET", 0, 0, 0]],
    "NOTB (>= 2^16)": [["MOVI", 1, 0, 1 << 100], ["NOTB", 1, 1, 0], ["RET", 0, 0, 0]],
    "RANGE (= 2^62)": [["MOVI", 1, 0, 1 << 62], ["RANGE", 1, 0, 0], ["RET", 0, 0, 0]],
    "RANGE (>= 2^64)": [["MOVI", 1, 0, 1 << 200], ["RANGE", 1, 0, 0], ["RET", 0, 0, 0]],
    "ARG (= nargs + 1)": [["MOVI", 2, 0, 3], ["ARG", 1, 2, 0], ["RET", 0, 0, 0]],
    "ARG (>= 2^16)": [["MOVI", 2, 0, 1 << 70], ["ARG", 1, 2, 0], ["RET", 0, 0, 0]],
    "ASEL": [["MOVI", 2, 0, 0], ["ASEL", 0, 2, 0], ["PAY", 1, 3, 0], ["RET", 0, 0, 0]],
    "PAY": [["MOVI", 2, 0, 555], ["MOVI", 1, 0, 0xdef], ["MOVI", 3, 0, 10**9], ["ASEL", 0, 2, 0], ["PAY", 1, 3, 0],
            ["RET", 0, 0, 0]],
    "ABURN": [["MOVI", 2, 0, 555], ["MOVI", 3, 0, 10**9], ["ABURN", 2, 3, 0], ["RET", 0, 0, 0]],
    "BHASH": [["MOVI", 2, 0, 77], ["BHASH", 1, 2, 0], ["RET", 0, 0, 0]],
    "BEACON": [["MOVI", 2, 0, 5], ["SLOAD", 3, 2, 0], ["BEACON", 1, 2, 0], ["RET", 0, 0, 0]],
    "OOB": [["MOVI", 1, 0, 1], ["SSTORE", 1, 1, 0]],
}
OOG = [["MOVI", 1, 0, 1], ["JMP", 0, 0, 0]]


def reverting(progs):
    ctx, actx = [0x1234, 0, 10, 20], [0, SELF, 0, 0]
    return [rec({"m": p}, "m", [11, 22], ctx, actx, beacons={}, block_hashes={}, abal={555: 3}, storage={5: 9}, reverts=True)
            for p in progs] + [rec({"m": [["MOVI", 1, 0, 1], ["SSTORE", 1, 1, 0], ["RET", 0, 1, 0]]}, "m", [11, 22], ctx,
                                   actx)]


# A DISHONEST PROVER's revert (VM_TAMPER=force_revert, vm::run_forced): the statement says the step reverts and the
# instruction does NOT fail. Every kind the circuit judges itself must be refused.
NOT_FAILING = {
    "REQUIRE on a nonzero word": ([["MOVI", 2, 0, 5], ["REQUIRE", 0, 2, 0], ["RET", 0, 0, 0]], 2, "REQUIRE"),
    "DIVMOD by a nonzero divisor": ([["MOVI", 1, 0, 9], ["MOVI", 2, 0, 3], ["DIVMOD", 1, 2, 0], ["RET", 0, 0, 0]], 3, "DIVMOD"),
    "DIVMODW by a nonzero divisor": ([["MOVI", 1, 0, 9], ["MOVI", 2, 0, 3], ["DIVMODW", 1, 2, 0], ["RET", 0, 0, 0]], 3, "DIVMODW"),
    "NOTB on 1": ([["MOVI", 1, 0, 1], ["NOTB", 1, 1, 0], ["RET", 0, 0, 0]], 2, "NOTB"),
    "NOTB on 0": ([["MOVI", 1, 0, 0], ["NOTB", 1, 1, 0], ["RET", 0, 0, 0]], 2, "NOTB"),
    "RANGE on 2^62 - 1": ([["MOVI", 1, 0, (1 << 62) - 1], ["RANGE", 1, 0, 0], ["RET", 0, 0, 0]], 2, "RANGE"),
    "ARG inside the args": ([["MOVI", 2, 0, 1], ["ARG", 1, 2, 0], ["RET", 0, 0, 0]], 2, "ARG"),
    "ASEL of a nonzero asset": ([["MOVI", 2, 0, 555], ["ASEL", 0, 2, 0], ["PAY", 1, 3, 0], ["RET", 0, 0, 0]], 2, "ASEL"),
    "OOB inside the method": ([["MOVI", 1, 0, 1], ["MOVI", 2, 0, 2], ["RET", 0, 0, 0]], 2, "OOB"),
    "OOG after 5 steps": ([["MOVI", 1, 0, 1], ["JMP", 0, 0, 0]], 5, "OOG"),
}


class Asm:
    def __init__(self):
        self.p = []
        self.key = 1

    def i(self, op, d=0, s=0, imm=0):
        self.p.append([op, d, s, imm])
        return len(self.p) - 1

    def store(self, r):
        self.i("MOVI", 6, 0, self.key)
        self.key += 1
        self.i("SSTORE", 6, r)


def edges_program():
    a = Asm()
    a.i("NOP")
    for x in EDGE:
        for y in EDGE[::3]:
            for o in ("ADD", "SUB", "MUL", "EQ", "LT"):
                a.i("MOVI", 1, 0, x); a.i("MOVI", 2, 0, y); a.i(o, 1, 2); a.store(1)
            if y:
                for o in ("DIVMOD", "DIVMODW"):
                    a.i("MOVI", 1, 0, x); a.i("MOVI", 2, 0, y); a.i(o, 1, 2); a.store(1); a.store(7)
        a.i("MOVI", 1, 0, x)
        a.i("NEZ", 2, 1); a.store(2)
        a.i("LO32", 2, 1); a.store(2)
        a.i("MOV", 3, 1); a.i("EQ", 3, 1); a.store(3)
    for b in (0, 1):
        a.i("MOVI", 1, 0, b); a.i("NOTB", 1, 1); a.store(1)
    for x in ((1 << 62) - 1, 0):
        a.i("MOVI", 1, 0, x); a.i("RANGE", 1)
    a.i("HINIT")                                   # absorb three words, read out; clear, absorb the result again
    for x in (0, M, 1 << 200):
        a.i("MOVI", 2, 0, x); a.i("HABS", 0, 2)
    a.i("HOUT", 3); a.store(3)
    a.i("HINIT"); a.i("HABS", 0, 3); a.i("HOUT", 3); a.store(3)
    for j in range(4):
        a.i("CTX", 2, 0, j); a.store(2)
        a.i("ACTX", 2, 0, j); a.store(2)
    for idx in (9, 0):
        a.i("MOVI", 2, 0, idx); a.i("ARG", 3, 2); a.store(3)
    a.i("MOVI", 2, 0, 1234); a.i("BHASH", 3, 2); a.store(3)
    a.i("MOVI", 2, 0, 7); a.i("BEACON", 3, 2); a.store(3)
    a.i("MOVI", 4, 0, 555); a.i("MOVI", 5, 0, 10); a.i("MOVI", 1, 0, 0xabc)
    a.i("ASEL", 0, 4); a.i("PAY", 1, 5)            # an asset PAY
    a.i("ACTX", 1, 0, 1)
    a.i("ASEL", 0, 4); a.i("AMINT", 1, 5)           # a mint to self
    a.i("ABURN", 4, 5)
    a.i("ABAL", 3, 4); a.store(3)
    a.i("ARENOUNCE", 4)
    a.i("MOVI", 1, 0, 0xdef); a.i("PAY", 1, 5)      # a native PAY
    a.i("MOVI", 1, 0, 0)
    j1 = a.i("JNZ", 0, 1, 0)                        # not taken (target patched to the next instruction)
    a.p[j1][3] = j1 + 1
    a.i("MOVI", 1, 0, 1 << 250)
    j2 = a.i("JNZ", 0, 1, 0)                        # taken, over a REQUIRE that would revert (r0 = arg 0 = 0)
    a.i("REQUIRE", 0, 0)
    a.p[j2][3] = len(a.p)
    a.i("REQUIRE", 0, 1)
    j3 = a.i("JMP", 0, 0, 0)
    a.i("REQUIRE", 0, 0)
    a.p[j3][3] = len(a.p)
    a.i("MOVI", 2, 0, 77); a.i("RET", 0, 2)
    return {"edges": a.p}


def random_program(rng, n):
    a = Asm()
    vals = EDGE + [rng.getrandbits(256) for _ in range(6)] + [rng.getrandbits(64) for _ in range(4)]
    for _ in range(n):
        o = rng.choice(["ADD", "SUB", "MUL", "EQ", "LT", "DIVMOD", "NEZ", "LO32", "MOV"])
        x, y = rng.choice(vals), rng.choice(vals)
        if o == "DIVMOD" and y == 0:
            y = 3
        a.i("MOVI", 1, 0, x); a.i("MOVI", 2, 0, y); a.i(o, 1, 2); a.store(1)
        if o == "DIVMOD":
            a.store(7)
    a.i("RET", 0, 1)
    return {"r": a.p}


def synthetic(seed, n_random):
    rng = random.Random(seed)
    args = [0] + [rng.getrandbits(256) for _ in range(8)] + [M]
    ctx = [rng.getrandbits(256), 12345, 678, 1793077097]
    actx = [555, rng.getrandbits(256), 0, 0]
    out = [rec(edges_program(), "edges", args, ctx, actx, beacons={7: M}, block_hashes={1234: 1 << 255}, abal={555: 10**6})]
    out += [rec(random_program(rng, 40), "r", [], ctx, actx) for _ in range(n_random)]
    return out


def statement(recs):
    h = lambda v: "%064x" % v
    progs, pidx, lines = [], {}, []
    for r in recs:
        key = json.dumps(r["code"])
        if key not in pidx:
            pidx[key] = len(progs)
            progs.append(r["code"])
    for p in progs:
        lines.append(f"PROG {len(p)}")
        lines += [f"I {o} {d} {s} {h(i)}" for o, d, s, i in p]
    for r in recs:
        rv = f" REVERT {r['revert']}" if r.get("revert") is not None else ""
        lines += [f"CALL {pidx[json.dumps(r['code'])]} {r['gas']}{rv}", "ARGS " + " ".join(h(a) for a in r["args"]),
                  "CTX " + " ".join(h(a) for a in r["ctx"]), "ACTX " + " ".join(h(a) for a in r["actx"])]
        lines += [f"IO {k} {h(a)} {h(b)}" for k, a, b in r["io"]]
    return "\n".join(lines) + "\n"


def drive(binp, recs, **env):
    """-> (stdout, stderr tail). A run that exits non-zero gets an EXIT line appended, so a check that looks for its
    verdict line also sees that it did not finish (vm_prove once panicked after printing `HONEST ok`, mid-forgeries)."""
    r = subprocess.run([binp], input=statement(recs), capture_output=True, text=True, timeout=3600,
                       env=dict(os.environ, **env))
    return r.stdout + ("" if r.returncode == 0 else f"\nEXIT {r.returncode}"), r.stderr[-2000:]


def finished(out):
    """the full forgery run completed: its summary and timing lines are there and it exited cleanly"""
    return "FORGED total=" in out and "\nTIME " in out and "\nEXIT " not in out


# The cells a row may leave free BY DESIGN: the ones that row never reads. col -> the ops that DO read it (on those, the
# column must not be free). The zero tests' inverses are free whenever the tested word is zero, on any op.
READERS = {
    "ab": {"MUL", "DIVMOD", "DIVMODW", "HABS"}, "bb": {"MUL", "DIVMOD", "DIVMODW", "HABS"},
    "cb": {"MUL", "DIVMOD", "DIVMODW"}, "pb": {"MUL", "DIVMOD", "DIVMODW"}, "mc": {"MUL", "DIVMOD", "DIVMODW"},
    "rem": {"DIVMOD", "DIVMODW"}, "rq": {"RANGE"}, "cidx": {"CTX", "ACTX", "ARG"},
    "io_a": set(zkvm2.OPS[o] for o in range(20, 34) if zkvm2.OPS[o] not in ("ARG", "DIVMODW", "ACTX")),
    "io_b": set(zkvm2.OPS[o] for o in range(20, 34) if zkvm2.OPS[o] not in ("ARG", "DIVMODW", "ACTX")),
    "inv_rd": set(), "inv_rs": set(), "inv_x": set(),
}


# A REVERT row (label "<op>!REVERT", "OOB", "OOG") reads its operands and, for the four kinds the verifier judges, its io
# entry; nothing else of it reaches a tuple (no next state). Free on it by design: the convolution bytes, the
# remainder, the RANGE quotient, the data index, the inverses of zero words, and on OOB/OOG (no instruction) the result
# and the immediate. Its io fields are free only where it emits nothing.
REVERT_FREE = {"ab", "bb", "cb", "pb", "mc", "rem", "rq", "cidx", "inv_rd", "inv_rs", "inv_x", "io_a", "io_b"}
REVERT_EMITS = {"PAY!REVERT", "ABURN!REVERT", "BHASH!REVERT", "BEACON!REVERT"}


def probe_ok(out):
    """-> (ok, detail): no HARMFUL line, and every HARMLESS class is a by-design one (padding rows aside)"""
    bad = [l for l in out.splitlines() if l.startswith("HARMFUL")]
    for l in out.splitlines():
        if l.startswith("HARMLESS"):
            op, col = l.split()[1].split(":")
            if op == "PAD":
                continue
            if op.endswith("!REVERT") or op in ("OOB", "OOG"):
                free = REVERT_FREE - ({"io_a", "io_b"} if op in REVERT_EMITS else set())
                free |= {"res", "imm"} if op in ("OOB", "OOG") else set()
                if col not in free:
                    bad.append(l)
                continue
            if col not in READERS or op in READERS[col]:
                bad.append(l)
    summary = [l for l in out.splitlines() if l.startswith("PROBE")]
    return not bad and bool(summary), (bad[:10], summary)


binp, build_log = build(_REAL_HOME, "vm_prove")
T.check("the crate builds when its toolchain is present", binp is not None or not build_log, build_log)
if binp is None:
    if not build_log:
        print(f"SKIP  no {NIGHTLY} toolchain: the Stwo prover cannot be run here")
    T.done("SKIPPED (no toolchain)")

real, rec_log = record_real()
syn = synthetic(1, 3) + synthetic(2, 30)[1:]
executed = lambda recs: {zkvm2.OPS[o] for r in recs for (o, *_rest) in r["code"]}
T.check("0. real contract calls were recorded (tictactoe, bet, pets, dex, reserve)",
        len(real) >= 50 and {"hatch", "mint", "open", "join", "claim"} <= {r["method"] for r in real},
        (len(real), rec_log))
T.check("0b. the real and synthetic programs together hold every one of zkvm2's 34 opcodes",
        executed(real) | executed(syn) == set(zkvm2.OPS), set(zkvm2.OPS) - executed(real) - executed(syn))

for name, recs in (("real", real), ("synthetic", syn)):
    out, err = drive(binp, recs, VM_DEBUG="1")
    T.check(f"1. {name}: the Rust reference agrees with zkvm2 on all {len(recs)} calls and every CPU constraint holds",
            "every CPU constraint holds" in out, (out, err))

for name, recs in (("real", real), ("synthetic", syn[:3])):
    out, err = drive(binp, recs)
    forged = [l for l in out.splitlines() if l.startswith("FORGED")]
    acc = [l for l in out.splitlines() if l.startswith("FORGE ") and l.endswith("ACCEPTED")]
    T.check(f"2. {name}: the honest proof verifies", "HONEST ok" in out and finished(out), (out[-800:], err))
    muts = [l for l in out.splitlines() if l.startswith("MUTATE ")]
    T.check(f"2b. {name}: the proof's table multiplicities are bound: each of {len(muts)} mutations of the honest proof is "
            "refused (one more, one fewer, moved to another row, an extra row)",
            len(muts) >= 3 and all(" refused " in l for l in muts), muts)
    T.check(f"3. {name}: every forged statement is refused ({forged[0] if forged else '?'})",
            bool(forged) and not acc and int(forged[0].split("total=")[1].split()[0]) >= 100, (acc[:5], forged, err))
    print("     " + " ".join(l for l in out.splitlines() if l.startswith("TIME")))

for t in ("mul_result", "jnz_not_taken", "stray_write", "hash_state", "lt_flipped"):
    out, err = drive(binp, syn[:3], VM_TAMPER=t)
    T.check(f"4. a dishonest prover ({t}) is refused", "HONEST" in out and "HONEST ok" not in out and "\nEXIT " not in out,
            (out, err))

for name, recs in (("real", real), ("synthetic", syn)):
    out, err = drive(binp, recs, VM_PROBE="3")
    ok, detail = probe_ok(out)
    T.check(f"5. {name}: the free-cell probe finds no perturbation that changes what a row does, and only by-design "
            f"free cells ({detail[1][0] if detail[1] else '?'})", ok, (detail, err))

# ---- 6. REVERTING calls: every kind (zkvm2.REVERT_KINDS), proven; forged and forced reverts refused ------------------
rv = reverting(REVERTING.values())
T.check("6a. zkvm2 reverts each program the way its name says",
        [zkvm2.REVERT_KINDS[r["revert"]] for r in rv[:-1]] == [n.split(" ")[0] for n in REVERTING], [r["revert"] for r in rv])
out, err = drive(binp, rv, VM_DEBUG="1")
T.check(f"6b. the Rust reference agrees with zkvm2 on {len(rv) - 1} reverting calls (and every CPU constraint holds)",
        "every CPU constraint holds" in out, (out, err))
out, err = drive(binp, rv)
forged = [l for l in out.splitlines() if l.startswith("FORGED")]
acc = [l for l in out.splitlines() if l.startswith("FORGE ") and l.endswith("ACCEPTED")]
nrv = sum(1 for l in out.splitlines() if l.startswith("FORGE call") and "revert" in l)
T.check("6c. their proof verifies", "HONEST ok" in out and finished(out), (out[-800:], err))
T.check(f"6d. every forged statement is refused, {nrv} of them about a revert (its kind, a return claimed, its step "
        f"count, its io entry) ({forged[0] if forged else '?'})", bool(forged) and not acc and nrv >= 3 * 15, (acc[:5], forged))
oog = reverting([OOG])[:1]
out, err = drive(binp, oog)
T.check(f"6e. an out-of-gas call ({oog[0]['gas']} steps) proves and verifies, and its forgeries are refused",
        oog[0]["gas"] == zkvm2.GAS_LIMIT and "HONEST ok" in out and finished(out) and "ACCEPTED" not in out,
        (out[-600:], err))
print("     " + " ".join(l for l in out.splitlines() if l.startswith("TIME")))
for name, (prog, n, kind) in NOT_FAILING.items():
    fake = {"method": "m", "code": [[zkvm2.OP[i[0]], i[1], i[2], i[3]] for i in prog], "args": [11, 22],
            "ctx": [0x1234, 0, 10, 20], "actx": [0, SELF, 0, 0], "io": [], "gas": n,
            "revert": zkvm2.REVERT_KINDS.index(kind)}
    out, err = drive(binp, [fake], VM_TAMPER="force_revert")
    T.check(f"6f. a dishonest prover's revert is refused: {name}",
            "HONEST" in out and "HONEST ok" not in out and "\nEXIT " not in out, (out, err))
out, err = drive(binp, rv, VM_PROBE="3")
ok, detail = probe_ok(out)
T.check(f"6g. the free-cell probe on every revert kind finds no perturbation that changes what a row does, and only "
        f"by-design free cells ({detail[1][0] if detail[1] else '?'})", ok, (detail, err))

T.done("ALL PASS — a Stwo proof of zkvm2 execution proves its io log, refuses forgeries and dishonest provers")
