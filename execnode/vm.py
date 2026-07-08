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
_KNOWN = _BINOPS | {"PUSH", "POP", "DUP", "SWAP", "NOT", "HASH", "CALLER", "ARG",
                    "MLOAD", "MSTORE", "REQUIRE", "RETURN", "HALT"}


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


def run(code, method, caller, args, storage):
    """Execute code[method]. `storage` is {mapname: {key: int}}. Runs on a deep copy; returns
    (ok, return_value, new_storage). On a missing method, REQUIRE-fail, out-of-gas, or any runtime
    error it returns (False, None, <ORIGINAL storage>) — i.e. the call is a no-op (revert)."""
    import copy
    if method not in code:
        return (False, None, storage)
    st = copy.deepcopy(storage)
    stack = []
    gas = 0
    try:
        for ins in code[method]:
            gas += 1
            if gas > GAS_LIMIT:
                raise VMOutOfGas("gas limit exceeded")
            op = ins[0]
            if op == "PUSH":
                stack.append(ins[1])
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
            elif op == "NOT":
                stack.append(0 if stack.pop() else 1)
            elif op == "HASH":
                stack.append(_hash_value(stack.pop()))
            elif op in _BINOPS:
                b = stack.pop()
                a = stack.pop()
                if op == "ADD":
                    stack.append(_int(a) + _int(b))
                elif op == "SUB":
                    stack.append(_int(a) - _int(b))
                elif op == "MUL":
                    stack.append(_int(a) * _int(b))
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
                    stack.append(str(a) + str(b))
            elif op == "MLOAD":
                key = stack.pop()
                stack.append(st.get(ins[1], {}).get(str(key), 0))
            elif op == "MSTORE":
                val = _int(stack.pop())
                key = str(stack.pop())
                m = st.setdefault(ins[1], {})
                if val == 0:
                    m.pop(key, None)          # keep state minimal: a zero balance is absence
                else:
                    m[key] = val
            elif op == "REQUIRE":
                if not stack.pop():
                    raise VMRevert("REQUIRE failed")
            elif op == "RETURN":
                return (True, stack.pop() if stack else None, st)
            elif op == "HALT":
                return (True, None, st)
        return (True, None, st)
    except (VMRevert, VMOutOfGas, IndexError, KeyError, ValueError, TypeError):
        return (False, None, storage)
