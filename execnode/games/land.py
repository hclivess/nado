"""Land — the title registry of the Land planet (doc/land.md): every plot is a native-asset NFT, and this contract holds
what the chain knows about each one — the commitment its owner last anchored, and who the owner lets build on it.

A PLOT IS A NATIVE ASSET. The operator wallet (ISSUER) issues plot p with an ordinary `asset_create` blob — `seed`
plot_seed(p), `dec` 0, `supply` 1, `mintable` false, `uri` its metadata — so a title lives in every wallet's Assets tab,
moves with `asset_transfer`, sells on the NFT marketplace (execnode/games/nft.py: fixed-price waves first, then anyone's
listings, offers and auctions, the issuer's royalty on every sale) and carries across a reroll with the asset ledger.
This contract never owns a title. Its id is derivable — asset_id(ISSUER, plot_seed(p)) = hash(ISSUER_DIGEST, seed) —
so neither the contract nor the page needs a registry: the contract recomputes it in-circuit on every call.

OWNERSHIP IS PROVEN BY SHOWING THE TITLE. A contract cannot read another account's balance (zkvm2 ABAL reads only its
own), so every owner action sends the plot's one unit IN as the call's asset value and pays it straight back to the
caller in the same call: only its holder can make the call, and the title never stays here. A title escrowed by a
marketplace listing cannot be shown, so a plot on sale is frozen (no anchor, no new builder) until it sells or is
unlisted — what the buyer sees anchored is what they buy.

ANCHORS ARE COMMITMENTS, NOT CONTENT. anchor(plot, commitment) records the owner's commitment to the plot's build: the
salted hash the Land client computes over the plot's block data (static/land-world.js plotCommitment). The chain sees
only the hash — a private interior stays private — while anyone handed the data and its salt can check it against the
chain. Each anchor bumps the plot's version and records the anchoring owner and height.

BUILDERS ARE GRANTED BY AN OWNER AND DIE WITH THEIR OWNERSHIP. allow(plot, builder) stores the GRANTOR's digest under
(plot, builder); the world server (scripts/land_server.py) honours a grant only while its grantor still holds the
title (builder_of == the current holder), so a sale voids the old owner's invitations with no cleanup call.

PLOT IDS: the planet is a cube-sphere — six faces of FACE_N x FACE_N plots of PLOT x PLOT blocks each.
plot = face * FACE_N^2 + row * FACE_N + col, every id below PLOT_MAX = 6 * 8192^2 < 2^32 (so field * 2^32 + plot never
aliases another field's slots — the storage-aliasing class, finding C2).

UPGRADABLE, ON PURPOSE (operator 2026-11-06: "make sure that the contract is not locked when deployed so we can keep
upgrading it"). It is deployed WITHOUT {"upgradable": false} and never `lock`ed, so its deployer can replace the code in
place (execnode/state.py op "upgrade": the cid and every storage cell are kept). INVARIANT for every upgrade: the field
numbers below and K_B are a storage layout already holding owners' anchors and grants — add new fields, never renumber
or reuse one (tests/test_a_land_title_is_shown_to_anchor_or_grant_and_a_sale_voids_the_old_owners_grants.py upgrades
the contract and reads every anchor and grant back).

Storage (field * 2^32 + plot; counts at field 0):
  counts: 1 anchored plots
  plot p: 10 commitment 11 version 12 height 13 anchoring owner (digest) 14 LIST (index of anchored plots, by order)
  hash(K_B, p, builder) -> the grantor's digest (0 = not a builder)
"""
from execnode import zkpy
from execnode.runtimes import zkvm_addr_digest

ISSUER = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f"   # the operator wallet that issues every title
FACE_N = 8192                     # plots along a cube face's edge
PLOT = 16                         # blocks along a plot's edge (a face is FACE_N * PLOT = 131072 blocks across)
PLOT_MAX = 6 * FACE_N * FACE_N    # 402,653,184 plots on the planet
SEED_TAG = 0x4C414E44 << 32       # "LAND": a title's asset seed is SEED_TAG | plot, apart from any other ISSUER asset
CNT_ANCHORED = 1
A_COMMIT, A_VER, A_H, A_BY, A_LIST = 10, 11, 12, 13, 14
K_B = 0x4C414E42                  # "LANB": the builder-grant hash-key tag; a hash never lands on a field*2^32+id slot


