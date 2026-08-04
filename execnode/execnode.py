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
DA = DaStore(DA_DIR)
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
# strength before posting, so an unverifiable bundle is never broadcast. It could not complete in Python;
# on the arena it is the only route to a proof small enough to settle on chain.
SETTLE_FOLD = True
# SETTLE_PROVE_TIMEOUT: seconds a single settle-prove may run before we give up on it and post a
# BARE attestation instead. Default 1200s (20 min) — comfortably above a measured unfolded prove (~1-3 min
# at protocol strength on live data) and far below the 5h07m a non-completing fold burned. Without a bound
# the settle loop simply never returns and the chain stops settling entirely.
SETTLE_PROVE_TIMEOUT = 1200      # safety bound, not a feature switch: a prove that outruns this is
                                 # abandoned and the settle goes bare rather than halting the chain.
# Largest settle tx we will try to submit INLINE. L1's /submit_transaction caps bodies at 8 MiB, so this
# sits just under it; anything bigger is published to DA and the tx carries only the commitment. An inline
# proof is strictly better when it fits (it settles the root trustlessly with no quorum), so this is a
# ceiling, not a preference.
SETTLE_INLINE_MAX = 7 * 1024 * 1024       # just under L1's 8 MiB submit cap; a protocol fact, not a knob
# Everything a settle tx carries BESIDES the proof: sender address, ML-DSA-44 signature (~2420 B) and
# public key (1312 B) in hex, txid, recipient, a handful of ints. A few KiB in total; 64 KiB is a ceiling
# with room to spare. Used to decide inline-vs-DA from the PROOF's serialized size alone, so the ~120 MiB
# tx never has to be serialized just to be measured (that cost ~160 s on the event loop, per the DA
# publish path below).
SETTLE_TX_ENVELOPE_MAX = 64 * 1024
# How long to wait for L1's verdict on a PROOF-CARRYING settle. L1 verifies the proof inline before it
# answers, and that is measured at 94.2 s for a real 118.57 MiB proof, so anything near the bare-settle
# budget guarantees a client-side timeout on a proof that is perfectly valid. Generous because the settle
# task is DETACHED (e1000cbd) — waiting here costs nothing but this task.
SETTLE_SUBMIT_TIMEOUT_PROOF = 300
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
SETTLE_PROOF_TX_MARGIN = 60
# Hard ceiling on the publish+submit hold. Comfortably covers a measured pipeline (publish ~139 s + L1's
# inline verification ~94 s) with margin, and guarantees that a hold which is never cleared — a task that
# dies between set and clear — expires by itself instead of stopping settlement permanently.
SETTLE_HOLD_MAX_S = SETTLE_SUBMIT_TIMEOUT_PROOF + 120
# True while a settle-prove worker thread is outstanding. asyncio cannot kill that thread, so this is what
# stops a timed-out prove from stacking a new one every cadence until the box dies.
_settle_proving = False
# True from the moment a proof EXISTS until its settle has been submitted — i.e. across the publish and the
# submit, which _settle_proving does NOT cover. That flag is cleared by the prove THREAD's done-callback, so
# it goes False at "BUILT" while ~230 s of publish (139 s) and inline L1 verification (94 s) still lie ahead.
# Bare settles resumed in that window and walked the justified tip forward, and the finished proof was then
# refused for aiming at a tip we had moved ourselves. Observed live 2026-08-04: two proofs built from
# pre-state 21780 while the settled tip reached 21840.
_settle_publishing = 0.0          # time.time() when a proof-carrying settle entered publish+submit, else 0
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
    DA = DaStore(DA_DIR)
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


