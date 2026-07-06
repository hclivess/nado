"""
Alias system: a human-readable name -> owner address, so a user can send to a short name instead of a
49-char ndo… address. Three on-chain ops via the reserved recipient "alias" (the operation is carried
in the tx `data`: {"op": "register"|"transfer"|"unregister", "name": <alias>, "to": <addr>}):

  * register    — claim a FREE name; the sender becomes the owner. Pays ALIAS_REGISTRATION_FEE (anti-squat).
  * transfer    — the owner reassigns the name to another address (`to`). Pays MIN_TX_FEE.
  * unregister  — the owner frees the name. Pays MIN_TX_FEE.

And RESOLUTION: an ordinary transfer whose recipient is a registered alias credits the alias's CURRENT
owner (account_ops.reflect_transaction resolves it). All revert-symmetric with NO side record — the tx
`sender` is always the prior owner for transfer/unregister, and a register only succeeds on a free name,
so rollback restores the exact prior mapping (and reverts are LIFO, so resolution is consistent too).
"""
import re

from ops import kv_ops
from ops.address_ops import validate_address
from protocol import (RESERVED_RECIPIENTS, ALIAS_MIN_LEN, ALIAS_MAX_LEN,
                      ALIAS_REGISTRATION_FEE, MIN_TX_FEE)

_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def valid_alias_name(name) -> bool:
    """A syntactically valid, non-colliding alias name: ALIAS_MIN_LEN..ALIAS_MAX_LEN chars, lowercase
    [a-z0-9_-] starting with a letter, NOT a reserved word, and NOT address-shaped ("ndo…")."""
    if not isinstance(name, str):
        return False
    if not (ALIAS_MIN_LEN <= len(name) <= ALIAS_MAX_LEN):
        return False
    if not _ALIAS_RE.match(name):
        return False
    if name in RESERVED_RECIPIENTS:
        return False
    if name.startswith("ndo"):                      # never let an alias be mistaken for an address
        return False
    return True


def resolve_alias(name):
    """The owner address if `name` is a registered alias, else None. A plain address / reserved word is
    not an alias (returns None), so callers do `resolve_alias(r) or r`."""
    if not isinstance(name, str) or not valid_alias_name(name):
        return None
    return kv_ops.alias_get(name)


def _op_fields(transaction):
    """(op, name, to) from an alias tx's `data`; raises AssertionError (rejecting the tx) when data
    isn't an object, so validate/apply never touch a malformed payload."""
    data = transaction.get("data")
    if not isinstance(data, dict):
        raise AssertionError("alias tx data must be an object")
    return data.get("op"), data.get("name"), data.get("to")


def validate_alias_op(transaction):
    """Validate an `alias` reserved-recipient tx (raises on invalid). Reads committed alias state
    (deterministic). Fee sufficiency vs. the sender's balance is enforced by the spending validators."""
    sender = transaction["sender"]
    op, name, to = _op_fields(transaction)
    assert transaction["amount"] == 0, "alias op moves no coins (amount must be 0)"
    assert valid_alias_name(name), f"Invalid alias name {name!r}"
    owner = kv_ops.alias_get(name)
    if op == "register":
        assert owner is None, f"Alias {name!r} is already registered"
        assert transaction["fee"] >= ALIAS_REGISTRATION_FEE, "alias registration fee too low"
    elif op == "transfer":
        assert owner == sender, f"Only the owner can transfer alias {name!r}"
        assert validate_address(to, allow_reserved=False), f"Invalid alias transfer target {to!r}"
        assert transaction["fee"] >= MIN_TX_FEE, "alias transfer fee too low"
    elif op == "unregister":
        assert owner == sender, f"Only the owner can unregister alias {name!r}"
        assert transaction["fee"] >= MIN_TX_FEE, "alias unregister fee too low"
    else:
        raise AssertionError(f"Unknown alias op {op!r}")


def apply_alias(transaction, sender, logger, revert=False):
    """Apply/revert the alias registry change. Revert-symmetric with no side record."""
    op, name, to = _op_fields(transaction)
    if op == "register":
        kv_ops.alias_del(name) if revert else kv_ops.alias_put(name, sender)
    elif op == "transfer":
        kv_ops.alias_put(name, sender if revert else to)   # revert restores the sender as owner
    elif op == "unregister":
        kv_ops.alias_put(name, sender) if revert else kv_ops.alias_del(name)
    return True
