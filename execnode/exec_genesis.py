"""The exec layer's genesis: contracts carried across a reroll (doc/stwo-migration.md §6.2).

A reroll used to start the exec layer EMPTY: every contract vanished, its pot was refunded and its game state lost, and
every frontend pointed at a dead contract until execnode.games.redeploy ran — which was forgotten more than once and
failed silently. The carry (tools/alphanet6_carryforward.py --exec-genesis) now writes the contracts it carries into
genesis_data/exec_genesis.json, tagged with the generation it was built for:

    {"generation": G,
     "contracts": {cid: {"code", "abi", "deployer", "runtime", "upgradable", "storage"}},
     "bridge":    {cid: "<raw>"},                         # each carried contract's pot (a decimal string, never a float)
     "assets": {aid: {...}}, "abal": {aid: {holder: n}}, "allow": {aid: {owner: {spender: n}}},   # exec assets, verbatim
     "zk_addrs": {digest: addr},                           # the digest->address registry payouts resolve through
     "stwo_pool": {"commitments": [cm, ...], "nullifiers": [nf, ...]},   # the Stwo shielded pool (order kept; no marks)
     "stwo_value": "<raw>", "pool_fees": "<raw>"}          # its value, and what else SHIELD_ESCROW holds (burned)

and every exec node loads it into a FRESH state (cursor -1, no contracts) — at boot and at an in-process reset to
genesis — so the new chain starts from identical bytes on every node. Contract ids are kept, so frontends need no
rewiring. The pots stay in L1's BRIDGE_ESCROW (genesis.py seeds the `bridgeescrow:default` counter from this same file
and refuses a mismatch), so the bridge invariant BRIDGE_ESCROW == Σ bridge + pending exits holds from block 0.

INVARIANT: only the tracked repository file is read — never a node-local copy — and a file that cannot be parsed RAISES,
because a node that silently started empty would compute a different genesis root from the rest of the fleet.
NADO_EXEC_GENESIS overrides the path for tests only. A file for another generation is ignored (the live chain of the
generation it was not built for starts empty, exactly as before).

THE STWO POOL CARRIES (doc/stwo-migration.md §5.1 "The carry"): a reroll that made holders unshield would publish every
holder's amount and destination — it would de-anonymise the whole pool. So the commitments (in their order: a note's
leaf position is part of its spend witness), the nullifier set (an already-spent note stays spent) and `stwo_value`
(the cap every Stwo spend is checked against) start the new layer, which therefore has the SAME `stwo_root` and
`stwo_nfset` as the old one, and an old note spends against the carried root. The block MARKS restart empty: they are
[old-chain height, note count] pairs, and on the new chain those heights name other blocks — a mark above the new tip
makes the first append raise ("a pool append below the last block that appended") and would stay "recent" for as long
as the new chain is shorter than the old. With no marks the anchors a spend may name are the carried tree's root and
its append window (StwoShieldedPool rebuilds both from the commitments), so a wallet re-proves an in-flight spend
against the carried root. `pool_fees` is everything else SHIELD_ESCROW holds — fees burned inside a pool and deposits
whose notes were never created — so the shielded invariant (ops/invariants.check_shielded) is EXACT from block 0, and
genesis.py refuses an L1 allocation whose SHIELD_ESCROW is not stwo_value + pool_fees. Every value is a pure function
of this file.
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
                   "assets": doc.get("assets") or {}, "abal": doc.get("abal") or {}, "allow": doc.get("allow") or {},
                   "zk_addrs": {str(k): str(v) for k, v in sorted((doc.get("zk_addrs") or {}).items())},
                   **_shield_part(doc)}
    _CACHE[p] = out
    return out


def _shield_part(doc) -> dict:
    """The carried Stwo pool of a genesis document, validated: {"stwo_pool": {commitments, nullifiers}, "stwo_value": int,
    "pool_fees": int, "shield": bool} ("shield" = the document carries the shielded section at all; one written before
    the Stwo carry existed does not, and then nothing about the pool or SHIELD_ESCROW is asserted, exactly as before).
    A document that names block marks, a nullifier or commitment in any spelling but the one (shielded_stwo.is_digest),
    a duplicate commitment, or value with no note RAISES: a node that read it differently from the rest of the fleet
    would start from a different root."""
    from execnode import shielded_stwo as _S
    shield = any(k in doc for k in ("stwo_pool", "stwo_value", "pool_fees"))
    sp = doc.get("stwo_pool") or {}
    if set(sp) - {"commitments", "nullifiers"}:
        raise ValueError(f"exec genesis: the carried Stwo pool names {sorted(set(sp) - {'commitments', 'nullifiers'})} "
                         "— its block marks restart empty (old-chain heights mean nothing on the new chain)")
    cms, nfs = list(sp.get("commitments") or []), list(sp.get("nullifiers") or [])
    if not all(_S.is_digest(x) for x in cms + nfs):
        raise ValueError("exec genesis: a carried Stwo commitment or nullifier is not 64 lowercase hex")
    if len(set(nfs)) != len(nfs) or nfs != sorted(nfs):
        raise ValueError("exec genesis: the carried Stwo nullifiers must be sorted and distinct")
    _S.StwoShieldedPool(cms, nfs)                     # duplicate commitments, capacity: the pool's own checks raise
    sv, fees = int(doc.get("stwo_value") or 0), int(doc.get("pool_fees") or 0)
    if sv < 0 or fees < 0:
        raise ValueError("exec genesis: a negative stwo_value or pool_fees")
    if sv and not cms:
        raise ValueError("exec genesis: stwo_value with no Stwo note to hold it")
    return {"stwo_pool": {"commitments": cms, "nullifiers": nfs}, "stwo_value": sv, "pool_fees": fees, "shield": shield}


def shield_total() -> int:
    """What L1 genesis must hold in SHIELD_ESCROW for the carried pool: stwo_value + pool_fees (0 without a carried
    genesis). genesis.py asserts it only when the document carries the shielded section (load()["shield"])."""
    g = load()
    return (g["stwo_value"] + g["pool_fees"]) if g else 0


def pots_total() -> int:
    """Σ carried pots (raw) — what L1 genesis must hold in BRIDGE_ESCROW for them. 0 without a carried genesis."""
    g = load()
    return sum(g["bridge"].values()) if g else 0


def apply(state) -> bool:
    """Load the carried contracts into `state` if it is a fresh layer (cursor -1, no contracts). Returns whether it did.
    Idempotent: a state that already holds contracts, or is past genesis, is left alone."""
    g = load()
    if not g or state.cursor != -1 or state.contracts or state.stwo_pool.commitments:
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
    # THE PAYEE REGISTRY (review 2026-10-11): carried storage names its players by field DIGEST, and a PAY to a digest the
    # registry cannot resolve REVERTS (runtimes.split_io). The registry is learned from call boundaries, so a fresh layer
    # knew nobody: a carried pets battle could not refund either owner until both had made some exec call on the new
    # chain. INVARIANT: the registry crosses with the storage that names it. It is not in the state root (state.py), so
    # the genesis root is unchanged; every node loads the same file, so every node resolves the same payees.
    state.zk_addrs = dict(g.get("zk_addrs") or {})
    # THE STWO POOL (module docstring): commitments in order, the spent set, the value cap — and NO marks (old-chain
    # heights). INVARIANT: pool_value == stwo_value, because the carry refuses notes in every other pool and any
    # pool_value stwo_value does not explain (tools/alphanet6_carryforward.exec_value_the_carry_would_drop); pool_fees
    # makes SHIELD_ESCROW == pool_value + pool_fees exact from block 0 (ops/invariants.check_shielded).
    from execnode.shielded_stwo import StwoShieldedPool
    sp = g.get("stwo_pool") or {}
    state.stwo_pool = StwoShieldedPool(sp.get("commitments") or [], sp.get("nullifiers") or [])
    state.stwo_value = int(g.get("stwo_value") or 0)
    state.pool_value = state.stwo_value
    state.pool_fees = int(g.get("pool_fees") or 0)
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
