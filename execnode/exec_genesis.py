"""The exec layer's genesis: contracts carried across a reroll (doc/stwo-migration.md §6.2).

A reroll used to start the exec layer EMPTY: every contract vanished, its pot was refunded and its game state lost, and
every frontend pointed at a dead contract until execnode.games.redeploy ran — which was forgotten more than once and
failed silently. The carry (tools/alphanet6_carryforward.py --exec-genesis) now writes the contracts it carries into
genesis_data/exec_genesis.json, tagged with the generation it was built for:

    {"generation": G,
     "contracts": {cid: {"code", "abi", "deployer", "runtime", "upgradable", "storage"}},
     "bridge":    {cid: "<raw>"},                         # each carried contract's pot (a decimal string, never a float)
     "assets": {aid: {...}}, "abal": {aid: {holder: n}}, "allow": {aid: {owner: {spender: n}}}}   # exec assets, verbatim

and every exec node loads it into a FRESH state (cursor -1, no contracts) — at boot and at an in-process reset to
genesis — so the new chain starts from identical bytes on every node. Contract ids are kept, so frontends need no
rewiring. The pots stay in L1's BRIDGE_ESCROW (genesis.py seeds the `bridgeescrow:default` counter from this same file
and refuses a mismatch), so the bridge invariant BRIDGE_ESCROW == Σ bridge + pending exits holds from block 0.

INVARIANT: only the tracked repository file is read — never a node-local copy — and a file that cannot be parsed RAISES,
because a node that silently started empty would compute a different genesis root from the rest of the fleet.
NADO_EXEC_GENESIS overrides the path for tests only. A file for another generation is ignored (the live chain of the
generation it was not built for starts empty, exactly as before).
"""
import copy
import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE = {}


def path() -> str:
    return os.environ.get("NADO_EXEC_GENESIS") or os.path.join(_HERE, "genesis_data", "exec_genesis.json")


def load():
    """The carried genesis {"contracts": ..., "bridge": {cid: int}} for THIS generation, or None."""
    p = path()
    if p in _CACHE:
        return _CACHE[p]
    out = None
    if os.path.exists(p):
        from protocol import CHAIN_GENERATION
        with open(p) as f:
            doc = json.load(f)                        # a malformed file raises: never "no genesis"
        if int(doc.get("generation", -1)) == int(CHAIN_GENERATION):
            contracts = doc.get("contracts") or {}
            bridge = {cid: int(v) for cid, v in (doc.get("bridge") or {}).items()}
            stray = sorted(set(bridge) - set(contracts))
            if stray:
                raise ValueError(f"exec genesis: pots for contracts it does not carry: {stray}")
            if any(v < 0 for v in bridge.values()):
                raise ValueError("exec genesis: a negative pot")
            out = {"contracts": contracts, "bridge": bridge,
                   "assets": doc.get("assets") or {}, "abal": doc.get("abal") or {}, "allow": doc.get("allow") or {}}
    _CACHE[p] = out
    return out


def pots_total() -> int:
    """Σ carried pots (raw) — what L1 genesis must hold in BRIDGE_ESCROW for them. 0 without a carried genesis."""
    g = load()
    return sum(g["bridge"].values()) if g else 0


def apply(state) -> bool:
    """Load the carried contracts into `state` if it is a fresh layer (cursor -1, no contracts). Returns whether it did.
    Idempotent: a state that already holds contracts, or is past genesis, is left alone."""
    g = load()
    if not g or state.cursor != -1 or state.contracts:
        return False
    for cid, rec in sorted(g["contracts"].items()):
        state.contracts[cid] = copy.deepcopy(rec)
    for cid, amt in sorted(g["bridge"].items()):
        if amt:
            state.bridge[cid] = amt
    # EXEC ASSETS carry verbatim: an asset record holds no height, its id derives from (issuer, seed), and it has no L1
    # form to fold into — so the only way a held token survives a reroll is to start the new layer holding it.
    state.assets = copy.deepcopy(g.get("assets") or {})
    state.abal = {a: {h: int(n) for h, n in hs.items()} for a, hs in (g.get("abal") or {}).items()}
    state.allow = copy.deepcopy(g.get("allow") or {})
    state._touch()
    return True


def genesis_root(state_cls=None) -> str:
    """The exec root a fresh node computes at cursor -1: the empty layer plus the carried contracts. Equals
    protocol.EXEC_GENESIS_ROOT when there is no carried genesis."""
    import tempfile
    if state_cls is None:
        from execnode.state import ExecState as state_cls
    with tempfile.TemporaryDirectory(prefix="nado-exec-genesis-") as d:
        st = state_cls(os.path.join(d, "s.json"))     # a path with no file: the empty layer
        apply(st)
        return st.state_root()