async def _build_settlement_proof(session, ns, st, cur, root, rec_root_at_cur=None):
    """Best-effort SELF-CHECKING settle-with-proof for (ns, cur, root), or None to fall back to quorum.

    Builds a sparse validity proof over the span (L1-justified settled tip, cur] from the DA calldata
    (calls_commit.block_calls — per-block cursor, ts=0, which matches L1's da_calls_commitment), then
    posts it ONLY if it verifiably (a) extends the L1-justified settled root and (b) reproduces THIS
    node's real root. Any mismatch — a TIME-reading call, a records-moving call, an epoch-boundary
    dividend accrual, a stale pre-state — makes a self-check fail and returns None, so a wrong proof is
    never posted and the quorum path (unchanged) settles instead. Proving runs in a worker thread under
    the proving semaphore. Validated end-to-end in tests/test_settle_prover_sim.py."""
    if not SETTLE_PROVE:
        return None
    from execnode.stark import settlement_sparse as SS, calls_commit as CC, storage_tree as SST
    from execnode import exec_root as ER
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
    def _skip(reason):
        _k = (ns, "skip")
        if _settle_skip_logged.get(_k) != reason:
            _settle_skip_logged[_k] = reason
            print(f"[execnode] settle-with-proof SKIPPED ns={ns} cursor {cur} — {reason}", flush=True)
        return None

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
                     f"(history holds {sorted((_settled_history.get(ns) or {}).keys())})")
    pre_contracts = (snap.get("state") or {}).get("contracts") or {}
    pre_bridge = (snap.get("state") or {}).get("bridge")
    # 3. conformance the validator enforces: advances, within the span cap, no epoch boundary (dividend).
    if cur <= sc:
        return _skip(f"span does not advance ({sc} -> {cur})")
    if (cur - sc) > SETTLE_PROOF_MAX_SPAN:
        return _skip(f"span {cur - sc} exceeds SETTLE_PROOF_MAX_SPAN {SETTLE_PROOF_MAX_SPAN}")
    if (sc // EPOCH_LENGTH) != (cur // EPOCH_LENGTH):
        # The tightest gate by far, and the one that made a 240-block cadence produce zero proofs: a
        # dividend at the boundary moves the RECORDS half, which the proof pins unchanged.
        return _skip(f"span {sc} -> {cur} crosses a dividend epoch boundary "
                     f"(epoch {sc // EPOCH_LENGTH} -> {cur // EPOCH_LENGTH}); records must be unchanged "
                     f"across a proven span, so settle cadence must stay inside one {EPOCH_LENGTH}-block epoch")
    # 4. the span's DA calls, per block (block_calls stamps cursor=h, ts=0 — the DA-binding form).
    calls = []
    for h in range(sc + 1, cur + 1):
        blk = await _get_json(session, f"/get_block_number?number={h}")
        if not blk or not blk.get("block_hash"):
            return None
        calls += CC.block_calls(blk, ns)
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
    if rec_pre_root != rec_root:
        return _skip(f"the RECORDS half moved across the span {sc} -> {cur} "
                     f"({SST.digest_hex(rec_pre_root)[:16]}… -> {SST.digest_hex(rec_root)[:16]}…); "
                     f"prove_settlement_sparse pins ONE records root for the whole span, so proving this "
                     f"span would assert something false. Waiting for a span whose records are constant")
    rec_hex = SST.digest_hex(rec_root)
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
    global _settle_proving
    if _settle_proving:
        return _skip("a previous settle-prove is still running; settling bare until it finishes")
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
        _rec_hex = SST.digest_hex(rec_root)
        print(f"[execnode] settle-with-proof ns={ns} self-check FAILED span {sc}->{cur} — "
              f"PRE {'ok' if _pre_ok else 'MISMATCH'}: proof={pre_full[:16]}… justified={str(sr)[:16]}… | "
              f"POST {'ok' if _post_ok else 'MISMATCH'}: proof={post_full[:16]}… ours={str(root)[:16]}… | "
              f"kv_pre={str(proof.get('kv_pre'))[:16]}… kv_post={str(proof.get('kv_post'))[:16]}… "
              f"rec={_rec_hex[:16]}… calls={len(calls)} — falling back to quorum", flush=True)
        return None
    # SAY THAT THE PROOF SURVIVED. Between "[settle-prove] ... total 239.9s" and the DA publish there was
    # NO log line at all, so a prove that completed and then went nowhere was indistinguishable from one
    # that was still running — which is how a garbage-collected settle task hid for hours. Every outcome
    # after a completed prove is now named: this line, the self-check line above, the DA publish/FAILED
    # lines, or the REFUSED retry.
    print(f"[execnode] settle-with-proof BUILT ns={ns} span {sc}->{cur} — self-checks passed", flush=True)
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
            proof = None
            try:
                proof = await _build_settlement_proof(session, ns, st, cur, root, rec_root_at_cur)
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
            if proof is None and (_settle_proving or _pub_active):
                _k = (ns, "hold-for-inflight-proof")
                if _settle_skip_logged.get(_k) != _k[1]:
                    _settle_skip_logged[_k] = _k[1]
                    print(f"[execnode] settle HELD ns={ns} cursor {cur} — a settle-prove is in flight and "
                          f"a bare settle now would advance the justified tip past the span it proves, "
                          f"guaranteeing its refusal ('pre_root must extend the settled tip')", flush=True)
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
            # PROOF-CARRYING SETTLES ARE SUSPENDED — they take this node OUT OF CONSENSUS.
            #
            # A settle carrying proof_da sits in our own mempool, and every block-candidate build
            # re-validates it. Validation resolves the proof from DA and verifies it, measured at 94.2 s,
            # so the core loop goes from ~1 s to 91 s and the node stops producing. Observed live
            # 2026-08-04 after two such submits:
            #     [DOWN] Blocks #22728 · 221s old
            #     Consensus OUTSIDE majority (66% / 3 peers)
            #     Loop durations: Core: 91
            # 219 NODE UNHEALTHY episodes, blocks frozen for ~9 minutes at a stretch while peers advanced.
            #
            # THREADING CANNOT FIX THIS. /submit_transaction already runs validation via
            # asyncio.to_thread, and the verifier is pure Python: it holds the GIL for the whole 94 s and
            # starves the loop regardless. Same reason to_thread did not save the DA encode.
            #
            # AND IT CANNOT LAND ANYWAY. There is exactly one DA node (all three peers have no listener on
            # :9273), _fetch_da_proof asks only 127.0.0.1, and nothing ever pushes shards — /da/accept has
            # no caller. Every other validator resolves nothing and DEFERS, so the tx is unincludable by
            # anyone. Three separate proof-carrying settles were accepted and none reached a block.
            #
            # So the cost is a node outage and the benefit is zero. Suspended until BOTH hold:
            #   1. the verifier is NATIVE (Rust), so validation cannot starve the loop; and
            #   2. shards are distributed (push k-of-n on publish + _fetch_da_proof tries peers via the
            #      _da_sources() discovery the exec node already has), so a peer can actually verify.
            # Everything upstream is proven and unchanged: the prover still builds and self-checks a proof
            # each cadence, which is what demonstrated the pipeline in the first place.
            _SUSPEND_DA_SETTLE = True
            if proof is not None and _SUSPEND_DA_SETTLE:
                _k = (ns, "da-settle-suspended")
                if _settle_skip_logged.get(_k) != _k[1]:
                    _settle_skip_logged[_k] = _k[1]
                    print(f"[execnode] proof-carrying settle SUSPENDED ns={ns} span→{cur}: a DA-carried "
                          f"settle stalls the core loop to 91 s (94 s Python verification, GIL-bound) and "
                          f"takes this node out of consensus, and cannot be included while this is the "
                          f"only DA node. Settling bare. Re-enable when the verifier is native AND shards "
                          f"are distributed.", flush=True)
                proof = None
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
                _margin = SETTLE_PROOF_TX_MARGIN if (proof is not None or proof_da) else 2
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
                async with session.post(L1 + "/submit_transaction", json=_tx,
                                        timeout=aiohttp.ClientTimeout(total=_budget)) as r:
                    _body = await r.text()
                    try:
                        _out = json.loads(_body) if _body.strip() else None
                    except ValueError:
                        _out = None
                    if _out is None:
                        _out = {"result": False,
                                "message": f"HTTP {r.status}, unparseable body: {(_body or '')[:120]!r}"}
                    return _out

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
            # THE ATTEMPT IS OVER — release the tip. Accepted or refused, this proof is no longer racing
            # anything, so holding longer would only stall settlement for no benefit.
            globals()["_settle_publishing"] = 0.0
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


async def h_da_get(request):
    """GET /da/get?c=<commitment> — reconstruct + return the RAW bytes from locally-held shards (>=k), or
    404. Convenience for a client that trusts this node; the trustless path is /da/meta + /da/shard."""
    # OFF THE EVENT LOOP. Reconstructing a settle proof is ~118 MiB of erasure decoding, and running it in
    # the handler froze the whole exec node — HTTP dead, block application stopped — for as long as it took.
    # The decode is far cheaper now that its Lagrange basis is hoisted (ops/da.py), but "cheaper" is not
    # "instant" at 118 MiB, and an endpoint any peer can call must never be able to stall the node: one
    # /da/get is otherwise a trivial remote DoS. Threaded, so the loop keeps serving while it decodes.
    data = await asyncio.to_thread(DA.get, request.query.get("c", ""))
    if data is None:
        return web.json_response({"error": "not reconstructible here"}, status=404)
    return web.Response(body=data, content_type="application/octet-stream")


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
        data = reconstruct_from(meta, list(pairs.values()))  # verifies every shard vs the commitment
        # The shards are bound to the commitment, but k/n/stripes/length came from an UNTRUSTED peer meta and
        # steer the decode (e.g. a smaller `length` truncates to different bytes that still pass the shard
        # checks). Round-trip: re-encode the result and require it to reproduce the ON-CHAIN commitment, so a
        # lied manifest is rejected and every honest node reconstructs identical bytes (determinism).
        if _da.encode(data, k, n)["commitment"] != commitment:
            return None
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
                    web.post("/da/accept", h_da_accept)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, BIND, PORT).start()
    print(f"[execnode] query API on {BIND}:{PORT}"
          + ("" if BIND != "0.0.0.0" else "  (PUBLIC — mutating /exec POSTs are unauthenticated; bounded by size cap + in-flight limit)"),
          flush=True)
    await tail_loop()


if __name__ == "__main__":
    asyncio.run(main())
