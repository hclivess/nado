"""
Sovereign — the persistent nation-war world contract (doc/sovereign.md). Unlike every other NADO game
(2-player duels, house-banked tables) this is ONE shared, always-on world: a single GLOBAL append-only
ACTION LOG that every player writes to and every browser replays. The contract is deliberately THIN — a
recorder, not a referee. The full economy + combat rules live in the browser engine
(static/sovereign-engine.js); each client folds the whole log into the world state (settling every nation
lazily between the actions that touch it) and re-derives a byte-identical world, exactly like the
stormhold/scrapline free-actor move log but world-scale.

Log entry i (keyed by index):
  la[i]  field 10   actor address (the caller — who acted)
  lc[i]  field 11   seed height = cursor + GAP (a FUTURE block; a raid's ±luck roll draws from bh(lc[i]),
                     unpredictable when the action was signed — the shared cards.js chain-draw convention)
  le[i]  field 12   packed action (op + params; see engine encAction)
  lt[i]  field 13   target address for a raid (0 for economy actions)
Counter:
  mc     slot 1     log length

ONE method: act(enc, target, ply). enc packs the action; target is 0 (economy) or the victim's address
string (raid); ply BINDS the entry to index == mc (a stale re-signed action can never double-append or
land out of order — the same anti-rollback trick as the duel move). The engine referees legality: an
illegal action (can't afford, hoarding, shielded target, unarmed) is a REPLAY no-op, and the tx fee that
carried it is the only cost — so the contract needs no per-action validation, just ordering.

No escrow, no house: Sovereign is a free strategy world; the L1 tx fee both funds and rate-limits it.
"""
from execnode import zkvmasm

MC = 1                       # log length (single slot)
LA, LC, LE, LT = 10, 11, 12, 13
GAP = 2                      # seed height = cursor + GAP (future block at signing time)
MAXLOG = 1_000_000

# act(enc, target, ply): r0=enc, r1=target(addr digest or 0), r2=ply
ACT = f"""
    movi r4 {MC}
    sload r3 r4            ; r3 = mc (current log length / next index)
    mov r5 r3
    eq r5 r2
    require r5             ; ply binding: append at exactly mc
    movi r5 {MAXLOG}
    mov r6 r3
    lt r6 r5
    require r6            ; log bounded
    ctx r6 caller         ; r6 = actor digest
    movi r4 {LA * 2**32}
    add r4 r3
    sstore r4 r6          ; la[mc] = actor
    ctx r5 cursor
    movi r7 {GAP}
    add r5 r7
    movi r4 {LC * 2**32}
    add r4 r3
    sstore r4 r5          ; lc[mc] = cursor + GAP (raid seed height)
    movi r4 {LE * 2**32}
    add r4 r3
    sstore r4 r0          ; le[mc] = enc
    movi r4 {LT * 2**32}
    add r4 r3
    sstore r4 r1          ; lt[mc] = target
    movi r4 {MC}
    movi r5 1
    add r5 r3
    sstore r4 r5          ; mc++
    ret r0
"""

SRC = {"act": ACT}

ABI = {
    "act": {"args": ["enc", "target", "ply"]},
    "_view": {
        "maps": {"la": LA, "lc": LC, "le": LE, "lt": LT},
        "index": {"cnt": MC, "range": True},   # keys 0..mc-1 (the whole log)
        "addr": ["la", "lt"],                  # resolve actor/target digests back to L1 addresses
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
