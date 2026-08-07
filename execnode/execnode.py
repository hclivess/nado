"""
NADO execution node (Phase 1) — the "beside the node" process.

It TAILS an L1 NADO node over plain HTTP, pulls the ordered `blob` payloads out of FINALIZED blocks,
replays them through the deterministic zkVM (execnode.state / execnode.zkvm), and persists the resulting
contract state. It also serves a small READ-ONLY query API so wallets and tools can read contract state
and run view methods. It never speaks to L1 consensus — a VM bug here can't fork the chain
(doc/execution-layer.md §3.2). Run one per operator who wants programmability; phones do not.

Env:
  NADO_L1_URL          L1 node base URL     (default http://127.0.0.1:9173)
  NADO_EXEC_STATE      state file path      (default ./exec_state.json)
  NADO_EXEC_PORT       query API port       (default 9273)
  NADO_EXEC_BIND       bind address         (default 127.0.0.1 — loopback-only; set 0.0.0.0 to let remote
                                             browsers reach the shielded pool. H-7: the mutating POST endpoints
                                             are unauthenticated, so exposing them is opt-in.)
  NADO_EXEC_MAX_INFLIGHT  concurrent prove/apply cap (default 2 — bounds CPU/memory under a POST flood)
  NADO_EXEC_POLL       poll seconds         (default 5)

Run:  python execnode/execnode.py
Query:  curl localhost:9273/exec/root
        curl 'localhost:9273/exec/view?cid=<id>&method=balanceOf&args=["<address>"]'
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from protocol import chain_clock as _chain_clock
from aiohttp import web

from execnode.state import ExecState

L1 = os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/")
STATE_PATH = os.environ.get("NADO_EXEC_STATE", "exec_state.json")
PORT = int(os.environ.get("NADO_EXEC_PORT", "9273"))
# H-7: loopback by default — the /exec POST endpoints prove/verify/apply and mutate state without auth, so a
# public bind is opt-in (a browser-reachable shielded pool sets NADO_EXEC_BIND=0.0.0.0). Even when exposed, the
# STARK size bound (stark.MAX_TRACE_ROWS) and the in-flight cap below bound a single request and a flood.
BIND = os.environ.get("NADO_EXEC_BIND", "127.0.0.1")
MAX_INFLIGHT = max(1, int(os.environ.get("NADO_EXEC_MAX_INFLIGHT", "2")))
MAX_BODY_BYTES = int(os.environ.get("NADO_EXEC_MAX_BODY", str(16 * 1024 * 1024)))   # cap POST size (proofs are ~1-4MB)
POLL = float(os.environ.get("NADO_EXEC_POLL", "5"))
# STALE-EXEC corroboration window: how many consecutive polls must show our cursor OUTRUNNING L1's finalized
# tip before we treat the on-disk state as reroll-stranded and reset to genesis (see tail_loop). ~30s so a
# slow L1 restart reporting a transient finalized=0 can never trigger it; a genuinely purged L1 stays >window.
STALE_RESET_POLLS = max(3, int(30 / POLL))

# --- DA layer: erasure-coded availability for the shielded-transfer STARK proofs (too big for an L1 blob,
# so only the transfer STATEMENT + the proof's `commitment` ride on-chain). This node keeps a local DaStore;
# NADO_DA_URL is a peer DA node to fetch a proof from by commitment when we don't hold it locally.
from ops.da_store import DaStore, reconstruct_from
from ops import da as _da
DA_DIR = os.environ.get("NADO_EXEC_DA", "exec_da")
DA_N_MAX = 64          # bound attacker-supplied meta.n so a lied manifest can't drive an unbounded fetch loop
DA_URL = os.environ.get("NADO_DA_URL", "").rstrip("/")
DA_K = int(os.environ.get("NADO_DA_K", "4"))
DA_N = int(os.environ.get("NADO_DA_N", "8"))
# ROLLING WINDOW. Without this the store is append-only: MEASURED 2026-08-06, exec_da held 41 GB in 109
# objects (1,916 files) — every settle proof published during the 2026-08-04/05 transport work, ~390 MB each
# (a ~120 MiB proof erasure-coded k=4/n=8). That was 99.8% of the node's footprint against 75 MB of actual
# blocks: a snapshot node had quietly become an archival one. DaStore.prune() had existed all along for
# exactly this and was called from nothing but a test.
# Nothing needs the old objects: SETTLE_PROOF_DEPTH_GATED means a settle proof is verified near the TIP and
# deep blocks accept without re-fetching it, so an object is only reachable for a short window after it is
# published. The bound is a COUNT, which caps disk at retain x blob size regardless of settle cadence.
DA_RETAIN = int(os.environ.get("NADO_DA_RETAIN", "24"))
DA = DaStore(DA_DIR, retain=DA_RETAIN)
# H-7: cap concurrent proving/applying so a flood of POSTs can't exhaust CPU/memory (each prove is a full
# STARK; each apply verifies a ~1MB proof). Created lazily on the running loop.
_inflight = None
def _sem():
    """Lazily create the in-flight semaphore on the RUNNING event loop (import time has no loop)."""
    global _inflight
    if _inflight is None:
        _inflight = asyncio.Semaphore(MAX_INFLIGHT)
    return _inflight
# Phase 2: if this node is a BONDED validator, post settlement attestations of its computed state root
# (needs its keys.dat via HOME). Always on; settles at most every SETTLE_EVERY blocks.
SETTLE = True                    # settling is what an exec node IS for; not a flag
# CADENCE DEPENDS ON WHETHER WE ARE PROVING, and the difference is 48x in bytes.
#
# A bare quorum attestation is a few hundred bytes, so settling often is free and gives bridge exits a
# fresher settled tip — 5 blocks (~30 s) is right for that.
#
# A settle-with-PROOF is ~97 MiB and its size is independent of the span: with the fold off,
# prove_settlement_sparse emits ONE bound epoch for the whole span, and the payload is dominated by FRI
# query openings rather than by call count. So proving every 5 blocks pays the same ~97 MiB for 5 blocks of
# work that proving every 240 blocks pays for 240 — 280 GiB/day versus 5.8 GiB/day, purely from cadence.
# Defaulting the proving cadence to the protocol's own max span is therefore a pure win with no consensus
# change; it is also the largest single lever available before the fold works. Overridable either way via
# See doc/settle-proof-transport.md for the measurements.
# Proving is unconditional, so the proving cadence is THE cadence — there is no bare-attestation-only mode
# to keep a 5-block cadence for.
if True:
    # THE EPOCH RULE, NOT THE SPAN CAP, IS THE BINDING CONSTRAINT — and defaulting to the span cap made the
    # prover silently impossible. _build_settlement_proof refuses any span that crosses a dividend epoch
    # boundary (`sc // EPOCH_LENGTH != cur // EPOCH_LENGTH`), because a dividend moves the RECORDS half and
    # the proof pins records UNCHANGED across the span. SETTLE_PROOF_MAX_SPAN is 4 * EPOCH_LENGTH, so
    # settling at the cap guarantees every span straddles ~4 boundaries: condition 3 returns None every
    # time and a proof is NEVER built. Observed live 2026-08-03 — the prover was switched on and the very
    # next settle was a bare attestation, with nothing in the log to say why.
    #
    # So the proving cadence must be a FRACTION of an epoch. At EPOCH_LENGTH/2 a span conforms whenever
    # both ends land in the same epoch. The span cap is kept as the upper bound it always was — it simply
    # can never bind while the epoch rule is 4x tighter.
    #
    # THIS COMMENT USED TO CLAIM the straddling spans "re-anchor the justified tip at the boundary so the
    # following span conforms". They did not: a straddling span skips the proof and settles BARE at
    # whatever `cur` happens to be, leaving the tip at an arbitrary offset that straddles again just as
    # easily. A fixed cadence only self-aligns when the cursor advances one block at a time; the real
    # cursor advances in BATCHES, so each settle fires at last+SETTLE_EVERY+jitter and the offset DRIFTS.
    # Measured 2026-08-04: 95 logged epoch-boundary skips, the largest skip class by far. maybe_settle now
    # does the re-anchor deliberately (see SETTLE_EPOCH there), which makes it drift-proof.
    try:
        from protocol import SETTLE_PROOF_MAX_SPAN as _SPAN, EPOCH_LENGTH as _EPOCH
        _SETTLE_EVERY_DEFAULT = max(1, min(int(_SPAN), int(_EPOCH) // 2))
        _SETTLE_EPOCH_DEFAULT = int(_EPOCH)
    except Exception:
        _SETTLE_EVERY_DEFAULT = 30
        _SETTLE_EPOCH_DEFAULT = 60
SETTLE_EVERY = _SETTLE_EVERY_DEFAULT      # derived from EPOCH_LENGTH; not an operator knob
SETTLE_EPOCH = _SETTLE_EPOCH_DEFAULT      # the dividend epoch a proven span may not cross
# VALIDITY PROVING IS UNCONDITIONAL. No flag, no opt-in, no way to run a node that quietly settles on a
# bonded attestation because someone forgot an env var. A settle carries a STARK validity proof; the bare
# attestation exists ONLY as the degradation path when a proof cannot be produced or is refused, and every
# such degradation names its reason in the log.
#
# This was opt-in while proving was accidentally running in PYTHON — 12+ minutes for one prove, ~75% of a
# core, RSS to 1.8 GB, which starved L1 into "Forked above the finality floor — re-anchoring" (2026-08-04).
# That was never a reason to make proving optional; it was a reason to fix the dispatch. stark.prove only
# reaches the Rust arena for the "recursion"/"alghash2" backends, and the settle path was defaulting to
# BLAKE2B, which the arena does not implement. With settlement_sparse defaulting to ALGHASH2 (7afb5728) the
# same proof takes 110s at protocol strength and verifies in 2s.
SETTLE_PROVE = True
# THE K->1 FOLD IS UNCONDITIONAL TOO. It collapses the span's K exec proofs into ONE recursion bundle, so L1
# verifies a single bundle instead of K per-segment stark.verify calls. It is gated at the call site on
# there being calls to fold (an empty span takes the unfolded path) and is self-VERIFIED at protocol
# strength before posting, so an unverifiable bundle is never broadcast. It could not complete in Python.
#
# CORRECTION (2026-08-06): this used to end "on the arena it is the only route to a proof small enough to
# settle on chain". THE FOLD DOES NOT SHRINK THE PROOF — it makes it BIGGER. prove_settlement_sparse keeps
# `segments` and ADDS `recursive`; nothing strips seg["proof"]. What the bundle replaces is the K
# per-segment exec-proof VERIFICATIONS, not the bytes (verify_settlement_sparse's docstring says exactly
# that, and the per-segment transition binding / calls commitment / kv chain still run). Size tracks the
# FRI query count — 320 queries x 0.381 MiB ~= 122 MiB, matching the 120.31 MiB measured — and the fold's
# outer proof runs at the SAME protocol strength (settlement_sparse: oq = num_queries), so it adds a second
# O(queries) object. What actually solved the size problem was carrying the proof INLINE
# (protocol.MAX_INLINE_TX_BYTES). The fold's real value is L1 verification cost.
# The size win people expect from "K->1" is still available and unimplemented: if the bundle
# authoritatively re-verifies each segment's exec proof, the wire may only need each segment's PUBLIC part
# — see doc/settle-proof-transport.md §7 for the caveat that must be checked first.
SETTLE_FOLD = True
# SETTLE_PROVE_TIMEOUT: seconds a single settle-prove may run before we give up on it and post a
# BARE attestation instead. Without a bound the settle loop never returns and the chain stops settling.
#
# RAISED 1200 -> 2400 ON A MEASUREMENT, not a guess. 1200s was sized against an UNFOLDED prove (~1-3 min,
# calls=0). The first FOLDED prove ever run on live data — 2026-08-06, once the games were driven so a
# span actually contained calls — came in at:
#     [settle-prove] cursor=42050 calls=1 net_updates=7 |
#         prove_epoch=8.9s sparse_projection=264.3s prove_transition=883.6s | total 1156.9s
# i.e. ONE call with 7 state updates costs ~883 s in prove_transition alone (~126 s per update; that is
# where the recursion fold lives). The prove SUCCEEDED at 1156.9 s of internal work, but the settle loop
# measures WALL CLOCK from when it started the worker, and that had already crossed 1200 s — so the first
# successful real fold was abandoned 43 seconds after finishing:
#     settle-with-proof SKIPPED cursor 42050 — prove exceeded SETTLE_PROVE_TIMEOUT=1200s (fold=True)
# 2400 s leaves room for a span with several calls. This is a SAFETY BOUND, not a target: the real fix is
# making the fold cheaper (see SETTLE_FOLD_FAN_IN and the untouched constant factors — blowup=8 from
# max_degree=8, the ext-field arena penalty, allocator churn), and the bound must not be raised to hide
# that. It still sits far below the 5h07m a non-completing fold once burned.
# HOW MANY RECORDS UPDATES ONE PROOF MAY COVER. prove_transition emits ONE STARK PER UPDATE, so both cost
# and size are LINEAR in the update count.
#
# THE CONSTRAINT CHANGED FROM TIME TO SIZE. This was 6, sized against ~170-240 s per update against
# SETTLE_PROVE_TIMEOUT=2400 s. That per-update cost was never the AIR's price — it was W=29 separate column
# Merkle trees, 79.6% of the prove, because merkle_update.prove_update left stark.prove's row_commit at its
# False default while the KV half had always derived it from the backend (see stark.row_commit_default).
# Row-committed, one update measures 35-45 s to prove and 10.83 MiB on the wire, so:
#
#     TIME:  2400 s / ~45 s          = ~53 updates
#     SIZE: (191.94 MiB - ~9 MiB KV) / 10.83 MiB = 16 updates      <-- BINDING
#
# so the cap is now SIZE-derived, and _RECORDS_CAP_FITS_INLINE below asserts it against the real budget
# rather than trusting this comment to stay true.
#
# WHAT THIS DOES AND DOES NOT UNBLOCK, CORRECTED BY MEASUREMENT. I shipped this cap believing a boundary
# span was "one T_DIV_BAL position per present miner, plus a few others from ordinary activity", which made
# SHORTENING THE SPAN the lever: the per-miner part is a floor, the rest is proportional to span length.
# Logging the tag breakdown killed that immediately — the live line reads
#
#     19 net updates from 38 effects [DIV_BAL=38]
#
# There are no others. EVERY effect is dividend accrual: 38 effects = two epoch boundaries x 19 present
# miners, netting to 19 distinct positions. So the update count is simply THE NUMBER OF PRESENT MINERS, one
# boundary is enough to reach it, and shortening the span cannot go below it. The floor is not 13-and-shrink
# but 19-and-GROWING, because it tracks fleet size.
#
# That makes the remaining gap STRUCTURAL, not a tuning problem: 19 x 10.83 MiB + 9 MiB = 215 MiB against a
# 191.94 MiB budget. Raising MAX_INLINE_TX_BYTES would cover today's 19 and lose again as miners join, on a
# wire whose peers already strain to PULL a ~120 MiB tx inside their admit budget. The lever that scales is
# making K updates cost less than K proofs — either the K->1 recursion bundle (already built by
# prove_transition(fold=True); today it is carried ALONGSIDE the per-update proofs rather than replacing
# them, so it costs verification time and not bytes), or one STARK over several updates.
#
# WHAT IS NOT THE LEVER: dropping NUM_QUERIES. 88% of the proof is FRI queries (320 x 30.5 KiB), so cutting
# them would close the gap immediately — and fri.py sizes 320 to clear 128 bits on the PROVABLE
# (Johnson-bound) branch, 320*0.4 + 18 grind ~ 146 bits, deliberately not the conjectured branch most
# deployments accept. Buying tx size with security bits is not a prover-side decision.
# DISABLED (0) PENDING A FIX FOR L1 VERIFICATION COST. A records-bearing settle is CORRECT — both halves
# verify ok=True on L1 — but its records half takes ~1020-1073 s to verify, and that is long enough to hurt
# the node that submitted it: after one landed in the mempool this node stalled at block 7364 for 200+ s
# while the rest of the fleet ran on to 7374, with the expired 51.53 MiB tx still in the mempool and L1
# burning CPU on it. Producing a proof that wedges the producer is worse than riding the bonded quorum,
# which is always correct and merely slower.
#
# 0 makes every records-bearing span decline (len(net) > 0), so spans ride the quorum exactly as they did
# before the feature. Everything else stays shipped and tested — the AIR, DIRP, K=9, the guards — and this
# flips back to 72 the moment verification fits inside a landing window.
SETTLE_RECORDS_MAX_UPDATES = int(os.environ.get("NADO_SETTLE_RECORDS_MAX_UPDATES", "0"))
# Measured 2026-08-06 at EXEC_TREE_DEPTH=256, row-committed, encoded exactly as the submit path encodes it
# (json.dumps(separators=(",", ":"), sort_keys=True)). Per PROOF, not per update — several updates now share
# one STARK (state_transition.DEFAULT_BATCH), and proof size grows with log T, so the marginal update is
# nearly free while the marginal PROOF is not:
#
#     K   T       prove s   MiB     MiB/update   peak RSS
#     1   16384     35.0    10.82     10.82       ~0.8 GB
#     2   32768     57.7    11.90      5.95        2.4 GB   <-- shipped
#     3   65536    215.6    13.03      4.34        6.7 GB
#     4   65536    332.6    13.03      3.26        8.7 GB
#
# K=2 is the knee. It is the last size that is also FASTER per update than not batching at all (28.9 s vs
# 35 s), because 3 and 4 spill into T=65536 and pay for ~35% padding; and its 2.4 GB peak leaves the exec
# node and the box's other work alone, where 4's 8.7 GB does not. Bigger K wins on bytes and loses on
# memory — memory is quadratic in K (a size-N inverse-denominator vector PER BOUNDARY, and boundaries grow
# with K too) while the byte win is only logarithmic.
SETTLE_RECORDS_PROOF_BYTES = 15 << 20
# What the KV half of the same settle tx costs alongside it — 8.77 MiB observed on chain, rounded up.
SETTLE_KV_HALF_BYTES = 9 << 20
SETTLE_PROVE_TIMEOUT = 2400      # safety bound, not a feature switch: a prove that outruns this is
                                 # abandoned and the settle goes bare rather than halting the chain.
# Largest settle tx we will try to submit INLINE. L1's /submit_transaction caps bodies at 8 MiB, so this
# sits just under it; anything bigger is published to DA and the tx carries only the commitment. An inline
# proof is strictly better when it fits (it settles the root trustlessly with no quorum), so this is a
# ceiling, not a preference.
# NOT a protocol fact — the previous comment here said so and was wrong. Nothing in consensus bounds
# transaction size; the binding limit was ops/net_ops.MAX_TX_BODY (1 MiB), which this 7 MiB value already
# EXCEEDED, so an "inline" proof anywhere near this size could never have been submitted anyway. Both are
# now keyed to protocol.MAX_INLINE_TX_BYTES so a real ~120 MiB proof rides inside the tx instead of going
# to DA — which cannot deliver it on this fleet, where only one node runs a DA store.
_MAX_INLINE_TX_BYTES = __import__("protocol").MAX_INLINE_TX_BYTES
# Everything a settle tx carries BESIDES the proof: sender address, ML-DSA-44 signature (~2420 B) and
# public key (1312 B) in hex, txid, recipient, a handful of ints. A few KiB in total; 64 KiB is a ceiling
# with room to spare. Used to decide inline-vs-DA from the PROOF's serialized size alone, so the ~120 MiB
# tx never has to be serialized just to be measured (that cost ~160 s on the event loop, per the DA
# publish path below).
SETTLE_TX_ENVELOPE_MAX = 64 * 1024
# Derived here, once the envelope size is known: the proof may be as large as the network's tx ceiling
# minus everything else the tx carries.
SETTLE_INLINE_MAX = _MAX_INLINE_TX_BYTES - SETTLE_TX_ENVELOPE_MAX
# THE RECORDS CAP MUST ACTUALLY FIT. SETTLE_RECORDS_MAX_UPDATES is derived from this budget, and a comment
# claiming so is worth nothing once someone raises the cap by env var or edits MAX_INLINE_TX_BYTES. A proof
# that is built and then refused for size is the worst outcome available: it costs the full prove (~45 s per
# update), stalls the settle cadence while it runs, and lands nothing. Fail here, at import, instead.
def _records_bytes(n_updates):
    """Wire cost of the records half for `n_updates` — counted in PROOFS, since several updates share one."""
    from execnode.stark import state_transition as _SX
    batch = max(1, int(_SX.DEFAULT_BATCH))
    return -(-int(n_updates) // batch) * SETTLE_RECORDS_PROOF_BYTES     # ceil-div: proofs, not updates


_RECORDS_CAP_FITS_INLINE = (SETTLE_KV_HALF_BYTES
                            + _records_bytes(SETTLE_RECORDS_MAX_UPDATES)) <= SETTLE_INLINE_MAX
if not _RECORDS_CAP_FITS_INLINE:
    from execnode.stark import state_transition as _SX0
    _b = max(1, int(_SX0.DEFAULT_BATCH))
    _fits = ((SETTLE_INLINE_MAX - SETTLE_KV_HALF_BYTES) // SETTLE_RECORDS_PROOF_BYTES) * _b
    raise RuntimeError(
        f"SETTLE_RECORDS_MAX_UPDATES={SETTLE_RECORDS_MAX_UPDATES} cannot fit inline: "
        f"{SETTLE_KV_HALF_BYTES >> 20} MiB KV half + {-(-SETTLE_RECORDS_MAX_UPDATES // _b)} proof(s) x "
        f"{SETTLE_RECORDS_PROOF_BYTES >> 20} MiB exceeds SETTLE_INLINE_MAX={SETTLE_INLINE_MAX >> 20} MiB. "
        f"At most {_fits} records updates fit at batch={_b} — lower the cap, raise the batch (memory is "
        f"quadratic in it), or raise protocol.MAX_INLINE_TX_BYTES knowing peers must PULL the whole tx "
        f"inside their admit budget.")
# How long to wait for L1's verdict on a PROOF-CARRYING settle. L1 verifies the proof inline before it
# answers, and that is measured at 94.2 s for a real 118.57 MiB proof, so anything near the bare-settle
# budget guarantees a client-side timeout on a proof that is perfectly valid. Generous because the settle
# task is DETACHED (e1000cbd) — waiting here costs nothing but this task.
#
# RAISED 300 -> 1200 FOR THE RECORDS-BEARING CASE, WHICH THE OLD VALUE WAS NEVER SIZED FOR. 300 came from a
# 118.57 MiB KV-ONLY proof verifying in 94.2 s. A records-bearing proof is 169.44 MiB AND adds 13 batched
# merkle-update verifications on top of the KV half, and this budget has to cover ALL of: aiohttp
# serialising ~169 MiB of nested Python to JSON, the upload, L1 re-parsing it, and both halves verifying.
# The first one ever built died on the clock at exactly ~305 s:
#     02:46:22  settle-with-proof span→4380: 1 segment(s), tx 169.44 MiB
#     02:51:27  settle error at execnode.py:1723 in _submit: TimeoutError
# with L1 producing blocks normally throughout — so the chain was never blocked; only this task gave up.
#
# THIS IS NOT HIDING A COST, IT IS MEASURING ONE. Nobody knows what a records-bearing submit actually costs
# because no attempt has been allowed to finish. The submit now logs its elapsed time on BOTH paths, so the
# next one reports a real number and this constant can be set from it — or, if the number is bad, the
# conclusion is that the PROOF must shrink (fewer/cheaper proofs per span), not that the budget must grow
# again. Waiting longer is free here; the settle task is detached and the loop keeps settling bare.
SETTLE_SUBMIT_TIMEOUT_PROOF = int(os.environ.get("NADO_SETTLE_SUBMIT_TIMEOUT_PROOF", "1200"))
# HOW FAR AHEAD A PROOF-CARRYING SETTLE AIMS max_block. A settle is an EXACT-LANDING tx (protocol.py: it
# "lands at exactly max_block"), and L1 spends ~94 s — about 16 blocks — verifying the proof INLINE before
# the submit even returns. So a deadline computed before the submit is already ~14 blocks in the PAST by
# the time the tx reaches the pool: it is accepted, then expires unincluded. Observed live 2026-08-04:
# "SETTLE-WITH-DA-PROOF ... → L1" logged (L1 said result=True) yet no settle tx for that cursor appears in
# any block and /get_settled never moved.
#
# This is the same anti-pattern protocol.py records under RESERVED_TX_MARGIN: tip+2/+4/+5 "forked
# alphanet-12 three times on 2026-07-28" because an exact-landing tx could not propagate in time. 60 blocks
# (~6 min) covers the verification plus propagation and stays far under TX_LANDING_WINDOW (360), so a tx
# admitted against a slightly-behind peer still fits.
# RAISED for the INLINE proof, then LOWERED AGAIN once the proof stopped being huge. 60 blocks (~6 min)
# covered "verification plus propagation" when the tx was small — a DA-carried settle ships only a
# commitment. When the tx became the ~120 MiB inline proof, propagation measured ~8 MINUTES end to end
# (2026-08-06): the first run where all three peers actually held it finished AFTER the exact-landing
# target had passed, so the tx was correct, propagated, and still unlandable. Hence 180.
#
# 1affffac made the proof 8.92 MiB instead of 120.31, and the margin is not free: because a settle is an
# EXACT-LANDING tx (protocol.py:115 — it "lands at exactly max_block"), the margin IS a settlement STALL.
# The exec node must hold every bare settle until the proven span lands, or it would advance the justified
# tip past the span the proof covers. MEASURED on the cursor-46538 proof: submitted 12:35, next settle
# 12:55 — ~20 minutes of frozen settlement for one proof.
#
# RE-MEASURED 2026-08-06 13:12 on a live 8.92 MiB proof (cursor 46892), polling each peer's own
# /transaction_pool until it held the tx (/tmp/proppropagate.py):
#     185.100.232.131   +3.4 s
#     185.184.192.210   +4.2 s
#     208.87.242.141   +31.7 s
# measured from 10 s after the submit line, so ~42 s end to end against the ~480 s the 180 was sized for.
# Block time measured the same minute: 6.0 s/block. So 60 blocks = ~6 min = 8.6x the observed worst case,
# and it halves-then-some the settlement stall (18 min -> 6 min).
#
# WHY NOT LOWER STILL: an exact-landing tx must be held by whoever produces THAT SPECIFIC block, not merely
# by someone. Block production on this chain is ~18 distinct producers per 66 blocks, and only the 3 peers
# above can be polled — propagation to the rest is unmeasured, so the 8.6x is doing real work. The failure
# mode is also asymmetric but bounded: too small and the tx expires unincluded, wasting one prove and
# falling back to a bare settle (recoverable, and the status quo for weeks); too large and settlement
# freezes for every proof. Stays far under TX_LANDING_WINDOW (360), so a tx admitted against a
# slightly-behind peer still fits.
SETTLE_PROOF_TX_MARGIN = 60
# THE SAME RUNWAY, SIZED FOR A RECORDS-BEARING PROOF. Its records half verifies on L1 in ~1073 s (measured,
# 27 effects) = ~179 blocks at 6 s, against the 60 above which was sized for ~42 s of propagation. 280
# blocks is ~28 min: over 1.5x the measured verification, and still well under TX_LANDING_WINDOW (360).
# Raise it only against a NEW measurement of the RECORDS half — the verification cost tracks the update
# count, and the update count tracks fleet size, so this is a constant with a moving target underneath it.
SETTLE_PROOF_RECORDS_TX_MARGIN = int(os.environ.get("NADO_SETTLE_RECORDS_TX_MARGIN", "280"))
# Hard ceiling on the publish+submit hold, and it must EXCEED what it is holding for, or it expires mid
# pipeline and hands the race back to the bare settles it exists to suppress.
#
# THE OLD VALUE DID NOT. SETTLE_SUBMIT_TIMEOUT_PROOF + 120 = 420 s against a publish measured at ~112-139 s
# followed by a submit budget of SETTLE_SUBMIT_TIMEOUT_PROOF (300 s) — i.e. up to ~439 s of pipeline under a
# 420 s ceiling. The hold lapsed, a bare settle advanced the justified tip, and the finished proof was then
# refused for aiming at a tip we had moved ourselves. Observed repeatedly 2026-08-04:
#     [ INFO ] Candidate excludes pool tx 23e34dd950ea90cb: Settle proof pre_root must extend the settled tip
#     settle ns=default not accepted: 'Settle proof pre_root must extend the settled tip'
# The block builder DROPS the tx from every candidate, so it never reaches a block at all — this is not a
# validation-cost race, it is self-inflicted.
#
# Derived from the two bounds it actually spans, rather than a round number: the submit budget plus a
# publish allowance with real margin. The prove phase is NOT covered here and does not need to be — it is
# held by _settle_proving and separately bounded by SETTLE_PROVE_TIMEOUT.
SETTLE_HOLD_MAX_S = SETTLE_SUBMIT_TIMEOUT_PROOF + 900
# True while a settle-prove worker thread is outstanding. asyncio cannot kill that thread, so this is what
# stops a timed-out prove from stacking a new one every cadence until the box dies.
_settle_proving = False
# True while the RECORDS half is being proven. A SEPARATE flag, and the distinction is the whole point.
#
# _settle_proving covers the KV prove and is set ~60 lines AFTER _build_records_half is called, so it is
# False for the entire multi-minute records window. Guarding the records prove on it — which is exactly what
# I shipped in 3b2644d8 — checks a flag that NOBODY RAISES during the window being protected, so every
# settle cadence (~8 s) still walked straight in and started another one. The instrumentation showed it
# unchanged after the "fix":
#     01:04:35  batch 1/13 K=2 T=32768  55.2s (cum  55.2s) rss=0.91GB
#     01:05:39  batch 1/13 K=2 T=32768 113.2s (cum 113.2s) rss=2.70GB
# Two concurrent invocations again, same pid, index still stuck at 1/13.
#
# So the records prove gets its own flag, set immediately before the call and cleared in a `finally`. Unlike
# _settle_proving it CAN be cleared that way: the records prove is awaited (asyncio.to_thread) rather than
# detached, so when the await returns the work really is over. _settle_proving deliberately uses a
# done-callback instead, because wait_for gives up while its thread keeps running.
_records_proving = False
# True from the moment a proof EXISTS until its settle has been submitted — i.e. across the publish and the
# submit, which _settle_proving does NOT cover. That flag is cleared by the prove THREAD's done-callback, so
# it goes False at "BUILT" while ~230 s of publish (139 s) and inline L1 verification (94 s) still lie ahead.
# Bare settles resumed in that window and walked the justified tip forward, and the finished proof was then
# refused for aiming at a tip we had moved ourselves. Observed live 2026-08-04: two proofs built from
# pre-state 21780 while the settled tip reached 21840.
_settle_publishing = 0.0          # time.time() when a proof-carrying settle entered publish+submit, else 0
# A proof-carrying settle that L1 ACCEPTED is still racing: it is an EXACT-LANDING tx, so it sits in the
# mempool until its own max_block — measured 22:15 -> block 24829, about five minutes — and a bare settle
# during that wait advances the justified tip and invalidates it. The publish hold released at SUBMIT
# ("the attempt is over"), which is true of the SUBMISSION and false of the TRANSACTION, so:
#     22:15:19 SETTLE-WITH-DA-PROOF cursor 24690 (settled tip 24660, pre_root correct, tx in the pool)
#     22:17:55 SETTLE ns=default            <- bare, carried the tip 24660 -> 24758
#     22:18:24 Candidate excludes pool tx 3492566cf165ec37: Settle proof pre_root must extend the settled tip
# THE GUARD'S LIFETIME MUST MATCH WHAT IT GUARDS — third time today. {ns: {"cursor", "max_block"}}, held
# until the settled tip reaches that cursor (it landed) or the height passes max_block (it expired).
_settle_pending = {}
# Resubmitting a BUILT-AND-PUBLISHED proof against a fresh landing block. A settle is EXACT-LANDING, so it
# can only be included by whoever produces exactly its max_block — and this validator wins ~19% of blocks
# (measured: 5 of 26, against ~14 distinct producers), while no other producer can realistically include it
# (that would mean fetching 118 MiB from DA and verifying it, ~21.7 s, inside a ~6 s slot). One shot is a
# ~19% coin flip on work that took ~5 minutes of proving.
#
# BOUND BY TIME, NOT BY A COUNT. The first cut allowed 6 attempts and live they were consumed in about two
# minutes. A count is the wrong unit because the retry itself is nearly free (the proof and its DA blob are
# reused, so the tx is ~8 KB); what actually costs anything is holding the justified tip still, which keeps
# bridge exits looking at a staler settlement.
#
# SIZED FROM THE MEASURED RATE, NOT THE ASSUMED ONE. This comment first claimed ~18 s per attempt, from the
# retry targeting latest+2 (~3 blocks). Live, attempts are CADENCE-driven, not miss-driven — a retry only
# goes out on the next maybe_settle poll — so the real spacing is ~45 s:
#     23:19 cursor 25230, attempt 13, 594s/600s held  ->  13 shots in 600 s, not 30
# and our block share is 19.3% (MEASURED over 301 blocks: 58 ours, 56 distinct producers). So 600 s bought
# P(miss) = 0.807^13 ≈ 6%, and this cycle lost that coin flip after ~5 minutes of proving.
#
# THE CEILING ONLY BINDS IN THE UNLUCKY TAIL. Expected attempts to land is 1/0.193 ≈ 5.2, i.e. ~234 s, so
# almost every cycle finishes far inside the budget and raising it costs nothing in the common case — while
# in the tail it saves a whole 118 MiB proof from being thrown away and reproved. 1200 s ≈ 26 shots,
# P(miss) ≈ 0.4%.
SETTLE_RESUBMIT_MAX_S = 1200
# Give up the hold early if the tx has not REACHED THE PEERS, because then it cannot land no matter how
# many landing blocks we try. MEASURED 2026-08-04, the whole reason this exists:
#     GIVING UP after 44 attempt(s) over 1217s
# 44 misses at our measured 19.3% block share is P ~ 1e-4 — not luck. A settle carrying proof_da is not
# ADMITTED by peers at all: validate_transaction resolves it via _fetch_da_proof under an 8s bound, while a
# peer needs ~118 MiB from the single DA node plus ~4.4s decode and ~21.7s verify (~36s), so it times out
# into ProofUnavailable. After 15 minutes of gossip our pool held it and all three peers held ZERO. And
# since every node deterministically builds the WINNER's block, when we win, a peer's candidate — built
# from a pool without our tx — is what gets adopted ("Remote block: True", 0 txs).
#
# So holding the justified tip for 20 minutes per cycle buys nothing and costs real liveness: bridge exits
# keep looking at a stale settlement. Detect the actual condition instead of guessing a budget — ask the
# peers whether they have it. This is self-correcting: once a proof becomes cheap enough for peers to admit
# (the K->1 fold), propagation succeeds and the hold runs its full course again with no change here.
# RAISED for the INLINE proof. 90 s was measured against a DA-carried settle, whose tx is tiny (it carries
# only a commitment) — so if peers did not hold it within 90 s they never would. An inline settle is the
# opposite: the tx IS the ~120 MiB proof, so reaching a peer legitimately takes a push of that body
# (measured 3.2 s and 18.0 s for 50 MiB to the two peers, i.e. up to ~45 s for 120 MiB) PLUS the peer
# verifying the proof before it answers (~22-94 s). Those add to more than 90 s, so the give-up fired while
# propagation was still in progress and healthy:
#     GIVING UP after 1 attempt(s) over 185s (tip is 40818, pre-state was 40818)
# The check is still worth having — it is what stops a hold from burning 20 minutes on a tx that can never
# land — it just has to outlast an honest transfer.
SETTLE_PROPAGATION_GRACE_S = 900
# Backstop only, so a pathological loop (blocks arriving far faster than expected) cannot spin unbounded.
SETTLE_RESUBMIT_MAX = 200
# STRONG REFERENCES to the detached settle tasks. asyncio keeps only a WEAK reference to a running task, so
# a task whose last strong reference is dropped can be garbage-collected MID-AWAIT — silently, with no
# result, no exception and no done-callback. The tail loop assigned each task to a local that it reassigned
# on the very next poll, so a maybe_settle sitting on a 240s prove was unreferenced for essentially all of
# its life. Observed live 2026-08-04: a prove completed ("[settle-prove] ... total 239.9s") and then
# NOTHING followed it — no DA publish, no self-check failure, no error, no settle. This set is what keeps
# them alive; entries are discarded when they finish.
_settle_tasks = set()


def _settle_task_done(_task):
    """Surface a crash in the DETACHED settle task. Fire-and-forget must not mean fire-and-never-know: an
    un-retrieved exception on a discarded task is swallowed by asyncio and the node would just quietly stop
    settling."""
    try:
        _task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[execnode] settle task failed: {type(e).__name__}: {e}", flush=True)


def _clear_settle_proving(_task):
    """Release the in-flight guard when the prove THREAD actually finishes (not when we stop waiting)."""
    global _settle_proving
    _settle_proving = False
    try:
        _task.result()                                     # surface a prover crash instead of swallowing it
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        print(f"[execnode] settle-prove worker ended with {type(e).__name__}: {e}", flush=True)
# SETTLED-CHECKPOINT BOOTSTRAP (idle-GC companion, see protocol.py GC note): a COLD exec node can no
# longer replay dividend accrual from genesis once L1 prunes ancient recert rows — instead it adopts a
# donor's snapshot VERIFIED against the L1-settled root (trust-minimized: the quorum vouches for the
# root, the joiner recomputes it from the payload). Set NADO_EXEC_BOOTSTRAP=http://<donor-exec>:9273.
BOOTSTRAP = os.environ.get("NADO_EXEC_BOOTSTRAP", "").rstrip("/")
# per-ns stash of the snapshot AT our last accepted settle, PRE-SERIALIZED to a JSON string
# (aliasing the live state dicts would let later mutations drift the payload away from its root) —
# what /exec/state_snapshot serves so a joiner can verify it against the L1-settled (cursor, root).
_settled_snapshots = {}
# ...and a small per-ns HISTORY of the same payloads keyed by cursor. The prover must hold the pre-state
# at L1's JUSTIFIED tip, which lags our newest accepted settle by however long justification takes, so a
# stash that keeps only the newest is regularly at the wrong cursor — "stashed pre-state is at cursor
# 18632, not the justified tip 18627" was the second-largest skip class measured live 2026-08-04.
# Bounded: these are full state payloads, and only the last few cursors can ever be the justified tip.
_settled_history = {}
_SETTLED_HISTORY_KEEP = 6

# ---- THE STASH SURVIVES A RESTART ------------------------------------------------------------------
# It used to be purely in-memory, so every restart threw it away and the node could not prove ANYTHING
# until it had settled once more — a full settle cadence (~5 min here) of blind spans after every deploy.
# MEASURED 2026-08-06: "no stashed pre-state" was 17 of the day's skips, and every one of them was
# self-inflicted by a restart. That is the largest skip class we can remove without a reroll (the other
# two — epoch boundary 55, records moved 36 — are the SAME records problem and need one).
#
# Files live BESIDE the state file so the two generation wipes already sweep them: both the boot-time
# marker wipe and _reset_states_to_genesis glob STATE_PATH + "*" and os.remove each hit. The "~" separator
# cannot appear in a validated namespace, so a stash file can never be mistaken for a namespace's state.
#
# TRUSTING A FILE HERE IS SAFE because the prover already treats the stash as untrusted input: it requires
# the payload's own cursor to equal L1's JUSTIFIED tip, and the finished proof must both extend the
# L1-justified root and reproduce THIS node's real root. A wrong stash yields no proof, never a bad one.
# _stash_load additionally refuses any payload that does not describe itself (its ns/cursor must match the
# name it was found under).
_STASH_SEP = "~stash~"


def _stash_path(ns, cursor):
    return f"{STATE_PATH}{_STASH_SEP}{ns}~{int(cursor)}.json"


def _stash_persist(ns, cursor, payload):
    """Write one stash entry to disk and keep only the newest _SETTLED_HISTORY_KEEP for this ns.

    BOUNDED ON PURPOSE. These are full state payloads (~4 MB each here), and an unbounded on-disk cache is
    exactly what turned exec_da into 41 GB — see the DA rolling window. Best-effort throughout: losing a
    stash costs one settle's worth of proving, never correctness."""
    try:
        p = _stash_path(ns, cursor)
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            f.write(payload)
        os.replace(tmp, p)
    except OSError as e:
        print(f"[execnode] settle stash: could not persist ns={ns} cursor={cursor} ({e}) — "
              f"the in-memory stash still works, it just will not survive a restart", flush=True)
        return
    try:
        import glob as _g
        pref = f"{STATE_PATH}{_STASH_SEP}{ns}~"
        mine = []
        for q in _g.glob(pref + "*.json"):
            try:
                mine.append((int(q[len(pref):-len(".json")]), q))
            except ValueError:
                continue
        for _c, q in sorted(mine)[:-_SETTLED_HISTORY_KEEP]:
            try:
                os.remove(q)
            except OSError:
                pass
    except OSError:
        pass


