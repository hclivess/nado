"""
Contract library for the NADO execution VM (execnode/vm.py) — a small assembler abstraction, a set of
GENERALIZED method patterns, and the first example contracts built from them. A contract is just a
{method: bytecode} dict the VM runs; the helpers here make the stack bytecode readable and reusable so new
contracts compose from patterns instead of hand-rolled opcodes.

The examples:
  COUNTER   — a shared integer counter (the "hello world").
  TIP_JAR   — a per-caller running total (the `accumulator` pattern: tipping, reputation, vote tallies).
  COIN_FLIP — a fair 2-player coin flip (the `commit_reveal` pattern: also sealed-bid, lotteries). Neither
              player can bias the result: each commits HASH(secret) first, then reveals; the outcome is the
              parity of HASH(secret0 ‖ secret1), unknowable until both secrets are out.

VM note: storage VALUES are ints only, so a contract can't remember an address as a value (only as a KEY).
That's why COIN_FLIP is a fair-RESULT oracle, not an escrow — staking value belongs on L1/the bridge, not in
this pure-compute VM.
"""

# ---- assembler: one VM instruction per helper (a [OP, arg?] list) --------------------------------
def PUSH(v):   return ["PUSH", v]
def POP():     return ["POP"]
def DUP():     return ["DUP"]
def SWAP():    return ["SWAP"]
def ADD():     return ["ADD"]
def SUB():     return ["SUB"]
def MUL():     return ["MUL"]
def DIV():     return ["DIV"]
def MOD():     return ["MOD"]
def LT():      return ["LT"]
def GT():      return ["GT"]
def GTE():     return ["GTE"]
def LTE():     return ["LTE"]
def EQ():      return ["EQ"]
def AND():     return ["AND"]
def OR():      return ["OR"]
def NOT():     return ["NOT"]
def CONCAT():  return ["CONCAT"]
def HASH():    return ["HASH"]
def CALLER():  return ["CALLER"]
def ARG(i):    return ["ARG", i]
def MLOAD(m):  return ["MLOAD", m]
def MSTORE(m): return ["MSTORE", m]
def REQUIRE(): return ["REQUIRE"]
def RETURN():  return ["RETURN"]
def HALT():    return ["HALT"]

_SEP = "|"   # key separator so CONCAT(a, SEP, b) can't collide across differently-split keys


def key2(a_seq, b_seq):
    """Instructions leaving CONCAT(a, '|', b) on the stack, given sub-sequences that each push one value.
    Namespacing a map by two parts (e.g. gameId|caller) without collisions."""
    return [*a_seq, PUSH(_SEP), CONCAT(), *b_seq, CONCAT()]


# ---- generalized method patterns -----------------------------------------------------------------
def counter_methods(m="n", key="c"):
    """A single shared integer at map[key]: inc() += 1, get() -> value. Generalizes to any named tally."""
    return {
        "inc": [PUSH(key), PUSH(key), MLOAD(m), PUSH(1), ADD(), MSTORE(m), HALT()],
        "get": [PUSH(key), MLOAD(m), RETURN()],
    }


def accumulator_methods(m="acc"):
    """Per-caller running total in map[caller]: add(amount) requires amount>0 and adds it; of(addr) and
    mine() read a total. Generalizes tips, reputation, per-address vote weight, staking points."""
    return {
        "add":  [ARG(0), PUSH(0), GT(), REQUIRE(),                 # require amount > 0
                 CALLER(), CALLER(), MLOAD(m), ARG(0), ADD(), MSTORE(m), HALT()],
        "of":   [ARG(0), MLOAD(m), RETURN()],
        "mine": [CALLER(), MLOAD(m), RETURN()],
    }


