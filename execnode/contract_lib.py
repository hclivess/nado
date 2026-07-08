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
    """Two-phase fair randomness, keyed by a gameId = ARG(0):
        commit(gameId, hash)   — first, each of two players stores HASH(secret) (computed off-chain).
        reveal(gameId, secret) — later, each proves HASH(secret)==their commit; the secret is recorded.
        flip(gameId)           — once both revealed, returns parity of HASH(secret0 ‖ secret1) ∈ {0,1}.
    Fair because neither player learns the other's secret before committing. Generalizes to sealed-bid
    auctions (compare revealed bids) and lotteries (more players/one more MOD)."""
    return {
        # store HASH(secret) at commit[gameId|caller]; refuse a second commit from the same player
        "commit": [*key2([ARG(0)], [CALLER()]), DUP(), MLOAD("commit"), NOT(), REQUIRE(),
                   ARG(1), MSTORE("commit"), HALT()],
        # verify HASH(secret)==commit, then append the secret at rev[gameId|idx] and bump nrev[gameId]
        "reveal": [*key2([ARG(0)], [CALLER()]), MLOAD("commit"), ARG(1), HASH(), EQ(), REQUIRE(),
                   ARG(0), MLOAD("nrev"),                          # [idx]
                   ARG(0), PUSH(_SEP), CONCAT(), SWAP(), CONCAT(), # [gameId|idx]
                   ARG(1), MSTORE("rev"),                          # rev[gameId|idx] = secret
                   ARG(0), ARG(0), MLOAD("nrev"), PUSH(1), ADD(), MSTORE("nrev"), HALT()],
        # both revealed -> fair coin = parity of HASH(secret0 ‖ secret1)
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