def _stash_load():
    """Repopulate the in-memory stash from disk at startup. Best-effort; a bad file is skipped, not fatal."""
    import glob as _g
    pref = f"{STATE_PATH}{_STASH_SEP}"
    n = 0
    for p in sorted(_g.glob(pref + "*.json")):
        tail = p[len(pref):-len(".json")]
        ns, _sep, cur = tail.rpartition("~")
        if not _sep or ns not in NAMESPACES:
            continue
        try:
            cur = int(cur)
            raw = open(p).read()
            snap = json.loads(raw)
        except (OSError, ValueError):
            continue
        if snap.get("ns") != ns or int(snap.get("cursor", -1)) != cur:
            continue                      # a payload that does not describe itself is not a pre-state
        _settled_history.setdefault(ns, {})[cur] = raw
        n += 1
    for _ns, _h in _settled_history.items():
        if _h:
            _settled_snapshots[_ns] = _h[max(_h)]
    if n:
        print(f"[execnode] settle stash: restored {n} pre-state(s) from disk "
              f"({ {k: sorted(v) for k, v in _settled_history.items()} }) — proving can resume without "
              f"waiting for the next accepted settle", flush=True)


def _stash_clear():
    """Drop the stash, in memory and on disk — for a generation reset, where every payload is stale-chain."""
    _settled_snapshots.clear()
    _settled_history.clear()
    import glob as _g
    for p in _g.glob(f"{STATE_PATH}{_STASH_SEP}*"):
        try:
            os.remove(p)
        except OSError:
            pass

# NAMESPACES this node maintains (multi-rollup). The DEFAULT namespace is the full canonical exec layer
# (contracts + bridge + shielded pool + presence dividend). Any EXTRA namespaces (NADO_EXEC_NAMESPACES,
# comma-separated, validated) are contract-only rollups fed by `blob`s tagged with their ns; each persists to
# its own state file and settles independently. `default` is always present so the wallet's shielded/bridge/
# dividend endpoints keep working.
def _ns_state_path(ns):
    return STATE_PATH if ns == "default" else f"{STATE_PATH}.{ns}"

from protocol import valid_namespace as _valid_ns
_extra_ns = [s.strip() for s in os.environ.get("NADO_EXEC_NAMESPACES", "").split(",")
             if s.strip() and s.strip() != "default" and _valid_ns(s.strip())]
NAMESPACES = ["default"] + _extra_ns

# CHAIN GENERATION (genesis-reroll flag) — SELF-OWNED marker so this is RACE-FREE. The old code read the
# SHARED data-generation marker (ops.data_ops.stored_chain_generation), but the L1 node restamps that to the
# new generation immediately after its own purge — BEFORE nado-exec even imports — so this self-purge was
# effectively dead and a reroll could leave a stale exec layer that replays the FRESH chain onto OLD state
# and silently forks L2. We now track OUR OWN generation in a file beside the exec state and wipe using the
# exec node's OWN path resolution (STATE_PATH / DA_DIR), which is authoritative for THIS process regardless
# of where install.sh put the data or which service restarted first. Belt to purge_chain_data's Gap-A wipe.
from protocol import CHAIN_GENERATION as _CHAIN_GENERATION
_EXEC_GEN_MARK = STATE_PATH + ".gen"


def _exec_stored_gen():
    """The CHAIN_GENERATION this exec layer's on-disk state was built under, or None (fresh / pre-marker)."""
    try:
        with open(_EXEC_GEN_MARK) as _f:
            return int(_f.read().strip())
    except (OSError, ValueError):
        return None


if _exec_stored_gen() not in (None, _CHAIN_GENERATION):
    import glob as _glob
    import shutil as _shutil
    print("[execnode] CHAIN_GENERATION bumped — reroll: dropping exec state + DA for a fresh replay", flush=True)
    for _p in _glob.glob(STATE_PATH + "*"):          # default + namespaced state files AND the stale .gen mark
        try: os.remove(_p)
        except OSError: pass
    _shutil.rmtree(DA_DIR, ignore_errors=True)

states = {ns: ExecState(_ns_state_path(ns)) for ns in NAMESPACES}
state = states["default"]   # the full-featured default layer; shielded/bridge/dividend endpoints use it

# JOINT-GENESIS CANARY: a freshly-loaded EMPTY default layer (cursor == -1) MUST hash to EXEC_GENESIS_ROOT.
# If it doesn't, the exec-root scheme drifted from the hardcoded genesis constant — starting would settle a
# root no other node agrees on and fork L2. Fail LOUD instead. (A non-empty state is mid-chain and exempt.)
from protocol import EXEC_GENESIS_ROOT as _EXEC_GENESIS_ROOT
if state.cursor == -1 and state.state_root() != _EXEC_GENESIS_ROOT:
    raise SystemExit(f"[execnode] FATAL: empty exec state root {state.state_root()[:16]} != EXEC_GENESIS_ROOT "
                     f"{_EXEC_GENESIS_ROOT[:16]} — scheme drift; refusing to start (would fork L2)")

# Stamp OUR generation now that we have loaded a clean state, so a later reroll is detected exactly once.
try:
    with open(_EXEC_GEN_MARK, "w") as _f:
        _f.write(str(_CHAIN_GENERATION))
except OSError:
    pass

# Restore the settle stash AFTER the generation wipe above (which globs STATE_PATH + "*" and so removes any
# stale-chain stash files) and after the genesis canary — so nothing is loaded onto a state we refused.
_stash_load()

_last_settled_cursor = -1
# Per-namespace throttle for the "settle SKIPPED (window not canonical)" notice: while gated, maybe_settle
# re-enters every poll and the randomness window can take a full retention span to heal, so an unthrottled
# print would flood the log for days.
_SETTLE_SKIP_LOG_EVERY = 300
_settle_skip_logged = {}


def _reset_states_to_genesis(reason=""):
    """Nuke the exec layer back to genesis IN-PROCESS and rebuild the state map — no restart needed.

    This is the RUNTIME belt to the boot-time generation-marker wipe above. That wipe only fires when a .gen
    marker EXISTS and disagrees with the code's generation; a reroll can strand exec two other ways it can't
    catch: (a) a PRE-marker on-disk state (marker == None → boot treats it as 'don't wipe'), or (b) exec winning
    a load-before-purge race with the L1 node (loads OLD state a beat before purge_chain_data removes the file).
    Both leave exec running on OLD-chain state whose cursor OUTRUNS the fresh L1 chain. Stale exec and fresh L1
    share no overlapping heights, so there's nothing to hash-compare — the tail loop detects the height inversion
    (cursor > finalized, impossible on a consistent chain) and calls this to self-heal."""
    global states, state, DA, _last_settled_cursor, prov_states, _prov_key, _prov_last, _prov_since_full
    import glob as _g
    import shutil as _s
    print(f"[execnode] RESET to genesis{(' — ' + reason) if reason else ''}: wiping exec state + DA", flush=True)
    for _p in _g.glob(STATE_PATH + "*"):          # default + namespaced state files AND the stale .gen mark
        try:
            os.remove(_p)
        except OSError:
            pass
    _s.rmtree(DA_DIR, ignore_errors=True)
    _stash_clear()          # stale-generation pre-states would fail every self-check; drop them outright
    DA = DaStore(DA_DIR, retain=DA_RETAIN)
    states = {ns: ExecState(_ns_state_path(ns)) for ns in NAMESPACES}
    state = states["default"]
    if state.cursor == -1 and state.state_root() != _EXEC_GENESIS_ROOT:
        raise SystemExit(f"[execnode] FATAL after reset: empty root {state.state_root()[:16]} != "
                         f"EXEC_GENESIS_ROOT {_EXEC_GENESIS_ROOT[:16]} — scheme drift; refusing to run")
    _last_settled_cursor = -1
    prov_states = None
    _prov_key = None
    _prov_last = None
    _prov_since_full = 0
    try:
        with open(_EXEC_GEN_MARK, "w") as _f:      # re-stamp so a subsequent reroll is still detected once
            _f.write(str(_CHAIN_GENERATION))
    except OSError:
        pass


def _state_for(request):
    """The ExecState for the request's ?ns= (default 'default'), or None if this node doesn't run that ns.
    ?provisional=1 returns the fast PRE-FINALITY clone (unfinalized L1 tail speculatively applied), so a
    dApp sees moves within ~one block (~6s) instead of a full finality window; falls back to the finalized
    state when the provisional view isn't ready. Provisional is display-only — settlement/proofs read the
    finalized state (a plain fetch, no ?provisional)."""
    ns = request.query.get("ns", "default")
    if request.query.get("provisional") in ("1", "true", "yes"):
        pv = prov_states
        if pv is not None and ns in pv:
            return pv[ns]
    return states.get(ns)


