"""
NADO execution-layer VM (Phase 1) — a minimal, DETERMINISTIC stack machine that the separate execution
nodes run over the ordered `blob` payloads pulled from L1. It is intentionally tiny: a stack, per-contract
key/value storage organised as named maps, gas as a step counter, and REQUIRE / RETURN. Values are ints
and strings only (JSON-safe), so contract state is canonical and any two execution nodes replaying the
same blob sequence reach byte-identical state.

This VM is NOT part of L1 consensus. It lives entirely beside the node (doc/execution-layer.md §3.2):
L1 orders + stores opaque blobs; this replays them. A VM bug can never fork the chain.

Contract shape:  { "<method>": [ [OP, arg?], ... ], ... }
  - the optional method "constructor" runs once at deploy (caller = deployer, args = []).
Opcodes:
  PUSH v · POP · DUP · SWAP · ADD SUB MUL DIV MOD · LT GT GTE LTE EQ AND OR · NOT · CONCAT
  HASH · CALLER · ARG i · MLOAD map · MSTORE map · REQUIRE · RETURN · HALT

HASH pops one value and pushes blake2b(canonical(value)) as a 256-bit int — the primitive that makes
commit-reveal contracts (fair coin flip, sealed-bid, lotteries) possible on a deterministic VM: a player
commits HASH(secret), later reveals `secret`, and the contract re-hashes to check it. DIV/MOD revert on a
zero divisor (so the call is a no-op, never a crash).
"""
import hashlib
import json as _json

GAS_LIMIT = 100_000


class VMError(Exception):
    pass


class VMRevert(VMError):
    pass


class VMOutOfGas(VMError):
    pass


_BINOPS = {"ADD", "SUB", "MUL", "DIV", "MOD", "LT", "GT", "EQ", "GTE", "LTE", "AND", "OR", "CONCAT"}
# VALUE/PAY/CURSOR (#value): the escrow primitive that lets a contract hold + move real bridged NADO — VALUE
# pushes the NADO escrowed with THIS call (debited from the caller into the contract), PAY pops (amount, to)
# and schedules a payout FROM the contract's escrow to `to`, CURSOR pushes the L1 block height (for deadlines).
# BEACON (#randao): pops an epoch and pushes that epoch's FINALIZED consensus RANDAO beacon as a 256-bit int
# — the grind-resistant, unpredictable-until-finalized randomness NADO's bonded validators produce by
# commit-reveal. It reverts if the epoch's beacon isn't finalized yet, so a game can only read a beacon that
# was fixed AFTER its bets closed. This is what lets a game settle OBJECTIVELY from chain randomness with no
# player secret-reveal and no trusted party (doc/execution-layer.md).
# BLOCKHASH (#randao): pops an L1 block height and pushes that FINALIZED block's hash as a 256-bit int. A block's
# hash is unpredictable until the block is mined but immutable once finalized and IDENTICAL on every node, so it
# is objective chain randomness a contract can pin to a FUTURE height: a table fixes settle_height when it opens,
# bets close at that height, and the result is derived from BLOCKHASH(settle_height) — nobody can know it while
# betting is open, nobody has to "spin", and every node computes the same outcome. Reverts if the height is in
# the future (> cursor) or older than the exec node retains, so a game can only read a hash fixed AFTER bets close.
_KNOWN = _BINOPS | {"PUSH", "POP", "DUP", "SWAP", "NOT", "HASH", "CALLER", "ARG",
                    "MLOAD", "MSTORE", "REQUIRE", "RETURN", "HALT", "VALUE", "PAY", "CURSOR", "BEACON", "BLOCKHASH",
                    "JUMP", "JUMPI"}
_MAX_PAYOUTS = 16          # bound the payouts one call can schedule (anti-abuse; a flip settles to ONE winner)


