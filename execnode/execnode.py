"""
NADO execution node (Phase 1) — the "beside the node" process.

It TAILS an L1 NADO node over plain HTTP, pulls the ordered `blob` payloads out of FINALIZED blocks,
replays them through the deterministic zkVM (execnode.state / execnode.zkvm2), and persists the resulting
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
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from execnode import block_apply as _BA
from protocol import EPOCH_LENGTH as _EPOCH_LENGTH
from aiohttp import web

from execnode.state import ExecState

L1 = os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/")
STATE_PATH = os.environ.get("NADO_EXEC_STATE", "exec_state.json")


def acquire_state_lock(state_path):
    """ONE EXEC NODE PER STATE FILE (2026-09-27). Take an exclusive, non-blocking flock on <state>.lock, or return None.
    Two exec processes over one exec_state.json both load it, both re-stamp the .gen marker and restore the settle stash,
    and both write it back — divergent state from one file. Nothing prevented that: the node's own exec supervisor
    (ops/exec_supervisor.py) runs the exec node as a child while nado-exec.service is down, and the service coming back
    must not run beside it. The lock is held for the life of the process (the kernel drops it on exit, even on kill)."""
    import fcntl
    fh = open(str(state_path) + ".lock", "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


if __name__ == "__main__":
    # BEFORE the module-level state load below: that load already writes (the .gen marker, the settle stash). Only the
    # running exec node takes it — tests import this module with their own temporary state and never contend.
    _STATE_LOCK = acquire_state_lock(STATE_PATH)
    if _STATE_LOCK is None:
        sys.exit(f"[execnode] another exec node already holds {STATE_PATH}.lock — refusing to run a second one over "
                 f"the same state (the node's exec supervisor hands over when nado-exec.service starts)")
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
# FINALITY-REVERT PROBE cadence (see tail_loop): polls between hash-agreement checks of our highest
# applied block against L1. EVERY poll: one extra local request per 5 s is nothing, and the requirement
# (operator, 2026-08-17) is that L1 and the exec layer never disagree — a once-a-minute probe was a
# minute of serving a dead chain. Together with the parent-linkage check on every applied block and the
# snapshot-hash check on every status, detection latency is one poll.
DIVERGENCE_PROBE_POLLS = 1

# ---- REWIND CHECKPOINTS -------------------------------------------------------------------------
# A finality revert is recovered by REWINDING to the newest checkpoint at or below the fork point and
# replaying the canonical tail from L1 — seconds, local, no donor — instead of a wipe-and-replay from
# genesis (minutes, needs a complete archive). Checkpoints are the same self-describing payloads the
# settle stash keeps (ns/cursor/state_root/state, restorable via ExecState._restore), written beside the
# state file under a distinct separator so the two generation wipes sweep them and _stash_load ignores
# them. A LADDER, so any fork depth has a nearby checkpoint at bounded disk:
#   fine   — every CKPT_FINE cursors, kept for the last CKPT_FINE_SPAN cursors
#   coarse — every CKPT_COARSE cursors, kept for the last CKPT_COARSE_SPAN cursors
# ~5 MB each here: (2000/500 + 100000/10000) ≈ 14 files ≈ 70 MB. Deeper than CKPT_COARSE_SPAN falls
# through to the archive / bootstrap ladder.
_CKPT_SEP = "~ckpt~"
CKPT_FINE, CKPT_FINE_SPAN = 500, 2_000
CKPT_COARSE, CKPT_COARSE_SPAN = 10_000, 100_000


def ckpt_keep(cursors, now):
    """Which checkpoint cursors to KEEP given the ladder above. Pure, so the retention is testable.

    Checkpoints are written at the TRUE cursor when it crosses a rung, so a batch apply (cold replay
    lands hundreds of blocks per poll) rarely produces a cursor that is an exact multiple. Retention
    therefore works in BUCKETS, keeping the OLDEST checkpoint per bucket — the one nearest the rung
    boundary — so that for ANY fork point there is a checkpoint at or below it within one bucket:
    within CKPT_FINE_SPAN of `now`, one per CKPT_FINE bucket; within CKPT_COARSE_SPAN, one per
    CKPT_COARSE bucket; the newest overall always; and never anything above `now` — a checkpoint from
    a rewound-away future is exactly what must not survive a rewind. (Newest-per-bucket was tried first
    and lost the coarse rung to a fine checkpoint sharing its bucket, leaving a 15k-block hole.)"""
    cs = sorted({int(c) for c in cursors if int(c) <= now})
    if not cs:
        return set()
    keep = {cs[-1]}
    fine, coarse = {}, {}
    for c in cs:                                # ascending -> setdefault keeps the OLDEST per bucket
        if now - c <= CKPT_FINE_SPAN:
            fine.setdefault(c // CKPT_FINE, c)
        if now - c <= CKPT_COARSE_SPAN:
            coarse.setdefault(c // CKPT_COARSE, c)
    keep.update(fine.values())
    keep.update(coarse.values())
    return keep


def rewind_target(checkpoints, fork_point):
    """The checkpoint cursor to rewind to: the NEWEST at or below the fork point that EVERY namespace has
    (all namespaces must land on one cursor, because the tail loop replays from a single watermark). None
    if no common checkpoint sits at or below it — the caller then falls through to the archive/bootstrap
    ladder. `checkpoints` is {ns: iterable of cursors}."""
    if not checkpoints:
        return None
    common = None
    for ns, cs in checkpoints.items():
        s = {int(c) for c in cs if int(c) <= fork_point}
        common = s if common is None else (common & s)
    return max(common) if common else None


def probe_height(block_hashes, tip: int) -> int:
    """The height to hash-check our applied state against L1, or 0 if there is nothing worth asking.

    The HIGHEST block we have applied that L1 can still be expected to answer for. Highest, because a
    sub-finality rewind leaves the chains agreeing BELOW the fork point and disagreeing above it — probing
    low is exactly the blindness that let the existing stale-exec guard pass a contaminated node. Capped at
    L1's tip because it cannot answer for heights it has not rebuilt yet.

    Pure and separately tested: the first test written for this file asserted against a COPY of the logic,
    which stayed green when the real gate was disabled, so the decision lives here where a test can call it."""
    if not block_hashes or tip <= 0:
        return 0
    h = min(max(block_hashes), tip)
    return h if h > 0 and h in block_hashes else 0


def recovery_available(l1_status, bootstrap_url: str) -> str:
    """Which recovery source, if any, can rebuild exec state after a finality revert. Returns a short
    label ("archive" / "bootstrap") or "" for none.

    A wipe-and-cold-replay is only a recovery when the L1 archive can actually feed it: earliest_block_height
    0 means bodies are contiguous from genesis (core_loop's canonical restore keeps that so). A truncated
    archive would replay the tail onto an empty state — the 2026-08-03 shape — so it does not qualify. A
    bootstrap donor (NADO_EXEC_BOOTSTRAP) qualifies regardless: it adopts a quorum-vouched checkpoint.
    Absent both, the caller keeps the current state and asks again next cycle."""
    try:
        earliest = int((l1_status or {}).get("earliest_block_height", -1))
    except (TypeError, ValueError):
        earliest = -1
    if earliest == 0:
        return "archive"
    if bootstrap_url:
        return "bootstrap"
    return ""


# Set (non-empty) while exec state is known to belong to an abandoned chain and no recovery source is
# available yet. Exposed on /exec/root so a client can tell "this node's balances are stale" from "this
# node is fine" — machine-readable state, not a log line for a human who is not there.
STRANDED = {}


def finality_reverted(block_hashes, height: int, l1_reply) -> bool:
    """True only on a PROVEN disagreement between our applied block at `height` and L1's block there.

    Every other outcome — no reply, a malformed one, a pruned body carrying no hash, a height we never
    applied — returns False. That asymmetry is the whole safety argument: this predicate drives an automatic
    wipe-and-replay, and on 2026-08-03 a guard that treated MISSING INFORMATION as evidence (a bare height
    inversion during a slow L1 restart) destroyed the live state and all 25 deployed contracts. Absence of
    information is never divergence."""
    if height not in (block_hashes or {}):
        return False
    if not isinstance(l1_reply, dict):
        return False        # a list/string/None body is a broken relay, not a statement about the chain
    body = l1_reply.get("block") or l1_reply
    l1_hash = body.get("block_hash") if isinstance(body, dict) else None
    if not l1_hash:
        return False
    try:
        return int(l1_hash, 16) != int(block_hashes[height])
    except (TypeError, ValueError):
        return False        # unparseable is not proof of anything


def linkage_broken(block_hashes, height: int, block) -> bool:
    """True iff the block about to be applied at `height` does NOT chain onto the block we applied at
    height-1. Same asymmetry as finality_reverted: only a parsed parent_hash that differs from a hash we
    hold is a break; a missing parent_hash, a height we never recorded, or garbage is 'no evidence'."""
    if not isinstance(block, dict) or height - 1 not in (block_hashes or {}):
        return False
    ph = block.get("parent_hash")
    if not ph or not isinstance(ph, str):
        return False
    try:
        return int(ph, 16) != int(block_hashes[height - 1])
    except (TypeError, ValueError):
        return False


def _ckpt_path(ns, cursor):
    return f"{STATE_PATH}{_CKPT_SEP}{ns}~{int(cursor)}.json"


def _ckpt_list():
    """{ns: sorted [cursor]} of on-disk rewind checkpoints (self-describing files only)."""
    import glob as _g
    out = {}
    pref = f"{STATE_PATH}{_CKPT_SEP}"
    for p in _g.glob(pref + "*.json"):
        tail = p[len(pref):-len(".json")]
        ns, _sep, cur = tail.rpartition("~")
        if not _sep or ns not in NAMESPACES:
            continue
        try:
            out.setdefault(ns, []).append(int(cur))
        except ValueError:
            continue
    return {ns: sorted(v) for ns, v in out.items()}


def _ckpt_maybe_persist(prev_cursor, cursor):
    """Write a rewind checkpoint for EVERY namespace when the cursor crosses a fine rung, then apply the
    ladder retention. Best-effort; a lost checkpoint costs a deeper rewind, never correctness."""
    if cursor < 0 or cursor // CKPT_FINE == prev_cursor // CKPT_FINE:
        return                                     # no rung crossed since the last persist
    # Written at the TRUE cursor (the payload must describe the state it holds); ckpt_keep buckets by rung.
    for ns, st in states.items():
        try:
            payload = json.dumps({"ns": ns, "cursor": st.cursor, "state_root": st.state_root(),
                                  "state": st._snapshot()}, sort_keys=True)
            p = _ckpt_path(ns, st.cursor)
            with open(p + ".tmp", "w") as f:
                f.write(payload)
            os.replace(p + ".tmp", p)
        except Exception as e:
            print(f"[execnode] rewind checkpoint ns={ns} cursor={st.cursor} not written: {e}", flush=True)
    try:
        for ns, cs in _ckpt_list().items():
            keep = ckpt_keep(cs, cursor)
            for cval in cs:
                if cval not in keep:
                    try:
                        os.remove(_ckpt_path(ns, cval))
                    except OSError:
                        pass
    except Exception:
        pass


async def _find_fork_point(session, block_hashes, tip):
    """Highest height at which our applied hash agrees with L1's canonical chain, or None. Binary search
    over the heights we hold, using hash_only so L1 answers below its body floor. Heights L1 cannot name
    at all are treated as unknown and the search narrows away from them; the result is only ever a height
    at which agreement was actually OBSERVED."""
    if not block_hashes:
        return None
    hs = sorted(h for h in block_hashes if 0 < h <= tip)
    if not hs:
        return None

    async def agrees(h):
        r = await _get_json(session, f"/get_block?number={h}&hash_only=1")
        body = (r or {}).get("block") or r or {}
        bh = body.get("block_hash") if isinstance(body, dict) else None
        if not bh:
            return None
        try:
            return int(bh, 16) == int(block_hashes[h])
        except (TypeError, ValueError):
            return None

    lo, hi, best = 0, len(hs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        a = await agrees(hs[mid])
        if a is True:
            best = hs[mid]
            lo = mid + 1
        elif a is False:
            hi = mid - 1
        else:
            # unknown at mid: probe upward for the nearest answerable height, else give up on this half
            k = mid + 1
            while k <= hi and (a := await agrees(hs[k])) is None:
                k += 1
            if k > hi:
                hi = mid - 1
            elif a:
                best = hs[k]
                lo = k + 1
            else:
                hi = k - 1
    return best


def _rewind_sources():
    """{ns: {cursor: path}} of EVERY on-disk state payload a rewind can restore from: the dedicated
    rewind checkpoints (~ckpt~) AND the settle stash (~stash~). The stash entries are the same
    self-describing {ns, cursor, state_root, state} shape, captured continuously for the prover — which
    makes them free extra rungs, and often FINER ones: on 2026-08-17 the first live finality revert hit
    while the checkpoint ladder was one rung old (nothing at/below the fork point 61380), but the stash
    held that exact cursor. Checkpoints win on a cursor collision (they were written for this purpose)."""
    import glob as _g
    out = {}
    for sep in (_STASH_SEP, _CKPT_SEP):          # ckpt second -> overwrites the stash on a cursor collision
        pref = f"{STATE_PATH}{sep}"
        for p in _g.glob(pref + "*.json"):
            tail = p[len(pref):-len(".json")]
            ns, _s, cur = tail.rpartition("~")
            if not _s or ns not in NAMESPACES:
                continue
            try:
                out.setdefault(ns, {})[int(cur)] = p
            except ValueError:
                continue
    return out


def _rewind_to(cursor):
    """Restore every namespace from its rewind source at `cursor` and reset the derived globals, exactly
    as _reset_states_to_genesis does minus the wipe. Stash entries ABOVE the cursor are from the abandoned
    chain and are dropped; the DA store is untouched (content-addressed). Returns True on success."""
    global _last_settled_cursor, prov_states, _prov_key, _prov_last, _prov_since_full
    sources = _rewind_sources()
    restored = {}
    for ns, st in states.items():
        p = sources.get(ns, {}).get(int(cursor)) or _ckpt_path(ns, cursor)
        try:
            snap = json.load(open(p))
            if snap.get("ns") != ns or int(snap.get("cursor", -1)) != int(cursor):
                raise ValueError("checkpoint does not describe itself")
            restored[ns] = snap["state"]
        except Exception as e:
            print(f"[execnode] rewind: checkpoint ns={ns} cursor={cursor} unusable ({e})", flush=True)
            return False
    for ns, st in states.items():
        st._restore(restored[ns])
        # TRUST NOTHING ABOVE THE PAYLOAD'S OWN CURSOR. A settle-stash payload is captured from the LIVE
        # state, and the state can advance mid-capture (the documented "records half moved on" race) — so
        # a payload claiming cursor C can carry block-hash ring entries for C+1.. from the branch being
        # abandoned. Observed live 2026-08-17: the stash at 61380 carried dead-branch hashes for
        # 61381-61382, so every rewind RESTORED the contamination the probe then re-detected — a perfect
        # 5-second rewind loop that ran for twenty minutes. The ring above the cursor is refilled from L1
        # by the very next apply either way, so dropping it costs nothing and ends the class.
        for h in [h for h in st.block_hashes if h > int(cursor)]:
            st.block_hashes.pop(h, None)
        st.save()
    _last_settled_cursor = -1
    prov_states = None
    _prov_key = None
    _prov_last = None
    _prov_since_full = 0
    # stash entries above the rewind point describe the dead chain
    for ns, hist in list(_settled_history.items()):
        for c in [c for c in hist if c > cursor]:
            hist.pop(c, None)
            try:
                os.remove(_stash_path(ns, c))
            except OSError:
                pass
        _settled_snapshots.pop(ns, None)
        if hist:
            _settled_snapshots[ns] = hist[max(hist)]
    # checkpoints above the rewind point likewise
    for ns, cs in _ckpt_list().items():
        for c in cs:
            if c > cursor:
                try:
                    os.remove(_ckpt_path(ns, c))
                except OSError:
                    pass
    STRANDED.clear()
    print(f"[execnode] REWOUND every namespace to checkpoint cursor {cursor}; replaying the canonical "
          f"tail from L1", flush=True)
    return True


async def _recover_from_revert(session, status, reason):
    """THE RECOVERY LADDER for a proven finality revert, best first — every rung lands somewhere strictly
    better than a state that mixes a dead fork with canonical history:
      0. REWIND to the newest common checkpoint at or below the fork point and replay the tail from L1
         — seconds, local, no donor, no wipe. The normal path.
      1. L1 archive contiguous from genesis -> wipe + cold replay (keeping DA).
      2. a bootstrap donor -> wipe + adopt its quorum-vouched checkpoint (keeping DA).
      3. neither -> keep the mostly-right state, record STRANDED, re-evaluate next poll.
    Nothing here is an alarm; every rung is a mechanism, and rung 3 is a retry."""
    tip = int((status or {}).get("latest_block_height", 0) or 0)
    fp = await _find_fork_point(session, state.block_hashes, tip)
    if fp is not None:
        target = rewind_target({ns: list(cs) for ns, cs in _rewind_sources().items()}, fp)
        if target is not None and _rewind_to(target):
            print(f"[execnode] recovered from finality revert ({reason}): fork point {fp}, rewound to "
                  f"checkpoint {target}", flush=True)
            return
        print(f"[execnode] finality revert ({reason}): fork point {fp} but no common checkpoint at or "
              f"below it — falling through to replay/bootstrap", flush=True)
    else:
        print(f"[execnode] finality revert ({reason}): fork point not determinable from L1 — falling through "
              f"to replay/bootstrap", flush=True)
    can_replay = recovery_available(status, BOOTSTRAP)
    if can_replay:
        _reset_states_to_genesis(reason=f"finality revert: {reason} ({can_replay})", keep_da=True)
        STRANDED.clear()
        await _maybe_bootstrap(session)
        return
    if not STRANDED:
        print(f"[execnode] exec state is STRANDED on an abandoned chain and no recovery source is available "
              f"yet (no checkpoint at/below the fork point, L1 archive incomplete: earliest "
              f"{status.get('earliest_block_height')}, no NADO_EXEC_BOOTSTRAP). Keeping the current state; "
              f"re-checking every {DIVERGENCE_PROBE_POLLS * POLL:.0f}s.", flush=True)
    STRANDED.update({"since_cursor": state.cursor, "reason": reason, "fork_point": fp})

# --- DA layer: erasure-coded availability for the shielded-transfer STARK proofs (too big for an L1 blob,
# so only the transfer STATEMENT + the proof's `commitment` ride on-chain). This node keeps a local DaStore;
# NADO_DA_URL is a peer DA node to fetch a proof from by commitment when we don't hold it locally.
from ops.da_store import DaStore, reconstruct_from
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
# PINNED ON TOP OF THE WINDOW (audit 2026-09-25, the eviction route to the exec stall). The count above is over EVERY
# object and /da/publish is open, so 24 junk publishes evicted a field transfer's proof before a lagging exec node had
# applied its block. Every proof _apply_block resolves for an on-chain op is therefore pinned (DaStore.pin) until this
# node's finalized tail passes the op's height + DA_PIN_BLOCKS (~7 days at 6.4 s: a node down for less than that still
# finds the bytes on every peer), at most DA_PIN_MAX of them (a ~4 MB transfer proof is ~3x that on disk). Local
# storage policy, not a verdict — which is why these are not protocol constants.
DA_PIN_BLOCKS = int(os.environ.get("NADO_DA_PIN_BLOCKS", str(7 * 13500)))
DA_PIN_MAX = int(os.environ.get("NADO_DA_PIN_MAX", "256"))
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
# G9 NOTE (2026-10-27): the measurements below were taken on the Goldilocks prover (prove_settlement_sparse,
# _build_settlement_proof), deleted in G9; every settle is bare until G8 wires the Stwo span settlement. The cadence
# is kept as it is because G8's span proofs are cut at the same settle points; re-measure it then, not before.
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
    # prover silently impossible. _build_settlement_proof (deleted in G9) refused any span that crosses a dividend epoch
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
# The Goldilocks settle prover's switches and size budget (SETTLE_PROVE, SETTLE_FOLD, the records-half caps) were
# deleted with it in G9; its measured history is in git and doc/settle-proof-transport.md. What stays below is the
# proof-carrying settle PIPELINE (inline-vs-DA, landing budget, holds), which the Stwo settlement (G8) reuses.
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
#
# THE NUMBER ARRIVED, AND IT IS BAD. 2026-08-07, span 8383->8400 with 29 updates:
#     09:56:45  serialised 0.8s (63.41 MiB) — POSTing
#     09:57:07  [settle-verify] KV half 10.0s ok=True
#     10:16:46  settle submit FAILED after 1201.0s (budget 1200s) — TimeoutError
# The records verification NEVER LOGGED, because its timing print only runs on completion: the client
# disconnected at the budget and the work was discarded mid-flight. L1 produced blocks at a steady 6.0 s
# THROUGHOUT (8541 at 09:57 -> 8736 at 10:16) while averaging 86% CPU, i.e. the Rust verify releases the
# GIL — so "the node looks healthy" is NOT evidence that verification is not running. It ran, for >1179 s,
# against a 1200 s budget, and lost.
#
# THIS RAISE IS DERIVED FROM THE LANDING WINDOW, NOT CHOSEN. A settle is admitted to the pool only AFTER
# verification returns, and must then be included by max_block = tip_at_build + margin. So verification is
# bounded, hard, by the margin: V < margin * 6 s. With the margin at its own ceiling (330 blocks, under
# TX_LANDING_WINDOW = 360) that is 1980 s, and 1800 leaves ~30 blocks for the tx to actually be included.
# There is no further raise available after this one — the next one has to come out of TX_LANDING_WINDOW,
# which is CONSENSUS-CRITICAL and would need the whole fleet moved together.
#
# So this buys exactly one more measurement, and the real fix is to shrink the verification. [records-bind]
# now splits it into `derive` (authenticated projection reads) and `stark` (proof verification) precisely to
# say WHICH, because they call for opposite fixes and only the `stark` half is what the K->1 fold addresses.
SETTLE_SUBMIT_TIMEOUT_PROOF = int(os.environ.get("NADO_SETTLE_SUBMIT_TIMEOUT_PROOF", "1800"))
# HOW FAR AHEAD A PROOF-CARRYING SETTLE AIMS max_block. A settle is an EXACT-LANDING tx (protocol.py: it
# "lands at exactly max_block"), and L1 spends ~94 s — about 16 blocks — verifying the proof INLINE before
# the submit even returns. So a deadline computed before the submit is already ~14 blocks in the PAST by
# the time the tx reaches the pool: it is accepted, then expires unincluded. Observed live 2026-08-04:
# "SETTLE-WITH-DA-PROOF ... → L1" logged (L1 said result=True) yet no settle tx for that cursor appears in
# any block and /get_settled never moved.
#
# This is the same anti-pattern protocol.py records under RESERVED_TX_MARGIN: tip+2/+4/+5 "forked
# betanet-12 three times on 2026-07-28" because an exact-landing tx could not propagate in time. 60 blocks
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
# blocks is ~28 min at the MEASURED 6.00 s/block (1680 s): ~600 s of slack over the verification, and
# still under TX_LANDING_WINDOW (360).
# Raise it only against a NEW measurement of the RECORDS half — the verification cost tracks the update
# count, and the update count tracks fleet size, so this is a constant with a moving target underneath it.
#
# THE NEW MEASUREMENT: >1179 s at 29 updates on 2026-08-07 (up from 1017-1073 s at 27-29), which at 6.0 s
# per block is >196 blocks and still climbing with fleet size. 280 was sized against ~1057 s and no longer
# has real headroom, so it goes to its own ceiling: TX_LANDING_WINDOW is 360 and the tx still has to be
# built, serialised and propagated, so 330 is the largest honest value. This is the LAST raise this
# constant has available; past it the verification itself has to come down.
SETTLE_PROOF_RECORDS_TX_MARGIN = int(os.environ.get("NADO_SETTLE_RECORDS_TX_MARGIN", "330"))
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
# _settle_proving covers the KV prove and is set ~60 lines AFTER _build_records_half (deleted in G9) was called, so it is
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
# Blocks of runway for an INLINE resubmission. The tx is the whole proof (~9 MiB), so peers need a push of that body
# plus a verification before any of them holds it: ~7 s warm after the verify child's fold cache (ops/proof_child),
# up to ~115 s cold on a peer's first proof. 20 blocks (~2 min at 6 s) covers the cold case and still gives ~10 tries
# inside SETTLE_RESUBMIT_MAX_S. A DA-carried retry keeps latest+2: its tx is a commitment peers already prefetched.
SETTLE_INLINE_RESUBMIT_MARGIN = 20
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
# THE SNAPSHOT AT EACH EPOCH BOUNDARY (2026-10-27), serialized in the same synchronous step that records the boundary's
# root (the tail loop, ExecState.boundary_roots), keyed per ns by cursor -> (root, payload). A quorum settle attests the
# latest boundary pair, not the live cursor, and its stash used to serialize the LIVE state after the submit's await:
# measured 2026-10-27, the stash labeled (4980, root@4980) held a state at cursor 4981. A stash must hash to its own
# (cursor, root) — a joiner verifies it against exactly that, and the gen-29 settlement prover (execnode/settle_b2.py,
# tools/settle_b2_shadow.py) starts its span from it. _stash_payload picks the matching one; bounded like the history.
_boundary_snaps = {}
_BOUNDARY_SNAPS_KEEP = 4


def _record_boundary(ns, st):
    """At an epoch-boundary cursor: the root (ExecState.boundary_roots, the exec hash pool's entry) and the serialized
    state, in one synchronous step, so the pair and the payload are of the same state. Called right after the boundary
    block applies; nothing at any other cursor."""
    if st.cursor < 0 or st.cursor % _EPOCH_LENGTH != 0:
        return
    st.boundary_roots[st.cursor] = st.state_root()
    for _old in sorted(st.boundary_roots)[:-32]:
        del st.boundary_roots[_old]
    bs = _boundary_snaps.setdefault(ns, {})
    bs[st.cursor] = (st.boundary_roots[st.cursor], json.dumps(
        {"ns": ns, "cursor": st.cursor, "state_root": st.boundary_roots[st.cursor], "state": st._snapshot()},
        sort_keys=True))
    for _old in sorted(bs)[:-_BOUNDARY_SNAPS_KEEP]:
        del bs[_old]


def _stash_payload(ns, st, cur, root):
    """The serialized snapshot AT (cur, root) for the settle stash, or None when this node holds none: the boundary
    snapshot recorded with that root, else the live state only if it is still exactly there. INVARIANT: never a payload
    whose state does not hash to `root` at `cur` (the mismatch this replaced)."""
    hit = (_boundary_snaps.get(ns) or {}).get(cur)
    if hit is not None and hit[0] == root:
        return hit[1]
    if int(st.cursor) == int(cur) and st.state_root() == root:
        return json.dumps({"ns": ns, "cursor": cur, "state_root": root, "state": st._snapshot()}, sort_keys=True)
    return None

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
state = states["default"]
# CARRIED CONTRACTS (execnode/exec_genesis.py): a fresh default layer starts from the contracts the reroll carried,
# not from nothing. INVARIANT: every place that builds a fresh layer (here and _reset_states_to_genesis) applies it,
# because a node that started empty would compute a different genesis root and settle a root nobody else holds.
from execnode import exec_genesis as _exec_genesis
if _exec_genesis.apply(state):
    print(f"[execnode] exec genesis: loaded {len(state.contracts)} carried contract(s)", flush=True)


# JOINT-GENESIS CANARY: a freshly-loaded default layer (cursor == -1) MUST hash to the genesis root — EXEC_GENESIS_ROOT
# for an empty layer, or the root of the carried contracts when the reroll carried some (exec_genesis.genesis_root()).
# If it doesn't, the exec-root scheme drifted — starting would settle a root no other node agrees on and fork L2.
# Fail LOUD instead. (A state past genesis is mid-chain and exempt.)
# The empty layer's root is the generation's canary (exec_root_b2.genesis_canary: the BLAKE2s one on gen 29) — reading
# the alghash constant here would have refused every exec node's start on generation 29.
from execnode.exec_root_b2 import genesis_canary as _genesis_canary
_GENESIS_ROOT_WANT = _exec_genesis.genesis_root(ExecState) if _exec_genesis.load() else _genesis_canary()
if state.cursor == -1 and state.state_root() != _GENESIS_ROOT_WANT:
    raise SystemExit(f"[execnode] FATAL: genesis exec state root {state.state_root()[:16]} != expected "
                     f"{_GENESIS_ROOT_WANT[:16]} — scheme drift; refusing to start (would fork L2)")

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


def _reset_states_to_genesis(reason="", keep_da=False):
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
    print(f"[execnode] RESET to genesis{(' — ' + reason) if reason else ''}: wiping exec state"
          f"{'' if keep_da else ' + DA'}", flush=True)
    for _p in _g.glob(STATE_PATH + "*"):          # default + namespaced state files AND the stale .gen mark
        try:
            os.remove(_p)
        except OSError:
            pass
    # DA blobs are CONTENT-ADDRESSED (keyed by commitment), so a blob is valid on every chain that references
    # it. A reroll makes them garbage (new genesis, nothing references them) — but a same-chain recovery, e.g.
    # a finality revert, must KEEP them: the cold replay below re-applies every DA-carried op and stalls on
    # a blob it cannot fetch, and this box is the fleet's only DA store (peers run no exec node), so a wipe
    # here is permanent loss of every proof ever posted.
    if not keep_da:
        _s.rmtree(DA_DIR, ignore_errors=True)
    _stash_clear()          # stale-generation pre-states would fail every self-check; drop them outright
    DA = DaStore(DA_DIR, retain=DA_RETAIN)
    states = {ns: ExecState(_ns_state_path(ns)) for ns in NAMESPACES}
    state = states["default"]
    _exec_genesis.apply(state)                     # the carried contracts, exactly as at boot (see above)
    if state.cursor == -1 and state.state_root() != _GENESIS_ROOT_WANT:
        raise SystemExit(f"[execnode] FATAL after reset: genesis root {state.state_root()[:16]} != "
                         f"expected {_GENESIS_ROOT_WANT[:16]} — scheme drift; refusing to run")
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


# G8: THE STWO SETTLEMENT PROVER (doc/stwo/g4-settlement-statement.md section 5). native/stwo_settle's vm_settle binary
# (nightly + the `prover` feature), where tests/_stwo_settle_build.py and the shadow run's --build put it, or
# $NADO_STWO_VM_SETTLE. NOT built here: a node without it still proves a span with no contract call (no VM proof needed)
# and settles every other span bare — settlement never waits for a prover.
STWO_VM_SETTLE = os.environ.get("NADO_STWO_VM_SETTLE") or os.path.expanduser(
    "~/.cache/nado-stwo-settle-target/release/vm_settle")


async def _stwo_settle_bundle(session, ns, st, cur, latest_height):
    """From protocol.STWO_SETTLE_HEIGHT: prove the span from L1's JUSTIFIED settled tip to our newest unattested epoch
    boundary and publish the bundle to DA -> (commitment, boundary cursor, boundary root), or None to settle bare.

    The pre-state is the stash AT the justified tip (_settled_history, the same payloads tools/settle_b2_shadow.py proves
    from), refused unless it hashes to exactly that (cursor, root). The chain inputs are the exec node's own bookkeeping
    replayed over the span (settle_b2.reference_chain) — L1 derives the same from its own state (ops/settle_chain.py; the
    shadow run's chain_eq checks the two agree). The span ends at an epoch boundary because that is the pair every settler
    attests (the cursor quantization below), and a validator settles a cursor once: the proof REPLACES our bare
    attestation of that boundary, so a boundary already attested bare is never proven. Every failure is logged and None:
    a missing prover, an unprovable span, a timeout or a DA failure costs one settle its proof, never the settle."""
    global _settle_proving
    from protocol import STWO_SETTLE_HEIGHT, SETTLE_PROOF_MAX_SPAN, DEFAULT_NS
    if ns != DEFAULT_NS or int(latest_height) < STWO_SETTLE_HEIGHT or _settle_proving:
        return None
    # RAISED BEFORE THE FIRST AWAIT: maybe_settle runs as one detached task per poll, so a flag raised only around the
    # prove let two tasks fetch the same span and prove it twice. While it is up every other task's hold sees it and
    # settles nothing (bare included). The body lowers it on every path that does not hand it to the prove thread, whose
    # done-callback lowers it; the finally covers an exception escaping before that.
    _settle_proving = True
    handed = [False]
    try:
        return await _stwo_settle_bundle_inner(session, ns, st, cur, SETTLE_PROOF_MAX_SPAN, handed)
    finally:
        if not handed[0]:
            _settle_proving = False


async def _stwo_settle_bundle_inner(session, ns, st, cur, SETTLE_PROOF_MAX_SPAN, handed):
    """_stwo_settle_bundle's body, entered with _settle_proving raised."""
    from execnode import settle_b2 as _S2

    def bare(msg=None):
        if msg:
            print(f"[execnode] stwo settle ns={ns}: {msg} — settling bare", flush=True)
        return None
    try:
        _sd = await _get_json(session, f"/get_settled?ns={ns}")
        sc, sroot = int(_sd["exec_cursor"]), str(_sd.get("state_root") or "")
    except Exception:
        return bare()
    if sc < 0 or len(sroot) != 64:
        return bare()                     # the first settlement of a namespace is by quorum (L1 refuses a proof)
    bcs = [c for c in st.boundary_roots if sc < c <= int(cur) and c - sc <= SETTLE_PROOF_MAX_SPAN]
    if not bcs:
        return bare()
    bc = max(bcs)
    br = st.boundary_roots[bc]
    if st.attested.get(bc) == br:
        return bare()                     # already attested bare: L1 takes one settle per (validator, cursor)
    raw = (_settled_history.get(ns) or {}).get(sc)
    if raw is None:
        return bare(f"no stashed pre-state at the justified tip {sc}")
    try:
        pre = ExecState.snapshot_view(json.loads(raw)["state"])
        if int(pre.cursor) != sc or pre.state_root() != sroot:
            return bare(f"the stash at {sc} is not the justified root")
        blocks = [await _get_json(session, f"/get_block?number={h}") for h in range(sc + 1, bc + 1)]
        if any(not isinstance(b, dict) or int(b.get("block_number", -1)) != h
               for h, b in zip(range(sc + 1, bc + 1), blocks)):
            return bare(f"L1 did not serve the span {sc}->{bc}")
        acc = {E: await _get_l1_accrual_inputs(session, E) for E in range(sc // _EPOCH_LENGTH, bc // _EPOCH_LENGTH)}
    except Exception as e:
        return bare(f"span {sc}->{bc} inputs unavailable ({type(e).__name__}: {e})")
    binary = STWO_VM_SETTLE if os.access(STWO_VM_SETTLE, os.X_OK) else None

    def _prove():
        # Unprovable is a BaseException (settle_b2): returned as a value here so the worker's done-callback never sees it
        try:
            chain = _S2.reference_chain(pre, blocks, lambda E: acc[E])
            return _S2.prove_span(pre, blocks, chain, binary)
        except _S2.Unprovable as u:
            return ("unprovable", str(u))

    t0 = time.time()
    fut = asyncio.ensure_future(asyncio.to_thread(_prove))
    handed[0] = True                                      # _settle_proving now drops when the THREAD ends (not when we stop
    fut.add_done_callback(_clear_settle_proving)          # waiting): a timed-out prove must not stack another one
    try:
        bundle = await asyncio.wait_for(asyncio.shield(fut), SETTLE_PROVE_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"[execnode] stwo settle ns={ns}: prove of span {sc}->{bc} exceeded {SETTLE_PROVE_TIMEOUT}s — settling bare",
              flush=True)
        return None
    except Exception as e:
        print(f"[execnode] stwo settle ns={ns}: prove of span {sc}->{bc} failed ({type(e).__name__}: {e})"
              + ("" if binary else " — no vm_settle prover on this node") + " — settling bare", flush=True)
        return None
    if isinstance(bundle, tuple):
        print(f"[execnode] stwo settle ns={ns}: span {sc}->{bc} is unprovable ({bundle[1]}) — settling bare", flush=True)
        return None
    if bundle.get("post_root") != br:
        # the prover replays the span itself; a root other than our boundary's is a bug to look at, not a settle to send
        print(f"[execnode] stwo settle ns={ns}: the proven root {str(bundle.get('post_root'))[:16]}… is not our boundary "
              f"root {br[:16]}… at {bc} — settling bare", flush=True)
        return None
    globals()["_settle_publishing"] = time.time()         # hold the tip across publish AND submit (cleared after submit)
    try:
        blob = await asyncio.to_thread(lambda: json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode())
        meta = await asyncio.to_thread(DA.put, blob, DA_K, DA_N)
        c = meta["commitment"]
        try:
            await da_announce(session, c)
        except Exception:
            pass                                          # best-effort: peers still fetch on demand
    except Exception as e:
        globals()["_settle_publishing"] = 0.0
        print(f"[execnode] stwo settle ns={ns}: DA publish failed ({type(e).__name__}: {e}) — settling bare", flush=True)
        return None
    print(f"[execnode] stwo settle ns={ns}: span {sc}->{bc} PROVEN in {time.time() - t0:.1f}s "
          f"({len(bundle['runs'])} VM run(s), {len(blob) / 1048576:.2f} MiB) → DA {c[:16]}…", flush=True)
    return c, bc, br


def settled_contradicts_attestation(settled, attested):
    """True iff L1's settled checkpoint (the /get_settled document: {ns, exec_cursor, state_root}) names a cursor this
    node attested with a DIFFERENT root — the quorum ruled against our lineage. maybe_settle's self-disqualification.
    It read `exec_root`, a key /get_settled never served, so for months it could not fire while a source-text test of
    it passed (found 2026-10-28, G8 review). INVARIANT: read the field the endpoint serves — the test drives this with
    nado.get_settled's own response shape."""
    if not isinstance(settled, dict) or "exec_cursor" not in settled:
        return False
    ours = attested.get(int(settled["exec_cursor"]))
    theirs = str(settled.get("state_root") or "")
    return ours is not None and bool(theirs) and ours != theirs


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
        # +12, not +2: settle is EXACT-landing, so its target IS its propagation deadline. 12 s of
        # headroom forked the chain whenever gossip ran a beat slow (fork seed h66830 — our block carried
        # the settle, the fleet's did not). 72 s costs one minute of settle latency and buys every
        # producer the tx before any may include it.
        target = int(latest["block_number"]) + 12
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
            # SELF-DISQUALIFICATION. If L1 has JUSTIFIED a (cursor, root) we also attested — with a
            # DIFFERENT root — then the quorum has ruled against our state. Our lineage is wrong by
            # definition (settled = canonical), and every future root we compute extends the wrong
            # lineage. Mark the state replay_gap so the gate below mutes us and auto-repair adopts the
            # canonical checkpoint. Without this, a divergent node keeps attesting its own roots forever
            # and (with enough shares) can freeze the quorum — betanet-3 ran 11k+ cursors frozen this way.
            try:
                _sd = await _get_json(session, f"/get_settled?ns={ns}")
                if isinstance(_sd, dict) and "exec_cursor" in _sd:
                    _sc = int(_sd["exec_cursor"])
                    _ours = st.attested.get(_sc)
                    _theirs = str(_sd.get("state_root") or "")
                    if settled_contradicts_attestation(_sd, st.attested):
                        st.replay_gap = True
                        st.save()
                        print(f"[execnode] settle ns={ns} SELF-DISQUALIFIED — L1 justified cursor {_sc} "
                              f"root {_theirs[:16]}… but we attested {_ours[:16]}…; our "
                              f"lineage is non-canonical. Muting attestations until repair-bootstrap "
                              f"adopts the settled checkpoint.", flush=True)
            except Exception:
                pass  # best-effort; the gate below still holds
            # COMPLETENESS GATE. window_canonical() checks the RANDOMNESS window against a MOVING
            # retention horizon — it self-heals with time even when the state underneath was built over
            # a replay gap (pruned bodies carrying deploys/calls were silently skipped). state_complete()
            # is PERMANENT provenance: genesis-clean floors, or a quorum-verified bootstrap, and never a
            # recorded replay gap. A node failing it must not vote on settlement — its root is a guess.
            if not st.state_complete():
                _now = time.time()
                _k = ("state_complete", ns)
                if (_now - _settle_skip_logged.get(_k, 0.0)) >= _SETTLE_SKIP_LOG_EVERY:
                    _settle_skip_logged[_k] = _now
                    print(f"[execnode] settle ns={ns} SKIPPED — state provenance incomplete "
                          f"(replay_gap={st.replay_gap}, bootstrapped={st.bootstrapped}, "
                          f"beacon_floor={st.beacon_floor}, blockhash_floor={st.blockhash_floor}); this "
                          f"node will not attest until auto-repair verifies a settled checkpoint from a "
                          f"peer (runs automatically) or a from-genesis replay completes.", flush=True)
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
            # OPTION R (doc/stwo-migration.md 9.3): a BLAKE2s root settles by quorum attestation only — L1 refuses a
            # Goldilocks proof for it (transaction_ops _validate_settle), and G9 deleted that prover. The proof-carrying
            # machinery below (_settle_pending, _settle_publishing, the DA publish) stays for the Stwo settlement (G8),
            # which builds its proof with execnode/settle_b2.py; until it is wired in, every settle here is bare.
            proof = None
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
                if ((_pend.get("proof_da") or _pend.get("stwo")) and not _pend.get("prop_checked")
                        and (time.time() - float(_pend.get("first_submitted") or 0)) > SETTLE_PROPAGATION_GRACE_S):
                    _pend["prop_checked"] = True
                    try:
                        from ops import peer_ops as _po2
                        _peers = [p for p in (_po2.known_peer_ips() or [])][:3]
                        _seen_by = 0
                        for _pip in _peers:
                            # aiohttp, NOT urllib: this runs on the event loop, and a blocking fetch here
                            # would stall the exec node for seconds per peer.
                            # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                            async with session.get(f"http://{_pip}:9173/transaction_pool",
                                                   timeout=aiohttp.ClientTimeout(total=4), allow_redirects=False) as _r2:
                                if _r2.status != 200:
                                    continue
                                _pp = json.loads(await _r2.text())
                            _ptx = _pp.get("transaction_pool") if isinstance(_pp, dict) else (_pp or [])
                            # G8: a Stwo settle is found by its `stwo` commitment, as a DA proof is by `proof_da`
                            _pkey = "stwo" if _pend.get("stwo") else "proof_da"
                            if any((t.get("data") or {}).get(_pkey) == _pend[_pkey]
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
                    except Exception:
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
                    # (Until 2026-09-24 this branch was DA-CARRIED ONLY, because an inline proof was not held
                    # anywhere it could be rebuilt from. It is now kept in the marker; see below.)
                    _held_for = time.time() - float(_pend.get("first_submitted") or time.time())
                    # AN INLINE PROOF RESUBMITS TOO (2026-09-24). It used to get exactly one shot: the marker kept
                    # only the DA commitment, so an inline proof had nothing to rebuild from and this branch gave
                    # up. Both proof-carrying settles of 2026-09-23 (210736, 211096) died that way, "GIVING UP
                    # after 1 attempt(s)", while their pre-state was still the justified tip. The marker now holds
                    # the proof it submitted (in memory only, ~9 MiB), so a retry re-signs the SAME bytes for a
                    # fresh landing block. Our L1 memoises the verdict by proof identity, so a retry costs a post,
                    # not a verification. THE INVARIANT IS UNCHANGED: a resubmission carries the proof or its DA
                    # commitment, never neither — construct_settle_tx with both None is a BARE settle, which would
                    # advance the justified tip past the span this proof extends.
                    _rproof = None if (_pend.get("proof_da") or _pend.get("stwo")) else _pend.get("proof")
                    if (_held_for < SETTLE_RESUBMIT_MAX_S and _att < SETTLE_RESUBMIT_MAX
                            and (_pend.get("proof_da") or _pend.get("stwo") or _rproof)
                            and _sc_now == int(_pend["pre_cursor"])):
                        try:
                            # An inline retry needs a runway: the tx IS the proof, so peers must receive ~9 MiB
                            # and verify it before any of them can include it. A DA-carried retry is ~8 KB and
                            # keeps the old latest+2.
                            _rtarget = (_h_now + SETTLE_INLINE_RESUBMIT_MARGIN) if _rproof is not None else target
                            _rtx = construct_settle_tx(keys, int(_pend["cursor"]), _pend["root"], _rtarget,
                                                       ns=ns, proof=_rproof, proof_da=_pend.get("proof_da"),
                                                       stwo=_pend.get("stwo"))
                            _rd = _rtx.get("data") or {}
                            if not (_rd.get("proof") or _rd.get("proof_da") or _rd.get("stwo")):
                                raise ValueError("a resubmission would carry no proof (a bare settle); refusing")
                            # Posted inline rather than through _submit(), which is defined further down
                            # this loop body. Same generous budget: L1 verifies a proof-carrying settle
                            # INLINE before it answers, so a short timeout would drop a good submit.
                            # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                            async with session.post(L1 + "/submit_transaction", json=_rtx,
                                                    timeout=aiohttp.ClientTimeout(
                                                        total=SETTLE_SUBMIT_TIMEOUT_PROOF), allow_redirects=False) as _rr:
                                _rb = await _rr.text()
                                try:
                                    _rout = json.loads(_rb) if _rb.strip() else None
                                except ValueError:
                                    _rout = None
                                if _rout is None:
                                    _rout = {"result": False, "message": f"HTTP {_rr.status}"}
                            if isinstance(_rout, dict) and _rout.get("result"):
                                _pend["max_block"] = int(_rtx.get("max_block") or _rtarget)
                                _pend["attempts"] = _att + 1
                                print(f"[execnode] settle-with-proof ns={ns} cursor {_pend['cursor']} missed "
                                      f"block {_h_now} (produced by someone else) — RESUBMITTED for "
                                      f"max_block {_pend['max_block']} (attempt {_att + 1}, "
                                      f"{_held_for:.0f}s/{SETTLE_RESUBMIT_MAX_S}s held); the "
                                      f"{'inline proof' if _rproof is not None else 'proof and its DA blob'} "
                                      f"are reused",
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
            _hold = (_settle_proving or _records_proving or _pub_active or _pend_active or _pend_hold)
            if proof is None and _hold:
                # HOLD ESCAPE (2026-08-20, betanet-4 h240 freeze): the hold exists to protect an
                # in-flight proof's LANDABILITY — but once the justified tip is more than
                # SETTLE_PROOF_MAX_SPAN behind our cursor, no proof over the old pre-state can land AT
                # ALL (span cap + 'pre_root must extend the settled tip'), so holding bare settles
                # protects nothing while a stuck flag freezes settlement forever. Observed: a records
                # flag wedged at ~18:50, the once-ever log throttle made every later hold SILENT, and
                # the quorum froze at 240 while boundaries 300..540 went unattested by the 10-share
                # anchor. Fourth instance of the records-half-after-every-gate pattern.
                try:
                    _jn = await _get_json(session, f"/get_settled?ns={ns}")
                    _jc = int((_jn or {}).get("exec_cursor", -1))
                except Exception:
                    _jc = -1
                from protocol import SETTLE_PROOF_MAX_SPAN as _SPMS
                if _jc >= 0 and (cur - _jc) > _SPMS:
                    print(f"[execnode] settle hold OVERRIDDEN ns={ns} — justified tip {_jc} is "
                          f"{cur - _jc} cursors behind (> span cap {_SPMS}); no in-flight proof can "
                          f"land, settling bare", flush=True)
                    _hold = False
            if proof is None and _hold:
                _k = (ns, "hold-for-inflight-proof")
                if _settle_skip_logged.get(_k) != _k[1]:
                    _settle_skip_logged[_k] = _k[1]
                    print(f"[execnode] settle HELD ns={ns} cursor {cur} — a settle-prove is in flight or a "
                          f"proof-carrying settle is waiting for its landing block, and a bare settle now "
                          f"would advance the justified tip past the span it proves, guaranteeing its "
                          f"refusal ('pre_root must extend the settled tip')", flush=True)
                continue
            # G8: A STWO-PROVEN SETTLE, from protocol.STWO_SETTLE_HEIGHT (below it _stwo_settle_bundle returns None at
            # once and this loop is unchanged). Reached only past the holds above, so nothing of ours is in flight; the
            # bundle then rides the same publish/submit/pending/resubmit pipeline a proof-carrying settle always used
            # (_settle_publishing, _settle_pending), keyed on the `stwo` field. INVARIANT: every gate below that names
            # `proof` / `proof_da` names `stwo_c` too — a hold that forgets the new field lets a bare settle walk the
            # justified tip past the span this proves (the records-half-after-every-gate pattern).
            stwo_c = None
            if proof is None:
                _sw = await _stwo_settle_bundle(session, ns, st, cur, int(latest["block_number"]))
                if _sw is not None:
                    stwo_c, _stwo_cur, _stwo_root = _sw
            # REFRESH THE DEADLINE AFTER PROVING. `target` was computed before this loop, and building a
            # proof takes MINUTES — long enough for max_block to fall into the past, which L1 rejects as
            # expired. Observed live 2026-08-03: the 97.45 MiB proof was refused for size (expected) and
            # the bare retry was then ALSO refused, because it inherited the same stale deadline; a settle
            # that should have landed was lost. Re-read the tip and re-derive the deadline so both the
            # proof-carrying tx and any bare retry are submitted against the CURRENT height.
            #
            # REFRESH UNCONDITIONALLY. Gating this on `proof is not None` missed the case that matters most:
            # when the prove TIMES OUT, _build_settlement_proof (deleted in G9) returned None, so the refresh was skipped and
            # the bare settle went out carrying a max_block from before a 20-MINUTE prove. Observed live
            # 2026-08-04: "prove exceeded SETTLE_PROVE_TIMEOUT=1200s" immediately followed by
            # "settle ns=default not accepted: 'Target block too low'". The settle we fell back to in order
            # to stay live was itself dead on arrival. Time passes whether or not a proof came back, so the
            # deadline is refreshed on every path.
            if True:
                try:
                    _fresh = await _get_json(session, "/get_latest_block")
                    target = int(_fresh["block_number"]) + 12
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
                           if (proof is not None or proof_da or stwo_c) else 12)
                target = int(_fresh2["block_number"]) + _margin
            except Exception:
                pass                                       # keep the old deadline rather than skip the settle
            # CURSOR QUANTIZATION (2026-08-20). A bare attestation only counts toward the quorum when
            # other settlers attest the IDENTICAL (cursor, root) — and free-running checkpoint cadences
            # almost never coincide: measured today, f58d attested cursor 84585 and 7174 attested 84584
            # with the SAME root, one apart, while share concentration (10/4/1 after auto-bond
            # compounding) means no pair without the anchor reaches the strict 2/3 — the quorum re-froze
            # at 68299 with every root AGREEING. Attest the latest recorded EPOCH-BOUNDARY pair instead
            # (ExecState.boundary_roots — every exec records the same k*EPOCH_LENGTH cursors by
            # construction, and canonical per-block accrual makes the roots equal), so all settlers meet
            # on identical (cursor, root) every epoch. Proof settles keep the live cursor — the proof's
            # span endpoints must match what is attested. Already-attested boundaries are skipped
            # (nothing new to say; saves a duplicate tx per SETTLE_EVERY tick).
            if proof is None and stwo_c is not None:
                cur, root = _stwo_cur, _stwo_root          # the boundary pair the bundle proves (never attested yet)
            elif proof is None:
                _bcs = [c for c in st.boundary_roots if c <= cur]
                if _bcs:
                    _bc = max(_bcs)
                    _br = st.boundary_roots[_bc]
                    if st.attested.get(_bc) == _br:
                        continue
                    cur, root = _bc, _br
            tx = construct_settle_tx(keys, cur, root, target, ns=ns, proof=proof, proof_da=proof_da, stwo=stwo_c)
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
                _carries_proof = bool((_tx.get("data") or {}).get("proof") or (_tx.get("data") or {}).get("stwo")
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
                    # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                    async with session.post(L1 + "/submit_transaction", data=_payload,
                                            headers={"Content-Type": "application/json"},
                                            timeout=aiohttp.ClientTimeout(total=_budget), allow_redirects=False) as r:
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
            if (proof is not None or stwo_c is not None) and not (isinstance(out, dict) and out.get("result")):
                _why = (out or {}).get("message") if isinstance(out, dict) else out
                # Re-derive the deadline again: the refused submit itself cost a round trip, and on a
                # 97 MiB body that is not instant.
                try:
                    _fresh = await _get_json(session, "/get_latest_block")
                    target = int(_fresh["block_number"]) + 12
                except Exception:
                    pass
                tx = construct_settle_tx(keys, cur, root, target, ns=ns)
                out = await _submit(tx)
                print(f"[execnode] settle-with-proof REFUSED ns={ns} cursor {cur} — retried bare: "
                      f"{'accepted' if isinstance(out, dict) and out.get('result') else 'also refused'}. "
                      f"L1 said: {str(_why)[:160]}", flush=True)
                proof = None
                stwo_c = None
            if isinstance(out, dict) and out.get("result"):
                ok_any = True
                # REMEMBER WHAT WE ATTESTED. The self-disqualification check above compares L1's justified
                # (cursor, root) against this memo: if the quorum later settles the SAME cursor with a
                # DIFFERENT root, we know — not guess — that our lineage lost. Bounded to the last 64.
                st.attested[cur] = root
                for _oc in sorted(st.attested)[:-64]:
                    del st.attested[_oc]
                # stash the snapshot AT this settle so /exec/state_snapshot can serve a joiner a
                # payload that is verifiable against exactly this (cursor, root) once justified — AND it is
                # the pre-state the NEXT settle-with-proof extends. The payload AT (cur, root), never the live
                # state after the await above (_stash_payload; a stash that does not hash to its own pair is
                # worse than none, so none is stashed when this node no longer holds it).
                _payload = _stash_payload(ns, st, cur, root)
                if _payload is None:
                    print(f"[execnode] settle stash SKIPPED ns={ns} cursor {cur}: no snapshot at that (cursor, root) "
                          f"here (live cursor {st.cursor})", flush=True)
                else:
                    _settled_snapshots[ns] = _payload
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
                         "-WITH-DA-PROOF" if proof_da else
                         "-WITH-STWO-PROOF" if stwo_c else "")
                _via = f" proof_da={proof_da}" if proof_da else (f" stwo={stwo_c}" if stwo_c else "")
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
            if isinstance(out, dict) and out.get("result") and (_txd.get("proof") or _txd.get("proof_da")
                                                                 or _txd.get("stwo")):
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
                # "proof": the INLINE proof itself, so a missed landing block can be retried with the same bytes
                # (see the resubmit branch). None for a DA-carried one, which retries by its commitment.
                _settle_pending[ns] = {"cursor": cur, "max_block": _mb, "root": root,
                                       "proof_da": _txd.get("proof_da"), "pre_cursor": -1,
                                       "stwo": _txd.get("stwo"),
                                       "proof": (None if (_txd.get("proof_da") or _txd.get("stwo"))
                                                 else _txd.get("proof")),
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
    # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
    async with session.get(L1 + path, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as r:
        return await r.json(content_type=None)


class L1Unavailable(RuntimeError):
    """An L1 answer that is not data: a non-200 status or a body without the field the caller needs."""


async def _get_l1_accrual_inputs(session, epoch):
    """(inflow, weights) of dividend epoch `epoch` from L1, or raise L1Unavailable — NEVER a default.

    THE ACCRUAL INPUTS ARE CONSENSUS (audit 2026-09-24 #25, confirmed 2026-10-18): _get_json decodes any body whatever
    the status, so a 429 or an error page on /get_dividend_inflow became inflow 0 and the exec node accrued that
    epoch with nothing — its state left every other exec node's, a silent exec-root fork caused by a rate limit (the
    weights call checked for an error, the inflow call checked nothing). INVARIANT: both accrual paths read through
    here; a refusal holds the cursor (_accrue_owed) or marks the span not derivable (records), never guesses."""
    out = []
    for path, field in ((f"/get_dividend_inflow?epoch={epoch}", "inflow"), (f"/get_open_weights?epoch={epoch}", "weights")):
        async with session.get(L1 + path, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as r:
            if r.status != 200:
                raise L1Unavailable(f"{path}: HTTP {r.status}")
            body = await r.json(content_type=None)
        if not isinstance(body, dict) or body.get("error") or field not in body:
            raise L1Unavailable(f"{path}: {(body or {}).get('error') if isinstance(body, dict) else 'not a JSON object'}")
        out.append(body[field])
    inflow, weights = out
    if isinstance(inflow, bool) or not isinstance(inflow, int) or inflow < 0 or not isinstance(weights, dict):
        raise L1Unavailable(f"epoch {epoch}: malformed accrual inputs")
    return inflow, weights


# PROVISIONAL (fast, pre-finality) view: clones of the finalized states with the UNFINALIZED L1 tail
# speculatively applied. Rebuilt every poll from the finalized checkpoint, so a reorg self-heals on the next
# rebuild and no persistent/finalized state is ever touched. Readers opt in with ?provisional=1. None until
# the first refresh (readers then fall back to the finalized state).
prov_states = None
PROV_MAX_TAIL = 64          # cap the speculative tail depth (bounds work if this node is far behind the tip)

# Blob ops whose proof rides the DA layer rather than L1: op -> the payload field the fetched bytes are
# injected into before apply_blob sees them. A Stwo spend's bundle is past the 64 KiB blob cap, so the blob carries a
# commitment and the bytes travel k-of-n.
# private_call LEFT THIS TABLE WITH ITS POOL (G9 slice 5): apply_blob refuses it at every height without reading the
# proof, and from block 1 the pre-resolve below already never fetched it (the old _da_op_refused_at), so it never
# stalled a block on generation 29. INVARIANT: an op apply_blob refuses unread is never in this table — a fetch for it
# would let one MIN_TX_FEE blob naming a proof_da nobody holds stall every exec node (review 2026-09-25).
#
# ONE TABLE, not two branches, because the all-or-nothing stall in _apply_block is what keeps every node
# applying the identical bundle: a per-op difference there is a fork. Adding an op here is all it takes to
# give it those semantics — INCLUDING the bounded wait (_da_deadline_passed): an op added here can never stall
# the tail past the exec DA deadline, so never give one its own resolver that waits unboundedly.
_DA_BLOB_OPS = {"field_transfer": "bundle_json"}


# LOCAL GRACE before the deadline refusal (liveness only, never a verdict input): a node that reaches block h long
# after the deadline — catching up after a restart, its peer list not loaded yet — must not refuse an op whose proof it
# simply has not had a chance to fetch, when the live fleet applied it. It retries for DA_SKIP_GRACE_S from its FIRST
# miss on that commitment before refusing. On the attack (nobody holds the proof) every node still ends up refusing;
# the grace only moves a node's decision toward "applied", the answer the live fleet reached.
DA_SKIP_GRACE_S = float(os.environ.get("NADO_DA_SKIP_GRACE", "60"))
_DA_MISS_SINCE = {}          # commitment -> time.monotonic() of this node's first failed fetch


def _da_deadline_passed(h, finalized):
    """True when a DA-carried op in block h whose proof this node cannot resolve is REFUSED instead of stalling the
    block: for h >= 1, once L1 finality has reached h + protocol.EXEC_DA_WAIT_BLOCKS (audit 2026-09-25, HIGH "exec
    stall" — see the protocol comment for what is and is not a pure function here).

    A function of (h, finalized) only — block heights, never a wall clock — so every exec node stops waiting at the
    same point of the L1 chain. `finalized` is None on the PROVISIONAL tail: a speculative view never refuses (it is
    rebuilt from the finalized state every poll and must not run ahead of the finalized verdict).
    Read from protocol at call time, so a test can move the wait."""
    import protocol as _p
    # `< 1`: gen 27's EXEC_DA_DEADLINE_HEIGHT, 1 from gen 28 (deleted). The exec node applies genesis (h = 0) from
    # cursor -1, which was below that gate, and keeps the stall it always had there.
    if finalized is None or int(h) < 1:
        return False
    return int(finalized) >= int(h) + int(_p.EXEC_DA_WAIT_BLOCKS)


def _da_grace_over(commitment):
    """Record a failed fetch of `commitment`; True once this node has retried it for DA_SKIP_GRACE_S."""
    if len(_DA_MISS_SINCE) > 4096:            # a flood of distinct unheld commitments must not grow this forever
        _DA_MISS_SINCE.clear()
    first = _DA_MISS_SINCE.setdefault(str(commitment), time.monotonic())
    return time.monotonic() - first >= DA_SKIP_GRACE_S


def _block_carries_stwo_spend(block, resolved):
    """True when any field_transfer in `block` carries a bundle apply_field_transfer would send to the Stwo verifier.
    DECIDED ON THE PARSED BUNDLE (state.field_transfer_bundle + state.carries_stwo_spend), with the DA bytes injected
    exactly as the dispatch loop below injects them — never on raw text: a JSON escape (`stwo\\u005fjs`) hid a spend from
    the old substring test, and a node without the library skipped what the others applied (review 2026-10-11).
    Over-matching costs only a stall on a node without the library; under-matching forks."""
    from execnode.state import field_transfer_bundle, carries_stwo_spend
    for tx in block.get("block_transactions", []):
        d = tx.get("data")
        if tx.get("recipient") != "blob" or not isinstance(d, dict) or d.get("op") != "field_transfer":
            continue
        if tx.get("txid") in resolved:                 # the dispatch loop's injection, byte for byte
            _field, _bytes = resolved[tx["txid"]]
            d = {**d, _field: _bytes}
        bundle, _err = field_transfer_bundle(d)
        if bundle is not None and carries_stwo_spend(bundle):
            return True
    return False


async def _apply_block(session, states_map, default_state, block, verbose=True, finalized=None):
    """Apply ONE L1 block's exec-relevant txs — blobs to their namespace in states_map, bridge/shield to
    default_state — then advance every state's cursor to this height. Returns False (applying NOTHING) if a
    DA-carried proof is unavailable via DA, so the block STALLS in L1 order — but only until the exec DA deadline
    (_da_deadline_passed(h, finalized)): past it the unresolvable op is REFUSED and the rest of the block applies,
    so no blob can freeze the exec layer. Shared by the finalized tail AND the provisional clone, so both apply
    identically; only the finalized tail passes `finalized` (the L1 finalized height it is working against).

    No proof rules are set around the block any more: stark.rules_at chose the Goldilocks STARK verification rules for
    the block's height, and nothing generation 29 runs reads them (the field VM, the field and wide pools and the
    Goldilocks settle verifier are gone; G9 slice 4 deleted execnode/stark). A Stwo proof's config is chosen by its
    landing height inside its own verifier (stwo_js_native.config_id_at)."""
    return await _apply_block_inner(session, states_map, default_state, block, verbose=verbose,
                                    finalized=finalized)


async def _apply_block_inner(session, states_map, default_state, block, verbose=True, finalized=None):
    h = block["block_number"]
    # The context each state had BEFORE this block, so a DA stall below can put it back exactly (EXEC-2, review
    # 2026-09-25): under EXEC_CTX_CURRENT the cursor is advanced to h up front, and returning False with it at h made
    # the tail loop resume at h+1 — every transaction in the stalled block silently lost, on the nodes that stalled.
    _prev_ctx = {id(_st): (_st.cursor, getattr(_st, "block_ts", 0)) for _st in states_map.values()}
    _BA.begin(states_map, h)
    # DA PRE-RESOLVE (all-or-nothing): resolve every field_transfer proof BEFORE mutating, so one missing
    # proof stalls the whole block rather than half-applying it (every node fetches the same bundle -> no divergence).
    resolved = {}
    refused = set()          # block positions of DA ops refused at the deadline: never dispatched below
    for _pos, tx in enumerate(block.get("block_transactions", [])):
        d = tx.get("data")
        # Which ops ride DA, and the field each one's bytes are injected back into — see _DA_BLOB_OPS.
        inject = _DA_BLOB_OPS.get(d.get("op")) if isinstance(d, dict) else None
        # AN OP apply_blob REFUSES UNREAD IS NEVER FETCHED (review 2026-09-25, reproduced): this pre-resolve runs FIRST,
        # and fetching private_call's proof stalled on an unavailable proof_da — one MIN_TX_FEE blob froze the exec cursor
        # on every node. Such an op is simply not in _DA_BLOB_OPS (private_call left it in G9 slice 5).
        if (tx.get("recipient") == "blob" and isinstance(d, dict)
                and inject and d.get("proof_da") and inject not in d):
            # A MALFORMED proof_da (path chars -> DaStore._dir raises) or non-UTF-8 DA bytes are NOT a
            # temporarily-unavailable proof — they are a permanently-bad tx, so SKIP it (apply_blob then
            # no-ops the field_transfer) rather than stall or crash the whole block forever. `bb is None`
            # (genuinely unavailable) still stalls in L1 order, unchanged. L1 admission now rejects such a
            # proof_da anyway (transaction_ops); this is defence in depth for any block already in history.
            try:
                bb = await da_fetch(session, d["proof_da"])
                if bb is None:
                    # BOUNDED WAIT (audit 2026-09-25, HIGH "exec stall", reproduced): the stall below used to be the
                    # only outcome, forever — one MIN_TX_FEE blob naming a proof_da nobody holds froze every exec node.
                    # Past the deadline (a function of h and the L1 finalized height only) the op is REFUSED: never
                    # dispatched, so nothing moves and nothing is credited or refunded (its L1 fee was burned on L1),
                    # and the rest of the block applies. Keep BOTH halves: dropping the stall half-applies blocks
                    # whose proof is merely slow, dropping the deadline brings the freeze back.
                    if _da_deadline_passed(h, finalized) and _da_grace_over(d["proof_da"]):
                        _DA_MISS_SINCE.pop(str(d["proof_da"]), None)
                        refused.add(_pos)
                        print(f"[execnode] block {h}: REFUSED {d['op']} {str(tx.get('txid') or '')[:12]}… — its proof "
                              f"{str(d['proof_da'])[:16]}… is still unavailable via DA at finalized {finalized} "
                              f"(exec DA deadline); the rest of the block applies", flush=True)
                        continue
                    _da_grace_over(d["proof_da"])              # start (or keep) this node's local grace clock
                    if verbose:
                        print(f"[execnode] block {h}: a {d['op']} proof is UNAVAILABLE via DA — stalling at {h}", flush=True)
                    for _st in states_map.values():           # EXEC-2: nothing of block h applied, so h is NOT done
                        _st.cursor, _st.block_ts = _prev_ctx[id(_st)]
                    return False
                _DA_MISS_SINCE.pop(str(d["proof_da"]), None)
                # PIN what an on-chain op needed (the eviction route): a node that applies this block later must
                # still find these bytes on its peers, whatever /da/publish floods the rolling window meanwhile.
                try:
                    DA.pin(d["proof_da"], int(h) + DA_PIN_BLOCKS, cap=DA_PIN_MAX)
                except Exception:
                    pass                                       # availability bookkeeping never fails a block
                resolved[tx.get("txid")] = (inject, bb.decode())
            except Exception as e:
                if verbose:
                    print(f"[execnode] block {h}: skipping {d.get('op')} with bad DA proof ({type(e).__name__})", flush=True)
    # A STWO SPEND NEEDS THE NATIVE VERIFIER ON THIS MACHINE, CHECKED BEFORE ANYTHING MUTATES (STWO_POOL_HEIGHT).
    # INVARIANT: a node that cannot load native/stwo_js stalls the whole block, exactly like an unavailable DA proof,
    # because apply_blob turns any exception into a "skip" — a node missing the library would otherwise skip a spend every
    # other node applies and fork its exec state silently. The crate is optional until the gate is set, so this is the
    # one place its absence must stop the node rather than be survived.
    # STWO_POOL_HEIGHT (gen 28's gate, 1 from gen 29, inlined in G9): `h >= 1` kept so block 0 is judged as before.
    if h >= 1 and _block_carries_stwo_spend(block, resolved):
        from execnode import stwo_js_native as _sjn
        from execnode.native_guard import NativeMissing as _NM
        try:
            _sjn.ensure_loaded()
        except _NM as e:
            print(f"[execnode] block {h}: a Stwo spend needs native/stwo_js and this node cannot load it ({e}) — "
                  f"STALLING at {h} (build the crate: cargo build --release in native/stwo_js)", flush=True)
            for _st in states_map.values():               # nothing of block h applied, so h is NOT done
                _st.cursor, _st.block_ts = _prev_ctx[id(_st)]
            return False
    _BA.dispatch(states_map, default_state, block, resolved, refused, verbose)
    _BA.close(states_map, h, block.get("block_hash"))
    if finalized is not None:
        # the finalized tail owns pin expiry: the provisional one must not release what finality still needs
        try:
            DA.expire_pins(h)
        except Exception:
            pass
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
        anchor = await _get_json(session, f"/get_block?number={_prov_last[0]}")
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
        block = await _get_json(session, f"/get_block?number={h}")
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
            b = await _get_json(session, f"/get_block?number={fh}")
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
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"{BOOTSTRAP}/exec/state_snapshot?ns={ns}",
                                       timeout=aiohttp.ClientTimeout(total=30), allow_redirects=False) as r:
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
                    # PROVENANCE: this state is now quorum-verified — whatever gaps or flags the DONOR's
                    # payload carried are superseded by the L1 attestation of this exact (cursor, root).
                    st.bootstrapped = True
                    st.replay_gap = False
                    st.attested = {}
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


_repair_last = 0.0                     # last _repair_bootstrap attempt (monotonic-ish wall clock)
_REPAIR_EVERY = 600.0                  # seconds between repair attempts while a ns stays incomplete


async def _repair_bootstrap(session):
    """AUTO-REPAIR (existing-state side): a namespace whose state is PROVENANCE-INCOMPLETE
    (state_complete() False — replay gap recorded, or non-genesis floors and never bootstrapped) is
    muted from settling by maybe_settle, and a muted node never heals by itself: its state is wrong,
    not late. This adopts a donor's settled checkpoint OVER the existing state, with exactly
    _maybe_bootstrap's trust model — the payload is accepted only if the state_root RECOMPUTED from
    it matches the L1-QUORUM-settled (cursor, root); the bonded quorum vouches, never the donor.

    Donors are the explicit NADO_EXEC_BOOTSTRAP url (if set) plus every L1 peer's exec port — no
    configuration needed on the broken node. NOTE the two-phase healing this implies fleet-wide:
    while the OLD settled checkpoint predates every donor's stash window, no donor can serve it and
    repair keeps failing quietly. That is correct — the muted divergent attesters age out of the
    settle-activity window (SETTLE_ACTIVITY_CURSORS), the remaining complete node(s) justify a FRESH
    cursor, and THAT checkpoint is servable. Called inline from the tail (single-task, so it can
    never race _apply_block), throttled to every _REPAIR_EVERY seconds."""
    global _last_settled_cursor, prov_states, _prov_key, _prov_last, _prov_since_full
    import threading as _threading
    need = [ns for ns, st in states.items() if st.cursor >= 0 and not st.state_complete()]
    if not need:
        return
    donors = ([BOOTSTRAP] if BOOTSTRAP else [])
    try:
        pr = await _get_json(session, "/peers")
        for ip in (pr.get("peers") or []) if isinstance(pr, dict) else []:
            host = f"[{ip}]" if (":" in ip and not ip.startswith("[")) else ip
            donors.append(f"http://{host}:{PORT}")
    except Exception:
        pass
    for ns in need:
        st = states[ns]
        settled = await _get_json(session, f"/get_settled?ns={ns}")
        if not (isinstance(settled, dict) and settled.get("state_root")):
            continue                       # nothing justified for this ns — nothing to verify against
        for donor in donors:
            try:
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"{donor}/exec/state_snapshot?ns={ns}",
                                       timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as r:
                    snap = await r.json(content_type=None)
                if not isinstance(snap, dict) or "state" not in snap:
                    continue
                cand = ExecState.__new__(ExecState)    # verify on a scratch instance, never on `st`
                cand.path = st.path + "#repair-verify"
                cand._mutate_lock = _threading.RLock()
                cand._restore(snap["state"])
                root = cand.state_root()
                if not (settled.get("state_root") == root
                        and int(settled.get("exec_cursor", -2)) == int(snap.get("cursor", -3))):
                    continue                           # stale or divergent donor — try the next one
                st._restore(snap["state"])
                # same hygiene as _rewind_to: the donor serialized this from a LIVE state, so the
                # block-hash ring can carry entries above the payload's own cursor — drop them.
                for h in [h for h in st.block_hashes if h > int(st.cursor)]:
                    st.block_hashes.pop(h, None)
                st.bootstrapped = True
                st.replay_gap = False
                st.attested = {}
                st.save()
                # the adopted payload IS this ns's settled checkpoint — seed the stash with it, and
                # drop everything derived from the abandoned lineage.
                _settled_snapshots[ns] = json.dumps({"ns": ns, "cursor": st.cursor, "state_root": root,
                                                     "state": st._snapshot()}, sort_keys=True)
                _settled_history[ns] = {st.cursor: _settled_snapshots[ns]}
                _stash_persist(ns, st.cursor, _settled_snapshots[ns])
                _last_settled_cursor = -1
                prov_states = None
                _prov_key = None
                _prov_last = None
                _prov_since_full = 0
                print(f"[execnode] REPAIR-BOOTSTRAPPED ns={ns} from {donor} at settled cursor "
                      f"{st.cursor} root {root[:16]}… (verified against L1 quorum) — provenance "
                      f"restored, settle attestations re-enabled", flush=True)
                break
            except Exception:
                continue                               # unreachable/slow donor — try the next one


# CANONICAL PER-BLOCK DIVIDEND ACCRUAL — UNGATED since the betanet-4 reroll (gen 22). The betanet-3
# height gate (82000) and the legacy batch-boundary epilogue accrual are DELETED: accrual runs before
# every block applies, so the dividend watermark is a pure function of the block stream from cursor 0.

# on-chain settle attestations observed during replay: ns -> cursor -> root -> set(sender prefixes).
# Exec nodes replay every finalized block, so two attesters posting DIFFERENT roots at the SAME
# cursor is directly visible to everyone — yet nothing ever looked. The frozen quorum ran 11k+
# cursors with 0/8 multi-attester agreement and the only symptom was /get_settled quietly not
# moving. This memo turns that into a CRITICAL log line the moment it happens.
_settle_observed = {}
_settle_conflict_logged = set()


async def _accrue_owed(session, st, epoch_incl):
    """Accrue presence-dividend epochs on `st` up to epoch_incl (inclusive). Returns False on any
    fetch/pruning problem — the caller must then HOLD the cursor (never apply a block whose owed
    accrual is missing: the order is the consensus rule)."""
    try:
        while st.last_div_epoch < epoch_incl:
            E = st.last_div_epoch + 1
            try:
                inflow, weights = await _get_l1_accrual_inputs(session, E)
            except L1Unavailable as e:
                print(f"[execnode] canonical accrual STALLED at epoch {E}: {e} — cursor holds", flush=True)
                return False
            dist = st.accrue_dividend_epoch(inflow, weights, epoch=E)
            st.last_div_epoch = E
            if dist:
                print(f"[execnode] dividend epoch {E}: +{dist} raw (canonical)", flush=True)
    except Exception as e:
        print(f"[execnode] canonical accrual error at epoch {st.last_div_epoch + 1}: "
              f"{type(e).__name__}: {e} — cursor holds", flush=True)
        return False
    return True


def _observe_settles(block, our_attested):
    """Record every settle attestation in `block` and CRITICAL-log the first time two attesters
    post different roots for the same (ns, cursor). Pure bookkeeping — never raises."""
    try:
        for t in block.get("block_transactions", []):
            if t.get("recipient") != "settle" or not isinstance(t.get("data"), dict):
                continue
            d = t["data"]
            try:
                sc = int(d.get("exec_cursor"))
            except (TypeError, ValueError):
                continue
            ns = str(d.get("ns", "") or "default")
            root = str(d.get("state_root", ""))
            roots = _settle_observed.setdefault(ns, {}).setdefault(sc, {})
            roots.setdefault(root, set()).add(str(t.get("sender", "")))   # FULL sender: anchor matching needs it
            if len(roots) > 1 and (ns, sc) not in _settle_conflict_logged:
                _settle_conflict_logged.add((ns, sc))
                ours = our_attested.get(sc)
                print(f"[execnode] CRITICAL: SETTLE ROOT CONFLICT ns={ns} cursor {sc} — "
                      + "; ".join(f"{r[:12]}… by {sorted(x[:10] for x in s)}" for r, s in roots.items())
                      + (f"; our attested root {ours[:12]}…" if ours else "")
                      + " — the settle quorum CANNOT justify this cursor; divergent exec state in the fleet",
                      flush=True)
            # bound the memo
            for old in [c for c in _settle_observed[ns] if c < sc - 2000]:
                del _settle_observed[ns][old]
    except Exception:
        pass


# FROZEN-QUORUM AUTO-RECOVERY (anchor-verified adoption). The settle quorum can DEADLOCK: N attesters,
# every one on a different lineage, no subset with the same root above 2/3 of active shares — betanet-3
# ran 12k+ cursors frozen this way, and no amount of waiting can end it (each attester keeps re-attesting
# its own lineage forever). Trust-minimized convergence is impossible once the last justified checkpoint
# ages out of every stash (proven irreproducible here: three replay attempts, including one using the
# journal-recorded accrual boundaries, all missed — /get_open_weights recomputes old epochs from TODAY's
# pool state). So the deadlock breaker anoints the ANCHOR — the chain operator's settle address, the same
# party whose pushed code every fleet node already auto-runs, so this encodes NO trust the fleet does not
# already extend. A node that sees the quorum frozen adopts the anchor's snapshot, verified against the
# anchor's OWN ML-DSA-SIGNED settle attestation as replayed from a FINALIZED L1 block (inclusion = the
# signature was verified by L1 consensus; _observe_settles carries the evidence). The anchor node itself
# never adopts. After every divergent attester converges onto the anchor lineage, the next settles agree,
# the quorum justifies, and the ordinary machinery (self-disqualify + repair-bootstrap against JUSTIFIED
# checkpoints) guards everything thereafter.
SETTLE_ANCHOR = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f"   # format 2 of ebd27698… (gen 28)
ANCHOR_STALL_CURSORS = 2880          # settled tip this many cursors behind ours = the quorum is frozen
ANCHOR_ADOPT_EVERY = 1800.0          # seconds between adoption attempts
_anchor_last = 0.0
_anchor_is_self = None               # tri-state cache: None = not yet checked


def _anchor_self():
    """True iff THIS node settles as the anchor (it must never adopt — it IS the lineage)."""
    global _anchor_is_self
    if _anchor_is_self is None:
        try:
            from ops.key_ops import load_keys
            _anchor_is_self = (load_keys().get("address") == SETTLE_ANCHOR)
        except Exception:
            _anchor_is_self = False
    return _anchor_is_self


async def _anchor_adopt(session, finalized):
    """One adoption attempt per frozen namespace: find a peer serving a snapshot whose RECOMPUTED root
    matches an (cursor, root) the ANCHOR attested in a finalized block, and adopt it. Guards:
      * only when /get_settled is ANCHOR_STALL_CURSORS+ behind our cursor (a live quorum never triggers)
      * snapshot cursor <= our finalized view (an adopted cursor above it would trip the reroll-stranded
        detector and reset the state to genesis — measured code path, not a hypothetical)
      * one adoption per freeze episode (anchor_adopted_at rate-limit)
      * the anchor node itself never adopts."""
    global _last_settled_cursor, prov_states, _prov_key, _prov_last, _prov_since_full
    import threading as _threading
    if _anchor_self():
        return
    for ns, st in states.items():
        if st.cursor < 0:
            continue
        settled = await _get_json(session, f"/get_settled?ns={ns}")
        try:
            settled_cur = int(settled.get("exec_cursor"))
        except (AttributeError, TypeError, ValueError):
            continue
        if st.cursor - settled_cur < ANCHOR_STALL_CURSORS:
            continue                                   # quorum is alive (or freeze too young) — never adopt
        if st.anchor_adopted_at >= 0 and st.cursor - st.anchor_adopted_at < ANCHOR_STALL_CURSORS:
            continue                                   # already adopted this episode; give settling time
        anchored = {(c, r) for c, roots in _settle_observed.get(ns, {}).items()
                    for r, senders in roots.items() if SETTLE_ANCHOR in senders}
        if not anchored:
            continue                                   # no anchor attestation replayed yet — wait
        donors = ([BOOTSTRAP] if BOOTSTRAP else [])
        try:
            pr = await _get_json(session, "/peers")
            for ip in (pr.get("peers") or []) if isinstance(pr, dict) else []:
                host = f"[{ip}]" if (":" in ip and not ip.startswith("[")) else ip
                donors.append(f"http://{host}:{PORT}")
        except Exception:
            pass
        # ask donors for the exact cursors we saw the anchor attest (newest first) — the donor's LATEST
        # stash is typically one settle ahead of what we've finalized/observed (settle cadence ≈ finality
        # lag), so fetching by cursor is what makes the on-chain evidence and the payload line up.
        # (Every checkpoint is canonical-era since the gen-22 reroll — accrual is per-block from
        # cursor 0, so any finalized checkpoint replays deterministically and is adoptable.)
        wanted = sorted((c for c, _ in anchored
                         if c <= finalized), reverse=True)[:6]
        adopted = False
        for donor, want in ((d, c) for c in wanted for d in donors):
            try:
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"{donor}/exec/state_snapshot?ns={ns}&cursor={want}",
                                       timeout=aiohttp.ClientTimeout(total=30), allow_redirects=False) as r:
                    snap = await r.json(content_type=None)
                if not isinstance(snap, dict) or "state" not in snap:
                    continue
                snap_cur = int(snap.get("cursor", -1))
                if snap_cur > finalized:
                    continue                           # stranded-detector guard: never outrun our finality
                cand = ExecState.__new__(ExecState)    # verify on a scratch instance, never on `st`
                cand.path = st.path + "#anchor-verify"
                cand._mutate_lock = _threading.RLock()
                cand._restore(snap["state"])
                root = cand.state_root()
                if (snap_cur, root) not in anchored:
                    continue                           # not the anchor lineage (or unattested) — next donor
                st._restore(snap["state"])
                for h in [h for h in st.block_hashes if h > int(st.cursor)]:
                    st.block_hashes.pop(h, None)       # same live-serialization hygiene as _rewind_to
                st.bootstrapped = True
                st.replay_gap = False
                st.attested = {}
                st.anchor_adopted_at = st.cursor
                st.save()
                _settled_snapshots[ns] = json.dumps({"ns": ns, "cursor": st.cursor, "state_root": root,
                                                     "state": st._snapshot()}, sort_keys=True)
                _settled_history[ns] = {st.cursor: _settled_snapshots[ns]}
                _stash_persist(ns, st.cursor, _settled_snapshots[ns])
                _last_settled_cursor = -1
                prov_states = None
                _prov_key = None
                _prov_last = None
                _prov_since_full = 0
                print(f"[execnode] ANCHOR ADOPTION ns={ns}: quorum frozen at {settled_cur} for "
                      f"{st.cursor - settled_cur}+ cursors — adopted the anchor lineage from {donor} at "
                      f"cursor {snap_cur} root {root[:16]}… (verified against the anchor's signed settle "
                      f"attestation in a finalized L1 block). Re-attesting from this lineage.", flush=True)
                adopted = True
                break
            except Exception:
                continue
        if adopted:
            continue


# EXEC ROOT POOL — the L1's hash-pool pattern, applied to the layer that never had it. The L1 never
# trusts its own block hash in isolation: it continuously compares against every peer's advertised
# hashes and treats "outside majority" as an alarm state. The exec layer shipped WITHOUT any of that —
# each node computed its root in a vacuum and submitted settle attestations blind, which is how three
# attesters ran divergent for 12k+ cursors with no node ever noticing. Settle cursors are batch-timing-
# staggered and never comparable across nodes; EPOCH-BOUNDARY cursors are hit by every node identically,
# so those are the pool's comparison points (ExecState.boundary_roots). This probe polls every peer's
# /exec/roots, compares at the newest shared boundary, and CRITICAL-logs the moment this node's root is
# out of majority — detection within ~one epoch (~6 min) instead of ~never.
ROOT_POOL_EVERY = 300.0
_root_pool_last = 0.0
_root_pool_logged = {}


async def _root_pool_probe(session):
    """Compare our epoch-boundary roots against every reachable peer's. Never raises; logs only."""
    try:
        pr = await _get_json(session, "/peers")
        peers = (pr.get("peers") or []) if isinstance(pr, dict) else []
    except Exception:
        return
    for ns, st in states.items():
        if not st.boundary_roots:
            continue
        votes = {}                                   # boundary cursor -> root -> count (incl. ourselves)
        for c, r in st.boundary_roots.items():
            votes.setdefault(c, {}).setdefault(r, []).append("self")
        reachable = 0
        for ip in peers:
            host = f"[{ip}]" if (":" in ip and not ip.startswith("[")) else ip
            try:
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"http://{host}:{PORT}/exec/roots?ns={ns}",
                                       timeout=aiohttp.ClientTimeout(total=8), allow_redirects=False) as r:
                    pj = await r.json(content_type=None)
                if not isinstance(pj, dict) or not isinstance(pj.get("boundary_roots"), dict):
                    continue
                reachable += 1
                for c, root in pj["boundary_roots"].items():
                    votes.setdefault(int(c), {}).setdefault(str(root), []).append(ip)
            except Exception:
                continue
        if not reachable:
            return                                   # nobody to compare against — no evidence either way
        shared = [c for c, roots in votes.items()
                  if c in st.boundary_roots and sum(len(v) for v in roots.values()) >= 2]
        if not shared:
            continue
        c = max(shared)                              # newest boundary with at least one peer answer
        roots = votes[c]
        ours = st.boundary_roots[c]
        total = sum(len(v) for v in roots.values())
        best_root, best = max(roots.items(), key=lambda kv: len(kv[1]))
        if ours != best_root and len(best) * 2 > total:
            if _root_pool_logged.get((ns, c)) is None:
                _root_pool_logged[(ns, c)] = True
                print(f"[execnode] CRITICAL: EXEC ROOT OUT OF MAJORITY ns={ns} boundary cursor {c} — "
                      f"ours {ours[:12]}… vs majority {best_root[:12]}… held by {len(best)}/{total} "
                      f"({[x[:15] for x in best]}); full pool: "
                      + "; ".join(f"{r[:10]}…×{len(v)}" for r, v in roots.items()), flush=True)
        elif ours == best_root:
            _root_pool_logged.pop((ns, c), None)
        for old in [k for k in _root_pool_logged if k[0] == ns and k[1] < c - 2000]:
            _root_pool_logged.pop(old, None)


# PEER BATCH FALLBACK for the tail prefetch. The local L1 shares this host's GIL and CPU with
# consensus work, so under load its API answers in 1-15+ s while fleet peers answer in 30-300 ms
# (measured). Fetching bodies from a peer is safe ONLY with full verification, which this has:
#   * parent-linkage anchored at OUR OWN last applied hash (the peer cannot choose the anchor),
#   * block_content_hash RECOMPUTED per block and required to equal the declared block_hash — the
#     same anti-fork invariant produce_block enforces, so a forged body cannot survive,
#   * heights bounded by OUR local finality (a peer cannot feed us past our own floor).
# A lying peer can therefore at worst serve us exactly the canonical chain, or nothing.
_peer_cache = [0.0, []]                 # (fetched_at, [ips]) — /peers cached ~10 min


async def _peer_batch(session, parent_hash, finalized, want=100):
    """Verified block batch from the first fleet peer that answers. {} when none does."""
    from ops.block_ops import block_content_hash    # lazy, like maybe_settle's ops import
    now = time.time()
    if now - _peer_cache[0] > 600:
        try:
            pr = await _get_json(session, "/peers")
            _peer_cache[0] = now
            _peer_cache[1] = [f"[{ip}]" if (":" in ip and not ip.startswith("[")) else ip
                              for ip in ((pr.get("peers") or []) if isinstance(pr, dict) else [])]
        except Exception as e:
            # keep any stale list (still good donors) but SAY the refresh failed — a quiet failure
            # here left the fallback iterating an empty list with zero log evidence (2026-08-20).
            print(f"[execnode] /peers refresh failed ({type(e).__name__}: {e}) — "
                  f"{len(_peer_cache[1])} cached peers", flush=True)
    for peer in _peer_cache[1]:
        try:
            # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
            async with session.get(f"http://{peer}:9173/get_blocks_after?hash={parent_hash}&count={want}",
                                   timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as r:
                d = await r.json(content_type=None)
            out = {}
            expect = parent_hash
            for b in (d.get("blocks_after") or []) if isinstance(d, dict) else []:
                if not isinstance(b, dict) or b.get("parent_hash") != expect:
                    break
                if b.get("block_number") is None or int(b["block_number"]) > finalized:
                    break
                if block_content_hash(b) != b.get("block_hash"):
                    print(f"[execnode] peer {peer} served a hash-inconsistent block "
                          f"{b.get('block_number')} — dropping the rest of its batch", flush=True)
                    break
                out[int(b["block_number"])] = b
                expect = b["block_hash"]
            if out:
                return out
        except Exception:
            continue
    return {}


async def tail_loop():
    """Follow L1 forever: each poll, replay every newly FINALIZED block's exec-relevant txs (blob /
    bridge / shield) into `state` in block order — skipping pruned (body-less) finalized blocks — then
    accrue the presence dividend, persist, settle if enabled, and rebuild the fast PROVISIONAL view over the
    unfinalized tail. Only FINALIZED blocks mutate the persistent state, so its cursor never handles a reorg;
    the provisional clone absorbs the tail (and any reorg) harmlessly. Any error waits out the poll; never dies."""
    print(f"[execnode] tailing {L1} · state={STATE_PATH} · cursor={state.cursor}", flush=True)
    async with aiohttp.ClientSession() as session:
        await _maybe_bootstrap(session)
        await _seed_root_ring(session)
        stale_polls = 0     # consecutive polls seeing cursor > finalized (reroll-stranded state); see below
        divergence_polls = 0    # polls since the last canonicality probe; see FINALITY-REVERT PROBE below
        while True:
            try:
                status = await _get_json(session, "/status")
                finalized = int(status.get("finalized_height", 0))

                # ---- FINALITY-REVERT PROBE ------------------------------------------------------------
                # THE HOLE THIS CLOSES. The stale-exec guard below only runs inside `cursor > finalized`,
                # and it compares at min(max_applied, finalized). Both facts fail on a sub-finality rewind:
                #
                #   * L1 CAN rewind below its finality floor. core_loop.reanchor_candidates passes floor=0
                #     for ESCALATED recovery ("a floor that keeps pinning us to a lighter chain is itself
                #     the fault"), so reverted-finalized blocks are a real code path, not a theoretical one.
                #   * If the re-anchor lands BELOW the fork point, the guard's comparison height sits below
                #     it too, the hashes agree, and it concludes "same chain, our state is fine" — while
                #     every block we applied ABOVE the fork came from the abandoned chain.
                #   * Worse, the inversion is TRANSIENT. Once L1 rebuilds past our cursor, `cursor >
                #     finalized` is false forever, the guard never runs again, and the contamination is
                #     permanent AND invisible. The node then serves confidently wrong balances and merely
                #     stops settling (maybe_settle refuses to post a proof that can't reproduce its own
                #     root) — a log line, not an alarm.
                #
                # So probe independently of the height ordering. We apply ONLY finalized blocks, so any
                # height in state.block_hashes was final when we applied it: if L1's chain now disagrees
                # there, finality itself was reverted and our state belongs to a chain that no longer
                # exists. Probe the HIGHEST such height L1 can still answer for — that is above the fork
                # point, where the guard below is blind.
                #
                # SAFE TO ACT ON, unlike the bare height inversion that wiped this node's 25 contracts on
                # 2026-08-03: only a genuine hash MISMATCH triggers. A restarting L1, a missing block, a
                # pruned body with no hash and a malformed reply all fall through to "no evidence, do
                # nothing" — the probe can report divergence, never absence of information.
                divergence_polls += 1
                if divergence_polls >= DIVERGENCE_PROBE_POLLS:
                    divergence_polls = 0
                    reason = None
                    # Our highest applied block vs L1's chain, hash-only so a body-less height still
                    # answers (a revert below the body floor must not be invisible). (A comparison against
                    # /status snapshot_hash was tried and REMOVED: that field is the snapshot PAYLOAD hash,
                    # not the block hash at snapshot_height — it fired on every poll on a healthy node.)
                    _probe = probe_height(state.block_hashes,
                                          int(status.get("latest_block_height", 0) or 0))
                    if _probe:
                        _pb = await _get_json(session, f"/get_block?number={_probe}&hash_only=1")
                        if finality_reverted(state.block_hashes, _probe, _pb):
                            reason = f"block {_probe} disagrees with L1"
                    if reason:
                        print(f"[execnode] FINALITY REVERTED: {reason} — exec state belongs to an abandoned "
                              f"chain; recovering", flush=True)
                        await _recover_from_revert(session, status, reason)
                        await asyncio.sleep(POLL)
                        continue
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
                        elif finalized > 0:
                            # L1's finalized height is BELOW our retained ring (a deep truncation, or a
                            # node re-syncing from genesis). Its number->hash index still answers for
                            # heights above finalized (?hash_only=1 needs no body), so compare our LOWEST
                            # retained height: a match is the same chain, a mismatch is a foreign one.
                            _shared = min(state.block_hashes)
                    _mismatch = False
                    if _shared is not None:
                        _blk = await _get_json(session, f"/get_block?number={_shared}&hash_only=1")
                        _bh = (_blk or {}).get("block") or _blk or {}
                        _l1h = _bh.get("block_hash") if isinstance(_bh, dict) else None
                        if _l1h and int(_l1h, 16) == int(state.block_hashes[_shared]):
                            # Same chain. L1 is restarting or catching up; our state is fine.
                            stale_polls = 0
                            await asyncio.sleep(POLL)
                            continue
                        _mismatch = bool(_l1h)
                    if not _mismatch:
                        # NO EVIDENCE: finalized == 0 (L1 still reloading, or serving a snapshot-booted
                        # /status), or L1 does not (yet) have any height we retain. The old code counted
                        # these polls toward the reset and, after ~30 s, WIPED the exec state AND the DA
                        # store — of which this box is the fleet's only copy — on a bare height inversion,
                        # the exact 2026-08-03 class the hash-compare was written to close. Only a block
                        # that L1 serves with a DIFFERENT hash at a height we applied is evidence of a
                        # purged chain; without one, wait (a reroll is caught at boot by the .gen marker).
                        print(f"[execnode] cursor {state.cursor} > L1 finalized {finalized} but no shared "
                              f"height is comparable yet — waiting, not resetting", flush=True)
                        stale_polls = 0
                        await asyncio.sleep(POLL)
                        continue
                    stale_polls += 1
                    print(f"[execnode] cursor {state.cursor} > L1 finalized {finalized} "
                          f"({stale_polls}/{STALE_RESET_POLLS}) — possible stale state from a reroll"
                          f"; block {_shared} hash MISMATCHES L1", flush=True)
                    if stale_polls >= STALE_RESET_POLLS:
                        _reset_states_to_genesis(reason=f"cursor {state.cursor} outran finalized {finalized}")
                    await asyncio.sleep(POLL)
                    continue
                stale_polls = 0
                applied = 0
                prev_cursor_for_ckpt = state.cursor
                prefetch = {}          # poll-local h -> block from ONE /get_blocks_after call (see below)
                while state.cursor < finalized:
                    h = state.cursor + 1
                    # BATCH PREFETCH, POLL-LOCAL. One block per HTTP round trip made catch-up latency-bound:
                    # on a loaded host each answer took 1-15 s, batches died after 1-3 blocks on the 15 s
                    # timeout, and the exec FELL BEHIND the chain while healthy (MEASURED 2026-08-20 00:01:
                    # 1.7 applied/min vs 8 produced/min, 500 behind and growing). /get_blocks_after?hash=
                    # returns up to ~100 descendants of our last applied block in ONE call, amortizing the
                    # round trip ~100x. The buffer lives inside this poll only (refilled from the CURRENT
                    # cursor's own hash each time), so a reorg/rewind can never serve a stale block, and
                    # every per-block rule below — linkage, canonical accrual, the body-less gap, settle
                    # observation — runs unchanged on buffered and single-fetched blocks alike. Any batch
                    # problem falls back to the single-block fetch, which remains the correctness path.
                    block = prefetch.pop(h, None)
                    if block is None:
                        _ph = state.block_hashes.get(state.cursor)
                        # the BLOCKHASH ring stores hashes as INTS (int(hex,16) — state.record_block_hash);
                        # a URL built from the decimal form matches nothing and the empty answer is not an
                        # exception, so the batch path silently never fired (observed 2026-08-20 00:55:
                        # zero batch-failure lines AND zero batch hits — all progress was single fetches).
                        if isinstance(_ph, int):
                            _ph = format(_ph, "064x")
                        if _ph and (finalized - state.cursor) > 3:
                            # OWN TIMEOUT, AND NEVER SILENT. A 100-block collect is ~100 disk reads +
                            # serialize on an L1 that answers single blocks in 1-15 s under load — the
                            # shared 15 s _get_json timeout killed the batch on exactly the hosts that
                            # need it, and the bare `except: pass` hid that completely (observed
                            # 2026-08-20 00:32: prefetch shipped, batches still +1/+2, zero log evidence
                            # why — the same invisibility bug as the empty str(TimeoutError), one layer
                            # up). One 60 s call per ~100 blocks is a fine trade; a failure names itself.
                            try:
                                # 20s, not 60: peers answer this same call in ~0.3s, so when the LOCAL
                                # L1 is GIL-starved (its emergency loop pins the process) a long local
                                # wait only delays the peer fallback — measured 2026-08-20 11:09-11:15:
                                # one poll burned 60s local batch + peer miss + 15s single fetch for
                                # ZERO blocks while finality ran 168 cursors ahead.
                                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                                async with session.get(f"{L1}/get_blocks_after?hash={_ph}&count=100",
                                                       timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as _resp:
                                    _r = await _resp.json(content_type=None)
                                for _b in (_r.get("blocks_after") or []) if isinstance(_r, dict) else []:
                                    if isinstance(_b, dict) and isinstance(_b.get("block_number"), int) \
                                            and _b["block_number"] <= finalized:
                                        prefetch[_b["block_number"]] = _b
                                block = prefetch.pop(h, None)
                            except Exception as _e:
                                print(f"[execnode] batch prefetch after {state.cursor} failed "
                                      f"({type(_e).__name__}: {_e}) — trying peers", flush=True)
                            if block is None and not prefetch:
                                # local L1 too slow/empty: VERIFIED peer batch (see _peer_batch — full
                                # content-hash recompute + own-anchor linkage; can only yield canon).
                                prefetch.update(await _peer_batch(session, _ph, finalized))
                                block = prefetch.pop(h, None)
                                if block is None and not prefetch:
                                    # NEVER SILENT (the empty-str(TimeoutError) lesson, one layer up
                                    # again): an empty peer fallback was invisible for 15 min on
                                    # 2026-08-20 — the /peers refresh had failed quietly and the
                                    # fallback looped over ZERO peers.
                                    print(f"[execnode] peer batch after {state.cursor} empty "
                                          f"({len(_peer_cache[1])} peers known) — single fetch",
                                          flush=True)
                    if block is None:
                        # A SLOW FETCH MUST END THE BATCH, NEVER THE POLL. _get_json RAISES on its 15s
                        # timeout; unhandled, that raise skipped the ENTIRE poll epilogue (dividend accrual,
                        # the state SAVE, the checkpoint, the settle spawn) — MEASURED 2026-08-19: 0
                        # completed epilogues in 100 minutes, exec_state.json 2h stale while blocks applied
                        # in memory. (Invisible for weeks because str(TimeoutError) is "".) A fetch failure
                        # is the NORMAL degraded case the `break` below was always meant for.
                        try:
                            block = await _get_json(session, f"/get_block?number={h}")
                        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
                            print(f"[execnode] block fetch {h} failed ({type(e).__name__}) — pausing batch, "
                                  f"keeping progress", flush=True)
                            block = None
                    if not isinstance(block, dict):
                        break                                  # fetch problem; retry next poll
                    # PARENT LINKAGE — the zero-gap detector. The block we are about to apply must chain
                    # onto the block we applied last. If it does not, L1's canonical chain no longer
                    # contains our block h-1: finality was reverted beneath us, and applying h would stack
                    # canonical history on top of a dead fork. Caught BEFORE the first wrong apply, on the
                    # very block that reveals it — no probe interval, no window of mixed state.
                    if linkage_broken(state.block_hashes, h, block):
                        print(f"[execnode] FINALITY REVERTED (linkage): block {h} does not chain onto our "
                              f"applied block {h - 1} — recovering", flush=True)
                        await _recover_from_revert(session, status, f"linkage break at {h}")
                        break
                    # CANONICAL ACCRUAL: before block h may apply, the dividend watermark must equal
                    # (h // EPOCH_LENGTH) - 1 — a pure function of h, from cursor 0 (ungated at gen 22).
                    if not await _accrue_owed(session, state, h // _EPOCH_LENGTH - 1):
                        break                                  # owed accrual unavailable: HOLD the cursor
                    if "block_transactions" not in block:
                        # A FINALIZED block (h <= finalized) with no body is PRUNED (rolling mode drops old
                        # block bodies, leaving only {block_number}). SKIP it so a fresh exec node can still
                        # cold-start on a pruned chain — BUT record the gap. The old premise ("such blocks
                        # predate the exec features") died at the reroll: a pruned body may carry deploys,
                        # calls, collects. A state built over a gap is a GUESS, and betanet-3 proved it
                        # (the frozen-quorum incident: gap-started exec nodes silently skipped the contract
                        # deploys and diverged on every multi-attester cursor). replay_gap is PERMANENT
                        # provenance: it makes state_complete() False, which mutes this node's settle
                        # attestations until a quorum-verified bootstrap replaces the state.
                        state.replay_gap = True
                        state.cursor = h
                        continue
                    _observe_settles(block, state.attested)    # divergence alarm: see _observe_settles
                    # `finalized` IS WHAT BOUNDS THE DA STALL (audit 2026-09-25): without it _apply_block waits for an
                    # unavailable proof forever. Only this tail passes it; the provisional ones must not.
                    if not await _apply_block(session, states, state, block, verbose=True, finalized=finalized):
                        break                                  # DA stall: do NOT advance the cursor; retry next poll
                    applied += 1
                    # REMEMBER THIS ROOT POINT (per ns): exit proofs must verify against the root L1
                    # SETTLED, which trails the live root by a settle cadence; the ring lets the proof
                    # handlers serve ?root=<settled> instead of forcing wallets to wait for the live root
                    # to coincide with a settled one (measured 5-12 h for dividend claims on a busy chain).
                    # Free when the block changed nothing (cached root) — but skipped entirely during
                    # deep catch-up (a cold replay computing the root per state-changing block would add
                    # hours); the ring only matters once the node serves proofs near the tip.
                    if h >= finalized - 240:
                        for _st in states.values():
                            try:
                                _st.note_root_point()
                            except Exception:
                                pass                           # bookkeeping must never stall the tail
                    # EXEC HASH POOL entry (see ExecState.boundary_roots): at every epoch-boundary cursor,
                    # record the root — the exactly-comparable point the root-pool probe below compares
                    # across peers, L1-hash-pool style. Recorded AFTER the boundary block applies, so it is
                    # a pure function of the block stream (canonical accrual already ran for h if due).
                    for _ns, _st in states.items():
                        _record_boundary(_ns, _st)
                    # PERSIST MID-BATCH. A long catch-up (hundreds of blocks after a restart or an L1
                    # stall) used to reach disk only at the epilogue — one interruption anywhere and the
                    # whole batch replayed again next restart. ~5.7 MB dump every 200 blocks is noise
                    # against the refetch cost of losing them.
                    if applied % 200 == 0:
                        for _st in states.values():
                            _st.save()
                if applied:
                    # (legacy batch-boundary epilogue accrual DELETED at gen 22 — the per-block
                    # canonical accrual above keeps last_div_epoch current before any block applies.)
                    for _st in states.values():
                        _st.save()
                    _ckpt_maybe_persist(prev_cursor_for_ckpt, state.cursor)
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
                        # builds. The in-flight guard inside _build_settlement_proof (deleted in G9) bounded concurrent
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
                # AUTO-REPAIR PROBE — inline (single-task, can never race _apply_block above), throttled,
                # and a no-op the moment every namespace passes state_complete(). See _repair_bootstrap.
                global _repair_last, _anchor_last
                _now = time.time()
                if (_now - _repair_last) >= _REPAIR_EVERY:
                    if any(st.cursor >= 0 and not st.state_complete() for st in states.values()):
                        _repair_last = _now
                        try:
                            await _repair_bootstrap(session)
                        except Exception as e:
                            print(f"[execnode] repair-bootstrap error: {e}", flush=True)
                # FROZEN-QUORUM AUTO-RECOVERY PROBE — same inline/throttled discipline. See _anchor_adopt.
                if (_now - _anchor_last) >= ANCHOR_ADOPT_EVERY:
                    _anchor_last = _now
                    try:
                        await _anchor_adopt(session, finalized)
                    except Exception as e:
                        print(f"[execnode] anchor-adopt error: {type(e).__name__}: {e}", flush=True)
                # EXEC ROOT-POOL PROBE — the L1 hash-pool pattern for the exec layer. See _root_pool_probe.
                global _root_pool_last
                if (_now - _root_pool_last) >= ROOT_POOL_EVERY:
                    _root_pool_last = _now
                    await _root_pool_probe(session)
                # Rebuild the PROVISIONAL view EVERY poll (even with no newly-finalized block — the tip still
                # advances ~every block_time, so a just-included bet/reveal/deposit shows within ~one block
                # instead of a whole finality window). Best-effort; never breaks the finalized tail.
                try:
                    latest = await _get_json(session, "/get_latest_block")
                    tip = int(latest.get("block_number", state.cursor)) if isinstance(latest, dict) else state.cursor
                    tip_hash = latest.get("block_hash") if isinstance(latest, dict) else None
                    # SKIP WHILE FAR BEHIND. The provisional view exists to show the unfinalized tail a
                    # beat early — meaningless when the FINALIZED cursor itself is hundreds of blocks
                    # stale, yet the refresh still cloned the full state and re-fetched/re-applied up to
                    # PROV_MAX_TAIL blocks EVERY POLL, competing for the same starved L1 + CPU the
                    # catch-up needed (measured 2026-08-20: exec at 70% CPU while applying 1.7 blocks/min,
                    # 500 behind and falling). Catch-up first; the tail view resumes within 200 of the tip.
                    if tip - state.cursor <= 200:
                        await _refresh_provisional(session, state.cursor, tip, tip_hash)
                except Exception as e:
                    # NAME THE TYPE — str(TimeoutError) is "" (the same invisibility the tail handler had).
                    print(f"[execnode] provisional refresh error: {type(e).__name__}: {e}", flush=True)
            except Exception as e:
                # NAME THE TYPE. str(asyncio.TimeoutError()) is "" — this line printed literally
                # "tail error: " for every timeout, which is how a 100%-poll-failure mode stayed
                # unnoticed for weeks. An empty message is not a small bug; it is invisibility.
                print(f"[execnode] tail error: {type(e).__name__}: {e}", flush=True)
            await asyncio.sleep(POLL)


# --- read-only query API ---------------------------------------------------------------------------
_NS404 = lambda: web.json_response({"error": "namespace not served by this node"}, status=404)


# ---- DA serving: publish / fetch erasure-coded objects by commitment -----------------------------
def _bad_commitment(c) -> bool:
    """The commitment shape check at the EDGE of every /da READ handler (announce spells the same expression
    inline — tests/test_da_announce.py pins that text). DaStore._dir raises ValueError('bad commitment') as the
    path-traversal backstop, but a raise there surfaced as a 500 + a journal traceback per request — a wrong
    status for a client error, and free log growth for a scanner once /da/ sits behind a public TLS relay
    (doc/relays.md). Refuse here with 400; the backstop stays."""
    return (not isinstance(c, str) or not c or len(c) > 128 or "/" in c or "\\" in c or c in (".", ".."))


async def h_da_meta(request):
    """GET /da/meta?c=<commitment> — the manifest {commitment,k,n,stripes,length}, or 404 if unknown here."""
    c = request.query.get("c", "")
    if _bad_commitment(c):
        return web.json_response({"error": "bad commitment"}, status=400)
    m = DA.meta(c)
    return web.json_response(m) if m else web.json_response({"error": "unknown commitment"}, status=404)


async def h_da_have(request):
    """GET /da/have?c=<commitment> — which shard indices this node currently holds."""
    c = request.query.get("c", "")
    if _bad_commitment(c):
        return web.json_response({"error": "bad commitment"}, status=400)
    return web.json_response({"commitment": c, "have": DA.have(c)})


async def h_da_shard(request):
    """GET /da/shard?c=<commitment>&i=<index> — one (shard, merkle-proof) the caller can verify against
    the commitment without trusting this node. 404 if not held."""
    c = request.query.get("c", "")
    if _bad_commitment(c):
        return web.json_response({"error": "bad commitment"}, status=400)
    try:
        i = int(request.query.get("i", ""))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad index"}, status=400)
    def _work():
        r = DA.shard(c, i)                                  # a ~30 MiB file read + hex: not on the loop
        return {"index": i, "shard": r[0].hex(), "proof": r[1]} if r else None
    out = await asyncio.to_thread(_work)
    if not out:
        return web.json_response({"error": "no such shard"}, status=404)
    return web.json_response(out)


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
    if _bad_commitment(_c):
        return web.json_response({"error": "bad commitment"}, status=400)
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
            # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
            async with session.post(f"{u}/da/announce", json={"commitment": commitment},
                                    timeout=aiohttp.ClientTimeout(total=budget_s), allow_redirects=False) as r:
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
        # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
        async with session.get(L1 + "/peers", timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False) as r:
            peers = await r.json() if r.status == 200 else []
    except Exception:
        peers = []
    # ASK ON THE PORT PEERS ACTUALLY EXPOSE. This used to build `http://{host}:{PORT}` — the peer's EXEC
    # port — on the reasoning that every node runs the exec/DA node on the same convention port. They do run
    # it; they just do not expose it. Measured 2026-08-08 across the live fleet: every peer's :9273 refused
    # the connection while :9173 answered, so _da_sources produced a list of URLs that could never serve a
    # shard, da_fetch returned None every time, and "publish the proof to DA" silently degraded to riding
    # ~69 MiB of proof inline in the transaction. THAT is why the inline threshold was pinned wide open.
    #
    # L1 now forwards /da/{meta,have,shard,get} to its own exec node (nado.py:da_proxy), so the reachable
    # port serves DA on every node. Our OWN exec node is still tried directly first — a local hop beats a
    # proxied one, and it is the one URL we know is up.
    _l1_port = int(str(L1).rsplit(":", 1)[-1].split("/")[0] or 9173)
    if f"http://127.0.0.1:{PORT}" not in seen:
        seen.add(f"http://127.0.0.1:{PORT}"); out.append(f"http://127.0.0.1:{PORT}")
    # L1's /peers ANSWERS {"peers": [...]} (nado.py _dump_handler), NOT a bare list. Iterating the object walked its KEYS,
    # so the only "peer" was the string "peers" -> http://peers:9173: no exec node ever fetched a DA blob from another
    # node, only from its own store. A DA-carried op (every relayed Stwo spend) was then applied by the node that
    # published it and REFUSED at the DA deadline by every other — an exec-state fork, found by the gen-29 rehearsal's
    # two-user walk (2026-10-26; the live pool never held a note, so it never fired on the fleet). INVARIANT: unwrap
    # the object; an IPv6 peer keeps its whole address (split(":")[0] cut 2001:b07:... to "2001").
    if isinstance(peers, dict):
        peers = peers.get("peers") or []
    for p in (peers if isinstance(peers, list) else []):
        host = str(p).strip()
        if host.count(":") == 1:
            host = host.split(":")[0]                       # an IPv4 peer given as ip:port
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"                              # IPv6 in a URL
        url = f"http://{host}:{_l1_port}" if host else ""   # its L1, which proxies /da to its exec node
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
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"{src}/da/meta?c={commitment}",
                                       timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False) as r:
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
                # allow_redirects=False: a peer's 302 to 127.0.0.1 would be a loopback-authorized GET here (ops/outbound_guard.py)
                async with session.get(f"{src}/da/shard?c={commitment}&i={i}",
                                       timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False) as r:
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


async def h_roots(request):
    """GET /exec/roots?ns= — this node's epoch-boundary root ring {cursor: root} plus its live cursor:
    the exec-layer HASH POOL entry. Boundary cursors are the exactly-comparable points every node passes
    through identically, so peers compare these to detect divergence within ~one epoch (see
    _root_pool_probe) instead of discovering it years later as a frozen settle quorum."""
    ns = request.query.get("ns", "default")
    st = states.get(ns)
    if st is None:
        return _NS404()
    return web.json_response({"ns": ns, "cursor": st.cursor,
                              "boundary_roots": {str(c): r for c, r in st.boundary_roots.items()}})


async def h_state_snapshot(request):
    """GET /exec/state_snapshot?ns=: the FULL state payload as of this node's LAST ACCEPTED settle,
    {ns, cursor, state_root, state} — the settled-checkpoint bootstrap donor side. The joiner
    re-derives state_root from `state` and accepts only if it matches the L1-settled (cursor, root),
    so a lying donor can waste its time but never poison it. 404 until this node has settled once."""
    ns = request.query.get("ns", "default")
    cur_q = request.query.get("cursor")
    if cur_q:
        # by-cursor: serve any stashed settle pre-state, so a joiner/repairer can ask for the exact
        # cursor L1 has justified instead of whatever this donor settled last.
        try:
            raw = (_settled_history.get(ns) or {}).get(int(cur_q))
        except ValueError:
            return web.json_response({"error": "bad cursor"}, status=400)
        if raw is None:
            return web.json_response({"error": f"no stashed snapshot at cursor {cur_q} "
                                               f"(held: {sorted(_settled_history.get(ns) or {})})"}, status=404)
        return web.Response(text=raw, content_type="application/json")
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
                              "cursor": st.cursor, "block_ts": st.block_ts, "contracts": len(st.contracts), "l1": L1,
                              # non-empty while this node's exec state is known to belong to an abandoned
                              # chain and is awaiting a recovery source (see FINALITY-REVERT PROBE)
                              "stranded": dict(STRANDED) if STRANDED else None})


async def h_settlement(request):
    """Settlement status for namespace ?ns= (default): its current (cursor, state_root), whether this node
    posts `settle` attestations, the cadence, the last cursor it settled, and every
    namespace this node runs. The interface combines this with L1's /get_settled?ns= to show tip vs settled.
    FINALIZED state only (never the ?provisional clone): a clone carries no kv store, so its state_root()
    is the full cold two-tree build — ~24 s on the event loop — and the clone is rebuilt every poll."""
    st = states.get(request.query.get("ns", "default"))
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
                          "runtime": c.get("runtime", "zkvm"), "abi": c.get("abi") or {},
                          "upgradable": c.get("upgradable", True) is not False})   # C5: say so (review 2026-09-23)
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
    # OFF THE EVENT LOOP, BOUNDED (audit 2026-09-24 #25, confirmed 2026-10-18): a view is a full contract call, up to
    # GAS_LIMIT steps of the pure-Python VM, and it ran ON the event loop — any client could freeze the exec node,
    # its block tail included, by repeating it. It runs in a worker under the state's mutate lock (never reading a
    # half-applied block), at most _VIEW_SLOTS at a time; a full house answers 429 instead of queueing.
    if _VIEW_BUSY[0] >= _VIEW_SLOTS:
        return web.json_response({"cid": cid, "method": method, "result": None, "error": "busy"}, status=429)
    _VIEW_BUSY[0] += 1
    try:
        def _run():
            with st._mutate_lock:
                return st.view(cid, method, args)
        _ret = await asyncio.to_thread(_run)
    finally:
        _VIEW_BUSY[0] -= 1
    return web.json_response({"cid": cid, "method": method, "result": None if _ret is None else str(_ret)})


_VIEW_SLOTS = 4                  # concurrent contract views (h_view); one event loop, so a plain counter is exact
_VIEW_BUSY = [0]


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


async def h_beacon(request):
    """Epoch beacons for the BEACON randomness (?epochs=E1,E2,…). Returns {cursor, beacons: {epoch: hex|null}} —
    null while the epoch is not final here or outside the node's window. FINALIZED state only: the value a banked
    game settles from, so a client derives the same outcome the contract will."""
    st = states.get(request.query.get("ns", "default"))
    if st is None:
        return _NS404()
    out = {}
    for e in (request.query.get("epochs") or "").split(",")[:64]:
        try:
            ei = int(e); v = st.beacons.get(ei)
            out[str(ei)] = (format(v, "x") if v is not None else None)
        except Exception:
            pass
    return web.json_response({"cursor": st.cursor, "beacons": out})


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
    the seq is unknown. FINALIZED state only — a proof against the provisional clone would be a cold
    root build on the loop and useless anyway (nothing settles a provisional root)."""
    st = states.get(request.query.get("ns", "default"))
    if st is None:
        return _NS404()
    from execnode import exec_root_b2 as ER
    try:
        msg = st.outbox[str(int(request.query.get("seq", "")))]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "not found"}, status=404)
    dg = ER.leaf_digest(ER.msg_outbox_leaf(msg))
    # ?root= — a recent remembered root (pass L1's settled root for this ns), else the live root.
    got = st.record_proof_at(request.query.get("root"), ER.T_DIGEST, "outbox", dg, value=1)
    if not got:
        return web.json_response({"error": "root not held (not applied yet, too old, or the record "
                                           "postdates it) — retry after the next settle"}, status=409)
    proof, root = got
    return web.json_response({"message": msg, "proof": proof,
                              "ns": request.query.get("ns", "default"), "state_root": root})


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
    """Merkle proof for a bridge-withdrawal record (?nonce=) against ?root= (a recent remembered root —
    pass L1's settled root) or the CURRENT state_root (also returned); the claim only succeeds on L1 once
    a settled root covers it. 404 if the nonce is unknown; 409 if ?root= is not held."""
    # the Merkle proof a user submits to L1's bridge_withdraw to claim their exit against the settled root
    from execnode import exec_root_b2 as ER
    nonce = str(request.query.get("nonce", ""))
    w = state.withdrawals.get(nonce)
    if not w:
        return web.json_response({"error": "not found"}, status=404)
    got = state.record_proof_at(request.query.get("root"), ER.T_BRIDGE_WD, w["addr"], nonce, value=w["amount"])
    if not got:
        return web.json_response({"error": "root not held (not applied yet, too old, or the record "
                                           "postdates it) — retry after the next settle"}, status=409)
    proof, root = got
    return web.json_response({"addr": w["addr"], "amount": w["amount"], "nonce": nonce,
                              "proof": proof, "state_root": root})


async def h_withdrawals(request):
    """?address= -> that address's CASH-OUTS still waiting for their L1 claim, each with its proof when L1's settled root
    covers it: {"address", "pending": [{nonce, amount, proof?, state_root?}], "settled_root", "settled_cursor",
    "cursor", "settle_every"}. ?root= overrides the root the proofs are built against (default: L1's justified one).

    WHY THIS EXISTS. A cash-out (blob op bridge_withdraw) only DEBITS the playable balance and records a withdrawal;
    the coins reach L1 when a second, L1 `bridge_withdraw` tx proves that record against a settled root. Nothing in the
    product built that second tx, and nothing could list a user's records except /exec/bridge, which returns every
    balance and every withdrawal on the layer: four cash-outs (10.06 NADO, 2026-10-10) were debited and never paid.
    The wallet and the game SDK read this to show "cash-out pending" and to claim each one the moment it is
    provable. A record disappears here when its claim FINALIZES on L1 (state.drop_claimed), so "gone after a claim"
    is the landed signal. Cheap for the common case: an address with nothing pending costs one dict scan and no L1
    read; the proofs reuse the per-root tree cache (state.record_proof_at)."""
    from execnode import exec_root_b2 as ER
    addr = request.query.get("address", "")
    if not addr:
        return web.json_response({"error": "address required"}, status=400)
    mine = [(n, w) for n, w in sorted(state.withdrawals.items(), key=lambda kv: (len(kv[0]), kv[0]))
            if w.get("addr") == addr]
    out = {"address": addr, "pending": [], "settled_root": None, "settled_cursor": None,
           "cursor": state.cursor, "settle_every": SETTLE_EVERY}
    if not mine:
        return web.json_response(out)
    s_cur, s_root = await _settled_root_hint()
    out["settled_root"], out["settled_cursor"] = s_root, s_cur
    root_hex = request.query.get("root") or s_root
    for nonce, w in mine:
        # amount as a STRING (see h_assets): past 2^53 a browser's JSON.parse rounds it, and the claim's amount must
        # equal the record exactly or the proof is refused — a cash-out above ~900k NADO would be unclaimable
        row = {"nonce": nonce, "amount": str(int(w["amount"]))}
        # only a proof against the SETTLED root can be claimed; with no settled root yet there is nothing to prove
        # against (record_proof_at(None) would answer with the LIVE root, which L1 refuses)
        got = state.record_proof_at(root_hex, ER.T_BRIDGE_WD, addr, nonce, value=w["amount"]) if root_hex else None
        if got:
            row["proof"], row["state_root"] = got
        out["pending"].append(row)
    return web.json_response(out)


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


# L1's justified settled root, remembered for the proof handlers. A dividend claim only LANDS when its
# proof is against a root L1 holds (the last 3 justified — ops/settlement_ops.recent_settled_roots), so a
# proof request that names no root gets the SETTLED one, not the live one. Before this, a wallet with the
# pre-5f08c0a9 interface.js (no ?root=) received live-root proofs that could never match, retried every
# tick for every pending nonce, and at ~2 req/s those retries pinned the exec event loop (2026-08-24,
# 436 unclaimed nonces). Refreshed by the poll loop; a short TTL fetch here covers a handler that runs
# before the first poll. (cursor, root, fetched_at).
_l1_settled_hint = {}
_SETTLED_HINT_TTL = 6.0


async def _settled_root_hint(ns="default"):
    """(cursor, root) of L1's justified settle for `ns`, or (None, None). Cached SETTLED_HINT_TTL seconds."""
    ent = _l1_settled_hint.get(ns)
    if ent and time.time() - ent[2] < _SETTLED_HINT_TTL:
        return ent[0], ent[1]
    try:
        async with aiohttp.ClientSession() as s:
            d = await _get_json(s, f"/get_settled?ns={ns}")
        cur, root = int((d or {}).get("exec_cursor", -1)), (d or {}).get("state_root")
    except Exception:
        cur, root = (ent[0], ent[1]) if ent else (None, None)
    _l1_settled_hint[ns] = (cur, root, time.time())
    return cur, root


def _dividend_proof_one(nonce, root_hex):
    """({addr, amount, nonce, proof, state_root} | None, status) for one collected dividend withdrawal
    against `root_hex` (None = live). status: 200, 404 (unknown nonce), 409 (root not held / record postdates it)."""
    from execnode import exec_root_b2 as ER
    w = state.dividend_withdrawals.get(nonce)
    if not w:
        return None, 404
    got = state.record_proof_at(root_hex, ER.T_DIV_WD, w["addr"], nonce, value=w["amount"])
    if not got:
        return None, 409
    proof, root = got
    return {"addr": w["addr"], "amount": w["amount"], "nonce": nonce, "proof": proof, "state_root": root}, 200


async def _proof_root_for(request):
    """The root a proof request is served against: ?root= if given; else L1's settled root when this node
    holds it (so the proof is CLAIMABLE); else the live root (the historical behaviour, for a node that has
    not yet applied the settled cursor — the wallet's equality check then waits, as before)."""
    root_hex = request.query.get("root")
    if root_hex:
        return root_hex
    _cur, sr = await _settled_root_hint()
    if sr and sr in getattr(state, "_root_ring", {}):
        return sr
    return None


def _seed_root_ring_sync(ns, cursor, root_hex):
    """Remember `root_hex` (L1's justified root at `cursor`) in the ring from its stash payload, so exit
    proofs against the SETTLED root are servable right after a restart. The ring is in-memory: a node
    restarted after the justified cursor has no entry for it until the NEXT settle justifies — one
    settle interval during which every claim silently waits (the old client shape) or 409s. The two BLAKE2s
    half-trees are rebuilt from the stash and the result is checked against the stash's own root before it is
    trusted.

    G9 (2026-10-27): this rebuilt the GOLDILOCKS root, which can never equal a gen-29 BLAKE2s root, so every seed
    since the reroll was refused and the window above was paid after every restart. The entry has
    ExecState.note_root_point's BLAKE2s shape ("b2", kv root, records projection), the one record_proof_at reads.
    INVARIANT: seed exactly what note_root_point records, or the seeded root serves proofs nobody can verify."""
    from execnode import csmt, exec_root_b2 as R2
    st = states.get(ns)
    if st is None or root_hex in getattr(st, "_root_ring", {}):
        return False
    path = _stash_path(ns, cursor)
    if not os.path.exists(path):
        return False
    with open(path) as f:
        payload = json.load(f)
    if str(payload.get("state_root")) != root_hex or int(payload.get("cursor", -1)) != int(cursor):
        return False
    view = ExecState.snapshot_view(payload.get("state") or {})
    kv_root = csmt.Tree(R2.kv_projection(view.contracts)).root()
    rec_p = R2.records_projection(view)
    rec = csmt.Tree(rec_p)
    if R2.full_root(kv_root, rec.root()).hex() != root_hex:
        print(f"[execnode] root-ring seed REFUSED ns={ns} cursor={cursor}: stash does not reproduce "
              f"{root_hex[:16]}…", flush=True)
        return False
    with st._mutate_lock:
        ring = getattr(st, "_root_ring", None)
        if ring is None:
            ring = st._root_ring = {}
        ring[root_hex] = ("b2", kv_root, rec_p)
        cache = getattr(st, "_ring_stores", None)
        if cache is None:
            cache = st._ring_stores = {}
        cache[root_hex] = rec
    return True


async def _seed_root_ring(session):
    """At boot: if L1's justified root is not in the ring but its stash is on disk, seed it (in a thread)."""
    for ns in list(states):
        try:
            settled = await _get_json(session, f"/get_settled?ns={ns}")
            cur, root = int((settled or {}).get("exec_cursor", -1)), (settled or {}).get("state_root")
            if cur < 0 or not root:
                continue
            t0 = time.time()
            if await asyncio.to_thread(_seed_root_ring_sync, ns, cur, root):
                print(f"[execnode] root ring seeded ns={ns} with L1's justified root at cursor {cur} "
                      f"({root[:16]}…) in {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            print(f"[execnode] root-ring seed error ns={ns}: {type(e).__name__}: {e}", flush=True)


async def h_dividend_proof(request):
    """Merkle proof for a collected dividend withdrawal (?nonce=) against ?root= (a recent root the tail
    remembered — pass L1's settled root), else L1's SETTLED root when held, else the CURRENT state_root;
    submitted to L1's dividend_withdraw. 404 if the nonce is unknown; 409 if the root is not held or the
    record postdates it (the wallet retries next settle)."""
    # the Merkle proof a miner submits to L1's dividend_withdraw to claim a collection against the settled root
    nonce = str(request.query.get("nonce", ""))
    out, status = _dividend_proof_one(nonce, await _proof_root_for(request))
    if status == 404:
        return web.json_response({"error": "not found"}, status=404)
    if status == 409:
        return web.json_response({"error": "root not held (not applied yet, too old, or the record "
                                           "postdates it) — retry after the next settle"}, status=409)
    return web.json_response(out)


async def h_dividend_proofs(request):
    """ONE request for every claimable proof of ?address= (optionally ?root=, same rules as
    /exec/dividend_proof): {"state_root", "proofs": [...], "skipped": n}. The wallet used to ask per
    pending nonce per tick — 53 nonces = 53 round trips every refresh — and the exec node answered each
    from scratch; this is the batched shape, and a proof here costs ~1ms (state.py _sparse_stores memo).
    Nonces whose record postdates the root are counted in `skipped`, not errored: they claim next settle."""
    addr = request.query.get("address", "")
    if not addr:
        return web.json_response({"error": "address required"}, status=400)
    root_hex = await _proof_root_for(request)
    proofs, skipped, root = [], 0, None
    for nonce, w in sorted(state.dividend_withdrawals.items()):
        if w["addr"] != addr:
            continue
        out, status = _dividend_proof_one(nonce, root_hex)
        if status == 200:
            proofs.append(out)
            root = out["state_root"]
        else:
            skipped += 1
    return web.json_response({"address": addr, "state_root": root or root_hex or state.state_root(),
                              "proofs": proofs, "skipped": skipped})


@web.middleware
async def _cors(request, handler):
    """Middleware: stamp allow-any-origin CORS headers on every response (HTTP-exception responses
    included) and short-circuit OPTIONS preflights with 204 — required because the wallet page is served
    from the L1 port, making every /exec/* browser fetch cross-origin."""
    # The light-miner page is served by the L1 node on a DIFFERENT port (:9173), so every /exec/* fetch from
    # the browser is cross-origin — without these headers the browser silently blocks the response (curl
    # doesn't, which is why it worked in tests but not in the wallet). Allow any origin. NOTE: the /exec/*
    # routes are read-only or compute-only — /exec/verify_call VERIFIES and returns a verdict, it doesn't mutate
    # (DA-only: calls and transfers apply solely via the L1-ordered blob stream). They are UNAUTHENTICATED — safe
    # to expose because (a) the exec node binds loopback unless NADO_EXEC_BIND is opened, (b) the STARK size bound
    # rejects oversized inputs before allocation, and (c) an in-flight semaphore caps concurrent work.
    # /da/publish is likewise size-capped + semaphore-bounded. Also answer the CORS preflight.
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


async def h_field_shielded(request):
    """The shielded pool a wallet deposits into and proves against: the Stwo pool (execnode/shielded_stwo.py) — root, note
    and spent counts, its depth. "pool": "stwo" is how the wallet recognises it (static/interface.js).
    The legacy field and wide pools this endpoint served below STWO_POOL_HEIGHT are deleted (G9 slice 5): a gen-29 exec
    node answers for the Stwo pool at every cursor (only a fresh state at cursor -1 was ever below the gate, and its
    pools were all empty). "pos" stays None and "wide" False for wallets that still read them."""
    sp = state.stwo_pool
    return web.json_response({"root": sp.root(), "notes": len(sp.commitments), "nullifiers": len(sp.nullifiers),
                              "cursor": state.cursor, "pos": None, "wide": False, "pool": "stwo",
                              "depth": _stwo_depth()})


def _stwo_pool_next():
    """Whether the NEXT block applies the Stwo-pool rules — ExecState.rules_stwo_pool's for the block a wallet's spend
    will land in (the tip+1 rule). STWO_POOL_HEIGHT was gen 28's gate, 1 from gen 29, inlined in G9; only a fresh state
    (cursor -1) is still below it."""
    return int(state.cursor) + 1 >= 1


def _stwo_depth():
    from execnode.shielded_stwo import DEPTH
    return DEPTH


async def h_field_leaves(request):
    """The Stwo pool's full commitment list (public, 64-hex BLAKE2s digests) so a browser builds its own Merkle path and
    proves ON-DEVICE — the witness never reaches this node. "wide": False so a wallet that does not know this pool
    refuses to prove against it. At every cursor (see h_field_shielded)."""
    return web.json_response({"leaves": list(state.stwo_pool.commitments), "wide": False, "pool": "stwo",
                              "depth": _stwo_depth()})


async def h_stwo_spendable(request):
    """GET /exec/stwo_spendable?root=&nf=&cm1=&cm2=&unshield=&fee= — would a Stwo spend naming these public inputs apply
    in the NEXT block, proof aside? {"live", "ok", "reason"}. What the node's spend relay (ops/stwo_relay.py) asks
    before it pays an L1 fee to publish a spend: a stale anchor, a spent or duplicate nullifier, a duplicate output or
    an exit beyond the pool's value would be skipped by every exec node, and the relay's fee with it.
    INVARIANT: decided by ExecState.stwo_spend_refusal, the method _apply_stwo_transfer itself asks, at the height the
    spend can first land (cursor + 1, the _stwo_pool_next rule) — never a second copy of the rules here.
    Every input is a public input of a spend that is about to be published; the answer reveals nothing the chain will
    not. "live": False before STWO_POOL_HEIGHT (the relay then refuses)."""
    from execnode import shielded_stwo as _S
    q = request.query
    if not _stwo_pool_next():
        return web.json_response({"live": False, "ok": False, "reason": "the Stwo pool is not live"})
    digs = [q.get(k, "") for k in ("root", "nf", "cm1", "cm2")]
    if not all(_S.is_digest(d) for d in digs):
        return web.json_response({"live": True, "ok": False, "reason": "root, nf, cm1, cm2 must be 64 lowercase hex"},
                                 status=400)
    un, fee = _S.wire_u64(q.get("unshield", "0")), _S.wire_u64(q.get("fee", "0"))
    if un is None or fee is None:
        return web.json_response({"live": True, "ok": False, "reason": "unshield and fee are integers"}, status=400)
    # `land` (optional): the LAST block the caller's blob can land in (the relay's max_block). A spend refused there is
    # refused for the relay too: the blob cannot land before L1 tip + TX_INCLUSION_DELAY and this cursor trails the tip
    # by finality, so judging only cursor + 1 let an anchor that ages out in between pass — the relay paid the L1 fee
    # for a spend every exec node then skipped (review 2026-10-12). Judged by shielded_stwo.root_valid_through.
    land = _S.wire_u64(q.get("land", "")) if q.get("land") else None
    with state._mutate_lock:
        cur = int(state.cursor)
        why = state.stwo_spend_refusal(*digs, un, fee, cur + 1)
        # fee_to=1: the spend names its fee's payee. STWO_FEE_TO_HEIGHT (gen 28's gate, 1 from gen 29, inlined in G9):
        # below it the exec layer IGNORES fee_to and verifies against the bare payout, so a proof bound to
        # "<addr>|fee:<payee>" would be refused — the relay would pay for nothing. Judged at cursor + 1, the earliest
        # block the blob can land in; only a fresh state (cursor -1) is still below it.
        if why is None and q.get("fee_to"):
            if not (cur + 1 >= 1):
                why = "skip field-transfer: a spend naming fee_to is not accepted yet (STWO_FEE_TO_HEIGHT)"
        if why is None and land is not None:
            until = state.stwo_pool.root_valid_through(digs[0], cur)
            if until is None or until < land:
                why = ("skip field-transfer: the anchor root can no longer be named by the block this spend can land in "
                       f"(valid through {until}, lands by {land}) — re-prove against the current root")
    return web.json_response({"live": True, "ok": why is None, "reason": why or ""})


async def h_stwo_nullifiers(request):
    """GET /exec/stwo_nullifiers — the Stwo pool's spent set, sorted (public: every one was published in a spend). A
    wallet restoring its notes from the chain marks the spent ones by testing its OWN nullifiers against this list
    locally, so the node never learns which nullifiers the wallet holds (the field_leaves rule for commitments)."""
    if not _stwo_pool_next():
        return web.json_response({"live": False, "nullifiers": []})
    with state._mutate_lock:
        nfs = sorted(state.stwo_pool.nullifiers)
    return web.json_response({"live": True, "nullifiers": nfs})


async def h_stwo_carried_deposits(request):
    """GET /exec/stwo_carried_deposits[?addr=] — the PUBLIC records (depositor, amount, owner, rho) of the Stwo deposit
    notes a reroll carried (execnode/exec_genesis.py "CARRIED DEPOSITS STAY RESTORABLE"). A wallet restoring its deposit
    notes from the recovery phrase reads its own shield transactions AND these: the transactions of a carried note stayed
    on the old chain. Everything here was published in the old chain's L1 transactions; amount and rho travel as decimal
    strings. [] without a carried genesis for this generation."""
    from execnode import exec_genesis as _EG
    addr = request.query.get("addr") or None
    return web.json_response({"deposits": _EG.carried_deposits(addr)})


async def h_unshields(request):
    """Pending unshield exits for an L1 address (?addr=) — how a wallet finds the nonce(s) to claim."""
    # a wallet lists its own pending unshield exits (by L1 address) to find the nonce(s) to claim
    return web.json_response({"unshields": state.unshields_for(request.query.get("addr", ""))})


async def h_unshield_proof(request):
    """Merkle proof for a recorded unshield exit (?nonce=) against ?root= (a recent remembered root —
    pass L1's settled root) or the CURRENT state_root, submitted to L1's `unshield` to release
    SHIELD_ESCROW coins once settled. 404 if the nonce is unknown; 409 if ?root= is not held."""
    # the Merkle proof a user submits to L1's `unshield` to release SHIELD_ESCROW coins against the settled root
    from execnode import exec_root_b2 as ER
    nonce = str(request.query.get("nonce", ""))
    w = state.unshield_withdrawals.get(nonce)
    if not w:
        return web.json_response({"error": "not found"}, status=404)
    got = state.record_proof_at(request.query.get("root"), ER.T_UNSHIELD_WD, w["addr"], nonce, value=w["amount"])
    if not got:
        return web.json_response({"error": "root not held (not applied yet, too old, or the record "
                                           "postdates it) — retry after the next settle"}, status=409)
    proof, root = got
    return web.json_response({"addr": w["addr"], "amount": w["amount"], "nonce": nonce,
                              "proof": proof, "state_root": root})


async def main():
    """Wire up the query API (CORS middleware, body-size cap), start it on BIND:PORT, then run the tail
    loop forever — the HTTP server and the L1 tail share one event loop."""
    app = web.Application(middlewares=[_cors], client_max_size=MAX_BODY_BYTES)   # H-7: cap POST body size
    app.add_routes([web.get("/exec/root", h_root),
                    web.get("/exec/roots", h_roots),
                    web.get("/exec/accounting", h_accounting),
                    web.get("/exec/state_snapshot", h_state_snapshot),
                    web.get("/exec/settlement", h_settlement),
                    web.get("/exec/field_shielded", h_field_shielded),
                    web.get("/exec/field_leaves", h_field_leaves),
                    web.get("/exec/stwo_spendable", h_stwo_spendable),
                    web.get("/exec/stwo_nullifiers", h_stwo_nullifiers),
                    web.get("/exec/stwo_carried_deposits", h_stwo_carried_deposits),
                    # Z7 (security review 2026-09-23): the delegated provers took the wallet's SPENDING KEY over
                    # HTTP. The wallet has proven on-device since interface.js proveTransfer2 (WASM), so these
                    # routes only remained as a way to hand a secret to a server. Unrouted for good and the
                    # handlers deleted (h_prove_transfer, h_prove_transfer2, h_prove_call): never re-add a route
                    # that takes a spending key or a note witness. A private key is never sent anywhere (CLAUDE.md §8).
                    # /exec/verify_call (a Goldilocks call proof) went with its verifier in G9.
                    web.get("/exec/unshields", h_unshields),
                    web.get("/exec/unshield_proof", h_unshield_proof),
                    web.get("/exec/examples", h_examples),
                    web.get("/exec/runtimes", h_runtimes),
                    web.get("/exec/contracts", h_contracts),
                    web.get("/exec/contract", h_contract),
                    web.get("/exec/view", h_view),
                    web.get("/exec/blockhash", h_blockhash),
                    web.get("/exec/beacon", h_beacon),
                    web.get("/exec/outbox", h_outbox),
                    web.get("/exec/outbox_proof", h_outbox_proof),
                    web.get("/exec/inbox", h_inbox),
                    web.get("/exec/bridge", h_bridge),
                    web.get("/exec/assets", h_assets),
                    web.get("/exec/asset", h_asset),
                    web.get("/exec/allowances", h_allowances),
                    web.get("/exec/withdrawal_proof", h_withdrawal_proof),
                    web.get("/exec/withdrawals", h_withdrawals),
                    web.get("/exec/dividend", h_dividend),
                    web.get("/exec/dividend_proof", h_dividend_proof),
                    web.get("/exec/dividend_proofs", h_dividend_proofs),
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
    if BIND == "0.0.0.0":  # nosec B104 # a comparison with the operator's NADO_EXEC_BIND, not a bind
        # DUAL-STACK: same approach as nado.py's L1 listener — a SEPARATE IPv6 socket with IPV6_V6ONLY=1,
        # so v4 clients keep arriving as plain v4 addresses on the v4 socket instead of ::ffff:-mapped
        # ones (rate-limit keys stay real v4). Best-effort: a host with no IPv6 just skips it. Without
        # this, a node behind IPv4 CGNAT with native IPv6 is reachable on :9173 but not :9273 (#86).
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s6.bind(("::", PORT))
            s6.setblocking(False)
            await web.SockSite(runner, s6).start()
            print(f"[execnode] also listening on [::]:{PORT} (IPv6)", flush=True)
        except Exception as e:
            print(f"[execnode] IPv6 listener not started (no IPv6 on this host?): {e}", flush=True)
    print(f"[execnode] query API on {BIND}:{PORT}"
          + ("" if BIND != "0.0.0.0" else "  (PUBLIC — mutating /exec POSTs are unauthenticated; bounded by size cap + in-flight limit)"),  # nosec B104 # a comparison with the operator's NADO_EXEC_BIND, not a bind
          flush=True)
    await tail_loop()


if __name__ == "__main__":
    # NO urlopen IN THE EXEC NODE FOLLOWS A REDIRECT TO A NON-PUBLIC ADDRESS (bandit B310 triage, 2026-09-30): it imports
    # ops code that polls peers, and a peer's 302 -> http://127.0.0.1:9173/terminate would reach the L1 node beside it
    # as a loopback-authorized GET. Its own aiohttp calls pass allow_redirects=False. See ops/outbound_guard.py.
    from ops.outbound_guard import install_redirect_guard
    install_redirect_guard()
    asyncio.run(main())