async def _build_records_half(session, ns, pre_view, span_blocks, sc, cur, rec_hex_expected=None):
    """Prove the RECORDS half of a span, or return None to leave it frozen.

    THE PROVER HAS NEVER BUILT ONE. records_transition.py has existed for weeks, ops/transaction_ops.py
    verifies `proof["records"]`, and three test files cover it — but nothing under execnode/ ever SET it, so
    every span whose records moved was skipped before proving. That is the whole reason a call-carrying span
    could not settle by proof: not the derivation flag, the missing producer.

    NO POST-STATE IS NEEDED, and that is the point. The KV half never materialises one either — it derives
    the post from the pre by executing. Here the updates come from the SAME effect derivation L1 will run
    against its own committed summaries (records_bind.span_effects), so `st` mutating under us during the
    prove cannot desynchronise anything. Building it from a live post-state would reintroduce exactly the
    "two roots that were never simultaneously true" trap records_root_from_snapshot documents.

    THE VERIFIER SOURCES THE EFFECTS ITSELF (ops/transaction_ops.py: "The effects come from THIS node's
    committed summaries — never from the proof"), so anything we derive differently simply fails to bind and
    the span rides the quorum. Refusal, never a forged settlement.

    Returns (transition, rec_post_hex, records_pre_projection) or None.
    """
    from execnode.stark import records_bind as RB, state_transition as SX, storage_tree as _SST
    from execnode import exec_root as _ER
    from protocol import EXEC_TREE_DEPTH as _D, EPOCH_LENGTH as _EL
    try:
        # DERIVE EXACTLY AS L1 DOES: PER BLOCK, via block_records_effects, in block order — NOT via
        # span_effects.
        #
        # THIS WAS WRONG AND THE LIVE TEST CAUGHT IT. The two functions do not derive the same thing:
        # measured on one value call with the flag on, block_records_effects returns the escrow's two
        # T_BRIDGE_BAL positions while span_effects returns []. L1 builds `records_out` by concatenating the
        # per-block `rec` lists its summaries stored, and those come from block_records_effects. A prover
        # using span_effects would therefore omit every value-call escrow, and bind_and_verify_records —
        # which demands tr["updates"] EQUAL the derived set — would refuse the proof every time. The reroll
        # would have shipped and delivered nothing.
        #
        # A NON-DERIVABLE BLOCK ENDS THE SPAN HERE, matching L1: verify_calls_bound_to_summaries refuses any
        # non-inert block whose summary is not rd==1, so proving past one could never bind.
        effects, carry = [], int(getattr(pre_view, "div_carry", 0))
        for _blk in span_blocks:
            _eff, _derivable = RB.block_records_effects(_blk)
            if not _derivable:
                # SAY WHICH BLOCK AND WHAT IS IN IT. "an effect this node cannot derive" collapses three
                # different causes into one sentence — a non-derivable block, an unavailable accrual input,
                # and the empty-effect trap — and they call for different responses. block_records_effects
                # refuses on a bridge_withdraw, a shield, an xmsg or a value>0 call, so naming the block and
                # its recipients turns "records unprovable" into a specific, actionable class.
                _rs = sorted({str((_t or {}).get("recipient", "?"))[:24]
                              for _t in (_blk.get("block_transactions") or [])})
                print(f"[execnode] records NOT DERIVABLE at block {_blk.get('block_number')}: "
                      f"{len(_blk.get('block_transactions') or [])} tx, recipients {_rs[:8]}", flush=True)
                return None                       # L1 will refuse this block too -> quorum
            effects.extend(_eff or ())
            # ...AND THE ACCRUAL, on a boundary block, exactly where core_loop appends it. Inputs come from
            # L1 consensus state, never from us: records_bind's header records that a verifier taking them
            # from the proof would be trusting the prover's unauthenticated HTTP client.
            _E = RB.epoch_accrual_due(_blk.get("block_number"), _EL)
            if _E is None:
                continue
            inf = await _get_json(session, f"/get_dividend_inflow?epoch={_E}")
            ow = await _get_json(session, f"/get_open_weights?epoch={_E}")
            if not isinstance(ow, dict) or ow.get("error"):
                print(f"[execnode] records NOT DERIVABLE: epoch {_E} weights unavailable at block "
                      f"{_blk.get('block_number')} ({(ow or {}).get('error', 'no response')}) — pruned "
                      f"recert history; never guessed", flush=True)
                return None                       # pruned recert history -> quorum, never a guess
            _aeff, carry = RB.dividend_accrual_effects(int((inf or {}).get("inflow", 0)),
                                                       (ow or {}).get("weights", {}) or {}, carry)
            effects.extend(_aeff)
        if not effects:
            # EMPTY-EFFECT TRAP: with nothing to prove L1 REQUIRES rec_post == rec_hex, which collapses to
            # the frozen case. Attaching an empty transition would move the half on nobody's authority.
            return None
        # EVERYTHING BELOW IS CPU-BOUND AND MUST NOT TOUCH THE EVENT LOOP.
        #
        # I SHIPPED IT ON THE LOOP AND IT HUNG THE NODE. prove_transition is a full STARK — measured 167.6 s
        # for a SINGLE records update — and calling it inline from this coroutine blocked block application,
        # HTTP and settlement outright: the exec node sat at 208% CPU, silent, stuck at cursor 60 while L1
        # ran to 221, with no crash and no traceback to show for it. Every other heavy call in this file
        # already goes through asyncio.to_thread (the KV prove, the pre-flight, DA put); this one did not.
        # The first accrual on the fresh chain — "dividend epoch 0: +8444800000 raw to 13 miner(s)" — was
        # what finally gave it something to prove, so the defect could only ever surface post-cutover.
        def _cpu():
            # ONE projection, reused. Computing it inside pre_get would rebuild the whole records map on
            # every record lookup — quadratic in a large state, inside the prove's critical path.
            proj = _ER.records_projection(pre_view)
            store = _SST.SparseStore(_D, proj)
            return proj, store, _SST.digest_hex(store.root())
        proj, store, pre_root_hex = await asyncio.to_thread(_cpu)
        if rec_hex_expected is not None and pre_root_hex != rec_hex_expected:
            # The stash must be the state at the JUSTIFIED cursor. If its records root is not the one the
            # tip committed, every update below would be derived against the wrong pre-values and the
            # binding would fail on L1 anyway — catch it here, cheaply, with a reason.
            print(f"[execnode] records half PRE MISMATCH for span {sc}->{cur}: stash {pre_root_hex[:16]}… "
                  f"!= tip {rec_hex_expected[:16]}… — quorum", flush=True)
            return None
        net = RB.net_records_updates(lambda tag, parts: int(proj.get(_ER.record_key(tag, *parts), 0)),
                                     effects, _D)
        if not net:
            return None                           # effects that cancel out move nothing; stay frozen
        # DECLINE A PROVE THAT CANNOT FINISH, BEFORE STARTING IT.
        #
        # prove_transition emits ONE STARK PER UPDATE (records_transition: "one RECURSION-committed
        # merkle-update proof per update, chaining the roots"), so its cost is LINEAR and predictable:
        # measured 167.6 s for 1 update and 712.2 s for 3, i.e. ~170-240 s each. SETTLE_PROVE_TIMEOUT is
        # 2400 s, so anything past ~10 updates cannot finish.
        #
        # STARTING ONE ANYWAY IS NOT MERELY WASTEFUL, IT STALLS SETTLEMENT. Observed live 2026-08-06: a
        # span with a dividend accrual (one T_DIV_BAL position per PRESENT MINER — 13 on this chain) ran
        # the full 2400 s, timed out, and left its worker thread running; the in-flight flag only clears
        # when that thread ENDS, so no settle of any kind proceeded. The settled tip sat at 557 while L1
        # reached 1060 — 503 blocks, far past SETTLE_PROOF_MAX_SPAN — which makes every later span
        # unprovable too. One doomed prove poisons the whole cadence.
        #
        # SINCE ROW-COMMITTING THE UPDATE PROOFS, THIS CAP IS ABOUT SIZE, NOT TIME. One update is ~45 s and
        # 10.83 MiB, so 16 of them fit under SETTLE_INLINE_MAX while ~53 would fit in SETTLE_PROVE_TIMEOUT.
        # A span that declines here still settles by bonded quorum, which is always correct and merely
        # slower — and declining is still far better than proving something that gets refused for size.
        if len(net) > SETTLE_RECORDS_MAX_UPDATES:
            _mib = (len(net) * SETTLE_RECORDS_PROOF_BYTES + SETTLE_KV_HALF_BYTES) >> 20
            # SAY WHAT THE UPDATES ARE, not just how many. The plan for closing the remaining gap rests on
            # the claim that a boundary span is "13 dividend positions + a few others" — if that is wrong,
            # shortening the span buys nothing, and a count alone can never tell us. Counted over `effects`
            # (pre-netting) by tag, which is the only place the tag still exists: `net` is keyed by the
            # HASHED record key, from which no tag can be recovered.
            _by_tag = {}
            for _e in (effects or ()):
                _by_tag[_e[0]] = _by_tag.get(_e[0], 0) + 1
            _names = {1: "BRIDGE_BAL", 2: "DIV_BAL", 3: "BRIDGE_WD", 4: "DIV_WD", 5: "UNSHIELD_WD",
                      6: "DIGEST", 7: "KVX", 8: "ASSET_BAL", 9: "ASSET_META", 10: "ASSET_ALLOW"}
            _brk = " ".join(f"{_names.get(t, t)}={n}" for t, n in sorted(_by_tag.items()))
            print(f"[execnode] records half DECLINED for span {sc}->{cur}: {len(net)} net updates from "
                  f"{len(effects or ())} effects [{_brk}] exceeds "
                  f"SETTLE_RECORDS_MAX_UPDATES={SETTLE_RECORDS_MAX_UPDATES} — at ~{SETTLE_RECORDS_PROOF_BYTES >> 20}"
                  f" MiB per update that is ~{_mib} MiB against SETTLE_INLINE_MAX={SETTLE_INLINE_MAX >> 20} MiB, "
                  f"so the proof would be built (~{45 * len(net)}s) and then refused. Riding the bonded quorum",
                  flush=True)
            return None
        # prove_transition APPLIES the updates to `store`, so its root afterwards IS the post root — the
        # same way settlement_sparse reads sparse_post_root straight off pre_store after proving.
        tr = await asyncio.to_thread(SX.prove_transition, store, [(k, n) for (k, _o, n) in net])
        tr["half"] = "records"
        return tr, _SST.digest_hex(store.root()), {str(k): int(v) for k, v in proj.items()}
    except RB.Unbindable as e:
        print(f"[execnode] records half not bindable for span {sc}->{cur}: {e} — quorum", flush=True)
        return None
    except Exception as e:
        print(f"[execnode] records half FAILED for span {sc}->{cur} ({type(e).__name__}: {e}) — quorum",
              flush=True)
        return None


def state_owes_accrual(st, cur, epoch_length):
    """The epoch this state still owes, or None when it is settle-consistent.

    The exec accrual loop advances the cursor FIRST and applies the dividend AFTER, with two HTTP awaits in
    between (/get_dividend_inflow, /get_open_weights). So `state.cursor` can already sit on a boundary while
    that epoch has not landed, and a records root read in that window is true for NO block.

    Measured exactly on span (4064, 4080] by the records DIFF diagnostic: 25 keys disagreed — the present
    miner count — with the SAME key set and the derived side uniformly higher by one epoch's share. The
    prover was right about WHICH epoch (both epoch_accrual_due(4080) and the loop's
    `while last_div_epoch < cursor//L - 1` name epoch 67); the state simply had not applied it yet.

    `last_div_epoch` is the deterministic watermark of the highest epoch already accrued, so this is exact
    rather than a heuristic: once the cursor has fully passed epoch E, E must be accrued before anything may
    settle against this state.
    """
    try:
        owed = (int(cur) // int(epoch_length)) - 1
    except Exception:
        return None                     # cannot tell -> do not invent a reason to refuse
    if owed < 0:
        return None
    return owed if int(getattr(st, "last_div_epoch", -1)) < owed else None


async def _build_settlement_proof(session, ns, st, cur, root, rec_root_at_cur=None):
    """Best-effort SELF-CHECKING settle-with-proof for (ns, cur, root), or None to fall back to quorum.

    Builds a sparse validity proof over the span (L1-justified settled tip, cur] from the DA calldata
    (calls_commit.block_calls — per-block cursor, ts=0, which matches L1's da_calls_commitment), then
    posts it ONLY if it verifiably (a) extends the L1-justified settled root and (b) reproduces THIS
    node's real root. Any mismatch — a TIME-reading call, a records-moving call, an epoch-boundary
    dividend accrual, a stale pre-state — makes a self-check fail and returns None, so a wrong proof is
    never posted and the quorum path (unchanged) settles instead. Proving runs in a worker thread under
    the proving semaphore. Validated end-to-end in tests/test_settle_prover_sim.py."""
    # Declared HERE, not at the later assignment: the in-flight guard is now read twice — once before the
    # records prove and once at the last moment before launching the KV prove — and Python requires the
    # global statement to precede the first use in the function.
    global _settle_proving, _records_proving
    if not SETTLE_PROVE:
        return None
    from execnode.stark import settlement_sparse as SS, calls_commit as CC, storage_tree as SST
    from execnode import exec_root as ER
    from execnode import settlement_proofs as SP
    from execnode.stark import field as _F
    from protocol import EXEC_TREE_DEPTH, SETTLE_PROOF_MAX_SPAN, EPOCH_LENGTH, SETTLE_PROOF_RECURSIVE
    # 1. L1's JUSTIFIED settled tip for this namespace (the proof must extend exactly this).
    settled = await _get_json(session, f"/get_settled?ns={ns}")
    sc, sr = int((settled or {}).get("exec_cursor", -1)), (settled or {}).get("state_root")
    # A SKIPPED PROOF MUST SAY WHY. Every gate below used to `return None` silently, so an operator who
    # switched the prover on saw ordinary bare settles forever with nothing anywhere to distinguish
    # "disabled", "waiting for a conforming span" and "broken" — the exact failure this codebase already
    # names elsewhere: a fallback nobody can observe is indistinguishable from one that never fires.
    # Rate-limited per (ns, reason) so a standing condition says so once, not once per settle.
    def _skip(reason, cls=None):
        # THE THROTTLE MUST DEDUPE ON THE CONDITION, NOT ON THE SENTENCE. It compared the whole formatted
        # reason, and several reasons embed the moving cursor ("span 25399 -> 25496 crosses …"), so the
        # string differed on every poll and the standing condition logged once per poll instead of once:
        # 25 identical epoch-boundary lines in one cycle, which is precisely what "rate-limited so a
        # standing condition says so once" was written to prevent. `cls` names the condition; it falls back
        # to the full reason for one-off skips that carry no moving value.
        _k = (ns, "skip")
        _key = cls or reason
        if _settle_skip_logged.get(_k) != _key:
            _settle_skip_logged[_k] = _key
            print(f"[execnode] settle-with-proof SKIPPED ns={ns} cursor {cur} — {reason}", flush=True)
        return None

    # NOTHING MAY BE PROVEN WHILE A RECORDS PROVE IS IN FLIGHT — not even a records-FREE span.
    #
    # The in-flight check further down sits inside `if rec_pre_root != rec_root`, so a span whose records
    # half did not move never reaches it: it proves its KV half, lands, and walks the justified tip forward
    # while an EARLIER records proof is still being built. That proof then cannot extend the settled tip and
    # is refused — the whole point of the hold. Observed 01:13:57, with the records prove at batch 5/13:
    #     [settle-prove] cursor=3630 calls=0 net_updates=0 | … | total 25.5s
    #     settle-with-proof BUILT span 3600->3630 … SETTLE-WITH-PROOF cursor 3630 → L1
    # The 25.5 s KV proof for a later span overtook the ~12-minute records proof for an earlier one.
    #
    # So the gate belongs HERE, before any span is examined, rather than in the branch that happens to run
    # the records prove. This also covers the concurrent-invocation case the flag was introduced for, since
    # a second pass now returns before doing any work at all.
    if _records_proving:
        return _skip("a RECORDS prove is in flight; no settle proof may be built until it finishes, or it "
                     "would advance the justified tip past the span that prove extends",
                     cls="records-prove-inflight")
    if sc < 0 or not sr:
        return _skip("no L1-justified settled tip yet; the first settlement in a namespace rides the quorum")
    # 2. our stashed exec state AT that justified cursor (pre-state). Only proceed if we hold exactly it.
    # Look the justified cursor up in the HISTORY, not just the newest stash: L1 justifies a settle some
    # time after we make it, so by the time we prove, our newest stash is typically one settle AHEAD of
    # the tip the proof has to extend. Falling back to the newest keeps the pre-e1000cbd behaviour for a
    # node that has settled exactly once.
    raw = (_settled_history.get(ns) or {}).get(sc) or _settled_snapshots.get(ns)
    if not raw:
        return _skip("no stashed pre-state (the stash is in-memory and empties on restart; it refills on "
                     "the next accepted settle)")
    snap = json.loads(raw)
    if int(snap.get("cursor", -2)) != sc:
        return _skip(f"stashed pre-state is at cursor {snap.get('cursor')}, not the justified tip {sc} "
                     f"(history holds {sorted((_settled_history.get(ns) or {}).keys())})", cls="stale-stash")
    pre_contracts = (snap.get("state") or {}).get("contracts") or {}
    pre_bridge = (snap.get("state") or {}).get("bridge")
    # 3. conformance the validator enforces: advances, within the span cap, no epoch boundary (dividend).
    if cur <= sc:
        return _skip(f"span does not advance ({sc} -> {cur})", cls="no-advance")
    if (cur - sc) > SETTLE_PROOF_MAX_SPAN:
        return _skip(f"span {cur - sc} exceeds SETTLE_PROOF_MAX_SPAN {SETTLE_PROOF_MAX_SPAN}", cls="span-cap")
    # THE EPOCH-BOUNDARY SKIP IS GONE, and it was the single largest refusal class — 55 of 146 over one
    # measured day, larger than "the RECORDS half moved" (36), and the two were always ONE problem: a
    # dividend accrues at every boundary block and moves records with NO transaction behind it.
    # It existed only because the accrual was INVISIBLE, not because it was unprovable. It is now derived at
    # incorporate time (records_bind.epoch_accrual_due + dividend_accrual_effects, committed into the
    # boundary block's exec summary), the prover reproduces it per block in _build_records_half, and L1's
    # epoch assert is conditional on the proof binding the records half. A span that crosses a boundary is
    # now refused only if the accrual genuinely cannot be derived — which _build_records_half reports with a
    # reason — rather than refused on sight.
    # 4. the span's DA calls, per block (block_calls stamps cursor=h, ts=0 — the DA-binding form).
    calls = []
    span_blocks = []       # the span's blocks in order — the RECORDS half derives PER BLOCK, like L1
    for h in range(sc + 1, cur + 1):
        blk = await _get_json(session, f"/get_block_number?number={h}")
        if not blk or not blk.get("block_hash"):
            return None
        calls += CC.block_calls(blk, ns)
        span_blocks.append(blk)          # the RECORDS half derives PER BLOCK, exactly as L1 does
    # 4b. DETECT AN UNPROVABLE CALL BEFORE PAYING FOR THE PROVE.
    #
    # A call the live chain SKIPS (sender cannot cover the escrow) or that REVERTS in the VM is a no-op on
    # chain, but the prover cannot represent one: settlement_proofs._run_call raises, and so does
    # vm_circuit.prove_epoch_calls. So ONE such call anywhere in the span means the span yields NO PROOF AT
    # ALL — folded or unfolded — and we only found out after ~1000 s of proving:
    #     fold FAILED span 42261->42291 (call 0 reverted — nothing to prove) — re-proving UNFOLDED
    #     settle-prove worker ended with ValueError: call 1 reverted — nothing to prove
    # One interpreter pass over the span's calls tells us that up front, for a fraction of the cost. The
    # proper fix (the AIR proving a reverting execution, or the verifier re-deriving which calls were
    # no-ops) is a consensus/circuit change; see settlement_proofs.first_unprovable_call.
    if calls:
        try:
            # Same chain randomness the real prove passes, computed here because the dry run must execute
            # the calls EXACTLY as the prove will — a BEACON/BHASH read against None would revert a call
            # that is actually fine and make us skip a provable span.
            _pf_beacons = {e: v % _F.P for e, v in st.beacons.items()}
            _pf_bhashes = {h: v % _F.P for h, v in st.block_hashes.items()}
            _bad_i, _why = await asyncio.to_thread(
                SP.first_unprovable_call, pre_contracts, calls, cur, 0, _pf_beacons, _pf_bhashes,
                pre_bridge, (snap.get("state") or {}).get("abal"), (snap.get("state") or {}).get("assets"))
        except Exception as e:                       # a dry-run failure must never block settling
            _bad_i, _why = None, f"pre-flight error {type(e).__name__}: {e}"
        if _bad_i is not None:
            _bad_h = int(calls[_bad_i].get("cursor", cur))
            # SKIP EARLY rather than narrow the span. Narrowing looks obvious and is WRONG here: the caller
            # captured `root` AND `rec_root_at_cur` at `cur` under the state's mutate lock, so moving `cur`
            # down would make the settle claim a post-root belonging to a different cursor — the "two roots
            # that were never simultaneously true" failure the records comment below describes. Proving the
            # clean prefix needs the snapshot RE-CAPTURED at the narrowed cursor, which only the caller
            # (ExecState.settle_snapshot) can do; until then, skipping costs one cadence instead of ~1000 s
            # of proving thrown away at the end.
            return _skip(f"span {sc} -> {cur} contains an unprovable call at block {_bad_h} (call {_bad_i}: "
                         f"{_why}). A call the chain SKIPS or REVERTS is a no-op on chain but the prover "
                         f"cannot represent one, so this span can yield no proof at all — folded or not. "
                         f"Skipping now instead of discovering it after the prove",
                         cls="unprovable-call")
    # 5. records half (frozen) + finalized chain randomness the proof reads.
    #
    # USE THE RECORDS ROOT CAPTURED WITH `root`, NOT A FRESH ONE. Recomputing it here reads the LIVE `st`,
    # which the detached tail has been advancing throughout step 4's per-block fetches and will keep
    # advancing through the prove. `root` is rnode(kv, records) AT `cur`; pairing it with a records half
    # from a later cursor makes the self-check compare two roots that were never simultaneously true, and
    # it failed exactly that way on spans wholly inside one dividend epoch. The caller captures both under
    # the state's mutate lock (ExecState.settle_snapshot). The fallback keeps standalone callers working.
    rec_root = (rec_root_at_cur if rec_root_at_cur is not None
                else SST.SparseStore(EXEC_TREE_DEPTH, ER.records_projection(st)).root())
    # THE STATE OWES AN ACCRUAL -> ITS RECORDS ROOT IS MID-UPDATE. REFUSE.
    #
    # The accrual loop advances the cursor FIRST and applies the dividend AFTER, with two HTTP awaits in
    # between (/get_dividend_inflow and /get_open_weights). So there is a window where state.cursor has
    # already reached a boundary but that epoch has not landed, and anything reading the records root in
    # that window sees a root that is real for no block.
    #
    # Measured exactly, by the records DIFF diagnostic (4ed7d0b4) on span (4064, 4080]:
    #     records DIFF at 4080: 25 key(s) disagree (derived 35 entries vs actual 35)
    #         …512…  89276075280 vs 87914257097   Δ 1361818183
    #         …331…   6538626417 vs  6266262781   Δ  272363636
    #         …749…  11197358394 vs 10924994758   Δ  272363636   (and so on)
    # 25 keys — exactly the present-miner count — SAME key set, values only, and the derived side uniformly
    # HIGHER by one epoch's share. The prover derived epoch 67 for block 4080 and was right to: both
    # records_bind.epoch_accrual_due(4080) and the exec loop's `while last_div_epoch < cursor//L - 1` name
    # epoch 67. Attribution was never the problem; the state had simply not applied it yet.
    #
    # `last_div_epoch` is the deterministic watermark of the highest epoch already accrued, so the condition
    # is exact rather than a heuristic: if the cursor has fully passed epoch E, E must be accrued before
    # this state can be settled against. A quiet skip and the next cadence proceeds — the alternative is a
    # ~15-minute prove that the self-check then throws away.
    _owed = state_owes_accrual(st, cur, EPOCH_LENGTH)
    if _owed is not None:
        return _skip(f"the state at {cur} still owes dividend accrual (last_div_epoch="
                     f"{getattr(st, 'last_div_epoch', None)}, cursor has passed epoch {_owed}) — its "
                     f"records root is mid-update and true for no block", cls="accrual-pending")
    # THE RECORDS HALF AT THE JUSTIFIED CURSOR, from the stash. prove_settlement_sparse pins ONE records
    # root for the whole span ("the (unchanged) records half"), so this is load-bearing twice over:
    #
    #  1. THE SELF-CHECK MUST COMPARE LIKE WITH LIKE. `sr` is L1's justified root at `sc`, i.e.
    #     rnode(kv_pre, records AT sc). Building pre_full from records at CUR compares two roots that were
    #     never simultaneously true — the exact `PRE MISMATCH` observed live on spans with ZERO calls,
    #     where the kv half provably had not moved and the POST side matched to the byte.
    #  2. IF THE RECORDS ACTUALLY MOVED, THE SPAN IS UNPROVABLE. The proof would assert a records half
    #     that was not constant across the span, so it must not be built at all. That is a clean skip with
    #     a reason, not a self-check failure discovered minutes later after a full prove.
    try:
        rec_pre_root = type(st).records_root_from_snapshot(snap["state"])
    except Exception as _e:
        return _skip(f"could not derive the records half at the justified cursor {sc} from the stash "
                     f"({type(_e).__name__}: {_e})")
    # rec_hex IS THE PRE ROOT. pre_full = rnode(kv_pre, rec_hex) must equal L1's JUSTIFIED root, which was
    # composed with the records half AT sc. It only happened to be safe to write digest_hex(rec_root) here
    # while the two were forced equal by the skip below.
    rec_hex = SST.digest_hex(rec_pre_root)
    _records_half = None
    if rec_pre_root != rec_root:
        # THE RECORDS HALF MOVED — which used to end the span here. It no longer has to: the prover can
        # now PROVE the half instead of pinning it (_build_records_half), and L1 checks that transition
        # against the effects IT derived from its own committed summaries. This is the change that lets a
        # span carrying calls, a bridge deposit or a dividend accrual settle by proof at all.
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # THE IN-FLIGHT GUARD HAS TO BE HERE TOO, NOT ONLY ~60 LINES BELOW.
        #
        # _build_records_half runs prove_transition — a multi-minute, CPU-bound, multi-GB STARK — and the
        # `if _settle_proving` check sits AFTER it. So every settle cadence (~8 s) started ANOTHER records
        # prove while the previous one was still running. The per-batch instrumentation caught it in one
        # run; the batch index never advances:
        #
        #     00:45:48  batch 1/13 K=2 T=32768  76.4s (cum  76.4s) rss=1.07GB
        #     00:47:08  batch 1/13 K=2 T=32768 147.0s (cum 147.0s) rss=1.63GB
        #     00:48:16  batch 1/13 K=2 T=32768 207.9s (cum 207.9s) rss=1.79GB
        #     00:49:19  batch 1/13 K=2 T=32768 261.8s (cum 261.8s) rss=1.96GB
        #
        # Four SEPARATE prove_transition calls, each restarting at batch 1 (cum == the batch time, so _t0
        # is fresh each line), all running CONCURRENTLY: identical work taking 76 -> 147 -> 208 -> 262 s as
        # they contend for cores. That is the whole mystery of tonight — the RSS climb to 14.6 GB, the ~4x
        # slowdown, and the prove that blew SETTLE_PROVE_TIMEOUT=2400s and was abandoned. None of it was
        # batching, and none of it was the AIR; it was N concurrent copies of the same proof.
        #
        # The comment on the later guard already states the rule — "without it a timeout every settle would
        # stack a new fold thread every cadence and the box would grind to a halt" — it simply guarded the
        # KV prove and left the records prove, added later and just as expensive, in front of it.
        #
        # The LATER check stays. It is not redundant: it re-reads at the last moment because the caller's
        # copy goes stale while this function walks the span over HTTP (that was its own bug, three fixes
        # deep). This one is the cheap early-out that stops the stacking; that one keeps the race honest.
        if _records_proving:
            return _skip("a RECORDS prove is already in flight; not starting a second one over the same "
                         "pre-state", cls="records-prove-inflight")
        if _settle_proving:
            return _skip("a previous settle-prove is still running; not starting a second RECORDS prove "
                         "over the same pre-state", cls="records-prove-inflight")
        if _settle_publishing and (time.time() - _settle_publishing) < SETTLE_HOLD_MAX_S:
            return _skip("the previous proof is still publishing/submitting; a records prove started now "
                         "would extend the same pre-state and could never land", cls="records-prove-inflight")
        _records_proving = True
        try:
            _records_half = await _build_records_half(session, ns, type(st).snapshot_view(snap["state"]),
                                                      span_blocks, sc, cur, rec_hex_expected=rec_hex)
        finally:
            # `finally`, not a trailing assignment: _build_records_half can return None, raise, or be
            # cancelled, and any path that leaves this True would wedge the records half permanently — a
            # far worse failure than the stacking it prevents.
            _records_proving = False
        if _records_half is None:
            return _skip(f"the RECORDS half moved across the span {sc} -> {cur} "
                         f"({rec_hex[:16]}… -> {SST.digest_hex(rec_root)[:16]}…) and could not be PROVEN "
                         f"(an effect this node cannot derive, or an unavailable accrual input); the proof "
                         f"would have to pin one records root for the whole span, which would assert "
                         f"something false. Riding the bonded quorum", cls="records-unprovable")
        if _records_half[1] != SST.digest_hex(rec_root):
            # The derived effects must land on the records root we actually captured at `cur`. If they do
            # not, our derivation disagrees with our own apply — refuse HERE rather than ship a proof that
            # can only fail to bind on L1 after every peer has paid to verify it.
            # SAY WHICH RECORDS DISAGREE, not just that some do. Two roots differing is unactionable: it
            # cannot distinguish a wrong dividend carry from a missed bridge deposit from an effect derived
            # at the wrong block. The pre-state projection and the derived updates are both in hand here,
            # so apply them and diff against what we actually hold at `cur`. Runs ONLY on this failure
            # path, and prints a bounded sample.
            try:
                _derived = dict(_records_half[2] or {})
                for (_k, _o, _n) in (_records_half[0].get("updates") or ()):
                    _derived[str(_k)] = int(_n)
                _actual = {str(_k): int(_v) for _k, _v in ER.records_projection(st).items()}
                _keys = set(_derived) | set(_actual)
                _diff = [(k, _derived.get(k), _actual.get(k)) for k in _keys
                         if int(_derived.get(k, 0)) != int(_actual.get(k, 0))]
                _diff.sort(key=lambda r: str(r[0]))
                print(f"[execnode] records DIFF at {cur}: {len(_diff)} key(s) disagree "
                      f"(derived {len(_derived)} entries vs actual {len(_actual)}); first few "
                      f"[key, derived, actual]: "
                      + "; ".join(f"{k[:18]}… {d} vs {a}" for k, d, a in _diff[:6]), flush=True)
            except Exception as _e:
                print(f"[execnode] records DIFF unavailable: {type(_e).__name__}: {_e}", flush=True)
            return _skip(f"the derived RECORDS half lands on {_records_half[1][:16]}… but our state at "
                         f"{cur} has {SST.digest_hex(rec_root)[:16]}… — derivation disagrees with apply",
                         cls="records-derivation-mismatch")
    beacons = {e: v % _F.P for e, v in st.beacons.items()}
    bhashes = {h: v % _F.P for h, v in st.block_hashes.items()}

    # only fold when BOTH the operator opted in (SETTLE_FOLD) AND the chain honours folds (SETTLE_PROOF_RECURSIVE);
    # otherwise the `recursive` bundle is ignored by verifiers and the proving effort is wasted.
    # A FOLD NEEDS SOMETHING TO FOLD. settlement_sparse raises ValueError("recursive settlement over an
    # empty call span") when the span carries no exec calls, while the UNFOLDED path proves an empty span
    # perfectly well. So on an idle chain, switching the fold on strictly REDUCED what we produce: spans
    # that had been yielding a (refused, 97.45 MiB) proof started yielding no proof at all. Observed live
    # within minutes of enabling the fold on 2026-08-04.
    #
    # Fold only when there is real traffic; otherwise fall through to the unfolded prove, which is what the
    # 61 proofs before this were. The fold is an upgrade to a proof we want either way, never a precondition
    # for producing one — the same shape as 82a8ab29 (a refused proof must still settle).
    _fold = SETTLE_FOLD and SETTLE_PROOF_RECURSIVE and bool(calls)
    if SETTLE_FOLD and SETTLE_PROOF_RECURSIVE and not calls:
        _k = (ns, "foldskip")
        if _settle_skip_logged.get(_k) != cur:
            _settle_skip_logged[_k] = cur
            print(f"[execnode] fold skipped ns={ns} span {sc}->{cur}: no exec calls to fold — proving "
                  f"UNFOLDED (the recursive path refuses an empty call span)", flush=True)
    def _prove():
        def _run(fold):
            return SS.prove_settlement_sparse(pre_contracts, calls, cursor=cur, rec_hex=rec_hex,
                                              beacons=beacons, block_hashes=bhashes, pre_bridge=pre_bridge,
                                              depth=EXEC_TREE_DEPTH, recursive=fold, fold=fold)
        if not _fold:
            return _run(False)
        try:
            return _run(True)
        except Exception as e:
            # A FOLD FAILURE MUST NOT COST US THE PROOF. The fold is a verification-strategy upgrade on top
            # of a proof we want regardless, so if the recursive path refuses, prove the SAME span unfolded
            # rather than returning nothing and settling bare. Retried inside the worker thread on purpose:
            # it keeps this to ONE task and ONE in-flight guard rather than restructuring the guard.
            print(f"[execnode] fold FAILED ns={ns} span {sc}->{cur} ({type(e).__name__}: {e}) — "
                  f"re-proving UNFOLDED", flush=True)
            return _run(False)
    # TIME-BOUND THE PROVE, and never run two at once. Without this, enabling the K->1 fold is an OUTAGE
    # rather than a feature: a fold over the W=106 exec AIR measured 5h07m at 492% CPU / 8.2 GB WITHOUT
    # COMPLETING (2026-08-02), and this call had no timeout — maybe_settle would simply never return, so
    # no settle of any kind would be posted. The bare-attestation fallback is downstream of here and would
    # never be reached. latest_settled() backs bridge_withdraw / unshield / dividend_withdraw, so that is
    # an outage, not a degraded mode.
    #
    # asyncio.wait_for CANNOT kill the worker thread, so the abandoned prove keeps burning a core until it
    # finishes. That makes the IN-FLIGHT GUARD the essential half: without it a timeout every settle would
    # stack a new fold thread every cadence and the box would grind to a halt. With it, at most ONE prove
    # is ever outstanding; while it runs, settles continue as bare attestations.
    if _settle_proving:
        return _skip("a previous settle-prove is still running; the settle is HELD until it finishes")
    # AND NOT WHILE THE PREVIOUS PROOF IS STILL PUBLISHING OR SUBMITTING. _settle_proving is cleared by the
    # prove THREAD's done-callback, i.e. at "BUILT", while ~112-139 s of DA publish and up to
    # SETTLE_SUBMIT_TIMEOUT_PROOF of submit still lie ahead — so a second prove started inside that window
    # every single cadence. Measured live 2026-08-04, two BUILTs about two minutes apart on every cycle:
    #     21:47:40 BUILT   21:49:57 BUILT   21:51:49 PUBLISHED   21:52:43 SETTLE
    # Both extend the SAME pre-state, so at most one of them could ever land — the second is a wasted
    # 118 MiB proof and a wasted core, on the node that also has to keep up with block production. This box
    # sat at 100% CPU and drifted 1-2 blocks off the tip because of it.
    _pub_active = (_settle_publishing
                   and (time.time() - _settle_publishing) < SETTLE_HOLD_MAX_S)
    if _pub_active:
        return _skip("the previous proof is still publishing/submitting; not starting a second prove that "
                     "extends the same pre-state and could never land")
    # ...AND RE-CHECK THE PENDING MARKER HERE, because the caller's copy is STALE BY THE TIME IT MATTERS.
    #
    # NAMED BY THE DIAGNOSTIC, after three fixes had guessed wrong:
    #   17:47:37 SETTLE-WITH-PROOF cursor 49530            <- marker recorded
    #   17:47:39 prove-gate span 49500->49534 LAUNCH — pending_cursor=49530 proving=False publishing=CLEAR
    # The caller computes `_pend_hold` at the TOP of its pass and then this function spends seconds walking
    # the span over HTTP before it commits to anything. A proof submitted inside that walk sets the marker
    # after the snapshot was taken, so the gate it was checked against no longer describes reality.
    # bd079982 added the caller-side gate, 7b612e1e moved the marker earlier, d4c24872 made the publish hold
    # continuous — none of them could help, because the read itself was stale, not the write.
    # Re-reading at the LAST moment before _settle_proving is set is what makes the check meaningful; that
    # is the same reason _pub_active is re-evaluated here rather than trusted from the caller.
    if _settle_pending.get(ns) is not None:
        return _skip("a proof-carrying settle is already waiting for its landing block; a second proof over "
                     "the same pre-state could never also land", cls="pending-landing")
    # WHY WAS THIS PROVE ALLOWED? Three fixes for the duplicate-prove race have shipped and the duplicate
    # survived all three (bd079982, 7b612e1e, d4c24872 — the last VERIFIED loaded: committed 16:21:22, exec
    # started 16:21:40, duplicate at 16:33-16:34). That means the open window is somewhere I have not
    # traced, not that the same place needs a fourth patch. Print the full guard state at the ONE moment a
    # prove is actually launched, so the next occurrence names its own cause instead of being
    # reverse-engineered from timestamps. One line per prove, and proves are minutes apart.
    _pg_pend = _settle_pending.get(ns)
    _pg_pub = f"{time.time() - _settle_publishing:.1f}s" if _settle_publishing else "CLEAR"
    print(f"[execnode] prove-gate ns={ns} span {sc}->{cur} LAUNCH — "
          f"pending_cursor={_pg_pend.get('cursor') if _pg_pend else None} "
          f"proving={_settle_proving} publishing={_pg_pub}", flush=True)
    _settle_proving = True
    # The flag must track the THREAD's lifetime, not this coroutine's. Clearing it in a `finally` would
    # release the guard the moment wait_for gives up — while the thread is still burning a core — and the
    # next cadence would start another. So clear it from a done-callback on the task, and SHIELD the task
    # from wait_for's cancellation (cancelling would not stop the thread regardless, but it would detach
    # the callback and lose the only signal we have that the prove really ended).
    _task = asyncio.ensure_future(asyncio.to_thread(_prove))
    _task.add_done_callback(_clear_settle_proving)
    try:
        async with _sem():                                 # bound concurrent proving (H-7)
            proof = await asyncio.wait_for(asyncio.shield(_task), timeout=SETTLE_PROVE_TIMEOUT)
    except asyncio.TimeoutError:
        return _skip(f"prove exceeded SETTLE_PROVE_TIMEOUT={SETTLE_PROVE_TIMEOUT}s "
                     f"(fold={_fold}); the worker thread is abandoned and settles stay BARE until it ends")
    # 6. THE SELF-CHECKS — never post a proof that doesn't extend the justified tip AND reproduce our root.
    # PRE pairs with the records half at `sc`, POST with the records half at `cur`. They are equal here —
    # the gate above refuses the span otherwise — but writing it explicitly is what keeps the comparison
    # honest if that ever stops being true.
    pre_full = ER.full_root_hex(SST.digest_from_hex(proof["kv_pre"]), rec_pre_root)
    post_full = ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]), rec_root)
    # SAY WHICH SIDE FAILED. "not conforming" named neither half, so three separate hypotheses (epoch
    # boundary, records-half skew, kv-half mismatch) all produced the identical line and could not be told
    # apart — the records-half fix (6a903a09) was deployed and this message looked exactly the same
    # afterwards. PRE failing means our stashed pre-state does not reproduce L1's justified root, i.e. the
    # stash is wrong for that cursor. POST failing means replaying the span's calls from that pre-state
    # does not land on the root we captured, i.e. the proof's semantics differ from the node's own apply.
    # Those are completely different bugs and they now print differently.
    _pre_ok, _post_ok = (pre_full == sr), (post_full == root)
    if not (_pre_ok and _post_ok):
        _rec_hex = f"{rec_hex[:16]}…->{SST.digest_hex(rec_root)[:16]}…"   # pre->post; they can differ now
        print(f"[execnode] settle-with-proof ns={ns} self-check FAILED span {sc}->{cur} — "
              f"PRE {'ok' if _pre_ok else 'MISMATCH'}: proof={pre_full[:16]}… justified={str(sr)[:16]}… | "
              f"POST {'ok' if _post_ok else 'MISMATCH'}: proof={post_full[:16]}… ours={str(root)[:16]}… | "
              f"kv_pre={str(proof.get('kv_pre'))[:16]}… kv_post={str(proof.get('kv_post'))[:16]}… "
              f"rec={_rec_hex} calls={len(calls)} — falling back to quorum", flush=True)
        return None
    # SAY THAT THE PROOF SURVIVED. Between "[settle-prove] ... total 239.9s" and the DA publish there was
    # NO log line at all, so a prove that completed and then went nowhere was indistinguishable from one
    # that was still running — which is how a garbage-collected settle task hid for hours. Every outcome
    # after a completed prove is now named: this line, the self-check line above, the DA publish/FAILED
    # lines, or the REFUSED retry.
    print(f"[execnode] settle-with-proof BUILT ns={ns} span {sc}->{cur} — self-checks passed", flush=True)
    # 6a. ATTACH THE RECORDS HALF, if the span moved it. The three fields are exactly what
    # ops/transaction_ops.py reads: the transition, the claimed post root, and the PRE projection that
    # records_bind.pinned_pre_get hashes against the tip's records root so every value the binding
    # arithmetic touches is authenticated rather than taken on the prover's word.
    # Attached only when there IS a transition — L1 requires rec_post == rec_hex for a span that committed
    # no effects, so an absent records half is the frozen case and stays byte-identical to before.
    if _records_half is not None:
        _rtr, _rpost, _rproj = _records_half
        proof["records"], proof["rec_post"], proof["records_pre"] = _rtr, _rpost, _rproj
        print(f"[execnode] settle-with-proof ns={ns} span {sc}->{cur} carries a RECORDS half: "
              f"{rec_hex[:16]}… -> {_rpost[:16]}… ({len(_rtr.get('updates') or ())} update(s))", flush=True)
    # 6b. FOLDED proofs: self-VERIFY the recursion bundle at PROTOCOL strength (exactly what L1 runs) before
    # posting — a malformed fold is never broadcast; fall back to quorum. Runs in the worker thread.
    if proof.get("recursive") is not None:
        ok_v, why_v = await asyncio.to_thread(
            lambda: SS.verify_settlement_sparse(proof, depth=EXEC_TREE_DEPTH)[:2])
        if not ok_v:
            print(f"[execnode] recursive settle-with-proof ns={ns} self-verify failed ({why_v}) "
                  f"— falling back to quorum", flush=True)
            return None
    return proof