def _hash_value(v):
    """Deterministic blake2b of a canonical encoding of `v` -> 256-bit int (commit-reveal primitive)."""
    return int.from_bytes(hashlib.blake2b(_json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")




def validate_code(code):
    """Reject malformed bytecode at deploy time (so a bad deploy blob is ignored, not crashing)."""
    if not isinstance(code, dict) or not code:
        raise VMError("contract code must be a non-empty {method: bytecode} object")
    for method, prog in code.items():
        if not isinstance(method, str) or not isinstance(prog, list):
            raise VMError(f"bad method {method!r}")
        for ins in prog:
            if not isinstance(ins, list) or not ins or ins[0] not in _KNOWN:
                raise VMError(f"unknown/invalid instruction {ins!r} in {method}")
            if ins[0] in ("PUSH", "ARG", "MLOAD", "MSTORE") and len(ins) != 2:
                raise VMError(f"{ins[0]} needs exactly one arg")
            if ins[0] == "PUSH" and not isinstance(ins[1], (int, str)):
                raise VMError("PUSH literal must be int or str")
            if ins[0] == "ARG" and (not isinstance(ins[1], int) or isinstance(ins[1], bool)):
                raise VMError("ARG index must be int")
            if ins[0] in ("MLOAD", "MSTORE") and not isinstance(ins[1], str):
                raise VMError("MLOAD/MSTORE map name must be str")
    return True


def _int(x):
    """Type-gate a stack value as an int (bools excluded); a mismatch raises VMRevert -> call is a no-op."""
    if not isinstance(x, int) or isinstance(x, bool):
        raise VMRevert(f"expected int, got {x!r}")
    return x


# Gas counts INSTRUCTIONS, not operand SIZE — so without this cap a handful of cheap ops (DUP;MUL squaring,
# or DUP;CONCAT string-doubling) grows a single value to gigabytes, and because replay is deterministic it
# OOMs every exec node at the same L1 height (a whole-layer liveness kill for one blob fee). Bound the size of
# any value a growth op produces; oversize -> VMRevert (the call reverts, never a crash/OOM).
_MAX_INT_BITS = 4096
_MAX_STR_LEN = 4096

def _bound(v):
    """Reject an over-large int/str operand (VMRevert). Returned unchanged when within bounds."""
    if isinstance(v, int):
        if v.bit_length() > _MAX_INT_BITS:
            raise VMRevert("int operand too large")
    elif isinstance(v, str):
        if len(v) > _MAX_STR_LEN:
            raise VMRevert("string operand too large")
    return v


def run(code, method, caller, args, storage, value=0, cursor=0, beacons=None, block_hashes=None):
    """Execute code[method]. `storage` is {mapname: {key: int|str}}. `value` is the NADO (raw) escrowed with
    this call (already debited from the caller into the contract by the exec); `cursor` is the L1 height.
    Runs on a deep copy; returns (ok, return_value, new_storage, payouts) where payouts is [(to, amount)] the
    contract scheduled via PAY (the exec pays them FROM the contract's escrow). On a missing method,
    REQUIRE-fail, out-of-gas, or any runtime error it returns (False, None, <ORIGINAL storage>, []) — a no-op."""
    import copy
    if method not in code:
        return (False, None, storage, [])
    st = copy.deepcopy(storage)
    stack = []
    payouts = []
    gas = 0
    prog = code[method]
    pc = 0
    try:
        while pc < len(prog):
            gas += 1                          # every executed instruction costs gas, so any loop halts at GAS_LIMIT
            if gas > GAS_LIMIT:
                raise VMOutOfGas("gas limit exceeded")
            ins = prog[pc]
            op = ins[0]
            if op == "PUSH":
                stack.append(_bound(ins[1]))
            elif op == "POP":
                stack.pop()
            elif op == "DUP":
                stack.append(stack[-1])
            elif op == "SWAP":
                stack[-1], stack[-2] = stack[-2], stack[-1]
            elif op == "ARG":
                i = ins[1]
                stack.append(args[i] if 0 <= i < len(args) else 0)
            elif op == "CALLER":
                stack.append(caller)
            elif op == "VALUE":
                stack.append(_int(value))
            elif op == "CURSOR":
                stack.append(_int(cursor))
            elif op == "BEACON":
                ep = _int(stack.pop())
                bv = (beacons or {}).get(ep)
                if bv is None:                       # not finalized yet (or before genesis) -> revert (no-op call)
                    raise VMRevert("beacon for epoch not available")
                stack.append(_int(bv))
            elif op == "BLOCKHASH":
                hgt = _int(stack.pop())
                hv = (block_hashes or {}).get(hgt)
                if hv is None:                       # future height, or older than the exec node retains -> revert
                    raise VMRevert("block hash for height not available")
                stack.append(_int(hv))
            elif op == "JUMP":                       # generic control flow: pop a RELATIVE offset, pc += offset.
                t = pc + _int(stack.pop())           # relative so a code block composes wherever it's embedded
                if not (0 <= t < len(prog)):
                    raise VMRevert("jump target out of range")
                pc = t
                continue                             # skip the pc += 1 below
            elif op == "JUMPI":                      # pop offset, then cond; pc += offset iff cond != 0 (else fall through)
                d = _int(stack.pop())
                cond = stack.pop()
                if cond:
                    t = pc + d
                    if not (0 <= t < len(prog)):
                        raise VMRevert("jump target out of range")
                    pc = t
                    continue
            elif op == "PAY":
                amount = _int(stack.pop())
                to = stack.pop()
                if amount < 0 or not isinstance(to, str) or not to:
                    raise VMRevert("bad PAY (amount>=0, non-empty str recipient)")
                if amount > 0:
                    payouts.append((to, amount))
                    if len(payouts) > _MAX_PAYOUTS:
                        raise VMRevert("too many payouts")
            elif op == "NOT":
                stack.append(0 if stack.pop() else 1)
            elif op == "HASH":
                stack.append(_hash_value(stack.pop()))
            elif op in _BINOPS:
                b = stack.pop()
                a = stack.pop()
                if op == "ADD":
                    stack.append(_bound(_int(a) + _int(b)))
                elif op == "SUB":
                    stack.append(_bound(_int(a) - _int(b)))
                elif op == "MUL":
                    stack.append(_bound(_int(a) * _int(b)))
                elif op == "DIV":
                    if _int(b) == 0:
                        raise VMRevert("division by zero")
                    stack.append(_int(a) // _int(b))
                elif op == "MOD":
                    if _int(b) == 0:
                        raise VMRevert("modulo by zero")
                    stack.append(_int(a) % _int(b))
                elif op == "LT":
                    stack.append(1 if _int(a) < _int(b) else 0)
                elif op == "GT":
                    stack.append(1 if _int(a) > _int(b) else 0)
                elif op == "GTE":
                    stack.append(1 if _int(a) >= _int(b) else 0)
                elif op == "LTE":
                    stack.append(1 if _int(a) <= _int(b) else 0)
                elif op == "EQ":
                    stack.append(1 if a == b else 0)
                elif op == "AND":
                    stack.append(1 if (a and b) else 0)
                elif op == "OR":
                    stack.append(1 if (a or b) else 0)
                elif op == "CONCAT":
                    stack.append(_bound(str(a) + str(b)))
            elif op == "MLOAD":
                key = stack.pop()
                stack.append(st.get(ins[1], {}).get(str(key), 0))
            elif op == "MSTORE":
                val = stack.pop()             # int OR str (JSON-safe) — strings let a contract store addresses
                if not isinstance(val, (int, str)) or isinstance(val, bool):
                    raise VMRevert("MSTORE value must be int or str")
                _bound(val)
                key = str(stack.pop())
                m = st.setdefault(ins[1], {})
                if val == 0 or val == "":
                    m.pop(key, None)          # keep state minimal: a zero / empty value is absence
                else:
                    m[key] = val
            elif op == "REQUIRE":
                if not stack.pop():
                    raise VMRevert("REQUIRE failed")
            elif op == "RETURN":
                return (True, stack.pop() if stack else None, st, payouts)
            elif op == "HALT":
                return (True, None, st, payouts)
            pc += 1                                  # advance (JUMP/JUMPI `continue` past this to keep their target)
        return (True, None, st, payouts)
    except (VMRevert, VMOutOfGas, IndexError, KeyError, ValueError, TypeError):
        return (False, None, storage, [])