def commit_reveal_methods():
    """Two-phase fair randomness, keyed by a gameId = ARG(0). Strict phase + player binding:
        commit(gameId, hash)   — commit phase ONLY (no reveals yet) and only the FIRST TWO players; each
                                 stores HASH(secret) and gets a fixed slot (1-based).
        reveal(gameId, secret) — only a committed player, once; proves HASH(secret)==their commit; the
                                 secret is recorded at their fixed slot.
        flip(gameId)           — once BOTH committed players revealed, returns parity of
                                 HASH(secret0 ‖ secret1) ∈ {0,1} (slot 0 ‖ slot 1).
    Binding matters: gating commit on `nrev==0` stops the second mover from committing AFTER seeing the
    other's revealed secret (which would let it CHOOSE the outcome), and gating reveal on having committed
    (max 2 committers) stops a third party from hijacking or DoSing the game via an extra reveal.
    KNOWN LIMITATION (inherent to commit-reveal): the LAST revealer already knows the result and can simply
    withhold its reveal to abort — so this is a fair-RESULT oracle for a demo, not an escrow. A real stake
    needs a reveal deadline + forfeit-to-opponent, settled on L1/the bridge (value can't live in this VM).
    Generalizes to sealed-bid auctions and lotteries."""
    K = key2([ARG(0)], [CALLER()])   # commit/slot/done are all keyed by gameId|caller
    return {
        "commit": [ARG(0), MLOAD("nrev"), NOT(), REQUIRE(),               # commit phase: no reveals yet
                   ARG(0), MLOAD("ncom"), PUSH(2), LT(), REQUIRE(),       # at most two players
                   *K, MLOAD("commit"), NOT(), REQUIRE(),                 # not already committed
                   *K, ARG(0), MLOAD("ncom"), PUSH(1), ADD(), MSTORE("slot"),  # slot = ncom+1 (1-based)
                   *K, ARG(1), MSTORE("commit"),                          # commit[gameId|caller] = hash
                   ARG(0), ARG(0), MLOAD("ncom"), PUSH(1), ADD(), MSTORE("ncom"), HALT()],
        "reveal": [*K, MLOAD("commit"), ARG(1), HASH(), EQ(), REQUIRE(),  # HASH(secret) == your commit
                   *K, MLOAD("done"), NOT(), REQUIRE(),                   # you haven't revealed yet
                   *K, PUSH(1), MSTORE("done"),
                   ARG(0), PUSH(_SEP), CONCAT(),                          # [gameId|]
                   *K, MLOAD("slot"), PUSH(1), SUB(),                     # [gameId|, idx]  (slot-1)
                   CONCAT(), ARG(1), MSTORE("rev"),                       # rev[gameId|idx] = secret
                   ARG(0), ARG(0), MLOAD("nrev"), PUSH(1), ADD(), MSTORE("nrev"), HALT()],
        "flip": [ARG(0), MLOAD("nrev"), PUSH(2), EQ(), REQUIRE(),
                 ARG(0), PUSH(_SEP), CONCAT(), PUSH(0), CONCAT(), MLOAD("rev"),
                 ARG(0), PUSH(_SEP), CONCAT(), PUSH(1), CONCAT(), MLOAD("rev"),
                 CONCAT(), HASH(), PUSH(2), MOD(), RETURN()],
    }


# ---- the first example contracts (deployable {method: bytecode} dicts) ----------------------------
COUNTER = counter_methods()
TIP_JAR = accumulator_methods("tips")
COIN_FLIP = commit_reveal_methods()

EXAMPLES = {"counter": COUNTER, "tip_jar": TIP_JAR, "coin_flip": COIN_FLIP}

# ABI = optional, non-consensus metadata: per method, the ARGUMENT NAMES a caller must pass (positionally,
# ARG(0), ARG(1), …) and a one-line DOC. The wallet renders labelled arg inputs + the doc from this; a
# deployer may ship an `abi` in the deploy blob so their contract is self-describing. Not committed to
# state_root (a UX hint), but deterministic (it rides the deploy blob, so every node stores the same one).
ABIS = {
    "counter": {
        "inc": {"args": [], "doc": "Increment the shared counter by 1."},
        "get": {"args": [], "doc": "Read the current counter value."},
    },
    "tip_jar": {
        "add":  {"args": ["amount"], "doc": "Add `amount` (>0) to YOUR running total."},
        "of":   {"args": ["address"], "doc": "Read the running total for an address."},
        "mine": {"args": [], "doc": "Read your own running total."},
    },
    "coin_flip": {
        "commit": {"args": ["gameId", "hash"], "doc": "Commit HASH(secret) for a game (commit phase; first two players)."},
        "reveal": {"args": ["gameId", "secret"], "doc": "Reveal your secret; it's checked against your commit."},
        "flip":   {"args": ["gameId"], "doc": "Once both revealed: the fair coin result, 0 or 1."},
    },
}

# what /exec/examples serves: name -> {code, abi}
LIBRARY = {name: {"code": EXAMPLES[name], "abi": ABIS.get(name, {})} for name in EXAMPLES}