async def maybe_settle(session):
    """If enabled, post a `settle` of the current (cursor, state_root) to L1 — a bare bonded attestation,
    or (when the span conforms) a self-checking settle-with-proof. Only
    once the cursor has advanced SETTLE_EVERY blocks since the last one. Best-effort; never fatal."""
    global _last_settled_cursor
    # EPOCH-ALIGNED CADENCE. A proven span may not cross a dividend epoch boundary, and a fixed
    # "every SETTLE_EVERY blocks" cadence leaves the justified tip at an ARBITRARY offset inside an
    # epoch, so whether the next span straddles a boundary is luck. The comment above SETTLE_EVERY
    # claimed a straddling span would "re-anchor the justified tip at the boundary so the following
    # span conforms" — it never did: a straddling span skips the proof and settles bare at whatever
    # `cur` happens to be, which is just as likely to straddle again. MEASURED live 2026-08-04 over
    # 128 skips: 95 of them (74%) were epoch-boundary crossings, versus the ~50% the fixed cadence
    # predicts and against exactly ONE prove timeout. The cadence, not the proving cost, is what was
    # keeping the conforming-span count near zero.
    #
    # So re-anchor DELIBERATELY: settle as soon as the cursor enters a new epoch. That lands the
    # justified tip a block or two past the boundary, and every settle for the rest of that epoch is
    # then epoch-internal by construction. One boundary settle per epoch is unavoidable (getting from
    # epoch k to k+1 must cross once) but it costs a few hundred bytes as a bare attestation, and it
    # buys a GUARANTEED conforming span every epoch instead of an occasional lucky one.
    _c = state.cursor
    _advanced = _last_settled_cursor < 0 or (_c - _last_settled_cursor) >= SETTLE_EVERY
    _new_epoch = (_last_settled_cursor >= 0
                  and (_c // SETTLE_EPOCH) != (_last_settled_cursor // SETTLE_EPOCH))
    if not (_advanced or _new_epoch):
        return
    try:
        from ops.transaction_ops import construct_settle_tx
        from ops.key_ops import load_keys
        keys = load_keys()
        latest = await _get_json(session, "/get_latest_block")
        target = int(latest["block_number"]) + 2
        ok_any = False
        for ns, st in states.items():
            # PROVENANCE GATE: never attest an exec_root computed from a NON-canonical randomness window. A
            # node that cold-started mid-flight on a pruned L1 (or fell back to plain replay after a failed
            # bootstrap) is missing beacons/blockhashes a from-genesis node still serves, so a BEACON/BHASH
            # read reverts here but returns a value there → our root diverges. Attesting it could push a wrong
            # root toward the settle quorum. Skip until the window is canonical (bootstrap-from-settled fixes
            # it immediately, or it self-heals once the gap ages past retention). See ExecState.window_canonical.
            if not st.window_canonical():
                # THROTTLED: while gated, ok_any stays False so maybe_settle re-enters every poll and the
                # window can take a full retention span to heal — an unthrottled print would flood the log
                # for days. One line per _SETTLE_SKIP_LOG_EVERY seconds per namespace.
                _now = time.time()
                if (_now - _settle_skip_logged.get(ns, 0.0)) >= _SETTLE_SKIP_LOG_EVERY:
                    _settle_skip_logged[ns] = _now
                    print(f"[execnode] settle ns={ns} SKIPPED — randomness window not canonical (cursor "
                          f"{st.cursor}, beacon_floor {st.beacon_floor}, blockhash_floor {st.blockhash_floor}); "
                          f"would risk a divergent exec_root. Set NADO_EXEC_BOOTSTRAP to adopt the settled "
                          f"checkpoint.", flush=True)
                continue
            # CAPTURE THE WHOLE PAIR ATOMICALLY, RECORDS HALF INCLUDED. This used to read (cursor, root)
            # and say "the tail loop is single-task, so st does not advance during the (possibly
            # minutes-long) proving await below". That was true when settling was AWAITED from the tail.
            # e1000cbd detached it — precisely so the tail would keep applying blocks — which made the
            # comment false and left the proof builder recomputing the RECORDS half from a live `st` that
            # had moved on. state_root is rnode(kv, records), so comparing a root taken at cursor C against
            # a records half taken later compares two things that were never simultaneously true.
            # Observed live: "self-check failed (span 19154->19184 not conforming)" on a span wholly inside
            # one dividend epoch — i.e. where the epoch gate guarantees the records did NOT move.
            cur, root, rec_root_at_cur, _gen_at_cur = st.settle_snapshot()
            # DO NOT PROVE A SECOND SPAN WHILE THE FIRST PROOF IS STILL WAITING FOR ITS LANDING BLOCK.
            # The hold below fires only `if proof is None`, so it suppressed a redundant BARE settle but
            # never a redundant PROOF: this loop proved first and then skipped the hold entirely. That was
            # invisible while a prove took 300+ s (the _settle_proving flag covered the whole window).
            # 1affffac took a prove to ~12 s, and the waste became obvious immediately — MEASURED
            # 2026-08-06 13:12:06-13:13:42, three proves and three 8.92 MiB transactions in 96 seconds:
            #     cursor=46892 total 11.7s -> tx 8.92 MiB
            #     cursor=46893 total 13.3s -> tx 8.92 MiB
            #     cursor=46897 total 11.9s -> tx 8.92 MiB
            # all for the SAME root 1b00b000dd28252d, and only one of them can ever land — the moment one
            # is justified the others fail "pre_root must extend the settled tip". That is ~27 MiB of
            # gossip and 3x the prove CPU for one settlement.
            # `_settle_pending[ns]` is cleared by the resolution block below when the proof lands, when it
            # is resubmitted, or when it gives up after SETTLE_RESUBMIT_MAX_S — so this can never wedge.
            _pend_hold = _settle_pending.get(ns) is not None
            proof = None
            try:
                if not _pend_hold:
                    proof = await _build_settlement_proof(session, ns, st, cur, root, rec_root_at_cur)
                    # HOLD THE TIP THE INSTANT A PROOF EXISTS — not later, at the publish step.
                    #
                    # THIRD ATTEMPT AT THIS BUG, and the first two missed because I pattern-matched instead
                    # of tracing the flag LIFECYCLE. Three guards cover the pipeline in sequence:
                    # _settle_proving (the prove), _settle_publishing (publish+submit), _settle_pending (the
                    # wait for the landing block). _settle_proving is cleared by the prove TASK's
                    # done-callback, but _settle_publishing was not set until the publish step — and between
                    # those two points sit the self-checks, the recursive self-verify, and an awaited
                    # /get_latest_block. A concurrent maybe_settle pass landing in that gap sees all three
                    # clear and starts a second prove.
                    # MEASURED 2026-08-06 16:16:43-16:17:12, AFTER both earlier fixes: prove for 48650
                    # finished 16:16:43, its submit returned 16:17:05, and a prove for 48654 ran inside that
                    # 22-second window. bd079982 gated the prove on _settle_pending and 7b612e1e removed an
                    # awaited fetch before the marker — neither could help, because the marker legitimately
                    # does not exist yet while the proof is still being submitted.
                    # Setting it here makes the hold CONTINUOUS from prove-start to submit-end; the publish
                    # step re-stamps it, which is idempotent.
                    if proof is not None:
                        globals()["_settle_publishing"] = time.time()
            except Exception as e:
                # BEST-EFFORT, BUT NOT SILENT. A bare attestation always works, so swallowing here is
                # correct for liveness — but swallowing it QUIETLY meant an operator who switched the
                # prover on saw "SETTLE" instead of "SETTLE-WITH-PROOF" forever with no reason anywhere,
                # and no way to tell a disabled prover from a broken one. Rate-limited per (ns, reason) so
                # a persistent fault says so once rather than once per settle.
                proof = None
                if SETTLE_PROVE:
                    _k = (ns, f"{type(e).__name__}: {e}")
                    if _settle_skip_logged.get(_k) != _k[1]:
                        _settle_skip_logged[_k] = _k[1]
                        print(f"[execnode] settle-with-proof UNAVAILABLE ns={ns} cursor {cur} — falling "
                              f"back to a bare quorum attestation: {type(e).__name__}: {e}", flush=True)
            # DO NOT BARE-SETTLE PAST A PROOF THAT IS STILL IN FLIGHT.
            #
            # A proof for span sc->cur is only acceptable while the justified tip is STILL sc: L1 checks
            # that "Settle proof pre_root must extend the settled tip". Every bare settle advances that
            # tip, so bare-settling while our own prove is running guarantees the proof it is racing gets
            # refused the moment it arrives.
            #
            # That is exactly what happened, and it is the LAST thing standing between here and a
            # proof-carrying settle. Observed live 2026-08-04:
            #     17:10:02  BUILT span 21660->21690        (prove 67.5 s)
            #     17:12:21  PUBLISHED to DA 118.57 MiB     (+139 s)
            #     17:14:39  not accepted: "Settle proof pre_root must extend the settled tip"  (+138 s)
            # The proof VERIFIED — it cleared the fetch, the parse and the full 94 s cryptographic check —
            # and was then refused because bare settles had carried the tip from 21660 to 21720 during the
            # ~300 s (≈50 blocks) the pipeline took, against a 30-block cadence. The proof can never win
            # that race while we ourselves keep moving the target.
            #
            # So while a prove is outstanding, SKIP the settle entirely rather than settling bare. The cost
            # is that the settled tip stops advancing for the length of one pipeline (~5 min), bounded by
            # SETTLE_PROVE_TIMEOUT and released by the same done-callback that clears the in-flight guard.
            # That is the honest price of a validity-settled root at the current proving speed; the way to
            # shrink it is a faster pipeline (the fold, the DA/verifier ports), not more bare settles.
            # SELF-EXPIRING. A hold that gets stuck stops settlement FOREVER, which is far worse than the
            # race it prevents, so the publish/submit hold is a timestamp with a hard ceiling rather than a
            # bare boolean: even if a task dies between setting and clearing it, settling resumes on its own.
            _pub_active = (_settle_publishing
                           and (time.time() - _settle_publishing) < SETTLE_HOLD_MAX_S)
            # AND A PROOF-CARRYING SETTLE THAT IS ALREADY IN THE POOL still owns the tip until it lands or
            # expires — see _settle_pending. Resolved against L1 rather than assumed: the tip having reached
            # the pending cursor means it LANDED, and the height passing max_block means it can never land.
            _pend, _pend_active = _settle_pending.get(ns), False
            if _pend:
                try:
                    _sn = await _get_json(session, f"/get_settled?ns={ns}")
                    _sc_now = int((_sn or {}).get("exec_cursor", -1))
                except Exception:
                    _sc_now = -1
                _h_now = target - 2                       # target was latest+2
                # DID IT EVEN REACH THE PEERS? If not, no landing block can help — see
                # SETTLE_PROPAGATION_GRACE_S. Checked once, after a grace period long enough for ordinary
                # pull-gossip, and only for a DA-carried proof (an inline one propagates normally).
                if (_pend.get("proof_da") and not _pend.get("prop_checked")
                        and (time.time() - float(_pend.get("first_submitted") or 0)) > SETTLE_PROPAGATION_GRACE_S):
                    _pend["prop_checked"] = True
                    try:
                        from ops import peer_ops as _po2
                        _peers = [p for p in (_po2.known_peer_ips() or [])][:3]
                        _seen_by = 0
                        for _pip in _peers:
                            # aiohttp, NOT urllib: this runs on the event loop, and a blocking fetch here
                            # would stall the exec node for seconds per peer.
                            async with session.get(f"http://{_pip}:9173/transaction_pool",
                                                   timeout=aiohttp.ClientTimeout(total=4)) as _r2:
                                if _r2.status != 200:
                                    continue
                                _pp = json.loads(await _r2.text())
                            _ptx = _pp.get("transaction_pool") if isinstance(_pp, dict) else (_pp or [])
                            if any((t.get("data") or {}).get("proof_da") == _pend["proof_da"]
                                   for t in (_ptx or [])):
                                _seen_by += 1
                        if _peers and _seen_by == 0:
                            _settle_pending.pop(ns, None)
                            print(f"[execnode] settle-with-proof ns={ns} cursor {_pend['cursor']} has NOT "
                                  f"PROPAGATED to any of {len(_peers)} peers after "
                                  f"{SETTLE_PROPAGATION_GRACE_S}s — a peer cannot admit a proof-carrying "
                                  f"settle within its validation budget, so no landing block can help. "
                                  f"Releasing the tip instead of holding settlement for nothing.", flush=True)
                            continue
                    except Exception as _pe:
                        pass                              # a failed probe must never stall settlement
                if _sc_now >= int(_pend["cursor"]):
                    # SAY SO. This pop released the tip silently, so a prove starting right afterwards
                    # looked unexplained. If the duplicate is this firing early, this line is the evidence.
                    _settle_pending.pop(ns, None)         # it landed; the tip is already past it
                    print(f"[execnode] pending settle-with-proof ns={ns} cursor {_pend['cursor']} RELEASED "
                          f"— justified tip is {_sc_now}, at or past it", flush=True)
                elif _h_now > int(_pend["max_block"]):
                    # ITS LANDING BLOCK CAME AND WENT. A settle is EXACT-LANDING (ops/block_ops
                    # _lands_flexibly excludes it), so it can only be included by whoever produces exactly
                    # that height — and this validator wins about 19% of blocks (measured: 5 of 26, against
                    # ~14 distinct producers). Worse, no OTHER producer can realistically include it: doing
                    # so means fetching 118 MiB from DA and verifying it (~21.7 s) inside a ~6 s slot. So a
                    # proof-carrying settle lands only when WE produce its exact block, and one shot at ~19%
                    # is why every attempt so far expired unlanded.
                    #
                    # OBSERVED 2026-08-04: cursor 24870 submitted 22:33:26 for max_block 25014, NEVER
                    # excluded (the tip was held, pre_root stayed valid) — block 25014 was simply produced
                    # by 5828bf2e…, not us, so it was not there to be included.
                    #
                    # RESUBMIT RATHER THAN SURRENDER. The proof is already built and already published to
                    # DA; the tx carrying its commitment is ~8 KB, so another attempt costs a rounding error
                    # against the ~5 minute pipeline that produced it. Retry while the pre-state it proves
                    # is still the justified tip — which the hold is keeping true — and only give up after
                    # SETTLE_RESUBMIT_MAX tries so a proof that can never land cannot stall settlement.
                    _att = int(_pend.get("attempts", 1))
                    # DA-CARRIED ONLY. An INLINE proof is not held anywhere we can cheaply rebuild it from,
                    # and construct_settle_tx with both proof and proof_da None yields a BARE attestation —
                    # which would advance the justified tip while reporting a successful "resubmit", i.e.
                    # exactly the race this whole hold exists to prevent, dressed as a retry.
                    _held_for = time.time() - float(_pend.get("first_submitted") or time.time())
                    if (_held_for < SETTLE_RESUBMIT_MAX_S and _att < SETTLE_RESUBMIT_MAX
                            and _pend.get("proof_da") and _sc_now == int(_pend["pre_cursor"])):
                        try:
                            _rtx = construct_settle_tx(keys, int(_pend["cursor"]), _pend["root"], target,
                                                       ns=ns, proof=None, proof_da=_pend["proof_da"])
                            # Posted inline rather than through _submit(), which is defined further down
                            # this loop body. Same generous budget: L1 verifies a proof-carrying settle
                            # INLINE before it answers, so a short timeout would drop a good submit.
                            async with session.post(L1 + "/submit_transaction", json=_rtx,
                                                    timeout=aiohttp.ClientTimeout(
                                                        total=SETTLE_SUBMIT_TIMEOUT_PROOF)) as _rr:
                                _rb = await _rr.text()
                                try:
                                    _rout = json.loads(_rb) if _rb.strip() else None
                                except ValueError:
                                    _rout = None
                                if _rout is None:
                                    _rout = {"result": False, "message": f"HTTP {_rr.status}"}
                            if isinstance(_rout, dict) and _rout.get("result"):
                                _pend["max_block"] = int(_rtx.get("max_block") or target)
                                _pend["attempts"] = _att + 1
                                print(f"[execnode] settle-with-proof ns={ns} cursor {_pend['cursor']} missed "
                                      f"block {_h_now} (produced by someone else) — RESUBMITTED for "
                                      f"max_block {_pend['max_block']} (attempt {_att + 1}, "
                                      f"{_held_for:.0f}s/{SETTLE_RESUBMIT_MAX_S}s held); the proof and its "
                                      f"DA blob are reused",
                                      flush=True)
                                _pend_active = True
                            else:
                                _settle_pending.pop(ns, None)
                                print(f"[execnode] settle-with-proof ns={ns} cursor {_pend['cursor']} could "
                                      f"not be resubmitted ({_rout}); releasing the tip", flush=True)
                        except Exception as _re:
                            _settle_pending.pop(ns, None)
                            print(f"[execnode] settle-with-proof ns={ns} resubmit failed "
                                  f"({type(_re).__name__}: {_re}); releasing the tip", flush=True)
                    else:
                        _settle_pending.pop(ns, None)
                        print(f"[execnode] pending settle-with-proof ns={ns} cursor {_pend['cursor']} GIVING "
                              f"UP after {_att} attempt(s) over {_held_for:.0f}s (tip is {_sc_now}, "
                              f"pre-state was {_pend['pre_cursor']}); releasing the tip", flush=True)
                else:
                    _pend_active = True
            # `_pend_hold` is included so the pass that DECLINED to prove (above) does not fall through to a
            # bare settle when the resolution block has just popped the pending entry as landed. Without it,
            # every landed proof would be followed by one bare settle, quietly halving the proof rate — the
            # opposite of what suppressing the duplicate prove is for. Holding costs one poll; the next pass
            # proves the wider span.
            # _records_proving belongs in this list for exactly the reason the message below states. The
            # RECORDS half takes minutes, and _settle_proving is False for all of it (it covers the KV prove
            # and is set later), so a bare settle sailed through this gate on every cadence and walked the
            # justified tip forward while the records proof was still being built — guaranteeing its refusal
            # the moment it finished. Observed 01:13:57: SETTLE-WITH-PROOF cursor 3630 landed while batch
            # 4/13 of a records prove was still running.
            #
            # THIRD INSTANCE OF ONE PATTERN, so it is worth naming: the records prove was added after all of
            # these guards were written for the KV prove, and it is just as expensive. It had to be added to
            # the in-flight check, given its own flag because _settle_proving is not raised during its
            # window, and now added here. When a second expensive path is introduced, every gate that names
            # the first one is a site that needs revisiting.
            if proof is None and (_settle_proving or _records_proving or _pub_active or _pend_active
                                  or _pend_hold):
                _k = (ns, "hold-for-inflight-proof")
                if _settle_skip_logged.get(_k) != _k[1]:
                    _settle_skip_logged[_k] = _k[1]
                    print(f"[execnode] settle HELD ns={ns} cursor {cur} — a settle-prove is in flight or a "
                          f"proof-carrying settle is waiting for its landing block, and a bare settle now "
                          f"would advance the justified tip past the span it proves, guaranteeing its "
                          f"refusal ('pre_root must extend the settled tip')", flush=True)
                continue
            # REFRESH THE DEADLINE AFTER PROVING. `target` was computed before this loop, and building a
            # proof takes MINUTES — long enough for max_block to fall into the past, which L1 rejects as
            # expired. Observed live 2026-08-03: the 97.45 MiB proof was refused for size (expected) and
            # the bare retry was then ALSO refused, because it inherited the same stale deadline; a settle
            # that should have landed was lost. Re-read the tip and re-derive the deadline so both the
            # proof-carrying tx and any bare retry are submitted against the CURRENT height.
            #
            # REFRESH UNCONDITIONALLY. Gating this on `proof is not None` missed the case that matters most:
            # when the prove TIMES OUT, _build_settlement_proof returns None, so the refresh was skipped and
            # the bare settle went out carrying a max_block from before a 20-MINUTE prove. Observed live
            # 2026-08-04: "prove exceeded SETTLE_PROVE_TIMEOUT=1200s" immediately followed by
            # "settle ns=default not accepted: 'Target block too low'". The settle we fell back to in order
            # to stay live was itself dead on arrival. Time passes whether or not a proof came back, so the
            # deadline is refreshed on every path.
            if True:
                try:
                    _fresh = await _get_json(session, "/get_latest_block")
                    target = int(_fresh["block_number"]) + 2
                except Exception:
                    pass                                   # keep the old deadline rather than skip the settle
            if proof is not None:
                globals()["_settle_publishing"] = time.time()   # hold the tip across publish AND submit
            # PUBLISH THE PROOF TO DA WHEN IT CANNOT RIDE ON CHAIN. Measured: a settle-with-proof is
            # ~97.45 MiB against an 8 MiB submit cap and a ~256 KiB block, so inlining it is refused and
            # the proof has, until now, existed only on this box — produced and thrown away. Publishing it
            # k-of-n and carrying only the commitment means any node can reconstruct and verify it
            # (da_fetch checks the commitment round-trip), which is the difference between "we assert this
            # root" and "here is the evidence, go check".
            #
            # A proof small enough to inline still goes inline: that path already settles the root
            # TRUSTLESSLY with no quorum, and is strictly better than a commitment.
            proof_da = None
            # PROOF-CARRYING SETTLES ARE LIVE. They were briefly suspended (02bcac6c) because a settle
            # carrying proof_da took this node OUT OF CONSENSUS: the tx sits in our own mempool and every
            # block-candidate build re-verified it, driving the core loop from ~1 s to 91 s (blocks frozen
            # 221 s, 219 unhealthy episodes, 2026-08-04). Both causes are now FIXED rather than avoided:
            #
            #   VERIFICATION COST  94.2 s -> 28.8 s. The 80 s hot spot was alghash2.merkle_verify_paths
            #                      running SINGLE-THREADED in Rust over 1.4 M sponge hashes (106,880 items
            #                      x 13 levels). Path verification is embarrassingly parallel and ctypes
            #                      releases the GIL, so the batch is now split across cores. Bit-identical,
            #                      including rejecting a corrupted item at the SAME index.
            #   RE-VERIFICATION    0.000001 s. The cryptographic verdict is a pure function of the proof's
            #                      bytes, so it is memoised per proof identity in validate_transaction.
            #                      Re-deriving it on every candidate build was the actual outage; every
            #                      context check around it still runs each time.
            #   DISTRIBUTION       /da/get now falls back to da_fetch, which gathers k+1 VERIFIED shards
            #                      from the peer network and caches them locally so proofs spread as nodes
            #                      fetch. Previously it read only local shards, so nobody but the publisher
            #                      could ever obtain a proof and every other validator deferred forever.
            if proof is not None:
                try:
                    # SERIALIZE THE PROOF ONCE, AND OFF THE EVENT LOOP.
                    #
                    # This used to json.dumps the WHOLE settle tx purely to measure it, discard those ~120
                    # MiB, and then serialize the proof AGAIN for the blob — twice the work, both times
                    # synchronously on the event loop. Measured live 2026-08-04: BUILT 14:22:15 -> PUBLISHED
                    # 14:25:48 is 213 s, of which the DA encode is only ~51 s at the post-08945e50 rate of
                    # 0.428 s/MiB. The redundant serialization was the other ~160 s, and it also froze block
                    # application for as long as it ran.
                    #
                    # construct_settle_tx embeds the proof as `d["proof"] = proof`, so the tx is the proof
                    # plus a small envelope (address, ML-DSA signature, public key, a few ints) — far under
                    # the allowance below. Measuring the blob and adding that allowance decides the inline
                    # question exactly as well, and the SAME bytes then go to DA.
                    _blob = await asyncio.to_thread(
                        lambda: json.dumps(proof, separators=(",", ":"), sort_keys=True).encode())
                    _inline = len(_blob) + SETTLE_TX_ENVELOPE_MAX
                    if _inline > SETTLE_INLINE_MAX:
                        _meta = await asyncio.to_thread(DA.put, _blob, DA_K, DA_N)
                        proof_da, proof = _meta["commitment"], None
                        print(f"[execnode] proof PUBLISHED to DA ns={ns} span→{cur}: "
                              f"{len(_blob)/1048576:.2f} MiB, k={DA_K}/n={DA_N}, commitment={proof_da} "
                              f"(too large to inline at ~{_inline/1048576:.2f} MiB)", flush=True)
                        # ANNOUNCE IMMEDIATELY, BEFORE THE TX EXISTS. This is what makes a proof-carrying
                        # settle admissible: peers begin pulling the blob NOW and finish while we are
                        # still refreshing the deadline, building, signing and gossiping the tx — so when
                        # validate_transaction finally calls _fetch_da_proof, the bytes are already local
                        # and the 8 s budget is spent on a local read instead of a 118 MiB transfer.
                        # Announcing returns as soon as peers ACK the string; their fetch runs in their
                        # background, so this costs us ~one round trip, not a transfer. The deadline is
                        # re-derived just below regardless, so the few seconds spent here are accounted.
                        try:
                            _told = await da_announce(session, proof_da)
                            print(f"[execnode] DA announce ns={ns} span→{cur}: {_told} peer(s) will "
                                  f"prefetch {proof_da[:16]}… before the settle tx reaches them", flush=True)
                        except Exception as e:
                            # Best-effort by design: peers still fall back to the on-demand fetch.
                            print(f"[execnode] DA announce failed ns={ns} span→{cur} "
                                  f"({type(e).__name__}: {e}) — peers will fetch on demand", flush=True)
                except Exception as e:
                    # Availability is best-effort: a DA failure must not cost us the settlement.
                    print(f"[execnode] DA publish FAILED ns={ns} span→{cur} ({type(e).__name__}: {e}) — "
                          f"settling without a published proof", flush=True)
                    proof_da, proof = None, None
            # REFRESH THE DEADLINE AGAIN, AFTER THE DA PUBLISH. The refresh above happens BEFORE the
            # publish, and publishing is itself a long operation: measured live 2026-08-04, serialising a
            # 120 MiB tx and erasure-coding the blob took 213 s — ~35 blocks at 6 s each. So the very first
            # DA publish this chain ever completed produced
            #     proof PUBLISHED to DA ns=default span→20010: 120.27 MiB, k=4/n=8, commitment=9a665eb8…
            #     settle ns=default not accepted: {'result': False, 'message': 'Target block too low'}
            # — the settle was refused BECAUSE the publish succeeded. Same class as 3c23e354 (refresh on
            # every path); the DA publish is simply a second minutes-long stage that invalidates a deadline
            # derived before it. Re-derive immediately before building the tx we actually submit.
            # UNCONDITIONAL, for the same reason the first refresh is: the inline path also serialises a
            # ~120 MiB tx to measure it, which is minutes of CPU on its own. Whatever happened above, this
            # is the last instant before the tx we actually submit is built.
            try:
                _fresh2 = await _get_json(session, "/get_latest_block")
                # A proof-carrying settle needs a MUCH longer runway: L1 verifies it inline (~94 s ≈ 16
                # blocks) before the submit returns, so +2 expires before the tx can ever be included.
                # A RECORDS-BEARING PROOF NEEDS A FAR LONGER RUNWAY THAN A KV-ONLY ONE, because L1
                # verifies it inline before the submit returns and the two cost wildly different amounts.
                # MEASURED on the first records half ever to verify (span 6644->6660, 27 effects):
                #     [settle-verify] KV half        12.1s
                #     [settle-verify] RECORDS half 1073.0s      <- 179 blocks at 6 s
                #     settle submit took 1094.4s -> HTTP 200
                # The proof was ACCEPTED — both halves ok=True — and then expired unincluded, because
                # max_block had been stamped only SETTLE_PROOF_TX_MARGIN=60 blocks ahead. That constant was
                # sized for PROPAGATION (~42 s observed), which is the right size for a KV-only settle and
                # roughly 3x too small for a records-bearing one. The comment on it already names this
                # failure — "too small and the tx expires unincluded, wasting one prove" — it simply could
                # not anticipate L1's own verification as the cause.
                #
                # So the margin follows the proof: KV-only keeps 60 (a blanket raise would stall every
                # ordinary settle by ~28 minutes for a cost it does not pay), and a records half gets a
                # runway that exceeds its measured verification with room for propagation on top. Both stay
                # under TX_LANDING_WINDOW (360), so a tx admitted against a slightly-behind peer still fits.
                _has_records = bool(isinstance(proof, dict) and proof.get("records"))
                _margin = ((SETTLE_PROOF_RECORDS_TX_MARGIN if _has_records else SETTLE_PROOF_TX_MARGIN)
                           if (proof is not None or proof_da) else 2)
                target = int(_fresh2["block_number"]) + _margin
            except Exception:
                pass                                       # keep the old deadline rather than skip the settle
            tx = construct_settle_tx(keys, cur, root, target, ns=ns, proof=proof, proof_da=proof_da)
            if proof is not None:
                # SIZE IS THE BINDING CONSTRAINT, so measure it rather than infer it. A settle carries one
                # proof PER SEGMENT and segments are block-aligned, so the payload grows with the span —
                # the widely-quoted "1263 KB, constant in call count" is per EPOCH, not per settle, and
                # conflating the two hides the fact that a 20-block span is tens of MB. Logged next to the
                # span that produced it so the achievable span is a measurement, not a guess.
                try:
                    _sz = len(json.dumps(tx, separators=(",", ":")))
                    _segs = len((proof or {}).get("segments") or [])
                    print(f"[execnode] settle-with-proof ns={ns} span→{cur}: {_segs} segment(s), "
                          f"tx {_sz / 1048576:.2f} MiB", flush=True)
                except Exception:
                    pass
            async def _submit(_tx):
                """POST one settle and return L1's verdict dict, never raising.

                NEVER let an unparseable reply abort the settle loop. L1 sometimes answers with an EMPTY
                body (a rate-limit or proxy path that returns no content), and r.json() then raises
                JSONDecodeError — which used to propagate to the outer handler and skip the whole
                namespace's settle for that tick, once a minute, reported only as
                "Expecting value: line 1 column 1 (char 0)" with no endpoint and no line. A submit whose
                RESULT is unknown is simply a submit that did not visibly succeed: treat it as not
                accepted, keep the reason, and let the next tick retry."""
                # A PROOF-CARRYING SETTLE IS VERIFIED INLINE BY L1 BEFORE IT ANSWERS, so the reply cannot
                # arrive until that finishes. MEASURED 2026-08-04: verify_settlement_sparse on a real
                # 118.57 MiB proof takes 94.2 s. Against a flat 15 s budget the POST timed out every time —
                # "settle error at execnode.py:707 in _submit: TimeoutError" — while L1 was still busy
                # verifying a proof that then VERIFIED FINE. The settle was lost to the clock, not to any
                # judgement about the proof.
                #
                # Only the proof-carrying path needs the longer budget; a bare attestation is a few hundred
                # bytes and must keep the short one so an unresponsive L1 cannot stall the settle loop.
                _carries_proof = bool((_tx.get("data") or {}).get("proof")
                                      or (_tx.get("data") or {}).get("proof_da"))
                _budget = SETTLE_SUBMIT_TIMEOUT_PROOF if _carries_proof else 15
                # TIME THE SUBMIT. This budget has never been measured for a records-bearing proof — the
                # first one built died on the clock at ~305 s against the old 300 s, so all anyone knows is
                # "more than 300". The elapsed number decides whether the budget was simply too small or
                # whether the PROOF has to shrink, and those call for opposite fixes.
                # SERIALIZE OURSELVES, IN A THREAD, AND TIME IT SEPARATELY.
                #
                # `json=_tx` makes aiohttp json.dumps the whole transaction INSIDE the coroutine. For a
                # records-bearing settle that is ~169 MiB of nested Python — seconds to minutes of pure CPU
                # ON THE EVENT LOOP, which is the same class of mistake as 3e58e485 (prove_transition run
                # inline hung the node silently). Blocks would stop being applied while it ran.
                #
                # It also hid where the time went. A 169.43 MiB submit FAILED after 1204.2s against a 1200s
                # budget, while a KV-only 8.92 MiB submit took 34.9s — 19x the bytes but far more than 19x
                # the time, so the cost is SUPER-LINEAR and "the proof is too big" and "we serialize badly"
                # are both live explanations. They call for completely different fixes, so measure them
                # apart: `ser` is ours, and the remainder is transfer + L1 parse + L1 verification.
                _t_ser = time.time()
                _payload = await asyncio.to_thread(
                    lambda: json.dumps(_tx, separators=(",", ":")).encode())
                _ser_s = time.time() - _t_ser
                if _carries_proof:
                    print(f"[execnode] settle payload serialised in {_ser_s:.1f}s "
                          f"({len(_payload) / 1048576:.2f} MiB) — POSTing", flush=True)
                _t_sub = time.time()
                try:
                    async with session.post(L1 + "/submit_transaction", data=_payload,
                                            headers={"Content-Type": "application/json"},
                                            timeout=aiohttp.ClientTimeout(total=_budget)) as r:
                        _body = await r.text()
                        if _carries_proof:
                            print(f"[execnode] settle submit took {time.time() - _t_sub:.1f}s "
                                  f"(budget {_budget}s) → HTTP {r.status}", flush=True)
                        try:
                            _out = json.loads(_body) if _body.strip() else None
                        except ValueError:
                            _out = None
                        if _out is None:
                            _out = {"result": False,
                                    "message": f"HTTP {r.status}, unparseable body: {(_body or '')[:120]!r}"}
                        return _out
                except Exception:
                    if _carries_proof:
                        print(f"[execnode] settle submit FAILED after {time.time() - _t_sub:.1f}s "
                              f"(budget {_budget}s)", flush=True)
                    raise

            out = await _submit(tx)
            # PROOF REJECTED ⇒ STILL SETTLE. The proof is an OPTIONAL upgrade to a settlement that must
            # happen either way: latest_settled() is what bridge_withdraw, unshield and dividend_withdraw
            # prove against, so a namespace that stops settling is an outage, not a degraded mode.
            #
            # Until this existed, the fallback covered only a proof that failed to BUILD — a proof that
            # built fine and was then REFUSED by L1 left the tx rejected, ok_any False and the cursor
            # retried forever. That is not hypothetical: a settle-with-proof measures 97.30 MiB against
            # L1's 8 MiB submit cap (doc/settle-proof-transport.md §1), so turning the prover on would have
            # answered every settle with HTTP 413 and stopped settlement dead, once per poll, while burning
            # minutes of proving CPU each time. Retrying the SAME (cursor, root) bare keeps the chain
            # settling while the prover runs in production, which is what makes unconditional proving safe
            # to enable before DA transport lands.
            if proof is not None and not (isinstance(out, dict) and out.get("result")):
                _why = (out or {}).get("message") if isinstance(out, dict) else out
                # Re-derive the deadline again: the refused submit itself cost a round trip, and on a
                # 97 MiB body that is not instant.
                try:
                    _fresh = await _get_json(session, "/get_latest_block")
                    target = int(_fresh["block_number"]) + 2
                except Exception:
                    pass
                tx = construct_settle_tx(keys, cur, root, target, ns=ns)
                out = await _submit(tx)
                print(f"[execnode] settle-with-proof REFUSED ns={ns} cursor {cur} — retried bare: "
                      f"{'accepted' if isinstance(out, dict) and out.get('result') else 'also refused'}. "
                      f"L1 said: {str(_why)[:160]}", flush=True)
                proof = None
            if isinstance(out, dict) and out.get("result"):
                ok_any = True
                # stash the snapshot AT this settle so /exec/state_snapshot can serve a joiner a
                # payload that is verifiable against exactly this (cursor, root) once justified — AND it is
                # the pre-state the NEXT settle-with-proof extends. Serialized NOW — the live dicts keep
                # mutating, a reference stash would drift.
                _settled_snapshots[ns] = json.dumps({"ns": ns, "cursor": cur, "state_root": root,
                                                     "state": st._snapshot()}, sort_keys=True)
                # ...and keep it addressable by cursor so the next prove can find the pre-state at
                # whatever cursor L1 ends up justifying, not only at our newest one.
                _h = _settled_history.setdefault(ns, {})
                _h[cur] = _settled_snapshots[ns]
                for _old in sorted(_h)[:-_SETTLED_HISTORY_KEEP]:
                    del _h[_old]
                # ...and to DISK, so a restart does not blind the prover for a whole settle cadence.
                _stash_persist(ns, cur, _settled_snapshots[ns])
                # NAME THE THREE OUTCOMES DISTINCTLY. This read `'-WITH-PROOF' if proof else ''`, but the
                # DA path sets `proof = None` the moment the proof moves to DA — so a settle carrying a DA
                # commitment logged as a bare "SETTLE", byte-identical to a quorum attestation. The one
                # event this whole subsystem exists to produce was therefore INVISIBLE in the log, and a
                # monitor grepping "SETTLE-WITH-PROOF" could never match it. Third instrumentation blind
                # spot of the day, same shape as the missing BUILT line and the case-sensitive grep.
                _kind = ("-WITH-PROOF" if proof is not None else
                         "-WITH-DA-PROOF" if proof_da else "")
                _via = f" proof_da={proof_da}" if proof_da else ""
                print(f"[execnode] SETTLE{_kind} ns={ns} cursor {cur} "
                      f"root {root[:16]}…{_via} → L1", flush=True)
            else:
                print(f"[execnode] settle ns={ns} not accepted: {out}", flush=True)
            # THE SUBMISSION is over, so release the publish hold. THE TRANSACTION MAY NOT BE: a settle is
            # an EXACT-LANDING tx, so an ACCEPTED proof-carrying settle now waits in the mempool until its
            # own max_block and is still racing every bare settle until then. Record it so the hold above
            # keeps covering it; a refused one is genuinely finished and records nothing.
            globals()["_settle_publishing"] = 0.0
            # Keyed on what was ACTUALLY SUBMITTED, not on the local `proof`/`proof_da` variables: when a
            # proof-carrying settle is refused, the code retries BARE (rebuilding `tx`, clearing `proof`)
            # while `proof_da` stays set, so testing those would register a hold for a bare attestation
            # that nothing is waiting on.
            _txd = (tx or {}).get("data") or {}
            if isinstance(out, dict) and out.get("result") and (_txd.get("proof") or _txd.get("proof_da")):
                try:
                    _mb = int((tx or {}).get("max_block") or target)
                except Exception:
                    _mb = target
                # Everything needed to rebuild the tx is kept: the proof itself stays in DA, so a
                # resubmission is just this commitment against a fresh landing block.
                # RECORD THE MARKER FIRST, THEN LOOK UP pre_cursor — NOT the other way round.
                # MEASURED 2026-08-06 16:08:54-16:09:13: two proof-carrying settles 19 s apart for the same
                # root (48582 then 48585, 7.19 MiB each). The prove gate added in bd079982 keys on
                # _settle_pending, and _settle_publishing (which guards the publish/submit window) is
                # cleared once the submit returns — so between "submit accepted" and "marker recorded" there
                # was a hole exactly one /get_settled round trip wide, and a fresh prove started inside it.
                # The awaited fetch was what opened it, for a value nothing needs immediately.
                _settle_pending[ns] = {"cursor": cur, "max_block": _mb, "root": root,
                                       "proof_da": _txd.get("proof_da"), "pre_cursor": -1,
                                       "attempts": 1, "first_submitted": time.time()}
                # `pre_cursor` is the justified tip this proof EXTENDS. The resubmit path is only sound
                # while that is still the tip — the proof pins pre_root to it — so it is recorded rather
                # than inferred later. -1 above means "not yet known"; the resubmit path already treats an
                # unknown pre_cursor as a reason to give up rather than to guess.
                try:
                    _pre = await _get_json(session, f"/get_settled?ns={ns}")
                    _settle_pending[ns]["pre_cursor"] = int((_pre or {}).get("exec_cursor", -1))
                except Exception:
                    pass
        if ok_any:
            _last_settled_cursor = state.cursor
    except Exception as e:
        # WHERE, not just WHAT. This printed a bare message, and "Expecting value: line 1 column 1
        # (char 0)" — json.loads("") — is the least informative string in Python: it names neither the
        # endpoint that returned empty nor the line that parsed it. One frame of location turns a recurring
        # mystery into a fix.
        import traceback as _tb
        _fr = _tb.extract_tb(e.__traceback__)
        # The DEEPEST frame is useless here — for a JSONDecodeError it is always json/decoder.py, which
        # names neither the endpoint nor the call. Report the deepest frame in OUR OWN file, which is the
        # line that actually made the request.
        _ours = [f for f in _fr if f.filename.endswith("execnode.py")]
        _pick = (_ours or _fr)[-1] if _fr else None
        _where = f"{_pick.filename.rsplit('/', 1)[-1]}:{_pick.lineno} in {_pick.name}" if _pick else "?"
        print(f"[execnode] settle error at {_where}: {type(e).__name__}: {e}", flush=True)


async def _get_json(session, path):
    """GET an L1 endpoint and decode the JSON body regardless of content-type, with a 15s timeout."""
    async with session.get(L1 + path, timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.json(content_type=None)


# PROVISIONAL (fast, pre-finality) view: clones of the finalized states with the UNFINALIZED L1 tail
# speculatively applied. Rebuilt every poll from the finalized checkpoint, so a reorg self-heals on the next
# rebuild and no persistent/finalized state is ever touched. Readers opt in with ?provisional=1. None until
# the first refresh (readers then fall back to the finalized state).
prov_states = None
PROV_MAX_TAIL = 64          # cap the speculative tail depth (bounds work if this node is far behind the tip)


async def _apply_block(session, states_map, default_state, block, verbose=True):
    """Apply ONE L1 block's exec-relevant txs — blobs to their namespace in states_map, bridge/shield to
    default_state — then advance every state's cursor to this height. Returns False (applying NOTHING) if a
    field_transfer proof is unavailable via DA, so the block STALLS in L1 order. Shared by the finalized tail
    AND the provisional clone, so both apply identically."""
    h = block["block_number"]
    # DA PRE-RESOLVE (all-or-nothing): resolve every field_transfer proof BEFORE mutating, so one missing
    # proof stalls the whole block rather than half-applying it (every node fetches the same bundle -> no divergence).
    resolved = {}
    for tx in block.get("block_transactions", []):
        d = tx.get("data")
        if (tx.get("recipient") == "blob" and isinstance(d, dict)
                and d.get("op") == "field_transfer" and d.get("proof_da") and "bundle_json" not in d):
            # A MALFORMED proof_da (path chars -> DaStore._dir raises) or non-UTF-8 DA bytes are NOT a
            # temporarily-unavailable proof — they are a permanently-bad tx, so SKIP it (apply_blob then
            # no-ops the field_transfer) rather than stall or crash the whole block forever. `bb is None`
            # (genuinely unavailable) still stalls in L1 order, unchanged. L1 admission now rejects such a
            # proof_da anyway (transaction_ops); this is defence in depth for any block already in history.
            try:
                bb = await da_fetch(session, d["proof_da"])
                if bb is None:
                    if verbose:
                        print(f"[execnode] block {h}: a field_transfer proof is UNAVAILABLE via DA — stalling at {h}", flush=True)
                    return False
                resolved[tx.get("txid")] = bb.decode()
            except Exception as e:
                if verbose:
                    print(f"[execnode] block {h}: skipping field_transfer with bad DA proof ({type(e).__name__})", flush=True)
    for tx in block.get("block_transactions", []):
      # PER-TX GUARD (halt-class, audit 2026-07): this DISPATCH code — not apply_blob, which is already
      # fully guarded — used a payload field (`ns`) as a dict key with no type check, so a blob carrying an
      # unhashable ns raised TypeError HERE and aborted the whole block before the cursor advance below. The
      # tail loop then refetched the same block forever: a permanent, fleet-wide exec halt for one
      # MIN_TX_FEE tx. L1 admission now refuses such a payload; this ensures ONE bad tx can never freeze the
      # cursor regardless (a block from history, or any future field this loop reads without checking).
      try:
        if tx.get("txid") in resolved and isinstance(tx.get("data"), dict):
            tx = {**tx, "data": {**tx["data"], "bundle_json": resolved[tx["txid"]]}}
        r = tx.get("recipient")
        if r == "blob":
            d = tx.get("data")
            bns = d.get("ns", "default") if isinstance(d, dict) else "default"
            tgt = states_map.get(bns) if isinstance(bns, str) else None
            if tgt is not None:
                res = tgt.apply_blob(d, tx.get("sender"), tx.get("txid"))
                if verbose:
                    print(f"[execnode] block {h} ns={bns}: {res}", flush=True)
        elif r == "xmsg":
            d = tx.get("data") or {}
            tgt = states_map.get(d.get("to_ns"))
            if tgt is not None:
                res = tgt.apply_xmsg(d.get("from_ns", "default"), d.get("message") or {})
                if verbose:
                    print(f"[execnode] block {h} ns={d.get('to_ns')}: {res}", flush=True)
            # the delivery burned the (from_ns, seq) L1 nullifier — GC the SOURCE outbox record too
            src = states_map.get(d.get("from_ns", "default"))
            if src is not None:
                src.drop_consumed_outbox((d.get("message") or {}).get("seq"))
        elif r in ("bridge_withdraw", "dividend_withdraw", "unshield"):
            # a FINALIZED claim burned its L1 nullifier — the exec-side exit record is dead weight
            # in state_root now; GC it (state.drop_claimed). ns-aware for bridge_withdraw.
            d = tx.get("data") or {}
            ns = d.get("ns", "default") if r == "bridge_withdraw" else "default"
            tgt = states_map.get(ns)
            if tgt is not None:
                tgt.drop_claimed(r, d.get("nonce"))
        elif r == "bridge":
            default_state.credit_deposit(tx.get("sender"), tx.get("amount", 0))
            if verbose:
                print(f"[execnode] block {h}: bridge deposit {tx.get('amount')} by {(tx.get('sender') or '')[:12]}…", flush=True)
        elif r == "faucet":
            # FAUCET DONATION (doc/faucet.md): an L1 tx to the reserved name locked `amount` in the L1
            # faucet escrow; mirror it as spendable balance of the FIXED-NAME faucet CONTRACT ("faucet"
            # is its literal cid — see state.FIXED_CIDS), whose claim() method PAYs grants to players.
            default_state.credit_deposit("faucet", tx.get("amount", 0))
            if verbose:
                print(f"[execnode] block {h}: faucet donation {tx.get('amount')} by {(tx.get('sender') or '')[:12]}…", flush=True)
        elif r == "treasury_execute":
            # TREASURY -> FAUCET payout: a MINED treasury_execute is a completed payout (L1 validation gated
            # the 2/3 quorum, funding and the one-shot pid nullifier, and apply credited the L1 faucet
            # escrow). When the approved spend targets the reserved faucet name, mirror it into the faucet
            # CONTRACT's spendable balance exactly like a donation, so game grants/prizes can pay from it.
            spend = (tx.get("data") or {}).get("spend") or {}
            if spend.get("recipient") == "faucet":
                default_state.credit_deposit("faucet", int(spend.get("amount") or 0))
                if verbose:
                    print(f"[execnode] block {h}: treasury->faucet payout {spend.get('amount')}", flush=True)
        elif r == "shield":
            d = tx.get("data") or {}
            if d.get("field"):
                res = default_state.apply_field_shield(tx.get("amount", 0), d.get("owner"), d.get("rho"))
            else:
                res = default_state.apply_shield(tx.get("amount", 0), d.get("out_commitments", []), d.get("openings", []))
            if verbose:
                print(f"[execnode] block {h}: {res}", flush=True)
        elif r == "reveal":
            # RANDAO reveal (#randao): accumulate the secret into every namespace's beacon accumulator, so the
            # BEACON opcode can read the same grind-resistant chain randomness consensus derives.
            d = tx.get("data") or {}
            for _st in states_map.values():
                _st.record_reveal(d.get("target_epoch"), d.get("secret"))
        elif r == "duty":
            # The live path emits attest/commit/reveal MERGED into one `duty` tx (core_loop), and L1 records
            # its carried reveal via reveal_put — but this loop only saw STANDALONE `reveal` txs, so every exec
            # BEACON was computed reveal-free (predictable + grind-able) AND mismatched L1's with-reveals value,
            # so a settle-with-proof over a BEACON contract could never pass the chain-read cross-check. Feed
            # the duty-carried reveal in exactly like a standalone one so the exec beacon == L1's.
            rv = (tx.get("data") or {}).get("reveal")
            if rv:
                for _st in states_map.values():
                    _st.record_reveal(rv.get("target_epoch"), rv.get("secret"))
      except Exception as e:
        # A single malformed tx must never abort the block — that is the permanent-wedge bug. Skip it and
        # go on; the cursor still advances below. Deterministic: every node hits the same exception on the
        # same tx and skips identically, so no fork. (apply_blob's own effects are already guarded upstream.)
        if verbose:
            print(f"[execnode] block {h}: skipped tx {(tx.get('txid') or '')[:12]}… ({type(e).__name__}: {e})", flush=True)
    for _st in states_map.values():
        _st.cursor = h
        # TIME opcode: the DETERMINISTIC chain clock, NOT block_timestamp. block_timestamp sits outside the
        # block-hash preimage (so honest clock skew cannot fork the chain) and therefore differs between
        # honest nodes for the SAME block — measured live at 1 s apart. Feeding it to the VM made any
        # contract that reads TIME able to diverge exec state, and with it exec_root and the settle quorum.
        # chain_clock(h) is a pure function of block height, so every node runs the contract identically.
        _st.block_ts = _chain_clock(h)
        _st.advance_beacons(h)      # cache every epoch beacon now finalized at this height
        _st.record_block_hash(h, block.get("block_hash"))   # BLOCKHASH randomness for this finalized height
    return True


# key of the last COMPLETE provisional build: (finalized, tip, tip_hash, sum of base-state versions).
# tip_hash pins the whole unfinalized tail (parent-hash linkage), the version sum pins the base states —
# so an identical key proves the rebuild would reproduce the exact same clones. None -> always rebuild.
_prov_key = None
# incremental-tail bookkeeping (see _refresh_provisional): the last (height, hash) applied to prov_states,
# and how many polls since the last full rebuild. PROV_FULL_EVERY bounds any drift the incremental path
# could accumulate — at one poll per block that is a fresh clone every few minutes, which costs one slow
# poll and makes the fast path unable to go quietly wrong for long.
_prov_last = None
_prov_since_full = 0
# The finalized state's dividend generation at the moment the current tail was forked. The tail may only be
# EXTENDED while this still matches — see the accrual note in _refresh_provisional.
_prov_div_epoch = None
PROV_FULL_EVERY = 50
PROV_DEBUG = os.environ.get("NADO_EXEC_PROV_DEBUG") == "1"


async def _refresh_provisional(session, finalized, tip, tip_hash=None):
    """Refresh the provisional states: the finalized states plus the speculatively-applied UNFINALIZED tail
    (finalized+1 .. tip). Best-effort: leaves prov_states None (readers fall back to finalized) if there's
    nothing unfinalized.

    EXTENDS the existing tail whenever it can, and only rebuilds from the finalized checkpoint when it must.
    Rebuilding every poll is O(tail) per block, and the tail is the finality window — raising FINALITY_DEPTH
    to 45 quietly turned that into ~20 SECONDS of re-execution per poll, measured live. Every game client
    polls /exec/root?provisional=1 on its own tick, so that latency was the whole site feeling frozen.

    Extending is not an optimisation gamble, it is the same state by construction: provisional(F+1, T+1) is
    finalized(F+1) + blocks F+2..T+1, and finalized(F+1) is finalized(F) + block F+1 — so it equals the tail
    we already applied plus the one new block. The window slides; the applied set only grows. What must NOT
    be assumed is that the chain under us is the same one, so the anchor block is re-checked by hash every
    poll (one request) and ANY mismatch — reorg, re-anchor, shorter chain — falls back to the full rebuild.
    A periodic forced rebuild bounds any drift the incremental path could ever accumulate."""
    global prov_states, _prov_key, _prov_last, _prov_since_full, _prov_div_epoch
    tip = min(tip, finalized + PROV_MAX_TAIL)
    if tip <= finalized:
        prov_states = None
        _prov_key = None
        _prov_last = None
        return
    key = (finalized, tip, tip_hash, sum(st._mut_gen for st in states.values()))
    if prov_states is not None and tip_hash is not None and key == _prov_key:
        return                                   # nothing changed since the last COMPLETE build — keep it

    t0, start_h = time.time(), finalized + 1
    clones, h, keep = None, finalized + 1, False
    # THE ACCRUAL FENCE. Extending assumes the finalized state moved ONLY by applying blocks — that is the
    # whole algebra in the docstring above. The presence-dividend accrual breaks it: it runs in the poll
    # loop AFTER a batch of blocks, writes state.dividend (a state_root leaf, exec_root T_DIV_BAL), and the
    # tail — forked from an older finalized state and fed nothing but _apply_block — never receives it. The
    # tail's root then disagrees with a rebuild for every epoch that pays out, which is exactly what the
    # audit kept catching (8 of 8 drifts on this node were preceded by accruals, none without).
    #
    # Replaying the accrual onto the tail instead is NOT equivalent, so don't be tempted: collect_dividend
    # burns the sender's WHOLE accrued balance (state.py), so a collect sitting in the unfinalized tail
    # would burn a pre-accrual balance and then have the replayed share added back on top — a different
    # dividend map AND a different withdrawal amount than the rebuild produces. Order matters, and the only
    # order that is right is the one the rebuild has.
    #
    # So: a tail may be extended only across pure block application. Any accrual retires it.
    _div_epoch_now = getattr(states.get("default"), "last_div_epoch", None)
    if (prov_states is not None and _prov_last and _prov_since_full < PROV_FULL_EVERY
            and finalized <= _prov_last[0] < tip
            and _prov_div_epoch == _div_epoch_now):
        anchor = await _get_json(session, f"/get_block_number?number={_prov_last[0]}")
        if isinstance(anchor, dict) and anchor.get("block_hash") == _prov_last[1]:
            # same chain: keep the tail we already executed and add only what's new. Clone it rather than
            # mutating in place — readers hold prov_states while we work, and a half-applied block is a
            # board that shows a bet placed and the balance not yet moved. The clone is what the old code
            # paid every poll anyway; the replay it replaces is the part that cost 20 seconds.
            clones, h, keep = {ns: st.clone() for ns, st in prov_states.items()}, _prov_last[0] + 1, True
    if clones is None:
        clones, h, keep = {ns: st.clone() for ns, st in states.items()}, finalized + 1, False
        _prov_since_full = 0
        _prov_div_epoch = _div_epoch_now      # this tail is forked from THIS dividend generation
    start_h = h
    default_clone = clones.get("default")
    last = _prov_last if keep else None
    while h <= tip:
        block = await _get_json(session, f"/get_block_number?number={h}")
        if not isinstance(block, dict) or "block_transactions" not in block:
            break                                # unfetchable / body-less -> stop the speculative tail here
        if not await _apply_block(session, clones, default_clone, block, verbose=False):
            break
        last = (h, block.get("block_hash"))
        h += 1
    # AUDIT: every PROV_FULL_EVERY polls the extended tail is re-derived from the finalized checkpoint and
    # the two are compared root-for-root. The incremental path must be bit-identical to the rebuild — this
    # state root is what the bonded quorum settles on L1 — so rather than trust the argument, prove it on
    # live data at a 1/PROV_FULL_EVERY amortised cost and shout if it is ever wrong. The rebuild always
    # wins, so a drift self-corrects within one audit window instead of settling something false.
    if keep and _prov_since_full + 1 >= PROV_FULL_EVERY and h > tip:
        # WHERE THE TIME GOES. This audit is the single slowest thing the exec node does — measured at
        # 119-199s against a 0.73s median poll, with the cursor frozen throughout, which is what players
        # experience as the game hanging for minutes. The obvious suspect (re-fetching the window over
        # HTTP) is NOT it: 46 blocks fetch in 0.5s when measured directly. So split the clock three ways
        # — clone, fetch, apply — and let the next occurrence say which one owns the minutes, instead of
        # guessing at a fix for the wrong bottleneck.
        _t_clone = time.time()
        fresh = {ns: st.clone() for ns, st in states.items()}
        _t_clone = time.time() - _t_clone
        _t_fetch = _t_apply = 0.0
        fdef, fh = fresh.get("default"), finalized + 1
        while fh <= tip:
            _m = time.time()
            b = await _get_json(session, f"/get_block_number?number={fh}")
            _t_fetch += time.time() - _m
            if not isinstance(b, dict) or "block_transactions" not in b:
                break
            _m = time.time()
            _ok_apply = await _apply_block(session, fresh, fdef, b, verbose=False)
            _t_apply += time.time() - _m
            if not _ok_apply:
                break
            fh += 1
        print(f"[execnode] prov AUDIT rebuild {finalized}..{tip}: clone {_t_clone:.1f}s · "
              f"fetch {_t_fetch:.1f}s · apply {_t_apply:.1f}s · {fh - (finalized + 1)} block(s)", flush=True)
        if fh > tip:
            bad = [ns for ns in fresh if ns in clones and fresh[ns].state_root() != clones[ns].state_root()]
            if bad:
                # NAME THE ROWS. "The two disagreed" tells you the audit works and nothing about WHY, and
                # this fires perhaps three times an hour on a live node — far too rare to catch under a
                # debugger and far too costly to leave alone (the rebuild it forces freezes every game read
                # for the length of the finality window). So the message carries the diff: which snapshot
                # component drifted and a sample of the differing keys. Read-only, bounded, and only ever
                # on this already-exceptional path.
                detail = []
                for ns in bad:
                    try:
                        inc, reb = clones[ns]._snapshot(), fresh[ns]._snapshot()
                        for k in sorted(set(inc) | set(reb)):
                            a, b = inc.get(k), reb.get(k)
                            if a == b:
                                continue
                            if isinstance(a, dict) and isinstance(b, dict):
                                keys = [x for x in sorted(set(a) | set(b)) if a.get(x) != b.get(x)]
                                extra = [x for x in keys if x not in reb.get(k, {})]
                                missing = [x for x in keys if x not in inc.get(k, {})]
                                detail.append(f"{ns}.{k}: {len(keys)} key(s) differ "
                                              f"(incremental-only {len(extra)}, rebuild-only {len(missing)}) "
                                              f"e.g. {keys[:4]}")
                            else:
                                detail.append(f"{ns}.{k}: incremental={repr(a)[:60]} rebuild={repr(b)[:60]}")
                    except Exception as e:                    # diagnostics must never break the audit
                        detail.append(f"{ns}: <diff failed: {type(e).__name__}: {e}>")
                print(f"[execnode] PROVISIONAL DRIFT at {finalized}..{tip} in {bad} — "
                      f"incremental tail disagreed with the rebuild; using the rebuild"
                      + ("  ||  " + "; ".join(detail[:8]) if detail else "  ||  roots differ, no component diff"),
                      flush=True)
            clones = fresh
            _prov_since_full = -1                # this WAS the full build; start the next window from it
            _prov_div_epoch = _div_epoch_now     # ...and it is forked from the current dividend generation

    if PROV_DEBUG:
        print(f"[execnode] prov {'extend' if keep else 'FULL'} {finalized}..{tip} "
              f"applied={h - (start_h)} in {time.time() - t0:.2f}s", flush=True)
    prov_states = clones
    _prov_last = last
    _prov_since_full += 1
    # record the key only for a COMPLETE build; a partial one (fetch break) must retry next poll
    _prov_key = key if h > tip else None


async def _maybe_bootstrap(session):
    """SETTLED-CHECKPOINT BOOTSTRAP (joiner side): a FRESH namespace state (cursor -1) with
    NADO_EXEC_BOOTSTRAP set adopts the donor's last-settled snapshot INSTEAD of replaying from
    genesis (required once L1's idle-GC prunes ancient recert rows — /get_open_weights refuses the
    ancient epochs a genesis replay would need). Trust-minimized: the payload is accepted ONLY if
    the state_root RECOMPUTED from it matches the L1-settled (cursor, root) for the namespace —
    the bonded quorum vouches for the root, never the donor. Retries a few times (donor may not
    have settled since ITS restart; the L1 quorum may lag the donor's stash), then falls back to
    plain replay (fine on a young/unpruned chain, loudly wrong later via the accrual guard)."""
    if not BOOTSTRAP:
        return
    import threading as _threading
    for ns, st in states.items():
        if st.cursor >= 0:
            continue                                   # existing state — never overwrite
        for attempt in range(12):
            try:
                async with session.get(f"{BOOTSTRAP}/exec/state_snapshot?ns={ns}",
                                       timeout=aiohttp.ClientTimeout(total=30)) as r:
                    snap = await r.json(content_type=None)
                if not isinstance(snap, dict) or "state" not in snap:
                    raise ValueError(f"donor has no snapshot: {snap}")
                settled = await _get_json(session, f"/get_settled?ns={ns}")
                cand = ExecState.__new__(ExecState)    # verify on a scratch instance, never on `st`
                cand.path = st.path + "#bootstrap-verify"
                cand._mutate_lock = _threading.RLock()
                cand._restore(snap["state"])
                root = cand.state_root()
                if (settled.get("state_root") == root
                        and int(settled.get("exec_cursor", -2)) == int(snap.get("cursor", -3))):
                    st._restore(snap["state"])         # payload carries cursor/last_div_epoch/pools
                    st.save()
                    print(f"[execnode] BOOTSTRAPPED ns={ns} from settled checkpoint cursor {st.cursor} "
                          f"root {root[:16]}… (verified against L1 quorum)", flush=True)
                    break
                raise ValueError(f"snapshot (cursor {snap.get('cursor')}, root {root[:12]}…) is not the "
                                 f"L1-settled checkpoint ({settled.get('exec_cursor')}, "
                                 f"{str(settled.get('state_root'))[:12]}…) — retrying")
            except Exception as e:
                print(f"[execnode] bootstrap ns={ns} attempt {attempt + 1}: {e}", flush=True)
                await asyncio.sleep(5)
        else:
            print(f"[execnode] bootstrap ns={ns} FAILED after retries — continuing with plain replay "
                  f"(safe only while L1 still retains full recert history)", flush=True)


async def tail_loop():
    """Follow L1 forever: each poll, replay every newly FINALIZED block's exec-relevant txs (blob /
    bridge / shield) into `state` in block order — skipping pruned (body-less) finalized blocks — then
    accrue the presence dividend, persist, settle if enabled, and rebuild the fast PROVISIONAL view over the
    unfinalized tail. Only FINALIZED blocks mutate the persistent state, so its cursor never handles a reorg;
    the provisional clone absorbs the tail (and any reorg) harmlessly. Any error waits out the poll; never dies."""
    print(f"[execnode] tailing {L1} · state={STATE_PATH} · cursor={state.cursor}", flush=True)
    async with aiohttp.ClientSession() as session:
        await _maybe_bootstrap(session)
        stale_polls = 0     # consecutive polls seeing cursor > finalized (reroll-stranded state); see below
        while True:
            try:
                status = await _get_json(session, "/status")
                finalized = int(status.get("finalized_height", 0))
                # STALE-EXEC GUARD (reroll self-heal): we apply ONLY finalized blocks, so on a consistent chain
                # the cursor can never exceed L1's finalized tip. If it DOES, our on-disk state belongs to an OLD
                # chain that a reroll purged on L1 but left here (pre-.gen-marker state, or a load-before-purge
                # race) — exec is replaying the fresh chain onto stale state and would silently fork L2. There's
                # nothing to hash-compare (no shared heights), so the height inversion itself is the signal.
                # Corroborate over STALE_RESET_POLLS (~30s) so a slow L1 restart briefly reporting finalized=0
                # can't false-trigger, then reset to genesis and cold-replay the fresh chain — no manual restart.
                if state.cursor > finalized:
                    # HASH-COMPARE BEFORE DESTROYING ANYTHING. The height inversion alone is NOT evidence of a
                    # reroll: an L1 RESTART reports a low finalized height for as long as it takes to reload,
                    # and if that exceeds the corroboration window this branch wipes the entire exec layer.
                    # That is not hypothetical — on 2026-08-03 a slow L1 restart destroyed the live state and
                    # all 25 deployed contracts, which then had to be redeployed.
                    #
                    # The old comment claimed "there's nothing to hash-compare (no shared heights)". There is:
                    # state.block_hashes retains ~20000 finalized heights. If L1's block at a height we have
                    # ALSO applied hashes the same, we are on the SAME chain and merely ahead of a restarting
                    # node — never reset. Only a genuine MISMATCH means our state belongs to a purged chain.
                    _shared = None
                    if state.block_hashes:
                        _h = min(max(state.block_hashes), max(0, finalized))
                        if _h in state.block_hashes and _h > 0:
                            _shared = _h
                    if _shared is not None:
                        _blk = await _get_json(session, f"/get_block_number?number={_shared}")
                        _bh = (_blk or {}).get("block") or _blk or {}
                        _l1h = _bh.get("block_hash")
                        if _l1h and int(_l1h, 16) == int(state.block_hashes[_shared]):
                            # Same chain. L1 is restarting or catching up; our state is fine.
                            stale_polls = 0
                            await asyncio.sleep(POLL)
                            continue
                    stale_polls += 1
                    print(f"[execnode] cursor {state.cursor} > L1 finalized {finalized} "
                          f"({stale_polls}/{STALE_RESET_POLLS}) — possible stale state from a reroll"
                          f"{'' if _shared is None else f'; block {_shared} hash MISMATCHES L1'}", flush=True)
                    if stale_polls >= STALE_RESET_POLLS:
                        _reset_states_to_genesis(reason=f"cursor {state.cursor} outran finalized {finalized}")
                    await asyncio.sleep(POLL)
                    continue
                stale_polls = 0
                applied = 0
                while state.cursor < finalized:
                    h = state.cursor + 1
                    block = await _get_json(session, f"/get_block_number?number={h}")
                    if not isinstance(block, dict):
                        break                                  # fetch problem; retry next poll
                    if "block_transactions" not in block:
                        # A FINALIZED block (h <= finalized) with no body is PRUNED (rolling mode drops old
                        # block bodies, leaving only {block_number}). Such blocks predate the exec features and
                        # carry nothing to replay, so SKIP them — otherwise a fresh exec node can never
                        # cold-start on a pruned chain. Advance only the default cursor (the loop watermark);
                        # other ns cursors catch up on the next block with a body.
                        state.cursor = h
                        continue
                    if not await _apply_block(session, states, state, block, verbose=True):
                        break                                  # DA stall: do NOT advance the cursor; retry next poll
                    applied += 1
                if applied:
                    # PRESENCE DIVIDEND (doc/presence-dividend.md) — DETERMINISTIC per-epoch accrual: for each
                    # fully-completed epoch not yet accrued, distribute that epoch's total DIVIDEND_POOL inflow
                    # (L1 /get_dividend_inflow?epoch=E) over weights_at_epoch(E) (L1 /get_open_weights?epoch=E).
                    # Both are epoch-bound, so accrual is a PURE FUNCTION of the finalized block stream —
                    # identical on every node, committed in state_root. (The old code read a LIVE pool balance +
                    # LIVE current-epoch weights per poll batch → non-deterministic → default-layer settlement
                    # divergence.) Dividend is a DEFAULT-layer feature, so it accrues on `state`.
                    try:
                        from protocol import EPOCH_LENGTH
                        cur_epoch = state.cursor // EPOCH_LENGTH
                        while state.last_div_epoch < cur_epoch - 1:      # only epochs the cursor has fully passed
                            E = state.last_div_epoch + 1
                            inf = await _get_json(session, f"/get_dividend_inflow?epoch={E}")
                            inflow = int(inf.get("inflow", 0)) if isinstance(inf, dict) else 0
                            ow = await _get_json(session, f"/get_open_weights?epoch={E}")
                            if isinstance(ow, dict) and ow.get("error"):
                                # L1 pruned the recert history this epoch's weights need (idle-GC).
                                # NEVER accrue from a truncated reconstruction (would fork the
                                # settled root) — stall accrual + tell the operator to re-bootstrap.
                                print(f"[execnode] dividend accrual STALLED at epoch {E}: {ow['error']} — "
                                      f"re-bootstrap this node from a settled checkpoint "
                                      f"(NADO_EXEC_BOOTSTRAP)", flush=True)
                                break
                            weights = (ow or {}).get("weights", {}) if isinstance(ow, dict) else {}
                            dist = state.accrue_dividend_epoch(inflow, weights)
                            state.last_div_epoch = E
                            if dist:
                                print(f"[execnode] dividend epoch {E}: +{dist} raw to {len(weights)} miner(s)", flush=True)
                    except Exception as e:
                        print(f"[execnode] dividend accrue error: {e}", flush=True)
                    for _st in states.values():
                        _st.save()
                    print(f"[execnode] +{applied} block(s) → cursor {state.cursor} · "
                          f"root {state.state_root()[:16]}… · {len(state.contracts)} contract(s)"
                          + (f" · +{len(states)-1} rollup ns" if len(states) > 1 else ""), flush=True)
                    if SETTLE:
                        # NEVER AWAIT SETTLING FROM THE TAIL. maybe_settle can spend MINUTES proving, and
                        # awaiting it here stops block application for that whole time — the tail is a
                        # single task. Measured 2026-08-04 with unconditional proving on real state (25
                        # contracts, not the empty fixture I benchmarked): the exec cursor froze at 17853
                        # for 30+ minutes while L1 advanced to 18180, lag climbing 316 -> 327 and still
                        # rising. The chain was fine; this node simply stopped following it.
                        #
                        # Settling is a SIDE EFFECT of following the chain, never a precondition for it. So
                        # it runs detached: the tail keeps applying blocks at full speed while the proof
                        # builds. The in-flight guard inside _build_settlement_proof bounds concurrent
                        # PROVES to one — but it does NOT bound concurrent maybe_settle TASKS, which this
                        # comment used to claim. Every poll spawns one; while a prove is outstanding the
                        # rest fall straight through the guard to a bare settle, which is the intent.
                        #
                        # KEEP A STRONG REFERENCE. `_t` was a local that the next poll overwrote, so the
                        # task awaiting the prove was referenced by nothing for almost all of its life and
                        # could be collected mid-await — which is exactly what a completed prove that
                        # produced no settle and no error looks like.
                        _t = asyncio.ensure_future(maybe_settle(session))
                        _settle_tasks.add(_t)
                        _t.add_done_callback(_settle_tasks.discard)
                        _t.add_done_callback(_settle_task_done)
                # Rebuild the PROVISIONAL view EVERY poll (even with no newly-finalized block — the tip still
                # advances ~every block_time, so a just-included bet/reveal/deposit shows within ~one block
                # instead of a whole finality window). Best-effort; never breaks the finalized tail.
                try:
                    latest = await _get_json(session, "/get_latest_block")
                    tip = int(latest.get("block_number", state.cursor)) if isinstance(latest, dict) else state.cursor
                    tip_hash = latest.get("block_hash") if isinstance(latest, dict) else None
                    await _refresh_provisional(session, state.cursor, tip, tip_hash)
                except Exception as e:
                    print(f"[execnode] provisional refresh error: {e}", flush=True)
            except Exception as e:
                print(f"[execnode] tail error: {e}", flush=True)
            await asyncio.sleep(POLL)


# --- read-only query API ---------------------------------------------------------------------------
_NS404 = lambda: web.json_response({"error": "namespace not served by this node"}, status=404)


# ---- DA serving: publish / fetch erasure-coded objects by commitment -----------------------------
async def h_da_meta(request):
    """GET /da/meta?c=<commitment> — the manifest {commitment,k,n,stripes,length}, or 404 if unknown here."""
    m = DA.meta(request.query.get("c", ""))
    return web.json_response(m) if m else web.json_response({"error": "unknown commitment"}, status=404)


async def h_da_have(request):
    """GET /da/have?c=<commitment> — which shard indices this node currently holds."""
    c = request.query.get("c", "")
    return web.json_response({"commitment": c, "have": DA.have(c)})


async def h_da_shard(request):
    """GET /da/shard?c=<commitment>&i=<index> — one (shard, merkle-proof) the caller can verify against
    the commitment without trusting this node. 404 if not held."""
    c = request.query.get("c", "")
    try:
        i = int(request.query.get("i", ""))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad index"}, status=400)
    r = DA.shard(c, i)
    if not r:
        return web.json_response({"error": "no such shard"}, status=404)
    return web.json_response({"index": i, "shard": r[0].hex(), "proof": r[1]})


async def h_da_publish(request):
    """POST /da/publish — body is the RAW object bytes; erasure-code + store, return the manifest. A
    publisher (prover/wallet) calls this so a shielded proof is available to every exec node by commitment.
    Bounded by MAX_BODY_BYTES and the in-flight semaphore."""
    async with _sem():
        data = await request.read()
        if not data:
            return web.json_response({"error": "empty body"}, status=400)
        meta = await asyncio.to_thread(DA.put, data, DA_K, DA_N)
        return web.json_response(meta)


async def h_da_accept(request):
    """POST /da/accept — {meta, index, shard(hex), proof}: store a single peer-supplied shard IFF it
    verifies against the commitment (spread k-of-n availability). Returns {ok}."""
    try:
        j = await request.json()
        ok = DA.accept(j["meta"], int(j["index"]), bytes.fromhex(j["shard"]), j["proof"])
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": bool(ok)})


async def h_da_announce(request):
    """POST /da/announce — {commitment}: "this object exists, start pulling it NOW". Returns immediately
    and does the fetch in the BACKGROUND, so the caller never waits on our bandwidth.

    THIS IS THE FIX FOR PROOF-CARRYING SETTLEMENT. A settle proof is ~118 MiB. Before this, the first
    time a peer ever heard of a commitment was when the settle tx referencing it arrived — so the whole
    118 MiB transfer, decode and verify had to happen INSIDE validate_transaction's 8 s
    `_fetch_da_proof` budget. Measured: ~10 s+ fetch from the single holder + ~4.4 s decode + ~21.7 s
    verify ~= 36 s, so every peer raised ProofUnavailable, held ZERO in its pool, and the tx could never
    be admitted anywhere but here (see ops/transaction_ops._fetch_da_proof and the "NOT PROPAGATED"
    give-up in the settle pipeline). The bytes were always AVAILABLE; they just could not arrive in time.

    Announcing decouples transfer from validation: the publisher tells peers the moment the blob is
    published, each peer pulls it concurrently while the settle tx is still being built and gossiped,
    and by the time validation runs `_fetch_da_proof` hits the LOCAL store and returns in ~0.002 s.

    NOT A TRUST PATH. We only learn a commitment string; da_fetch then collects k+1 shards and checks
    each against the commitment, exactly as an on-demand fetch does. A bogus or hostile announcement
    costs one failed background fetch and nothing else — it cannot poison the store, because
    DaStore.accept/da.reconstruct verify the commitment round-trip before anything is kept.

    PUSH WAS NOT AN OPTION: /da/accept carries one shard HEX-ENCODED in a POST body capped at
    MAX_BODY_BYTES (16 MiB), while a k=4 shard of a 118 MiB proof is ~29.6 MiB raw / ~59 MiB hex. So the
    existing push endpoint structurally cannot carry a settle-proof shard; pull-on-announce reuses the
    fetch path that already works and already caches."""
    try:
        j = await request.json()
        c = str(j.get("commitment", ""))
    except Exception:
        return web.json_response({"ok": False, "error": "bad body"}, status=400)
    # Same shape guard the settle validator applies before this string reaches DaStore._dir.
    if not c or len(c) > 128 or "/" in c or "\\" in c or c in (".", ".."):
        return web.json_response({"ok": False, "error": "bad commitment"}, status=400)
    if DA.have(c) or c in _DA_PREFETCHING:
        # Already held, or a fetch for it is already in flight. Re-announcing is normal (every peer
        # announces to every peer), so this must be idempotent and must NOT start a second 118 MiB pull.
        return web.json_response({"ok": True, "already": True})
    _DA_PREFETCHING.add(c)

    async def _pull():
        try:
            async with aiohttp.ClientSession() as s:
                b = await da_fetch(s, c)                     # verifies + caches locally, or returns None
            print(f"[execnode] DA prefetch {'OK' if b else 'FAILED'} {c[:16]}…"
                  + (f" ({len(b)/1048576:.2f} MiB)" if b else ""), flush=True)
        except Exception as e:
            print(f"[execnode] DA prefetch ERROR {c[:16]}… ({type(e).__name__}: {e})", flush=True)
        finally:
            _DA_PREFETCHING.discard(c)                       # always clear, or a failure blocks retries forever

    asyncio.create_task(_pull())
    return web.json_response({"ok": True, "already": False})


async def h_da_get(request):
    """GET /da/get?c=<commitment> — reconstruct + return the RAW bytes from locally-held shards (>=k), or
    404. Convenience for a client that trusts this node; the trustless path is /da/meta + /da/shard."""
    # OFF THE EVENT LOOP. Reconstructing a settle proof is ~118 MiB of erasure decoding, and running it in
    # the handler froze the whole exec node — HTTP dead, block application stopped — for as long as it took.
    # The decode is far cheaper now that its Lagrange basis is hoisted (ops/da.py), but "cheaper" is not
    # "instant" at 118 MiB, and an endpoint any peer can call must never be able to stall the node: one
    # /da/get is otherwise a trivial remote DoS. Threaded, so the loop keeps serving while it decodes.
    # PULL FROM PEERS WHEN WE DO NOT HOLD IT. This called DA.get, which reads ONLY the local shard store —
    # so a node that had never published the proof itself answered 404 forever, and its L1 could never
    # resolve a DA-carried settle. That is why proof-carrying settlement could not work across a fleet: the
    # publisher held every shard and nobody else could obtain one, so every other validator deferred.
    #
    # da_fetch is the function this endpoint's own docstring in _fetch_da_proof already claimed it used —
    # "local store first, else collect k(+1) VERIFIED shards from ACROSS the peer network and reconstruct
    # trustlessly", caching the result so this node can then re-serve it. It was written and never wired
    # in here. Local hits still short-circuit inside da_fetch, so the publisher's own path is unchanged and
    # still answers from the blob cache in ~0.002 s.
    _c = request.query.get("c", "")
    data = await asyncio.to_thread(DA.get, _c)         # local: cached blob, or a shard reconstruct — THREADED
                                                       # (see the DoS note above; do not inline this again)
    if data is None:
        async with aiohttp.ClientSession() as _s:      # not held locally: gather k+1 verified shards
            data = await da_fetch(_s, _c)
    if data is None:
        return web.json_response({"error": "not reconstructible here"}, status=404)
    return web.Response(body=data, content_type="application/octet-stream")


_DA_PREFETCHING = set()    # commitments with a background pull in flight (h_da_announce dedupe)


async def da_announce(session, commitment, budget_s=20.0):
    """Tell every peer that `commitment` is published so they start pulling it NOW, in parallel, while we
    are still building and gossiping the settle tx that references it.

    Bounded and BEST-EFFORT: announcing is an optimisation, never a precondition for settling. Peers that
    are down, slow, or running older code simply do not prefetch, and fall back to the on-demand fetch
    that exists today — so this is safe to run against a mixed fleet. Returns the number of peers that
    accepted the announcement, for the log line."""
    urls = await _da_sources(session)
    if not urls:
        return 0

    async def _tell(u):
        try:
            async with session.post(f"{u}/da/announce", json={"commitment": commitment},
                                    timeout=aiohttp.ClientTimeout(total=budget_s)) as r:
                return 1 if r.status == 200 else 0
        except Exception:
            return 0                                        # unreachable / no such endpoint / timeout

    return sum(await asyncio.gather(*(_tell(u) for u in urls)))


async def _da_sources(session):
    """DA endpoints to try for a shard, in order — UNIVERSAL, no single hardcoded provider:
    the live L1 PEER SET (each peer runs the exec/DA node on the same convention port), plus an optional
    NADO_DA_URL seed. Availability rides the peer network, so any node that holds a shard can serve it."""
    out, seen = [], set()
    try:
        async with session.get(L1 + "/peers", timeout=aiohttp.ClientTimeout(total=10)) as r:
            peers = await r.json() if r.status == 200 else []
    except Exception:
        peers = []
    for p in (peers or []):
        host = str(p).split(":")[0].strip()                 # peer IP, strip any :port
        url = f"http://{host}:{PORT}" if host else ""       # its exec/DA node (same host, exec port)
        if url and url not in seen:
            seen.add(url); out.append(url)
    if DA_URL and DA_URL not in seen:
        out.append(DA_URL)                                  # optional extra seed, NOT the only source
    return out


async def da_fetch(session, commitment):
    """Resolve `commitment` to bytes: local store first, else collect k(+1) VERIFIED shards from ACROSS the
    peer network (any peers that hold them) and reconstruct trustlessly. Caches the result locally so this
    node can then re-serve it (proofs spread organically as nodes fetch). Returns bytes or None if the whole
    reachable network can't supply k good shards."""
    local = DA.get(commitment)
    if local is not None:
        return local
    meta, pairs = None, {}
    for src in await _da_sources(session):
        try:
            if meta is None:
                async with session.get(f"{src}/da/meta?c={commitment}",
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    meta = await r.json() if r.status == 200 else None
                # meta is UNTRUSTED (from a peer). Bound k/n before iterating so a lied manifest can't drive
                # an unbounded fetch loop; the definitive check is the commitment round-trip after reconstruct.
                if isinstance(meta, dict) and not (1 <= int(meta.get("k", 0)) <= int(meta.get("n", 0)) <= DA_N_MAX):
                    meta = None
            if meta is None:
                continue
            need = int(meta["k"]) + 1                        # +1 gives da.reconstruct its consistency check
            for i in range(int(meta["n"])):
                if i in pairs:
                    continue
                async with session.get(f"{src}/da/shard?c={commitment}&i={i}",
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        continue
                    jj = await r.json()
                pairs[i] = (i, bytes.fromhex(jj["shard"]), jj["proof"])
                if len(pairs) >= need:
                    break
            if len(pairs) >= need:
                break
        except Exception:
            continue
    if meta is None or len(pairs) < int(meta["k"]):
        return None
    try:
        k, n = int(meta["k"]), int(meta["n"])
        # PIN THE COMMITMENT WE ASKED FOR. `meta` came from a peer, so its own "commitment" field is just a
        # claim; everything below must be checked against the commitment the CALLER wants resolved.
        meta = dict(meta, commitment=commitment)
        # reconstruct_from verifies every shard against that commitment — and, since the manifest is bound
        # into each leaf (ops/da.py _leaf), that same check now authenticates k/n/stripes/length as well.
        # A lied manifest (e.g. a shorter `length`, which truncates the decode to different bytes that would
        # still pass a shard-only check) fails there, so every honest node reconstructs identical bytes.
        #
        # THIS USED TO RE-ENCODE THE WHOLE BLOB and compare commitments, because the manifest sat OUTSIDE
        # the commitment and nothing else could bind it. That round-trip cost ~50 s on a 118 MiB settle
        # proof — inside block validation — which is a large part of why a peer could not resolve a
        # DA-carried proof inside the block cadence at all.
        data = reconstruct_from(meta, list(pairs.values()))
        DA.put(data, k, n)                                   # cache -> we can now serve it too
        return data
    except Exception:
        return None


async def h_state_snapshot(request):
    """GET /exec/state_snapshot?ns=: the FULL state payload as of this node's LAST ACCEPTED settle,
    {ns, cursor, state_root, state} — the settled-checkpoint bootstrap donor side. The joiner
    re-derives state_root from `state` and accepts only if it matches the L1-settled (cursor, root),
    so a lying donor can waste its time but never poison it. 404 until this node has settled once."""
    ns = request.query.get("ns", "default")
    raw = _settled_snapshots.get(ns)
    if raw is None:
        return web.json_response({"error": "no settled snapshot yet (node hasn't settled since start)"},
                                 status=404)
    return web.Response(text=raw, content_type="application/json")


async def h_accounting(request):
    """GET /exec/accounting?ns=: the exec layer's AGGREGATE owed-value figures, for the L1 node's
    conservation invariants (ops/invariants.py). Totals only — no per-address detail, nothing private.

    The shielded numbers are the interesting ones: individual note VALUES are private, but every CHANGE to
    their total is public by construction (a deposit carries its L1 amount; a transfer's public_value/fee
    are public proof inputs), so `pool_value` is the pool's live total and IS safe to publish. That is what
    lets L1 reconcile SHIELD_ESCROW against the pool without seeing into it."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    def _sum(d):
        return sum(int(w.get("amount", 0)) for w in (d or {}).values())
    return web.json_response({
        "cursor": st.cursor,
        "bridge_credited": sum(int(v) for v in (st.bridge or {}).values()),
        "bridge_pending": _sum(st.withdrawals),
        "pool_value": int(getattr(st, "pool_value", 0) or 0),
        "pool_fees": int(getattr(st, "pool_fees", 0) or 0),
        "unshield_pending": _sum(st.unshield_withdrawals),
        "dividend_accrued": sum(int(v) for v in (st.dividend or {}).values()),
        "dividend_pending": _sum(st.dividend_withdrawals),
        "div_carry": int(getattr(st, "div_carry", 0) or 0),
    })


async def h_root(request):
    """Node summary for ?ns= (default): exec state_root, applied cursor, contract count, L1 tailed.

    The PROVISIONAL root is not computed unless it is already cached (or ?root=1 asks for it). Measured on
    this state: a cold state_root is ~24 SECONDS — the two depth-256 sparse trees are incremental, but a
    clone starts with an empty store, and the provisional view is a fresh clone after every rebuild. Since
    this handler shares the event loop with the whole query API, one poll of this endpoint froze EVERY exec
    request for 20+ seconds, which is what made the games feel dead. Nothing consumes the provisional root:
    the SDK reads cursor/block_ts, and settlement is always the FINALIZED root (only that one is ever posted
    to L1). So it is reported when free and null otherwise, rather than being paid for on every poll."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    prov = st is not states.get(request.query.get("ns", "default"))
    want_root = (not prov) or request.query.get("root") == "1" or st._root_cache is not None
    return web.json_response({"ns": request.query.get("ns", "default"),
                              "state_root": st.state_root() if want_root else None,
                              "cursor": st.cursor, "block_ts": st.block_ts, "contracts": len(st.contracts), "l1": L1})


async def h_settlement(request):
    """Settlement status for namespace ?ns= (default): its current (cursor, state_root), whether this node
    posts `settle` attestations, the cadence, the last cursor it settled, and every
    namespace this node runs. The interface combines this with L1's /get_settled?ns= to show tip vs settled."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({
        "ns": request.query.get("ns", "default"),
        "namespaces": list(states.keys()),
        "cursor": st.cursor,
        "state_root": st.state_root(),
        "contracts": len(st.contracts),
        "settle_enabled": SETTLE,
        "settle_every": SETTLE_EVERY,
        "last_settled_cursor": _last_settled_cursor,
        "l1": L1,
    })


async def h_examples(request):
    """The starter zkVM contract library (execnode/zkvm_examples.py) as {name: {code, abi}} — the wallet's
    Rollup tab offers these as one-click deploys."""
    from execnode import zkvm_examples
    return web.json_response({"examples": zkvm_examples.LIBRARY})   # name -> {code, abi}


async def h_runtimes(request):
    """The contract runtimes this node can execute (zkvm is the only one). A deploy blob may
    name one via {"op":"deploy","runtime":"<name>",...}."""
    from execnode import runtimes
    return web.json_response({"runtimes": runtimes.names(), "default": runtimes.DEFAULT_RUNTIME})


async def h_contracts(request):
    """Contracts in ?ns= (cid, deployer, method names, runtime) — storage omitted, use /exec/contract.
    SCALABLE: bounded + filterable so a huge namespace doesn't dump everything. Query params:
      ?deployer=<addr>  only that deployer's contracts (the wallet's "my contracts")
      ?prefix=<hex>     only cids starting with <prefix> (search-as-you-type)
      ?limit=<n>        cap the returned rows (default 100, max 500)
    Returns {ns, contracts:[…], total, limit} where total is the full match count (may exceed limit)."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    q_deployer = request.query.get("deployer")
    q_prefix = request.query.get("prefix", "")
    try:
        limit = max(1, min(500, int(request.query.get("limit", "100"))))
    except (TypeError, ValueError):
        limit = 100
    items, total = [], 0
    for cid, c in st.contracts.items():
        if q_deployer and c["deployer"] != q_deployer:
            continue
        if q_prefix and not cid.startswith(q_prefix):
            continue
        total += 1
        if len(items) < limit:
            items.append({"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys()),
                          "runtime": c.get("runtime", "zkvm"), "abi": c.get("abi") or {}})
    return web.json_response({"ns": request.query.get("ns", "default"), "contracts": items,
                              "total": total, "limit": limit})


async def h_contract(request):
    """One contract in full (?cid=&ns=): deployer, method names, and its ENTIRE storage. 404 if unknown."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    cid = request.query.get("cid", "")
    c = st.contracts.get(cid)
    if not c:
        return web.json_response({"error": "not found"}, status=404)
    # zkVM contracts with a view schema present their flat slots as the named maps the frontend expects
    # (so a ported game changes only its cid); others return raw storage.
    return web.json_response({"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys()),
                              "code": c["code"], "storage": st.decode_view(c), "runtime": c.get("runtime", "zkvm"),
                              "upgradable": c.get("upgradable", True), "abi": c.get("abi") or {}})


async def h_view(request):
    """Read-only contract call (?cid&method&args=<JSON list>&ns=) via ExecState.view — storage is never
    persisted; unparsable args degrade to []. Result is None for a missing contract/method or a revert."""
    import json
    st = _state_for(request)
    if st is None:
        return _NS404()
    cid = request.query.get("cid", "")
    method = request.query.get("method", "")
    try:
        args = json.loads(request.query.get("args", "[]"))
    except Exception:
        args = []
    # RET is a 64-bit field element (up to ~1.8e19) — a raw JSON number loses precision past 2^53 the instant
    # the browser JSON.parses it (amounts over ~900k NADO, hashes, commitments). Emit it as a STRING so the
    # client can BigInt() it exactly; Number("123") still works for small legacy readers (forward-compatible).
    _ret = st.view(cid, method, args)
    return web.json_response({"cid": cid, "method": method, "result": None if _ret is None else str(_ret)})


# (coinflip read endpoints removed — the Coin Flip dApp reads its state from the generic /exec/contract
# endpoint, since it is now an on-chain contract, not a native module)


async def h_blockhash(request):
    """One or more L1 block hashes for the BLOCKHASH randomness (?height=H  or  ?heights=H1,H2,…). Returns
    {height: hex|null} — null if the height is in the future or older than the node retains. Lets a game UI
    derive the same result the contract will (e.g. show the dice/wheel before anyone settles).

    DEFAULT is the FINALIZED state — a hash there can never reorg. This MUST be used for HIDDEN information
    (Hold'em hole cards): a provisional hash that reorged would silently show a player a different hand at
    showdown than they played. ?provisional=1 opts INTO the fast pre-finality tail — only safe for PUBLIC,
    on-chain-VALIDATED randomness (Farkle dice, wheel spins): if such a hash reorgs, the settling tx simply
    reverts and the player re-acts — a visible retry, never silent unfairness. It cuts the reveal wait from
    ~FINALITY_DEPTH blocks (~90s) to ~one block (~6-18s)."""
    ns = request.query.get("ns", "default")
    if request.query.get("provisional") in ("1", "true", "yes") and prov_states and ns in prov_states:
        st = prov_states[ns]           # fast pre-finality tail (opt-in; public+validated randomness only)
    else:
        st = states.get(ns)            # finalized: immutable, safe for hidden info
    if st is None:
        return _NS404()
    q = request.query
    hs = []
    if q.get("height"):
        hs = [q["height"]]
    elif q.get("heights"):
        hs = q["heights"].split(",")
    out = {}
    for h in hs:
        try:
            hi = int(h); v = st.block_hashes.get(hi)
            out[str(hi)] = (format(v, "x") if v is not None else None)
        except Exception:
            pass
    return web.json_response({"cursor": st.cursor, "hashes": out})


async def h_outbox(request):
    """List the cross-domain outbox messages emitted by namespace ?ns= (each {seq, from, to_ns, data})."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"),
                              "outbox": sorted(st.outbox.values(), key=lambda m: m.get("seq", 0))})


async def h_outbox_proof(request):
    """Merkle proof (?ns=&seq=) that outbox message `seq` is committed in the namespace's state_root (also
    returned). A consumer verifies it against the sender rollup's SETTLED root (L1 /get_settled?ns=). 404 if
    the seq is unknown."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    p = st.outbox_proof(request.query.get("seq", ""))
    if p is None:
        return web.json_response({"error": "not found"}, status=404)
    p["ns"] = request.query.get("ns", "default")
    p["state_root"] = st.state_root()
    return web.json_response(p)


async def h_inbox(request):
    """List the cross-domain messages DELIVERED to namespace ?ns= (each {from_ns, seq, data}) — messages an
    L1-verified `xmsg` folded into this rollup's inbox."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"), "inbox": st.inbox})


async def h_bridge(request):
    """All exec-side bridge balances plus every recorded (still-claimable) withdrawal record.
    ?provisional=1 reads the fast pre-finality clone (display-only, like every other provisional read);
    bridge balances live on the DEFAULT layer regardless of ?ns=, so pick the default clone directly."""
    st = state
    if request.query.get("provisional") in ("1", "true", "yes"):
        pv = prov_states
        if pv is not None and "default" in pv:
            st = pv["default"]
    return web.json_response({"balances": st.bridge, "withdrawals": st.withdrawals, "cursor": st.cursor})


async def h_assets(request):
    """The asset registry (doc/assets.md): every asset's metadata plus its holder count. ?issuer= filters to
    one issuer's assets; ?holder= adds that holder's balance per asset (so a wallet renders its whole token
    list in ONE request instead of one per asset — the full-storage-per-poll ceiling applies here too)."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    issuer, holder = request.query.get("issuer"), request.query.get("holder")
    out = []
    for aid, meta in sorted(st.assets.items()):
        if issuer and meta["issuer"] != issuer:
            continue
        # supply/balance go out as STRINGS. The cap is 2^62 and JSON numbers are IEEE doubles, so a browser
        # would silently truncate anything past 2^53 on parse — a balance that reads slightly wrong is worse
        # than one that fails loudly. Strings feed BigInt() exactly. (`dec`, `seed`, `holders` are small.)
        row = dict(meta, id=aid, supply=str(meta["supply"]), holders=len(st.abal.get(aid, {})))
        if holder:
            bal = st.asset_balance(aid, holder)
            if not bal:
                continue
            row["balance"] = str(bal)
        out.append(row)
    return web.json_response({"assets": out, "cursor": st.cursor})


async def h_asset(request):
    """One asset (?id=) with its metadata and holder table; ?holder= narrows to a single balance."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    aid = str(request.query.get("id") or "")
    meta = st.assets.get(aid)
    if meta is None:
        return web.json_response({"error": "no such asset"}, status=404)
    holder = request.query.get("holder")
    row = dict(meta, id=aid, supply=str(meta["supply"]))    # string amounts — see h_assets
    if holder:
        return web.json_response({"asset": row, "holder": holder,
                                  "balance": str(st.asset_balance(aid, holder)), "cursor": st.cursor})
    return web.json_response({"asset": row,
                              "holders": {h: str(v) for h, v in st.abal.get(aid, {}).items()},
                              "cursor": st.cursor})


async def h_allowances(request):
    """Delegated-spend authorizations (doc/assets.md §7a). Filters: ?owner= (approvals I GRANTED),
    ?spender= (approvals granted TO me), ?asset= (narrow to one asset). A wallet renders both of its
    allowance lists in two requests. Amounts are STRINGS (see h_assets — past 2^53 a browser truncates)."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    want_asset = request.query.get("asset")
    owner_f, spender_f = request.query.get("owner"), request.query.get("spender")
    out = []
    for aid, owners in st.allow.items():
        if want_asset and aid != want_asset:
            continue
        meta = st.assets.get(aid) or {}
        for owner, row in owners.items():
            if owner_f and owner != owner_f:
                continue
            for spender, amt in row.items():
                if spender_f and spender != spender_f:
                    continue
                out.append({"asset": aid, "sym": meta.get("sym", "?"), "dec": meta.get("dec", 0),
                            "owner": owner, "spender": spender, "amount": str(amt)})
    return web.json_response({"allowances": out, "cursor": st.cursor})


async def h_withdrawal_proof(request):
    """Merkle proof for a bridge-withdrawal record (?nonce=) against the CURRENT state_root (also
    returned); the claim only succeeds on L1 once a settled root covers it. 404 if the nonce is unknown."""
    # the Merkle proof a user submits to L1's bridge_withdraw to claim their exit against the settled root
    p = state.withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


async def h_dividend(request):
    """Presence-dividend view: with ?address= one miner's accrued balance + pending (collected,
    unclaimed) withdrawals; without it, the whole accrual map."""
    # a miner's accrued (uncollected) presence dividend + any COLLECTED-but-not-yet-claimed withdrawals (each
    # provable against the settled root via /exec/dividend_proof). Off-L1 (doc/presence-dividend.md). No addr -> all.
    addr = request.query.get("address")
    if addr:
        pending = [{"nonce": n, "amount": w["amount"]} for n, w in sorted(state.dividend_withdrawals.items())
                   if w["addr"] == addr]
        return web.json_response({"address": addr, "accrued": int(state.dividend.get(addr, 0)),
                                  "pending": pending, "cursor": state.cursor})
    return web.json_response({"dividend": state.dividend, "cursor": state.cursor})


async def h_dividend_proof(request):
    """Merkle proof for a collected dividend withdrawal (?nonce=) against the CURRENT state_root,
    submitted to L1's dividend_withdraw once settled. 404 if the nonce is unknown."""
    # the Merkle proof a miner submits to L1's dividend_withdraw to claim a collection against the settled root
    p = state.dividend_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


@web.middleware
async def _cors(request, handler):
    """Middleware: stamp allow-any-origin CORS headers on every response (HTTP-exception responses
    included) and short-circuit OPTIONS preflights with 204 — required because the wallet page is served
    from the L1 port, making every /exec/* browser fetch cross-origin."""
    # The light-miner page is served by the L1 node on a DIFFERENT port (:9173), so every /exec/* fetch from
    # the browser is cross-origin — without these headers the browser silently blocks the response (curl
    # doesn't, which is why it worked in tests but not in the wallet). Allow any origin. NOTE: the /exec/*
    # routes are read-only or compute-only — the /exec/prove_transfer[2] delegated provers PROVE and RETURN a
    # proof, they don't mutate (DA-only: transfers apply solely via the L1-ordered blob stream). They are
    # UNAUTHENTICATED — safe to expose because (a) the exec node binds loopback unless NADO_EXEC_BIND is opened,
    # (b) the STARK size bound rejects oversized inputs before allocation, and (c) an in-flight semaphore caps
    # concurrent proving. /da/publish is likewise size-capped + semaphore-bounded. Also answer the CORS preflight.
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    # Exec state is live + per-request (finalized vs ?provisional). NEVER let a proxy/CDN cache it, or two
    # clients can see divergent game/balance state. no-store beats any edge caching regardless of the fetch's
    # own cache mode.
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def h_shielded(request):
    """Phase-1 pool status: root, note/nullifier counts, recent anchors — aggregate data only, nothing
    per-note."""
    # Public shielded-pool state: the current Merkle root (an anchor), note count, and spent-nullifier count.
    # Reveals NOTHING about individual notes/owners/values (doc/privacy.md).
    return web.json_response({"root": state.shielded.root(), "notes": state.shielded.size(),
                             "nullifiers": len(state.shielded.nullifiers), "cursor": state.cursor,
                             "anchors": state.shielded.anchor_list[-8:]})


async def h_field_shielded(request):
    """Field-native pool status; with ?cm=<int> also that commitment's leaf position (None if absent).
    Big field ints are returned as strings."""
    # Phase-2 field-native pool status + (optionally) a commitment's position.
    fp = state.field_pool
    cm = request.query.get("cm")
    pos = fp.position(int(cm)) if (cm and cm.lstrip("-").isdigit()) else None
    return web.json_response({"root": str(fp.root()), "notes": len(fp.commitments),
                              "nullifiers": len(fp.nullifiers), "cursor": state.cursor, "pos": pos})


async def h_prove_transfer(request):
    """Delegated prover, 1-output (DA-only): the wallet POSTs its SECRET witness (nsk, note opening, output,
    amounts); we build the Merkle path and prove the join-split STARK off the event loop, then RETURN the
    proof as bundle_json. The caller publishes it to /da/publish + submits the commitment blob; we NEVER apply
    out-of-band. Semaphore-bounded (H-7); UNAUTHENTICATED, hence the loopback-by-default bind."""
    # DELEGATED PROVER: the wallet POSTs its secret witness; we build the Merkle path from the field pool and
    # produce the full join-split STARK proof. Returns the bundle as an opaque JSON string (big field ints).
    try:
        w = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    fp = state.field_pool
    try:
        pos = fp.position(int(w["cm"]))
        if pos is None:
            return web.json_response({"error": "note not in the field pool"}, status=404)
        from execnode import shielded_field as SFP

        def _prove():
            """Blocking STARK prove, run in a worker thread via asyncio.to_thread."""
            return SFP.prove_transfer(fp, int(w["nsk"]), int(w["value_in"]), int(w["rho_in"]), pos,
                                      int(w["out_value"]), int(w["out_owner"]), int(w["out_rho"]),
                                      int(w["public_value"]), int(w["fee"]), withdraw_addr=w.get("withdraw_addr"))
        async with _sem():                                 # H-7: bound concurrent proving
            bundle, public = await asyncio.to_thread(_prove)   # heavy STARK proving off the event loop
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
        # DA-ONLY (alphanet, no legacy single-operator apply): the delegated prover RETURNS the proof; the
        # caller publishes it to /da/publish and submits an L1 blob carrying only the commitment, so every
        # exec node applies it in L1 order. The exec node NEVER applies a transfer out-of-band. The bundle
        # rides as an opaque JSON STRING (its big field ints survive re-parse).
        return web.json_response({
            "bundle_json": json.dumps(bundle),
            "root": str(public["root"]), "nf": str(public["nullifiers"][0]),
            "cm_out": str(public["out_commitments"][0]),
            "public_value": public["public_value"], "fee": public["fee"],
        })
    except KeyError as e:
        return web.json_response({"error": f"missing witness field {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_field_leaves(request):
    """The field pool's full commitment list (public; big ints as strings) so a browser can build its own
    Merkle path and prove ON-DEVICE — the witness never reaches this node."""
    # the field pool's commitment list (public) so the browser can build the Merkle path itself and prove
    # ON-DEVICE (the node never sees the witness). Big ints as strings.
    return web.json_response({"leaves": [str(c) for c in state.field_pool.commitments]})


async def h_prove_transfer2(request):
    """Delegated prover, 2-output (send v1 to recipient + keep v2 change) — otherwise identical to
    h_prove_transfer: prove off-loop, then RETURN bundle_json for the caller to DA-publish + blob (no apply)."""
    # DELEGATED PROVER, 2-output: send v1 to a recipient + keep v2 change. Proves -> verifies -> applies.
    try:
        w = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    fp = state.field_pool
    try:
        pos = fp.position(int(w["cm"]))
        if pos is None:
            return web.json_response({"error": "note not in the field pool"}, status=404)
        from execnode import shielded_field as SFP

        def _prove():
            """Blocking 2-output STARK prove, run in a worker thread via asyncio.to_thread."""
            return SFP.prove_transfer2(fp, int(w["nsk"]), int(w["value_in"]), int(w["rho_in"]), pos,
                                       int(w["v1"]), int(w["o1"]), int(w["r1"]),
                                       int(w["v2"]), int(w["o2"]), int(w["r2"]),
                                       int(w["public_value"]), int(w["fee"]), withdraw_addr=w.get("withdraw_addr"))
        async with _sem():                                 # H-7: bound concurrent proving
            bundle, public = await asyncio.to_thread(_prove)
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
        # DA-ONLY: return the proof; the caller publishes it to DA + submits the commitment blob (see
        # h_prove_transfer). No out-of-band apply.
        return web.json_response({
            "bundle_json": json.dumps(bundle),
            "root": str(public["root"]), "nf": str(public["nullifiers"][0]),
            "cm_out1": str(public["out_commitments"][0]), "cm_out2": str(public["out_commitments"][1]),
        })
    except KeyError as e:
        return web.json_response({"error": f"missing witness field {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_shielded_note(request):
    """Spend witness for a Phase-1 note (?cm=): position + Merkle path (public data, leaks nothing);
    with ?nf= also whether that nullifier is already spent. 404 if the commitment isn't in the pool."""
    # a wallet's spend witness: position + Merkle path for its note commitment (public data, leaks nothing),
    # plus whether the note's nullifier is already spent (the wallet passes its own nf).
    cm = request.query.get("cm", "")
    p = state.shielded_note_proof(cm)
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    nf = request.query.get("nf")
    if nf:
        p["spent"] = state.shielded.has_nullifier(nf)
    return web.json_response(p)


async def h_unshields(request):
    """Pending unshield exits for an L1 address (?addr=) — how a wallet finds the nonce(s) to claim."""
    # a wallet lists its own pending unshield exits (by L1 address) to find the nonce(s) to claim
    return web.json_response({"unshields": state.unshields_for(request.query.get("addr", ""))})


async def h_unshield_proof(request):
    """Merkle proof for a recorded unshield exit (?nonce=) against the CURRENT state_root, submitted to
    L1's `unshield` to release SHIELD_ESCROW coins once settled. 404 if the nonce is unknown."""
    # the Merkle proof a user submits to L1's `unshield` to release SHIELD_ESCROW coins against the settled root
    p = state.unshield_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


def _zkvm_contract(st, cid):
    """The (contract, error-response) pair for a zkvm-runtime contract id."""
    c = st.contracts.get(cid)
    if not c:
        return None, web.json_response({"error": f"no contract {cid}"}, status=404)
    if c.get("runtime") != "zkvm":
        return None, web.json_response({"error": "contract is not on the zkvm runtime"}, status=400)
    return c, None


async def h_prove_call(request):
    """PROVEN EXECUTION (doc/zk-execution-proofs.md): execute one zkvm call against the CURRENT finalized
    state and return a STARK proof + the public I/O log. Any other node verifies with /exec/verify_call
    and applies the call via the log — never executing the contract. Body: {cid, method, caller, args,
    value?}. Returns {bundle_json, ret, cursor} — bundle_json is the self-contained proven-call bundle
    (stringified: its field ints don't survive JS JSON)."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    st = _state_for(request)
    if st is None:
        return _NS404()
    from execnode import runtimes as _rt
    from execnode.stark import vm_circuit, field as _F
    try:
        cid, method = body["cid"], body["method"]
        caller = body.get("caller", "prover")
        args = body.get("args", [])
        value = int(body.get("value", 0))
        c, err = _zkvm_contract(st, cid)
        if err:
            return err
        reg = dict(st.zk_addrs)                         # read-only path: never mutate state on a query
        cf, fargs = _rt.zkvm_statement(caller, args, reg)
        slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
        cursor, ts = st.cursor, st.block_ts
        beacons = {e: v % _F.P for e, v in st.beacons.items()}
        bhashes = {h: v % _F.P for h, v in st.block_hashes.items()}

        # ASSET CONTEXT (doc/assets.md): `asset` names the currency of `value`; `selfd` is DERIVED from the
        # cid on both sides, so it is never something the requester gets to choose.
        in_asset = int(body.get("asset") or 0)
        selfd = _rt.zkvm_addr_digest(cid)
        abal = st.holder_assets(cid)

        def _prove():
            """Blocking STARK prove (~tens of seconds), run in a worker thread via asyncio.to_thread."""
            return vm_circuit.prove_call(c["code"], method, cf, fargs, slots, value=value, cursor=cursor,
                                         timestamp=ts, beacons=beacons, block_hashes=bhashes,
                                         asset=in_asset, selfd=selfd, abal=abal)
        async with _sem():                               # H-7: bound concurrent proving
            proof, io, ret, _new = await asyncio.to_thread(_prove)
        bundle = {"cid": cid, "method": method, "caller": caller, "args": args, "value": value,
                  "asset": in_asset,
                  "cursor": cursor, "timestamp": ts, "io": [list(e) for e in io], "proof": proof}
        return web.json_response({"bundle_json": json.dumps(bundle), "ret": str(ret), "cursor": cursor})
    except KeyError as e:
        return web.json_response({"error": f"missing field {e}"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)   # incl. "call reverted — nothing to prove"
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_verify_call(request):
    """Verify a proven zkvm call WITHOUT executing it, then check its I/O log against THIS node's current
    state (zkvm.replay_io + chain-randomness cross-check). Body: {bundle_json} (from /exec/prove_call) or
    the same fields inline. Returns {ok, reason, ret, state_match, payouts} — ok = the proof is sound for
    the stated call; state_match = the log also applies cleanly to this node's state right now."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    st = _state_for(request)
    if st is None:
        return _NS404()
    from execnode import runtimes as _rt, zkvm
    from execnode.stark import vm_circuit, field as _F
    try:
        b = json.loads(body["bundle_json"]) if "bundle_json" in body else body
        c, err = _zkvm_contract(st, b["cid"])
        if err:
            return err
        cf, fargs = _rt.zkvm_statement(b.get("caller", "prover"), b.get("args", []), {})
        io = [tuple(int(x) for x in e) for e in b["io"]]

        def _verify():
            return vm_circuit.verify_call(b["proof"], c["code"], b["method"], cf, fargs, io,
                                          value=int(b.get("value", 0)), cursor=int(b.get("cursor", 0)),
                                          timestamp=int(b.get("timestamp", 0)),
                                          asset=int(b.get("asset") or 0),
                                          selfd=_rt.zkvm_addr_digest(b["cid"]))
        async with _sem():
            ok, why = await asyncio.to_thread(_verify)
        if not ok:
            return web.json_response({"ok": False, "reason": why})
        slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
        ok2, ret, _new_slots, payouts, chain, effects = zkvm.replay_io(io, slots, with_assets=True)
        chain_ok = all(
            (k == zkvm.IO_BHASH and st.block_hashes.get(a) is not None and st.block_hashes[a] % _F.P == v) or
            (k == zkvm.IO_BEACON and st.beacons.get(a) is not None and st.beacons[a] % _F.P == v)
            for k, a, v in chain)
        # The asset half of state_match: the log's ABAL reads must match this node's ledger and every move
        # it declares must be one the contract is actually allowed to make. Staged, never committed — this
        # is a query endpoint; it reports whether the call WOULD apply, it does not apply it.
        named = [(k, a, st.zk_addrs.get(str(t)) if t else None, amt) for k, a, t, amt in effects]
        assets_ok, assets_why, _d, _s, _m = st.stage_asset_effects(b["cid"], named)
        pays = [[st.zk_addrs.get(str(to)), amt] for to, amt in payouts]
        return web.json_response({"ok": True, "reason": "ok", "ret": str(ret),
                                  "state_match": bool(ok2 and chain_ok and assets_ok),
                                  "assets_reason": assets_why or "ok",
                                  "payouts": pays,
                                  "asset_effects": [[k, a, t, amt] for k, a, t, amt in named]})
    except KeyError as e:
        return web.json_response({"error": f"missing field {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def main():
    """Wire up the query API (CORS middleware, body-size cap), start it on BIND:PORT, then run the tail
    loop forever — the HTTP server and the L1 tail share one event loop."""
    app = web.Application(middlewares=[_cors], client_max_size=MAX_BODY_BYTES)   # H-7: cap POST body size
    app.add_routes([web.get("/exec/root", h_root),
                    web.get("/exec/accounting", h_accounting),
                    web.get("/exec/state_snapshot", h_state_snapshot),
                    web.get("/exec/settlement", h_settlement),
                    web.get("/exec/shielded", h_shielded),
                    web.get("/exec/field_shielded", h_field_shielded),
                    web.get("/exec/field_leaves", h_field_leaves),
                    web.post("/exec/prove_transfer", h_prove_transfer),
                    web.post("/exec/prove_transfer2", h_prove_transfer2),
                    web.post("/exec/prove_call", h_prove_call),
                    web.post("/exec/verify_call", h_verify_call),
                    web.get("/exec/shielded_note", h_shielded_note),
                    web.get("/exec/unshields", h_unshields),
                    web.get("/exec/unshield_proof", h_unshield_proof),
                    web.get("/exec/examples", h_examples),
                    web.get("/exec/runtimes", h_runtimes),
                    web.get("/exec/contracts", h_contracts),
                    web.get("/exec/contract", h_contract),
                    web.get("/exec/view", h_view),
                    web.get("/exec/blockhash", h_blockhash),
                    web.get("/exec/outbox", h_outbox),
                    web.get("/exec/outbox_proof", h_outbox_proof),
                    web.get("/exec/inbox", h_inbox),
                    web.get("/exec/bridge", h_bridge),
                    web.get("/exec/assets", h_assets),
                    web.get("/exec/asset", h_asset),
                    web.get("/exec/allowances", h_allowances),
                    web.get("/exec/withdrawal_proof", h_withdrawal_proof),
                    web.get("/exec/dividend", h_dividend),
                    web.get("/exec/dividend_proof", h_dividend_proof),
                    web.get("/da/meta", h_da_meta),
                    web.get("/da/have", h_da_have),
                    web.get("/da/shard", h_da_shard),
                    web.get("/da/get", h_da_get),
                    web.post("/da/publish", h_da_publish),
                    web.post("/da/accept", h_da_accept),
                    web.post("/da/announce", h_da_announce)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, BIND, PORT).start()
    print(f"[execnode] query API on {BIND}:{PORT}"
          + ("" if BIND != "0.0.0.0" else "  (PUBLIC — mutating /exec POSTs are unauthenticated; bounded by size cap + in-flight limit)"),
          flush=True)
    await tail_loop()


if __name__ == "__main__":
    asyncio.run(main())