def plot_seed(plot):
    """The asset seed of plot `plot`'s title (asset_create `seed`)."""
    return SEED_TAG | plot


def plot_id(face, row, col):
    return (face * FACE_N + row) * FACE_N + col


def _word(m, n):
    """A 256-bit constant as a VM value. m.const carries 64 bits only (the immediate), so the word is rebuilt from its
    32-bit limbs, most significant first (Horner: a left-deep tree, two registers)."""
    v = m.const(n >> 224)
    for i in range(6, -1, -1):
        v = v * (1 << 32) + ((n >> (32 * i)) & 0xFFFFFFFF)
    return v


def _title(m, issuer_digest):
    """Require the caller to SHOW plot arg(0)'s title (its one unit sent in as the call's asset value), then hand it
    straight back. The asset id is recomputed here from the plot number, so no other asset can stand in for it."""
    m.require(m.arg(0) < PLOT_MAX)
    m.require(m.in_asset() == zkpy.hash(_word(m, issuer_digest), m.arg(0) + SEED_TAG))
    m.require(m.value() == 1)
    m.apay(m.in_asset(), m.caller(), m.const(1))


def build(issuer=ISSUER):
    issuer_digest = zkvm_addr_digest(issuer)
    c = zkpy.Contract()

    # anchor(plot, commitment) [ASSET VALUE = the plot's title, 1 unit, returned] — its holder records the commitment
    # to the plot's current build.
    with c.method("anchor") as m:
        _title(m, issuer_digest)
        m.require(m.arg(1) != 0)
        m.jnz(m.slot(A_VER, m.arg(0)).get() != 0, "seen")
        m.slot(A_LIST, m.slot(0, m.const(CNT_ANCHORED)).get()).set(m.arg(0))
        m.slot(0, m.const(CNT_ANCHORED)).set(m.slot(0, m.const(CNT_ANCHORED)).get() + 1)
        m.label("seen")
        m.slot(A_COMMIT, m.arg(0)).set(m.arg(1))
        m.slot(A_VER, m.arg(0)).set(m.slot(A_VER, m.arg(0)).get() + 1)
        m.slot(A_H, m.arg(0)).set(m.cursor())
        m.slot(A_BY, m.arg(0)).set(m.caller())
        m.ret(m.slot(A_VER, m.arg(0)).get())

    # allow(plot, builder) [title shown] — the holder lets `builder` build on the plot while they hold it.
    with c.method("allow") as m:
        _title(m, issuer_digest)
        m.require(m.arg(1) != m.caller())
        m.at(zkpy.hash(K_B, m.arg(0), m.arg(1))).set(m.caller())
        m.ret(m.const(1))

    # revoke(plot, builder) [title shown] — the holder withdraws a grant (theirs or a previous owner's).
    with c.method("revoke") as m:
        _title(m, issuer_digest)
        m.at(zkpy.hash(K_B, m.arg(0), m.arg(1))).set(m.const(0))     # writing 0 deletes the cell
        m.ret(m.const(0))

    # ---- read-only views (/exec/view) ---------------------------------------------------------------------------
    # builder_of(plot, addr) -> the digest of whoever granted `addr` on `plot` (0 = no grant); the server compares it
    # with the title's current holder.
    with c.method("builder_of") as m:
        m.ret(m.at(zkpy.hash(K_B, m.arg(0), m.arg(1))).get())

    return c.build()


def carry_in_flight(storage):
    """Nothing here counts old-chain heights or escrows anything: anchors, versions and grants cross a reroll as they
    are (the anchoring height is a record, not a deadline)."""
    return []


ABI = {
    "anchor":     {"args": ["plot", "commitment"], "value": True},
    "allow":      {"args": ["plot", "builder"], "value": True},
    "revoke":     {"args": ["plot", "builder"], "value": True},
    "builder_of": {"args": ["plot", "address"]},
    "_view": {
        "maps": {name: {"field": f, "index": "anchored"} for name, f in
                 (("commit", A_COMMIT), ("ver", A_VER), ("h", A_H), ("by", A_BY))},
        "indexes": {"anchored": {"cnt": CNT_ANCHORED, "list": A_LIST}},
        "addr": ["by"],
    },
}
