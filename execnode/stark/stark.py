"""
STARK over an AIR — prove that an execution TRACE satisfies its constraints, post-quantum, no trusted setup
(doc/privacy.md). This is the layer between "a computation" and FRI.

An AIR here is:
  * a TRACE: T rows × W columns (T a power of two) — the registers of the computation over time;
  * optional PERIODIC columns: fixed PUBLIC per-row values (round constants, selector flags) the verifier can
    recompute itself — this is what lets one uniform constraint behave differently on different rows (e.g. a
    hash round vs a "inject the next Merkle sibling" step), which the shielded-pool circuit needs;
  * TRANSITION constraints c(cur_row, next_row, periodic_row) = 0, required on every step;
  * BOUNDARY constraints (row, col, value) — pinned inputs/outputs.

The STARK: interpolate each column to degree<T, evaluate on a BLOWUP·T coset and Merkle-commit it; form the
COMPOSITION polynomial = a Fiat-Shamir-random combination of every constraint DIVIDED by the polynomial that
vanishes where it must hold — low-degree IFF every constraint holds — prove that with FRI, and spot-check at
FRI's own query points that the committed composition equals the quotient recomputed from the committed trace.
Cheating requires a non-low-degree quotient (FRI rejects) or a trace/composition mismatch (spot-checks reject).
Soundness assumption: BLAKE2b collision-resistance.
"""
from execnode.stark.native_guard import NODE_LOCAL_ERRORS as _NODE_LOCAL_ERRORS
from execnode.stark.native_guard import NativeMissing as _NativeMissing
import os
from collections import OrderedDict
import sys
from execnode.stark import field as F, merkle, fri, backend as _backend, extf as ext2
from execnode.stark.transcript import Transcript, DOMAIN_STARK
from execnode.stark.fri import NUM_QUERIES

OFF = F.GENERATOR                    # LDE coset shift (disjoint from the trace subgroup)

# ---- CONSENSUS RULES FOR PROOF VERIFICATION, keyed on the L1 block being judged ------------------------------
# Security review 2026-09-23 (P0, A1): two verifier pins that an honest prover already satisfies but that change
# what a VERIFIER accepts, so they are height-gated (gen 25's PROOF_BIND_HEIGHT) like every other validation rule.
# The rules are a pure function of the height of the block whose transaction carries the proof, never of "now":
#   pin_fri_domain  the FRI sub-proof's (N, offset) must equal the STARK's own (P0). Without it a FRI declared
#                   over 2N is a genuinely low-degree vector whose second half is free, and ANY trace verifies.
#   bind_statement  an exec epoch proof absorbs a digest of its public statement into the transcript before the
#                   trace roots (A1), so the query points depend on the io log / args / programs being claimed.
#                   This changes the proof FORMAT: prover and verifier must flip at the same block.
# WHY A CONTEXT VARIABLE AND NOT A PARAMETER. stark.verify is reached through a dozen wrappers (vm_circuit,
# settlement_sparse, exec_state_bind, state_transition, merkle_update, recursive_verify, io_replay, appnote,
# joinsplit2 ...) and a rule threaded by hand through every one of them is a rule that is missed in one of them.
# The three CONSENSUS entry points set it for everything beneath them: ops/transaction_ops (the L1 settle branch,
# and the out-of-process verifier it spawns), execnode._apply_block (the exec layer at cursor h) and the settler
# (which must PRODUCE the format the landing block will judge). Unset means STRICT: a path that forgets to set
# the rules refuses an old-format proof loudly rather than accepting a forged one silently.
import contextvars as _cv
from collections import namedtuple as _nt
from contextlib import contextmanager as _cm
#   in_block_selector  the exec AIR carries the P_IN column and the "outside a block => NOP" constraint (A2,
#                   PROOF_BLOCK_SELECTOR_HEIGHT). A format change on both sides, like bind_statement.
#   round2          REVIEW_R2_HEIGHT: the AIR identity (T, W, max_degree, constraint count, boundaries, and the
#                   periodic tables unless a statement digest already binds them) is absorbed before the roots
#                   (P3/Z8); a string `aux` is absorbed as digest lanes, never by byte sum (P2); every Merkle
#                   opening path is exactly log2(N) long (P4); a settle proof's pre_contracts keys are canonical (A4).
#   trace_ldt       PROOF_TRACE_LDT_HEIGHT (P1): the trace columns enter FRI with the composition, as the batch
#                   sum_c beta^(c+1) f_c(x) with beta drawn after the alphas; the verifier adds the same term at
#                   every query point. Defaults to False so a four-field Rules(...) written before the gate still
#                   constructs (it names the pre-gate format); RULES_STRICT carries it on.
#   zk_harden       ZK_HARDEN_HEIGHT (zk audit 2026-09-26): the exec AIR tags calls from 1 on the ARG bus, a settle
#                   proof's pre_contracts must be exactly the exporter's records, and the wide pool is depth 48.
#                   Defaults to False, so every Rules(...) written with six fields names the pre-gate format.
Rules = _nt("Rules", "pin_fri_domain bind_statement in_block_selector round2 trace_ldt full_query zk_harden",
            defaults=(False, False, False))
RULES_STRICT = Rules(True, True, True, True, True, True, True)    # every pin on: the default when nothing set them
RULES_PRE_HARDEN = Rules(True, True, True, True, True, True, False)   # from block 1 until ZK_HARDEN_HEIGHT
RULES_LEGACY = Rules(False, False, False, False, False, False)   # below every gate: what every node accepted before 2026-09-23
_RULES = _cv.ContextVar("nado_proof_rules", default=None)


def rules_for_height(height):
    """The verification rules in force for a proof carried by the block at `height` — pure, replayable.
    `None` (no height known) is STRICT: a caller that cannot say which block it is judging gets the new rules,
    which reject an honest old-format proof visibly instead of accepting a forged one invisibly.

    EVERY PIN IS ON FROM HEIGHT 1. The six fields were gen-25 gates (PROOF_BIND_HEIGHT for the first two,
    PROOF_BLOCK_SELECTOR_HEIGHT, REVIEW_R2_HEIGHT, PROOF_TRACE_LDT_HEIGHT, PROOF_QUERY_FULL_HEIGHT), each 1 from gen
    26; the constants are deleted. The plumbing (Rules, rules_at, with_rules, the child-process hand-off) is KEPT:
    height 0 — genesis, applied by the exec node from cursor -1 — was below every gate and still gets RULES_LEGACY,
    and the prover/verifier branches on each field are exercised by the tests that construct Rules explicitly."""
    if height is None:
        return RULES_STRICT
    from protocol import ZK_HARDEN_HEIGHT
    if int(height) >= ZK_HARDEN_HEIGHT:
        return RULES_STRICT
    if int(height) >= 1:
        return RULES_PRE_HARDEN
    return RULES_LEGACY


def current_rules():
    r = _RULES.get()
    return RULES_STRICT if r is None else r


@_cm
def with_rules(rules):
    """`with stark.with_rules(Rules(...)):` — explicit rules, for a child process handed them over a pipe."""
    tok = _RULES.set(Rules(*rules))
    try:
        yield
    finally:
        _RULES.reset(tok)


@_cm
def rules_at(height):
    """`with stark.rules_at(h):` — every prove/verify inside judges (or produces) under the rules for block h.
    Contexts are per thread: a worker thread or a child process must enter its own (see the three sites)."""
    with with_rules(rules_for_height(height)):
        yield


def trace_batch_beta(t, rules, ext):
    """P1 (PROOF_TRACE_LDT_HEIGHT): the trace low-degree batch challenge, drawn from the transcript right AFTER
    the constraint alphas — one draw, the columns take its powers. None below the gate. Every prover
    (stark.prove, stark_native.prove, the wallet's stark.js) and every verifier draws it at this position."""
    if not rules.trace_ldt:
        return None
    return t.challenge_ext() if ext else t.challenge()


def query_pos(idx, N, rules):
    """Where a FRI query opens the trace. LEGACY: idx mod N/2, the lower half only — and the composition claim was
    compared against FRI layer 0 ONLY there. FRI tests degree < N/2 with fri_blowup = 2, and N/2 points always
    interpolate a polynomial of that degree, so a prover could run an honest FRI on the interpolant of the TRUE
    composition's lower half and every spot-check passed: any statement verified (review 2026-09-24, reproduced
    under every rule then live). From PROOF_QUERY_FULL_HEIGHT the trace is opened at idx itself, uniform over the
    whole domain, and compared with whichever of FRI's (lo, hi) pair idx is (fri_claim)."""
    # mod N under the new rule: an honest FRI index is already < N (the verifier pins FRI's N to the STARK's), so this
    # only keeps a malformed or forged index from indexing past the LDE in a prover or a test harness.
    return int(idx) % N if rules.full_query else int(idx) % (N // 2)


def fri_claim(step0, pos, N, rules):
    """The FRI layer-0 value at `pos`: the lower element of the pair below N/2, the upper one above it."""
    if rules.full_query and pos >= N // 2:
        return step0["hi"]
    return step0["lo"]


def trace_batch_shift(deg_bound, T, rules):
    """The exponent every trace column is shifted by inside the P1 batch. LEGACY 0: a column then only had to have
    degree < deg_bound (= next_pow2(md)*T), and for max_degree >= 3 a column of degree N/4 could make a degree-4
    constraint vanish on the whole LDE coset while the trace it denotes violates it (review 2026-09-24,
    reproduced). From PROOF_QUERY_FULL_HEIGHT each column enters as x^(deg_bound-T) * f(x), which FRI's bound
    deg < deg_bound forces to deg f < T — the degree the ALI argument assumes."""
    return (int(deg_bound) - int(T)) if rules.full_query else 0


def trace_batch_add(cp, col_lde, W, N, beta, ext, shift=0):
    """cp[j] += sum_{c < W} beta^(c+1) * col_lde[c][j], in place — the prover's half of P1. Bit-identical to
    native/starkprove sp_batch_add. Under extension alphas cp and beta are extension-valued, the columns base."""
    # the sum is accumulated first and shifted ONCE: x^s is common to every column (bit-identical to sp_batch_add_shift)
    acc = [ext2.ZERO if ext else 0 for _ in range(N)]
    pw = beta
    for c in range(W):
        col = col_lde[c]
        if ext:
            for j in range(N):
                acc[j] = ext2.add(acc[j], ext2.scalar_mul(pw, col[j]))
            pw = ext2.mul(pw, beta)
        else:
            for j in range(N):
                acc[j] = F.add(acc[j], F.mul(pw, col[j]))
            pw = F.mul(pw, beta)
    xs = F.pw(OFF, shift) if shift else 1
    step = F.pw(F.primitive_root_of_unity(N), shift) if shift else 1
    for j in range(N):
        if ext:
            cp[j] = ext2.add(cp[j], _ext_scale(acc[j], xs))
        else:
            cp[j] = F.add(cp[j], F.mul(xs, acc[j]))
        xs = F.mul(xs, step)


def _ext_scale(e, k):
    """An extension element times a base scalar, limb by limb."""
    return tuple(F.mul(int(v) % F.P, k) for v in ext2.lift(e))


def trace_batch_point(row, beta, ext, x=None, shift=0):
    """x^shift * sum_c beta^(c+1) * row[c] — the verifier's half of P1 at one opened row (every main and aux
    column); `shift` is trace_batch_shift, 0 below PROOF_QUERY_FULL_HEIGHT."""
    acc = ext2.ZERO if ext else 0
    pw = beta
    for v in row:
        if ext:
            acc = ext2.add(acc, ext2.scalar_mul(pw, int(v) % F.P)); pw = ext2.mul(pw, beta)
        else:
            acc = F.add(acc, F.mul(pw, int(v) % F.P)); pw = F.mul(pw, beta)
    if shift:
        k = F.pw(int(x) % F.P, shift)
        acc = _ext_scale(acc, k) if ext else F.mul(acc, k)
    return acc


def statement_lanes(statement):
    """A 32-byte statement digest as 8 little-endian u32 lanes — exact under both transcript backends (the
    alghash2 backend hashes a STRING by its byte SUM, so a hex digest must never be absorbed as text)."""
    b = bytes(statement)
    if len(b) != 32:
        raise ValueError("statement digest must be 32 bytes")
    return tuple(int.from_bytes(b[i:i + 4], "little") for i in range(0, 32, 4))


def absorb_statement(t, statement):
    """The ONE place the statement enters a transcript: stark.prove, stark_native.prove, stark.verify and
    recursive_verify._fs all call this, right after `aux` and before any root, so they cannot drift apart."""
    if statement is not None:
        t.absorb("statement", *statement_lanes(statement))


def absorb_aux(t, aux, rules=None):
    """The `aux` hook (H-4: the unshield destination). LEGACY: `t.absorb("aux", str(aux))` — which the alghash2
    backend hashes by the string's BYTE SUM (review P2: ~2,400 classes; an attacker grinds an address with the
    victim's sum and swaps the exit). Under round2 a string is absorbed as the 8 u32 lanes of its blake2b, exact
    under every backend; ints/tuples are absorbed as field lanes. Mirrored by the wallet's stark.js prover."""
    if aux is None:
        return
    r = current_rules() if rules is None else rules
    if not r.round2:
        t.absorb("aux", str(aux))
        return
    if isinstance(aux, (bytes, str)):
        import hashlib
        d = hashlib.blake2b(aux if isinstance(aux, bytes) else str(aux).encode(), digest_size=32).digest()
        t.absorb("aux", *statement_lanes(d))
    else:
        t.absorb("aux", aux)


def air_digest(T, W_total, blowup, n_transitions, boundaries, periodic=None):
    """P3/Z8 (round2): the 32-byte identity of the AIR a proof claims to satisfy — geometry (T, the TOTAL trace
    width including aux columns, the LDE blowup — public and derived from max_degree, so the fold needs no
    extra input), constraint count, the boundary statement and (when given) the public periodic tables, in
    a fixed byte layout that the wallet's stark.js reproduces byte for byte (no JSON): every value a
    little-endian u64. A structured periodic column is expanded to its dense form first, so the
    representation never matters. `periodic=None` when a statement digest already binds the tables (the exec
    AIR), so the cost is not paid twice."""
    import hashlib
    from array import array
    h = hashlib.blake2b(b"nado-air-v1", digest_size=32)
    head = array("Q", [int(T), int(W_total), int(blowup), int(n_transitions), len(boundaries),
                       0 if periodic is None else len(periodic)])
    h.update(head.tobytes())
    for (row, col, val) in boundaries:
        h.update(array("Q", [int(row), int(col), int(val) % F.P]).tobytes())
    if periodic is not None:
        for pc in periodic:
            dense = _per_expand(pc, T)
            h.update(len(dense).to_bytes(8, "little"))
            try:
                h.update(array("Q", dense).tobytes())
            except (OverflowError, TypeError):
                h.update(array("Q", [int(v) % F.P for v in dense]).tobytes())
    return h.digest()


def absorb_air(t, digest):
    """round2: the AIR identity enters right after the statement and before every root — the same position in
    stark.prove, stark_native.prove, stark.verify, recursive_verify._fs and the wallet's stark.js."""
    if digest is not None:
        t.absorb("air", *statement_lanes(digest))

# H-7: a hard ceiling on the trace length a proof may claim. N (= blowup·T) is read from the proof and fed to
# F.domain(N) BEFORE any FRI/query check, so an unbounded N is an unauthenticated single-request OOM
# (N = 2^32 builds a ~34 GB list). Real shielded circuits use T ≈ 1024, so 2^17 is ~128× headroom and caps the
# LDE at ~2^21 elements — generous for legit proofs, fatal to the OOM.
MAX_TRACE_ROWS = 1 << 17
# EXT_ALPHAS: the constraint-combination alphas are drawn from GF(p^2) (Transcript.challenge_ext) rather than
# the base field. This term — not FRI — was the binding one: a base-field alpha caps the STARK at
# log2(q) - log2(nc) ~ 63 bits (and lower the more constraints an AIR has) however strong FRI's commit phase
# is. This now applies to EVERY backend including RECURSION — the in-circuit AIRs verify extension proofs as
# of the recursion port, so a folded proof is no longer the weak link it was at ~47 bits.
# Read by execnode/stark/soundness.py, which must never assume this rather than measure it.
EXT_ALPHAS = True


def ext_challenges_active(backend=None):
    """Whether a proof on `backend` draws its alphas AND its aux (LogUp) challenges from GF(p^2).

    ONE definition, called by prove, verify and every aux_spec AIR. It used to be an inline expression
    repeated at each site, which is precisely how a prover and a verifier drift into drawing different
    challenges from the same transcript and rejecting honest proofs. AIRs need it too, because the aux
    geometry itself depends on it: an extension-valued aux column is carried as a PAIR of base columns, so
    num_aux doubles under ext and the AIR must declare the width the prover will actually build.

    The RECURSION backend used to be excluded: its in-circuit verifiers did base-field arithmetic, so a proof
    destined to be FOLDED had to be produced base-field and carried the OLD ~47-bit commit bound while the
    ordinary path reached 109-112. That exclusion is GONE — fri_verify, rowcomp_verify and recursive_verify
    all carry extension arithmetic now (test_recursion_ext), so a folded proof is as strong as any other.

    The cost is speed, not soundness: the Rust arena multiplies by a base-field u64 alpha, so an ext proof
    composes in Python. Measured 2.8x on a real exec AIR (17.4s vs 6.2s). Porting native/starkprove's
    sp_fold to extension arithmetic recovers it and changes nothing about what is proven.

    `backend` is now unread — every backend answers the same. It stays in the signature ON PURPOSE: every
    caller asks this question ABOUT a backend, and the day a base-field one is reintroduced the answer
    becomes backend-dependent again without a single call site changing. tests/test_challenge_field_policy
    pins both halves of that (no weaker field exists today; the guard still refuses one if it returns)."""
    from execnode.stark import fri
    return bool(getattr(fri, "EXT_CHALLENGES", False))

MAX_COLUMNS = 8192   # verify-side sanity/DoS cap on trace width (a pure Python bound; the native prover has no
                     # column limit — it keeps LDE columns in a Rust arena). Raised in two steps:
                     #   256 -> 384: the recursion's ROW-MODE composition of a W-wide inner AIR is 18 + 2*W wide
                     #     (rowcomp_verify _CARRY + 2*W), so folding the exec AIR (W_TOTAL=131) needs a
                     #     280-column composition proof — 256 rejected it as "bad column count", silently
                     #     breaking the K→1 settlement fold once the exec AIR grew past ~119 columns.
                     #   384 -> 8192: a Keccak-f[1600] AIR (the shape the removed ML-DSA/SHAKE work needed) was the gating
                     #     primitive) is inherently WIDE and SHORT — 6080 boolean columns x 32 rows, because a
                     #     1600-bit GF(2) state plus its degree-splitting witnesses only fits across columns
                     #     while the 24 rounds run down the rows. Width is cheap here: the LDE is W x (blowup*T)
                     #     = 6080 x 128, well under the memory a tall trace costs.
                     # The cap bounds allocation, not soundness (geometry is still checked against max_degree and
                     # T), and it is transparent for every existing proof — it only ADDS validity for wide traces.


def _next_pow2(x):
    """Smallest power of two ≥ x."""
    p = 1
    while p < x:
        p <<= 1
    return p


def row_commit_default(backend):
    """THE one authority on "should this proof commit rows?". Callers pass row_commit=None meaning
    "match the backend" and resolve it here.

    This exists because the question was answered TWICE. settlement_sparse derived it from the backend and
    ran the KV settle half in row mode (~15 s/span); merkle_update never asked, so the RECORDS half took
    stark.prove's False default and paid W=29 separate Merkle trees per update — 146.5 s of a 184 s prove,
    79.6%, measured per arena call. Same arena, same backend, same AIR, an order of magnitude apart, and the
    only visible symptom was `records half DECLINED … exceeds SETTLE_RECORDS_MAX_UPDATES`. Two copies of one
    default is how that happens; one function is how it stops.

    row_commit REQUIRES the RECURSION backend (see the guard in prove/verify below), so this is exactly the
    backend test and nothing more."""
    return getattr(backend, "name", "") == "recursion"


def _blowup(max_degree):
    """LDE blowup for constraints of degree ≤ max_degree: 2·next_pow2(max_degree), so the composition
    (degree ≤ max_degree·T) still sits at Reed–Solomon rate 1/2 for FRI."""
    # LDE must leave FRI room: composition degree ≤ max_degree·T, and FRI needs blowup ≥ 2 over that bound.
    return 2 * _next_pow2(max_degree)


def _coset_evaluate(coeffs, N, offset):
    """Evaluate a coefficient polynomial on the size-N coset {offset·ω^i}: substitute x → offset·y (scale
    coeff j by offset^j), then NTT on the subgroup. Uses the native Rust path when built."""
    from execnode.stark import goldilocks_native as _gn
    if _gn.available() and N <= _gn.NMAX:
        return _gn.coset_evaluate(coeffs, N, offset)
    c = list(coeffs) + [0] * (N - len(coeffs))
    g = [0] * N
    s = 1                                    # incremental offset^j (not a fresh pw per point)
    for j in range(N):
        g[j] = F.mul(c[j], s)
        s = F.mul(s, offset)
    return F.evaluate(g)


def _per_expand(pc, T):
    """Materialize one public periodic column to its full length-T list. A plain length-T sequence passes
    through (legacy dense form). The STRUCTURED form {"period": p, "base": [p values], "sparse": [(row, val)]}
    means base[i % p] everywhere except the listed rows, which take their absolute value verbatim — the compact
    way to say "a fixed p-row pattern plus a few instance-specific rows". Proving with either form of the same
    column yields byte-identical proofs (this expansion IS the definition)."""
    if isinstance(pc, dict):
        p, base = pc.get("period", 1), pc.get("base", [0])
        if not isinstance(p, int) or p < 1 or (p & (p - 1)) or T % p or len(base) != p:
            raise ValueError("structured periodic: period must be a power of two dividing T, len(base)=period")
        full = [base[i % p] % F.P for i in range(T)]
        for (r, v) in pc.get("sparse", ()):
            if not isinstance(r, int) or r < 0 or r >= T:
                raise ValueError("structured periodic: sparse row out of range")
            full[r] = v % F.P
        return full
    if len(pc) != T:
        raise ValueError("dense periodic column must have length T")
    return list(pc)


# ---- cached periodic coset-LDEs -------------------------------------------------------------------------
#
# After 51cc4f43 removed the per-query Horner passes, building each dense periodic column's coset LDE became
# the dominant term in verification (measured live: lde-prep 15.6-38.3 s of a ~35-60 s query loop). It is
# also the most repetitive: merkle_update._periodic_batch derives 15 of its 16 columns from (T, D, K) alone
# — only DIRP depends on the positions — so a 32-update span (K = 9,9,9,5) rebuilds the SAME 15 columns for
# each of its three K=9 proofs, and rebuilds them again for every subsequent settle.
#
# THIS MATTERS MOST WHERE IT IS WORST. A node REPLAYING history hits one proof-carrying block after another;
# on 2026-08-07 a peer spent ~55 minutes on a single such block while this box took ~8. Every cache hit is a
# whole coset NTT it does not run.
#
# KEYED ON THE COLUMN'S BYTES, NEVER ON POSITION OR GEOMETRY. A cache keyed on (T, D, K), or on the column's
# index, would hand back the wrong polynomial the moment a caller's layout differed — and the verifier would
# then check a proof against values nobody derived from the statement. blake2b-128 over the packed column is
# cheap next to what it saves (5.2 ms vs ~159 ms) and binds the contents exactly, which is the same rule
# settle_verify_key follows for proof verdicts: bind the BYTES.
#
# Stored as array('Q'), not a list: field elements are < P < 2^64, so one LDE at N=524288 costs 4 MB instead
# of ~23 MB of PyLong objects. That is what makes caching affordable at all — the Horner form existed to
# avoid an O(N) allocation, and a 23 MB-per-column cache would have handed the memory straight back.
# EVICTION AND ADMISSION BOTH MATTER, and the first attempt got both wrong. A 32-update span touches ~34
# DISTINCT columns (15 shared per K=9 proof + a different DIRP each + a wholly separate K=5 set), so a
# 24-entry FIFO flushed the reusable ones before the next settle could use them — measured: 31 misses on a
# cold cache and 31 again on a warm one, i.e. the cache bought exactly nothing.
#
# Two fixes, together:
#   LRU, not FIFO      — reuse should protect an entry; insertion order should not.
#   ADMIT ON SECOND USE — DIRP is different for every proof, so caching it on FIRST sight evicts precisely
#                         the columns that DO repeat. Columns are only given a slot once they have proved
#                         they recur; one-shot columns cost 16 bytes of digest instead of 4 MB of LDE.
_PER_LDE_CACHE = OrderedDict()       # key -> array('Q'); LRU, ~128 MB at N=524288
_PER_LDE_CACHE_MAX = 32              # the ~30 recurring columns fit; the per-proof DIRPs never take a slot
_PER_LDE_SEEN = OrderedDict()        # key -> True, admission filter (digests only, no payload)
_PER_LDE_SEEN_MAX = 256


def _per_lde_key(col, N, T, offset):
    # The OFFSET IS PART OF THE KEY. The value is the column's LDE on the coset offset·<g>, so two callers
    # with different shifts must never share an entry: every current call site passes OFF, and a key that
    # omitted it was correct only by that coincidence — a future caller would silently get another coset.
    from array import array as _arr
    import hashlib as _hl
    return (N, T, int(offset) % F.P, _hl.blake2b(_arr("Q", col).tobytes(), digest_size=16).digest())


_PER_HINTED = set()                  # digests already reported, so the hint is once per column, not per query


def _periodic_period_hint(col):
    """Smallest POWER-OF-TWO period p < len(col) with col[i] == col[i % p], else None.

    AN AIR-AUTHORING CHECK, not a correctness one. A periodic column whose period is a power of two
    dividing T can be handed to the verifier in STRUCTURED form ({"period", "base", "sparse"}), which
    _per_evaluator evaluates in O(period + #sparse) — INDEPENDENT of T. Passed as a dense list instead, the
    same column costs an O(T) interpolation and a coset LDE, which is what made periodic evaluation 97.6%
    of this verifier's time before the LDE cache existed.

    This is how StarkWare's verifier avoids the cost entirely rather than caching it. Verified in
    cairo-lang's periodic_columns.cairo: eval_pedersen_x is a Horner loop over the PERIOD's coefficients,
    with "A periodic column of N values yields these values on the subgroup of size N. To simulate a
    periodic column with 2**k repetitions, one should evaluate at point**(2**k) instead." Their AIRs are
    designed so the period is a power of two; ours are not — merkle_update repeats on BR=55 and
    seg=257*55=14135, neither a power of two, which is precisely why its 16 columns are dense and needed a
    cache. That is a design lesson worth catching automatically rather than remembering.
    """
    n = len(col)
    p = 1
    while p < n:
        if n % p == 0 and all(col[i] == col[i % p] for i in range(p, n)):
            return p
        p <<= 1
    return None


def _per_lde_cached(col, N, T, offset):
    """The coset LDE of a dense periodic column, computed once per distinct RECURRING column.

    Returns (array('Q'), hit). Values are identical to `_coset_evaluate(...)` either way — this only decides
    whether the NTT runs again, never what it returns.
    """
    from array import array as _arr
    k = _per_lde_key(col, N, T, offset)
    hit = _PER_LDE_CACHE.get(k)
    if hit is not None:
        _PER_LDE_CACHE.move_to_end(k)                      # LRU: reuse protects the entry
        return hit, True
    if k not in _PER_HINTED:
        _PER_HINTED.add(k)
        if len(_PER_HINTED) > 512:
            _PER_HINTED.clear()                            # bounded; the hint may simply repeat later
        _p = _periodic_period_hint(col)
        if _p is not None and _p * 8 <= len(col):          # only worth saying when the win is large
            print(f"[stark] AIR HINT: a dense periodic column of length {len(col)} is actually "
                  f"{_p}-periodic (a power of two). Passing it as {{'period': {_p}, 'base': [...]}} lets "
                  f"the verifier evaluate it in O({_p}) instead of building an O(N={N}) coset LDE.",
                  flush=True)
    lde = _arr("Q", _coset_evaluate(F.interpolate(list(col)), N, offset))
    if k in _PER_LDE_SEEN:                                 # seen before -> it recurs -> earn a slot
        _PER_LDE_SEEN.pop(k, None)
        _PER_LDE_CACHE[k] = lde
        while len(_PER_LDE_CACHE) > _PER_LDE_CACHE_MAX:
            _PER_LDE_CACHE.popitem(last=False)             # drop the LEAST RECENTLY USED
    else:
        _PER_LDE_SEEN[k] = True
        while len(_PER_LDE_SEEN) > _PER_LDE_SEEN_MAX:
            _PER_LDE_SEEN.popitem(last=False)
    return lde, False


def _per_evaluator(pc, T, gT):
    """Return ev(x, xT) evaluating this public periodic column's degree<T interpolation at an arbitrary point x
    (xT = x^T precomputed by the caller). Dense form: one O(T) interpolation, then Horner — the legacy cost.
    STRUCTURED form: O(period + #sparse) per point, INDEPENDENT of T — the succinct-verifier path. Why it is the
    same polynomial: a p-periodic column's interpolation is h(x^(T/p)) where h interpolates the base over the
    size-p subgroup (g_p = g_T^(T/p) exactly, since both are GENERATOR^((P-1)/n)); overriding row r adds
    (v - base[r%p])·L_r(x) with the closed-form Lagrange basis L_r(x) = g^r·(x^T - 1)/(T·(x - g^r))."""
    if isinstance(pc, dict):
        p, base = pc.get("period", 1), pc.get("base", [0])
        if not isinstance(p, int) or p < 1 or (p & (p - 1)) or T % p or len(base) != p:
            raise ValueError("structured periodic: period must be a power of two dividing T, len(base)=period")
        h = F.interpolate([v % F.P for v in base])
        step = T // p
        invT = F.inv(T)
        over = {}
        for (r, v) in pc.get("sparse", ()):
            if not isinstance(r, int) or r < 0 or r >= T:
                raise ValueError("structured periodic: sparse row out of range")
            over[r] = v % F.P                    # later entries win, matching _per_expand's sequential writes
        ent = [(F.pw(gT, r), F.sub(v, base[r % p] % F.P)) for r, v in over.items()]

        # Only entries with a non-zero delta contribute; select them ONCE rather than re-testing per query.
        ent_nz = [(gr, dv) for (gr, dv) in ent if dv]

        def ev(x, xT):
            out = F.poly_eval(h, F.pw(x, step))
            zT = F.mul(F.sub(xT, 1), invT)
            # MONTGOMERY BATCH INVERSION: one modular exponentiation for the whole sparse-override row
            # instead of one per entry. Measured on the live 118.57 MiB settle proof this site alone made
            # 122,240 of 217,607 F.inv calls (1,280 evaluations x ~95 overrides); batching makes it 1,280.
            # A zero denominator (x == gr) still raises ZeroDivisionError out of batch_inverse exactly as
            # F.inv did, so a query landing on an override point fails verification as before.
            if ent_nz:
                invs = F.batch_inverse([F.sub(x, gr) for (gr, _) in ent_nz])
                for (gr, dv), idn in zip(ent_nz, invs):
                    out = F.add(out, F.mul(dv, F.mul(F.mul(gr, zT), idn)))
            return out
        return ev
    coeffs = F.interpolate(list(pc))
    return lambda x, xT: F.poly_eval(coeffs, x)


def _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
                 challenges=None, ext_alphas=False):
    """Evaluate the composition polynomial on the LDE coset: the α-random linear combination of every
    transition constraint divided by its vanishing polynomial (x^T - 1)/(x - last) — zero on every step but
    the wrap-around — plus every boundary column minus its pinned value divided by (x - point). Each quotient
    is a polynomial (hence the sum low-degree) IFF the corresponding constraint actually holds; any violation
    leaves a non-polynomial term that FRI's low-degree test rejects. `next row` on the LDE is index j+blowup
    (one trace step = blowup coset steps). With `challenges` (two-phase aux protocol) every constraint is
    called as con(cur, nxt, per, challenges)."""
    last = F.pw(gT, T - 1)
    # Transition vanishing is the same for every constraint: invZ[j] = (x-last)/(x^T - 1). One batch inversion
    # for the whole vector instead of an inv() per (constraint, point).
    inv_xTm1 = F.batch_inverse([F.sub(F.pw(x_lde[j], T), 1) for j in range(N)])
    invZ = [F.mul(F.sub(x_lde[j], last), inv_xTm1[j]) for j in range(N)]
    # per-boundary 1/(x - g^row) vectors (one batch inversion each) — shared by both the native and Python
    # paths. DEDUP by row: the denominator depends only on `row`, and the recursion AIRs carry MANY boundaries
    # at the SAME rows (a leaf frame pins ~6 lanes at one row; column roots repeat), so computing the size-N
    # batch inverse once per UNIQUE row instead of per boundary saves the bulk of the setup (bit-identical —
    # boundaries sharing a row map to the same vector).
    _den_by_row = {}
    for (row, _col, _val) in boundaries:
        if row not in _den_by_row:
            _den_by_row[row] = F.batch_inverse([F.sub(x_lde[j], F.pw(gT, row)) for j in range(N)])
    bnd_inv_dens = [_den_by_row[row] for (row, _col, _val) in boundaries]

    # NATIVE-FIELD PATH: trace the constraints into the shared IR (air_ir) and evaluate the whole composition in
    # Rust — bit-identical to the Python loop below (verified in tests), an order of magnitude faster on the
    # execution AIR. Falls back to Python if the lib is unbuilt or rejects the program (returns None).
    # The Rust arena multiplies by a BASE-field alpha, so it cannot carry GF(p^2) constraint alphas. When
    # they are in use the composition MUST run in Python (below); this is the cost of lifting the alphas term,
    # which was capping the whole STARK at 63 bits however strong FRI got.
    #
    # build_program is INSIDE this branch, not above it: it traces every constraint with symbolic _Sym cells
    # to lower it into the IR, and an extension-valued constraint (LogUp under GF(p^2) challenges) cannot be
    # traced that way — ext2 arithmetic on a _Sym raises TypeError. Tracing a program that is then discarded
    # was always waste; under ext it is also a crash.
    if not ext_alphas:
        from execnode.stark import air_ir
        prog = air_ir.build_program(transitions, W, len(per_lde), 0 if challenges is None else len(challenges))
        cp = air_ir.compose_native(prog, N, blowup, col_lde, per_lde, list(challenges or []), alphas, invZ,
                                   boundaries, bnd_inv_dens)
        if cp is not None:
            return cp

    # PYTHON FALLBACK (reference): the same arithmetic, per point.
    cur_rows = [[col_lde[c][j] for c in range(W)] for j in range(N)]
    nxt_rows = [[col_lde[c][(j + blowup) % N] for c in range(W)] for j in range(N)]
    per_rows = [[pc[j] for pc in per_lde] for j in range(N)]
    # With ext alphas the constraint VALUES stay base-field (they come from the base trace); only the alpha
    # multiply lifts, so each term is scalar_mul(ext_alpha, base_value) and cp becomes GF(p^2)-valued. FRI
    # carries that from layer 0 via its data-driven ext0.
    # A constraint returns a BASE value normally, but under GF(p^2) aux challenges the LogUp constraints are
    # EXTENSION-valued (the aux columns they read are ext, carried as base-column pairs). Accept both: lift a
    # base value, then quotient by the base invZ and scale by the ext alpha. For a base v this is exactly the
    # old scalar_mul(a, v*invZ), so nothing changes for AIRs that stay base-field.
    _add = ext2.add if ext_alphas else F.add
    if ext_alphas:
        def _combine(a, v, iz):
            return ext2.mul(a, ext2.scalar_mul(v if isinstance(v, tuple) else ext2.lift(v), iz))
    else:
        def _combine(a, v, iz):
            return F.mul(a, F.mul(v, iz))
    cp = [(ext2.ZERO if ext_alphas else 0)] * N
    ai = 0
    for con in transitions:
        a = alphas[ai]; ai += 1
        if challenges is None:
            for j in range(N):
                cp[j] = _add(cp[j], _combine(a, con(cur_rows[j], nxt_rows[j], per_rows[j]), invZ[j]))
        else:
            for j in range(N):
                cp[j] = _add(cp[j], _combine(a, con(cur_rows[j], nxt_rows[j], per_rows[j], challenges),
                                             invZ[j]))
    for bi, (row, col, val) in enumerate(boundaries):
        a = alphas[ai]; ai += 1
        inv_den = bnd_inv_dens[bi]
        for j in range(N):
            cp[j] = _add(cp[j], _combine(a, F.sub(col_lde[col][j], val), inv_den[j]))
    return cp


def _row_tree(col_lde_group, N):
    """Row-commitment tree: ONE recursion-Merkle tree whose leaf j = alghash2.rrow of LDE row j across the
    given column group. An in-circuit verifier authenticates a whole opened row with ONE path instead of one
    per column — the enabler for recursing wide (execution-AIR) traces."""
    from execnode.stark import alghash2 as _a2
    leaves = [_a2.rrow([col[j] for col in col_lde_group]) for j in range(N)]
    return merkle.commit_digests(leaves, _backend.RECURSION)


_NATIVE_FALLBACKS = set()


def _native_fallback(exc):
    """RAISE. The native prover failing is a fault, not a reason to compute the right answer slowly.

    THE DEFAULT IS INVERTED as of the Rust-only policy (doc/rust-only-proving.md). This used to warn once and
    fall through to the Python body, with NADO_STRICT_NATIVE as an opt-in to make it fatal. The comment at the
    call site records what that cost: it hid a real wiring bug for days — compose_ext flattened the alphas and
    not the challenges, int() raised on a tuple, the native path simply never ran, and two "native" timings
    were the Python path mislabelled. A fallback nobody can observe is indistinguishable from one that never
    fires, and it is how a fold quietly becomes a six-hour job.

    NADO_ALLOW_PYTHON_KERNELS is the one escape, and it is for BUILDS and for the differential tests that
    prove the native prover correct — not for running. Nothing in a node sets it."""
    msg = f"{type(exc).__name__}: {exc}"
    from execnode.stark.native_guard import allow_absent
    if not allow_absent():
        raise RuntimeError(
            f"the native prover failed and there is no Python fallback in production: {msg}. Since the "
            f"Rust-only policy the Python prove body is reachable only for the conformance tests "
            f"(NADO_ALLOW_PYTHON_KERNELS=1) and for the two geometries the arena does not implement (the BLAKE2B backend and commit_periodic), which are selected by the CALL, not by an env var. "
            f"Fix the native path or rebuild native/starkprove.") from exc
    if os.environ.get("NADO_STRICT_NATIVE"):
        raise RuntimeError(f"native prover unavailable and NADO_STRICT_NATIVE is set — {msg}") from exc
    if msg not in _NATIVE_FALLBACKS:
        _NATIVE_FALLBACKS.add(msg)
        sys.stderr.write(f"[stark] native prover fell back to Python: {msg}\n")


def zk_randomizer_add(cp, col_lde, W, N, T, x_lde, k, ext):
    """Z1: cp[j] += sum_{i<k} x_j^(i*T) * col_lde[W-k+i][j] — the RANDOMIZER polynomial R(x), a uniformly
    random polynomial of degree < k*T assembled from the k random columns at the END of the trace (each
    interpolates T uniform values, so each is a uniform polynomial of degree < T, and x^(iT) places it in its
    own coefficient block). Adding R to the FRI input makes that input uniformly random, so nothing FRI reveals
    (layer roots, fold openings, the final polynomial) depends on the witness. Committed BEFORE the challenges,
    like every column, so a prover cannot pick R against the alphas. k == next_pow2(max_degree) covers the whole
    degree range of the composition; the verifier adds the same term at every opened row."""
    for j in range(N):
        xT = F.pw(x_lde[j], T)
        pw = 1
        acc = 0
        for i in range(k):
            acc = F.add(acc, F.mul(pw, col_lde[W - k + i][j]))
            pw = F.mul(pw, xT)
        cp[j] = ext2.add(cp[j], ext2.lift(acc)) if ext else F.add(cp[j], acc)


def zk_randomizer_point(row, x, T, k, ext):
    """The verifier's half of zk_randomizer_add at one opened row (the last k cells are the randomizers)."""
    xT = F.pw(x, T)
    pw, acc = 1, 0
    for i in range(k):
        acc = F.add(acc, F.mul(pw, int(row[len(row) - k + i]) % F.P))
        pw = F.mul(pw, xT)
    return ext2.lift(acc) if ext else acc


def _zk_salts(N):
    import secrets as _sec
    return [_sec.token_hex(32) for _ in range(N)]


def prove(trace, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None,
          aux_spec=None, backend=None, row_commit=False, commit_periodic=None, statement=None, zk=None):
    """Prove `trace` satisfies the AIR (transitions + boundaries [+ public periodic columns]). Interpolates
    and Merkle-commits each column's LDE, draws the constraint-combination challenges α from the committed
    roots (Fiat–Shamir), FRI-proves the composition is low-degree, and opens the cur/next trace rows at every
    FRI query point so the verifier can recompute the composition there. `aux` binds an extra public input
    (e.g. an unshield withdraw address, H-4) into the transcript. Returns the proof dict.

    `aux_spec` enables the TWO-PHASE protocol that lookup/permutation arguments (LogUp — the memory-checking
    machinery the VM execution circuit needs) require: {"num_challenges": k, "num_aux": n, "build": fn}.
    Phase 1 commits the MAIN trace columns; only THEN are k challenges drawn from the transcript (so the
    prover cannot pick witness values that suit them); `build(trace, challenges)` returns n extra aux columns
    (running sums / helper inverses) which are committed in phase 2 before the constraint αs are drawn.
    With aux_spec, every transition constraint is called as con(cur, nxt, per, challenges) and cur/nxt span
    main+aux columns. Without aux_spec the transcript and proof are byte-identical to the one-phase protocol
    (live shielded-pool proofs are untouched).

    `row_commit=True` (RECURSION backend only) commits LDE ROWS instead of columns: ONE recursion-Merkle tree
    per phase (main / aux) whose leaf j = alghash2.rrow(row j). The transcript absorbs one root per phase and
    each FRI query opens whole rows with ONE path per tree — 2 (or 4, two-phase) paths per query instead of
    2W, which is what makes recursing a wide (W=106) trace feasible. A DIFFERENT proof format ("row_roots" /
    row openings), verified by the matching verify(row_commit=True); column-mode proofs are untouched.

    `zk=k` (Z1, the shielded pool): ZERO-KNOWLEDGE mode on the blake2b backend. The trace's LAST k columns are
    RANDOMIZERS (uniform values the circuit never constrains): their combination R(x) = sum x^(iT) r_i(x) is
    added to the FRI input so FRI reveals nothing about the witness; every column leaf is SALTED
    (backend.leaf_salted) so an unopened leaf hides its value; the openings carry the salts. The CIRCUIT
    supplies the rest of the property — at least 2·num_queries random rows past its real rows, with its
    constraints gated off there — because what an opened row shows is the column polynomial at that point,
    and only enough random rows make those evaluations independent of the secret. Verified with the same k."""
    # HOLISTIC NATIVE PROVER (native/starkprove): the whole pipeline (LDE -> Merkle -> composition -> FRI ->
    # openings) runs in a PERSISTENT Rust arena instead of materializing every LDE column as a Python int list,
    # which is the recursion/settlement memory wall. Per doc/rust-only-proving.md this is not a preference:
    # where the arena covers the geometry it is the ONLY production path, and a native failure RAISES.
    #
    # THE PYTHON BODY BELOW IS NOT A FALLBACK. It is the sole implementation for two geometries the arena does
    # not implement, and both are real:
    #   * BLAKE2B backend (= _backend.DEFAULT) — the arena's Merkle speaks only the alghash2 family (hmode 0
    #     rleaf/rnode, 1 hashn). The LIVE shielded pool proves here: joinsplit2.prove_transfer calls
    #     stark.prove with no backend, and execnode/shielded_field.py ships that proof in the bundle.
    #   * commit_periodic — committed periodic columns absorb their roots BEFORE the trace commitment, while
    #     the arena assigns periodic column ids AFTER the aux phase, so the transcript order and the arena's
    #     id layout disagree. Used by bound_epoch_o1 (succinct verify); no live caller today.
    # Porting either is a real piece of work, NOT a deletion. Until then they are reached deliberately, never
    # by silent degradation: every path the arena DOES cover raises instead of falling through.
    _b = backend or _backend.DEFAULT
    from execnode.stark import stark_native as _sn
    _arena_covers = getattr(_b, "name", "") in ("recursion", "alghash2") and not commit_periodic
    if _arena_covers:
        if ext_challenges_active(_b) and not _sn.ext_capable():
            # A .so built before the extension port would emit a BASE-field proof under ext challenges, which
            # verify rightly refuses ("unexpected FRI challenge field"). Silently taking the Python path here
            # is precisely the invisible degradation the Rust-only policy abolishes: correct answers, 84x
            # slower, nothing raised. Rebuild the crate.
            from execnode.stark.native_guard import NativeMissing
            raise NativeMissing(
                "native/starkprove predates the GF(p^n) port (no sp_compose_ext/sp_fold_ext) but the "
                "challenge field is an extension — rebuild the crate. There is no Python fallback for this "
                "geometry; see doc/rust-only-proving.md.")
        try:
            from execnode.stark import stark_native
            if stark_native.available():
                return stark_native.prove(trace, transitions, boundaries, periodic=periodic,
                                          max_degree=max_degree, num_queries=num_queries, aux=aux,
                                          aux_spec=aux_spec, row_commit=row_commit, backend=_b,
                                          statement=statement)
        except Exception as _e:
            _native_fallback(_e)                        # RAISES unless NADO_ALLOW_PYTHON_KERNELS
    # The arena did not cover this call (BLAKE2B backend or commit_periodic). Everything below is
    # PURE PYTHON proving, which on 2026-08-04 took 12+ minutes for one settle prove and starved L1
    # into a re-anchor. _arena_covers being False used to route AROUND _native_fallback and reach
    # here silently — the exact invisible degradation the Rust-only policy exists to abolish.
    from execnode.stark.native_guard import require_native_prover
    require_native_prover("stark.py:prove (backend=%s, commit_periodic=%s)"
                          % (getattr(_b, "name", "?"), bool(commit_periodic)))
    if zk is not None:
        if getattr(_b, "name", "") != "blake2b" or aux_spec is not None or row_commit or commit_periodic:
            raise ValueError("zk mode is column-mode, single-phase, blake2b only")
        if not isinstance(zk, int) or zk < _next_pow2(max_degree) or zk >= len(trace[0]):
            raise ValueError("zk needs at least next_pow2(max_degree) randomizer columns at the end of the trace")
    periodic = periodic or []
    commit_periodic = sorted(set(commit_periodic or []))  # periodic-column indices to COMMIT instead of publish
    if commit_periodic and (commit_periodic[0] < 0 or commit_periodic[-1] >= len(periodic)):
        raise ValueError("commit_periodic index out of range")
    if commit_periodic and row_commit:
        raise ValueError("commit_periodic is column-mode only (row_commit not yet supported)")
    T = len(trace); W = len(trace[0])
    blowup = _blowup(max_degree); N = blowup * T
    gT = F.primitive_root_of_unity(T)
    col_polys = [F.interpolate([trace[i][c] for i in range(T)]) for c in range(W)]
    col_lde = [_coset_evaluate(p, N, OFF) for p in col_polys]
    per_lde = [_coset_evaluate(F.interpolate(_per_expand(pc, T)), N, OFF) for pc in periodic]
    x_lde = F.domain(N, OFF)
    deg_bound = _next_pow2(max_degree) * T

    b = backend or _backend.DEFAULT
    if row_commit and getattr(b, "name", "") != "recursion":
        raise ValueError("row_commit requires the RECURSION backend")
    t = Transcript(DOMAIN_STARK, backend=b)
    _rules = current_rules()
    absorb_aux(t, aux, _rules)               # H-4 / P2: bind an extra public input (e.g. an unshield withdraw_addr)
    absorb_statement(t, statement)           # A1: the public statement digest, same position as every verifier
    if _rules.round2:                        # P3/Z8: the AIR identity (periodic too, unless the statement holds it)
        absorb_air(t, air_digest(T, W + (aux_spec["num_aux"] if aux_spec is not None else 0), blowup,
                                 len(transitions), boundaries, None if statement is not None else periodic))
    # COMMITTED periodic columns (succinct verify): commit the listed columns' LDE and absorb their roots here,
    # as a public-parameter position BEFORE the main trace commitment (so the FS challenges depend on them). The
    # verifier opens these at each query point (O(log N)) instead of an O(T) dense poly_eval — the caller binds
    # each per-root to the public statement (io_commitment / program root). Non-committed columns stay public.
    per_roots, per_mlayers = [], []
    for idx in commit_periodic:
        root, ml = merkle.commit(per_lde[idx], b)
        per_roots.append(root); per_mlayers.append(ml); t.absorb(root)
    col_roots, col_mlayers = [], []
    row_roots, row_layers = [], []
    salts = [_zk_salts(N) for _ in range(W)] if zk is not None else None
    if row_commit:
        root, ml = _row_tree(col_lde, N)
        row_roots.append(root); row_layers.append(ml); t.absorb(root)
    else:
        for c in range(W):
            root, ml = (merkle.commit_salted(col_lde[c], salts[c], b) if zk is not None
                        else merkle.commit(col_lde[c], b))
            col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
    # EXTENSION-FIELD FLAG, hoisted above the aux draw because the AUX challenges need it too (see below).
    # RECURSION-backend proofs stay base-field (the in-circuit AIRs cannot verify ext), same rule as the fold.
    _ext_a = ext_challenges_active(b)
    challenges = None
    if aux_spec is not None:                 # phase 2: challenges AFTER the main commitment, then aux columns
        # AUX (LogUp) CHALLENGES IN GF(p^2). A LogUp/permutation argument's soundness error is
        # (lookups + rows)/|challenge field|, so drawing beta/gamma from the BASE field capped every
        # aux_spec circuit — vm_circuit, logup_bind, the settlement path — at ~44 bits: below FRI's 112 and
        # the alphas' 126, i.e. the binding term for the whole system. Lifting them means the aux COLUMNS and
        # their constraints are extension-valued too; an AIR expresses that by returning each logical aux
        # column as a PAIR of base columns (c0, c1) meaning c0 + c1*X, and returning ext-valued constraints
        # (_composition accepts either). num_aux therefore counts the BASE columns, so it doubles.
        challenges = [(t.challenge_ext() if _ext_a else t.challenge())
                      for _ in range(aux_spec["num_challenges"])]
        aux_cols = aux_spec["build"](trace, challenges)
        if len(aux_cols) != aux_spec["num_aux"] or any(len(c) != T for c in aux_cols):
            raise ValueError("aux builder returned wrong geometry")
        aux_lde = [_coset_evaluate(F.interpolate([v % F.P for v in col]), N, OFF) for col in aux_cols]
        col_lde.extend(aux_lde)
        if row_commit:
            root, ml = _row_tree(aux_lde, N)
            row_roots.append(root); row_layers.append(ml); t.absorb(root)
        else:
            for lde in aux_lde:
                root, ml = merkle.commit(lde, b)
                col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
        W += aux_spec["num_aux"]
    # CONSTRAINT ALPHAS IN GF(p^2). These were the binding term: a base-field alpha caps the STARK at
    # log2(q) - log2(nc) ~ 63 bits (worse with more constraints) no matter how strong FRI's commit phase is.
    # (_ext_a is computed above, before the aux draw, because the aux challenges use the same rule.)
    alphas = [(t.challenge_ext() if _ext_a else t.challenge())
              for _ in range(len(transitions) + len(boundaries))]
    cp = _composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
                      challenges, ext_alphas=_ext_a)
    # P1 (PROOF_TRACE_LDT_HEIGHT): the trace columns ride into FRI with the composition. Drawn AFTER the alphas
    # (the verifier replays the same order), over every main and aux column (W is the total here).
    _beta = trace_batch_beta(t, _rules, _ext_a)
    if _beta is not None:
        trace_batch_add(cp, col_lde, W, N, _beta, _ext_a, shift=trace_batch_shift(deg_bound, T, _rules))
    if zk is not None:                       # Z1: the randomizer polynomial masks everything FRI shows
        zk_randomizer_add(cp, col_lde, W, N, T, x_lde, zk, _ext_a)

    fri_blowup = N // deg_bound
    # RECURSION-DESTINED PROOFS STAY BASE-FIELD (item 14 of the ext-challenge port). The in-circuit FRI
    # verifier AIRs (fri_verify.py) and the arena's sp_fold both do BASE-field arithmetic, so a GF(p^2) proof
    # is not foldable by them — they would have to check it under the base-field bound, which is precisely the
    # ~47-bit weakness this change exists to remove. So a proof built with the RECURSION backend (the marker
    # for "this will be folded") is EXPLICITLY produced base-field and its verifier is told to expect that,
    # rather than silently mixing the two. The recursion path therefore still carries the OLD ~47-bit commit
    # bound until fri_verify/sp_fold are ported to extension arithmetic; the ordinary (non-folded) path gets
    # the full ~111 bits. Making that split explicit is the point — an implicit one is how this was missed.
    fri_proof = fri.prove(cp, OFF, fri_blowup, num_queries, transcript=t, backend=b,
                          ext=ext_challenges_active(b))

    openings = []
    for q in fri_proof["queries"]:
        lo = query_pos(q["idx"], N, _rules)          # the whole domain from PROOF_QUERY_FULL_HEIGHT (query_pos)
        nxt = (lo + blowup) % N
        if row_commit:
            openings.append({"lo": lo,
                             "cur": [col_lde[c][lo] for c in range(W)],
                             "nxt": [col_lde[c][nxt] for c in range(W)],
                             "cur_paths": [merkle.open_at(ml, lo) for ml in row_layers],
                             "nxt_paths": [merkle.open_at(ml, nxt) for ml in row_layers]})
        else:
            cols = [{
                "cur": col_lde[c][lo], "cur_path": merkle.open_at(col_mlayers[c], lo),
                "nxt": col_lde[c][nxt], "nxt_path": merkle.open_at(col_mlayers[c], nxt),
            } for c in range(W)]
            if zk is not None:
                for c in range(W):
                    cols[c]["cur_salt"] = salts[c][lo]; cols[c]["nxt_salt"] = salts[c][nxt]
            op = {"lo": lo, "cols": cols}
            if commit_periodic:                          # open each committed periodic column at the query point
                op["per"] = [{"val": per_lde[idx][lo], "path": merkle.open_at(per_mlayers[k], lo)}
                             for k, idx in enumerate(commit_periodic)]
            openings.append(op)

    out = {"T": T, "W": W, "N": N, "blowup": blowup, "deg_bound": deg_bound,
           "boundaries": boundaries, "fri": fri_proof, "openings": openings}
    if row_commit:
        out["row_roots"] = row_roots
    else:
        out["col_roots"] = col_roots
    if commit_periodic:
        out["per_roots"] = per_roots
    return out


def verify(proof, transitions, boundaries, periodic=None, max_degree=2, num_queries=NUM_QUERIES, aux=None,
           aux_spec=None, backend=None, row_commit=False, commit_periodic=None, periodic_roots=None,
           statement=None, zk=None):
    """Verify a STARK proof. Returns (ok, reason). The AIR itself (transitions, boundaries, periodic,
    max_degree) comes from the CALLER, never from the proof; the proof only supplies commitments and openings.
    Order of checks: LDE geometry pinned to max_degree·T before any allocation (H-7); transcript replayed to
    re-derive the same α challenges; FRI verified with the protocol-fixed blowup=2 and query count (C-1); then
    at every query point the composition is recomputed from the Merkle-opened trace rows + the verifier's own
    periodic values and must equal the committed FRI layer-0 value — this spot-check is what binds the
    low-degree polynomial FRI accepted to the committed trace actually satisfying the constraints."""
    try:
        periodic = periodic or []
        commit_periodic = sorted(set(commit_periodic or []))
        committed_set = set(commit_periodic)
        if commit_periodic and (commit_periodic[0] < 0 or commit_periodic[-1] >= len(periodic)):
            return False, "commit_periodic index out of range"
        if commit_periodic and row_commit:
            return False, "commit_periodic is column-mode only"
        T, W, N, blowup = proof["T"], proof["W"], proof["N"], proof["blowup"]
        # H-7: validate the LDE geometry — which is fully determined by max_degree and T — BEFORE allocating
        # F.domain(N). Otherwise an oversized N (verbatim from the proof) OOMs the process ahead of every check.
        if not all(isinstance(v, int) for v in (T, W, N, blowup)):
            return False, "bad proof dimensions"
        if T < 1 or (T & (T - 1)) != 0 or T > MAX_TRACE_ROWS:
            return False, "bad trace length"
        if W < 1 or W > MAX_COLUMNS:
            return False, "bad column count"
        if blowup != _blowup(max_degree) or N != blowup * T:
            return False, "bad LDE geometry"
        gT = F.primitive_root_of_unity(T)
        wN = F.primitive_root_of_unity(N)        # query points computed as OFF·ω^lo — no O(N) domain allocation
        last = F.pw(gT, T - 1)
        # public periodic polynomials — but NOT for committed columns (those come from opened committed cells,
        # skipping the O(T) dense poly_eval). (structured {period,base,sparse} columns are O(period+entries)/query.)
        per_evals = [None if i in committed_set else _per_evaluator(pc, T, gT) for i, pc in enumerate(periodic)]
        # committed-periodic roots: caller-supplied public inputs (bound to the statement) take precedence; else
        # read from the proof (the caller is then responsible for binding proof["per_roots"] to the statement).
        per_roots = list(periodic_roots) if periodic_roots is not None else list(proof.get("per_roots", []))
        if len(per_roots) != len(commit_periodic):
            return False, "committed-periodic root count mismatch"

        b = backend or _backend.DEFAULT
        if row_commit and getattr(b, "name", "") != "recursion":
            return False, "row_commit requires the RECURSION backend"
        if zk is not None and (getattr(b, "name", "") != "blake2b" or aux_spec is not None or row_commit
                               or commit_periodic or not isinstance(zk, int) or zk < _next_pow2(max_degree) or zk >= W):
            return False, "zk mode: column-mode blake2b with at least next_pow2(max_degree) randomizer columns"
        n_aux = aux_spec["num_aux"] if aux_spec is not None else 0
        w_main = W - n_aux
        if aux_spec is not None and W <= n_aux:
            return False, "bad aux geometry"
        col_roots = row_roots = None
        if row_commit:
            row_roots = proof["row_roots"]
            if len(row_roots) != (2 if aux_spec is not None else 1):
                return False, "bad row-root count"
        else:
            col_roots = proof["col_roots"]
            if aux_spec is not None and len(col_roots) != W:
                return False, "bad aux geometry"
        t = Transcript(DOMAIN_STARK, backend=b)
        _rules = current_rules()
        absorb_aux(t, aux, _rules)           # H-4 / P2: same extra public input the prover bound (unshield addr)
        absorb_statement(t, statement)       # A1: a proof for statement S1 presented with S2 draws other challenges
        if _rules.round2:                    # P3/Z8: the AIR the VERIFIER holds is what enters, never the proof's
            absorb_air(t, air_digest(T, W, blowup, len(transitions), boundaries,      # W = proof["W"], the total
                                     None if statement is not None else periodic))
        for r in per_roots:                  # committed-periodic roots: same public-parameter position as prove
            t.absorb(r)
        challenges = None
        # Hoisted above the aux draw: the AUX challenges are drawn from GF(p^2) under the same rule as the
        # alphas, and prove() draws them in this order, so the flag has to exist before the replay.
        _ext_a = ext_challenges_active(b)
        if aux_spec is not None:
            # Two-phase replay: the aux geometry comes from the CALLER's protocol (aux_spec), never the proof.
            # Main roots are absorbed first, the k challenges drawn, THEN the aux roots — same order as prove,
            # so a prover that built aux columns before its main commitment gets different challenges and fails.
            for r in (row_roots[:1] if row_commit else col_roots[:w_main]):
                t.absorb(r)
            challenges = [(t.challenge_ext() if _ext_a else t.challenge())
                          for _ in range(aux_spec["num_challenges"])]
            for r in (row_roots[1:] if row_commit else col_roots[w_main:]):
                t.absorb(r)
        else:
            for r in (row_roots if row_commit else col_roots):
                t.absorb(r)
        alphas = [(t.challenge_ext() if _ext_a else t.challenge())
                  for _ in range(len(transitions) + len(boundaries))]
        _beta = trace_batch_beta(t, _rules, _ext_a)          # P1: same position as every prover
        deg_bound = N // 2                   # FRI's bound: fri_blowup is pinned to 2 below, so N = 2·deg_bound

        # fri_blowup is ALWAYS 2 for a STARK proof (N = 2·next_pow2(max_degree)·T, deg_bound = N/2), so pin it —
        # that forces the full FRI geometry and, with the fixed query count, closes the C-1 empty-proof bypass.
        # expected_ext is PINNED, not read from the proof: the verifier decides the challenge field.
        # P0 (2026-09-23): THE FRI DOMAIN IS THE STARK'S DOMAIN. Nothing below compared proof["fri"]["N"] and
        # ["offset"] with the STARK's N and OFF: fri.verify checked the sub-proof against its OWN declared
        # geometry, and the spot-check loop binds layer-0 values at idx mod (N/2) with the STARK's N. So a FRI
        # declared over 2N with the same offset proves "degree < N" for a length-2N vector whose first N entries
        # are v[j] = cp(x_{j mod N/2}) and whose second N entries are whatever makes the whole thing a degree < N
        # polynomial — and N free points ALWAYS interpolate. Every fold, opening, grind and final layer is then
        # honest for ANY trace, constraints violated or not. tests/test_proof_bind_gate.py builds exactly that
        # forgery and shows it verifying under the legacy rules. Pinned here AND inside fri.verify (expected_N /
        # expected_offset) so a caller that reaches fri.verify without this wrapper cannot lose the pin.
        if _rules.pin_fri_domain:
            _fN, _fO = proof["fri"].get("N"), proof["fri"].get("offset")
            if _fN != N or _fO != OFF:
                return False, f"FRI domain ({_fN}, {_fO}) is not the STARK's ({N}, {OFF})"
        ok, why = fri.verify(proof["fri"], transcript=t, num_queries=num_queries, expected_blowup=2, backend=b,
                             expected_ext=ext_challenges_active(b),
                             expected_N=(N if _rules.pin_fri_domain else None),
                             expected_offset=(OFF if _rules.pin_fri_domain else None))
        if not ok:
            return False, f"composition is not low-degree: {why}"

        # C-1: the trace/composition spot-checks live in the loop below; enforce that there is exactly one
        # opening per required FRI query, so an empty/short `openings` (or `queries`) can't skip them via zip().
        if len(proof["openings"]) != num_queries or len(proof["fri"]["queries"]) != num_queries:
            return False, "wrong opening/query count"
        # P4 (round2): every authentication path is exactly log2(N) long. A path of the wrong length cannot
        # reach an honest root, but pinning it removes the question rather than relying on the answer.
        if _rules.round2:
            _plen = N.bit_length() - 1
            for _op in proof["openings"]:
                _paths = ([p for c in (_op.get("cols") or []) for p in (c.get("cur_path"), c.get("nxt_path"))]
                          if not row_commit else list(_op.get("cur_paths") or []) + list(_op.get("nxt_paths") or []))
                _paths += [po.get("path") for po in (_op.get("per") or [])]
                if any(not isinstance(p, (list, tuple)) or len(p) != _plen for p in _paths):
                    return False, "opening path length is not log2(N)"

        # ONE CROSSING FOR EVERY AUTHENTICATION PATH IN THE PROOF.
        #
        # Column mode opens 2*W paths per query, so this loop used to call merkle.verify 2*W*num_queries
        # times, each of which walked the path in Python calling a NATIVE permute per level: measured ~3248
        # permutations per proof, every one its own ctypes crossing, and 82% of a 145.7 ms verify. The kernel
        # was never the problem (pure-Python permute 3167 us vs 54 us through ctypes). This is the same
        # Python-loop-around-a-native-kernel shape the prover port already removed from _permute_snapshots
        # (146x) and fri.prove, and doc/rust-only-proving.md says to move the LOOP, not the function.
        #
        # So: collect every (root, index, value, path) up front, verify them in a single native call, and let
        # the loop below read the answers. Order is preserved exactly, so the FIRST failure reported is the
        # same one the per-item loop would have reported. `None` (no native lib, a ragged batch, or a backend
        # the crate does not implement, e.g. blake2b) falls back to the per-item path.
        _batch_ok = None
        if not row_commit and getattr(b, "name", "") in ("recursion", "alghash2"):
            _pending = []
            for _q, _op in zip(proof["fri"]["queries"], proof["openings"]):
                _lo = query_pos(_q["idx"], N, _rules)
                _nxt = (_lo + blowup) % N
                _cols = _op.get("cols") or []
                if len(_cols) != W:
                    _pending = None
                    break
                for _c in range(W):
                    _col = _cols[_c]
                    _pending.append((col_roots[_c], _lo, _col["cur"], _col["cur_path"]))
                    _pending.append((col_roots[_c], _nxt, _col["nxt"], _col["nxt_path"]))
            if _pending:
                from execnode.stark import alghash2 as _a2b
                _batch_ok = _a2b.merkle_verify_paths(_pending, getattr(b, "name", ""))

        # ROW-COMMITMENT OPENINGS TAKE THE SAME ONE CROSSING. row_commit mode opens 2 paths per query per
        # trace tree starting from a PRECOMPUTED row digest (rrow), and merkle.verify_digest climbed those
        # in PYTHON — one ctypes crossing per level, exactly the shape the column batch above already
        # removed. Measured on the live 118.57 MiB settle proof this was the largest Python cost left in
        # verify: 57,600 alghash2.node calls, 4.35 s. The native routine now accepts the digest directly.
        _row_ok, _ri = None, 0
        if row_commit and getattr(b, "name", "") in ("recursion", "alghash2"):
            from execnode.stark import alghash2 as _a2r
            _rp = []
            for _q, _op in zip(proof["fri"]["queries"], proof["openings"]):
                _lo = query_pos(_q["idx"], N, _rules)
                _nxt = (_lo + blowup) % N
                _cur = [int(v) % F.P for v in _op["cur"]]
                _nxr = [int(v) % F.P for v in _op["nxt"]]
                if len(_cur) != W or len(_nxr) != W:
                    _rp = None
                    break                                  # the loop below reports the width error
                _groups = [(0, w_main, 0)] + ([(w_main, W, 1)] if aux_spec is not None else [])
                for (_s, _e, _ti) in _groups:
                    _rp.append((row_roots[_ti], _lo, _a2r.rrow(_cur[_s:_e]), _op["cur_paths"][_ti]))
                    _rp.append((row_roots[_ti], _nxt, _a2r.rrow(_nxr[_s:_e]), _op["nxt_paths"][_ti]))
            if _rp:
                _row_ok = _a2r.merkle_verify_paths(_rp, getattr(b, "name", ""), digest=True)
                if _row_ok is None:
                    # NO SILENT PYTHON WALK. Falling back here is what hid this cost in the first place; a
                    # missing export means the crate is stale, which must be fixed, not worked around.
                    raise _NativeMissing(
                        "alghash2 native merkle_verify_paths(digest) unavailable — the native crate is "
                        "stale. Rebuild with `cargo build --release` in native/alghash2.")

        # WHERE VERIFICATION ACTUALLY SPENDS ITS TIME. A records-bearing settle verifies in ~1267 s and the
        # submit budget had to be raised twice to cover it, so this is consensus work whose cost decides
        # whether a proof-carrying settle is validatable at all — and until now nobody knew which part of it
        # was expensive. The suspicion is the `per` line below: every UNCOMMITTED periodic column is
        # re-evaluated with a dense O(T) Horner pass PER QUERY, and at T=131072 one pass measured 17.3 ms,
        # against NUM_QUERIES=320 and 16 periodic columns in the batch merkle-update AIR — ~88 s per proof,
        # ~354 s over the four proofs a 32-update span carries. Measure it rather than act on that estimate;
        # six extrapolations from a single data point were wrong on 2026-08-07 alone.
        import time as _time
        _t_all = _time.time(); _t_per = 0.0; _t_con = 0.0; _n_per = 0
        # THE 97.6%. Measured live on one of the four proofs a 32-update records span carries:
        #     [stark-verify] T=131072 W=29 queries=320 periodic=16 committed=0 |
        #     query-loop 470.9s = periodic 459.7s (5120 dense evals) + constraints 1.1s + rest 10.1s
        # Every DENSE periodic column was re-evaluated by an O(T) Horner pass ONCE PER QUERY — 320 x 16
        # passes over 131072 coefficients, in pure Python, on the GIL. That single line was the entire
        # records verification cost, and the reason the submit budget was blown at 1200s and again at 1800s.
        #
        # The query point is a DOMAIN point — x = OFF·wN^lo, computed a few lines below — so the value of a
        # periodic column's degree<T interpolation at x is EXACTLY its coset-LDE evaluation at index lo.
        # That is already how the PROVER gets it (per_lde, line 388). One NTT per column replaces 320 Horner
        # passes and returns the SAME field element, so this is a pure speedup: no constraint is weakened,
        # nothing the verifier accepts changes, and a proof that verified before verifies identically.
        #
        # HARVEST AND DISCARD, one column at a time. Horner was chosen here deliberately — see the comment
        # at the wN assignment, "query points computed as OFF·ω^lo — no O(N) domain allocation" — so holding
        # all 16 LDEs of N = blowup·T = 524288 would buy the time back with ~300 MB. Only the ~320 values
        # actually queried are kept; each LDE is freed as soon as it has been sampled.
        _t_pre = _time.time()
        _los = [query_pos(q["idx"], N, _rules) for q in proof["fri"]["queries"]]
        _per_q = {}
        _lde_hits = 0
        for _i, _pc in enumerate(periodic):
            # committed cells arrive in the opening; STRUCTURED columns already evaluate in
            # O(period + #sparse) INDEPENDENT of T, so neither needs (or wants) an LDE.
            if _i in committed_set or isinstance(_pc, dict):
                continue
            _lde, _hit = _per_lde_cached(_per_expand(_pc, T), N, T, OFF)
            _lde_hits += 1 if _hit else 0
            _per_q[_i] = [_lde[_l] for _l in _los]
            del _lde                      # drop OUR reference; the cache keeps its own
        _t_pre = _time.time() - _t_pre
        _bi = 0
        for _qi, (q, op) in enumerate(zip(proof["fri"]["queries"], proof["openings"])):
            lo = query_pos(q["idx"], N, _rules)
            if lo != op["lo"]:
                return False, "opening index mismatch"
            nxt = (lo + blowup) % N
            cur_row, nxt_row = [], []
            if row_commit:
                from execnode.stark import alghash2 as _a2
                cur_row = [int(v) % F.P for v in op["cur"]]
                nxt_row = [int(v) % F.P for v in op["nxt"]]
                if len(cur_row) != W or len(nxt_row) != W:
                    return False, "bad row opening width"
                groups = [(0, w_main, 0)] + ([(w_main, W, 1)] if aux_spec is not None else [])
                for (s, e, ti) in groups:
                    if _row_ok is not None:
                        # answers from the single native crossing, in the order they were queued
                        if not _row_ok[_ri]:
                            return False, f"bad row opening (cur) tree {ti}"
                        if not _row_ok[_ri + 1]:
                            return False, f"bad row opening (nxt) tree {ti}"
                        _ri += 2
                    else:
                        # only reached for a backend the native crate does not implement (blake2b, tests)
                        if not merkle.verify_digest(row_roots[ti], lo, _a2.rrow(cur_row[s:e]),
                                                    op["cur_paths"][ti], b):
                            return False, f"bad row opening (cur) tree {ti}"
                        if not merkle.verify_digest(row_roots[ti], nxt, _a2.rrow(nxt_row[s:e]),
                                                    op["nxt_paths"][ti], b):
                            return False, f"bad row opening (nxt) tree {ti}"
            else:
                for c in range(W):
                    col = op["cols"][c]
                    if _batch_ok is not None:
                        if not _batch_ok[_bi]:
                            return False, f"bad trace opening (cur) col {c}"
                        if not _batch_ok[_bi + 1]:
                            return False, f"bad trace opening (nxt) col {c}"
                        _bi += 2
                    elif zk is not None:
                        # Z1: salted leaves — a proof without salts (the unsalted format) is refused outright
                        if not merkle.verify_salted(col_roots[c], lo, col["cur"], col.get("cur_salt"), col["cur_path"], b):
                            return False, f"bad salted trace opening (cur) col {c}"
                        if not merkle.verify_salted(col_roots[c], nxt, col["nxt"], col.get("nxt_salt"), col["nxt_path"], b):
                            return False, f"bad salted trace opening (nxt) col {c}"
                    else:
                        if not merkle.verify(col_roots[c], lo, col["cur"], col["cur_path"], b):
                            return False, f"bad trace opening (cur) col {c}"
                        if not merkle.verify(col_roots[c], nxt, col["nxt"], col["nxt_path"], b):
                            return False, f"bad trace opening (nxt) col {c}"
                    cur_row.append(col["cur"]); nxt_row.append(col["nxt"])
            x = F.mul(OFF, F.pw(wN, lo))
            xT = F.pw(x, T)
            opened = {}
            if commit_periodic:                                     # verify + collect the committed periodic cells
                perops = op.get("per", [])
                if len(perops) != len(commit_periodic):
                    return False, "wrong committed-periodic opening count"
                for k, idx in enumerate(commit_periodic):
                    po = perops[k]
                    if not merkle.verify(per_roots[k], lo, po["val"], po["path"], b):
                        return False, f"bad periodic opening col {idx}"
                    opened[idx] = int(po["val"]) % F.P
            # periodic row at x: opened committed cell where committed, else the verifier's O(T) dense eval
            _tp0 = _time.time()
            per = [opened[i] if i in committed_set
                   else (_per_q[i][_qi] if i in _per_q else per_evals[i](x, xT))
                   for i in range(len(periodic))]
            _t_per += _time.time() - _tp0
            _n_per += len(periodic) - len(committed_set) - len(_per_q)
            # Mirror the prover EXACTLY, including the base-or-ext constraint value: under GF(p^2) aux
            # challenges the LogUp constraints return extension elements (their aux columns are ext, carried
            # as base-column pairs), so lift a base value and combine in ext. See _composition._combine.
            _add = ext2.add if _ext_a else F.add
            if _ext_a:
                def _combine(a, v, iz):
                    return ext2.mul(a, ext2.scalar_mul(v if isinstance(v, tuple) else ext2.lift(v), iz))
            else:
                def _combine(a, v, iz):
                    return F.mul(a, F.mul(v, iz))
            cp = (ext2.ZERO if _ext_a else 0); ai = 0
            # ONE INVERSION PER QUERY, NOT TWO PER CONSTRAINT. The quotient factor is inv(z) for
            # z = (x^T - 1)/(x - last); z itself is never used, so computing z and then inverting it spent
            # two modular exponentiations to obtain what algebra gives directly:
            #     inv(z) = (x - last) * inv(x^T - 1)
            # and nothing in it depends on `con`, so it is loop-invariant and hoisted. Measured on the live
            # 118.57 MiB settle proof: 91,520 of 217,607 F.inv calls came from this one site (320 queries x
            # 2 x 143 transitions); this makes it 320. Verification is CONSENSUS work that L1 runs inside
            # block validation, so its cost is what decides whether a proof-carrying settle can be validated
            # inside the block cadence at all.
            _xl = F.sub(x, last)
            if _xl == 0:
                # x is an LDE COSET point and `last` is a trace-domain point, so they can never coincide —
                # that separation is why the coset offset exists. Assert it rather than assume it: the old
                # form raised ZeroDivisionError here, and the rewritten one would instead yield iz = 0 and
                # silently contribute NOTHING for every transition constraint, i.e. a violated constraint
                # would verify. A faster verifier must not be a weaker one.
                return False, "query point coincides with the trace domain (x == last)"
            iz = F.mul(_xl, F.inv(F.sub(xT, 1)))
            _tc0 = _time.time()
            for con in transitions:
                a = alphas[ai]; ai += 1
                cval = con(cur_row, nxt_row, per) if challenges is None else con(cur_row, nxt_row, per, challenges)
                cp = _add(cp, _combine(a, cval, iz))
            _t_con += _time.time() - _tc0
            for (row, col, val) in boundaries:
                a = alphas[ai]; ai += 1
                pt = F.pw(gT, row)
                cp = _add(cp, _combine(a, F.sub(cur_row[col], val), F.inv(F.sub(x, pt))))
            if _beta is not None:
                # P1: the opened row's own batch term. A column that is not low-degree cannot survive FRI
                # once it is inside the polynomial FRI tests, whatever the composition looks like pointwise.
                cp = _add(cp, trace_batch_point(cur_row, _beta, _ext_a, x=x,
                                                shift=trace_batch_shift(deg_bound, T, _rules)))
            if zk is not None:
                cp = _add(cp, zk_randomizer_point(cur_row, x, T, zk, _ext_a))     # Z1: the randomizer polynomial
            _claim = fri_claim(q["steps"][0], lo, N, _rules)     # the half the query really lands in
            if cp != (ext2.lift(_claim) if _ext_a else _claim):
                return False, "trace/composition mismatch (a constraint is violated)"
        _el = _time.time() - _t_all
        if _el > 5.0:                       # only the proofs whose cost is consensus-relevant, never test noise
            print(f"[stark-verify] T={T} W={W} queries={len(proof['openings'])} "
                  f"periodic={len(periodic)} committed={len(committed_set)} "
                  f"lde={len(_per_q)} (cached {_lde_hits}) | "
                  f"query-loop {_el:.1f}s = lde-prep {_t_pre:.1f}s + periodic {_t_per:.1f}s "
                  f"({_n_per} dense evals) + constraints {_t_con:.1f}s + "
                  f"rest {_el - _t_pre - _t_per - _t_con:.1f}s", flush=True)
        return True, "ok"
    except _NODE_LOCAL_ERRORS:              # memory or a missing/stale kernel: not a verdict
        # S5 (2026-09-23): a RESOURCE failure is not a verdict. Converting it to (False, ...) let one node memoise
        # an out-of-memory as a cryptographic refutation that its peers, with more RAM, never saw — a fork on the
        # resource axis. It propagates; the settle branch never caches an exception (see ops/proof_child too).
        raise
    except Exception as e:
        # SAY WHERE. This returned only the exception's text, which for a TypeError deep in the verifier
        # ("int() argument must be ... not 'list'") names neither the file, the line, nor the value — and a
        # settle proof is ~118 MiB of nested structure, so "somewhere in there" is not a starting point.
        # Observed live 2026-08-04: the first settle proof ever to REACH verification (every earlier one was
        # refused for size before the verifier ran) failed with exactly that text and nothing else.
        import traceback as _tb
        _f = _tb.extract_tb(e.__traceback__)[-1]
        return False, (f"malformed proof: {type(e).__name__}: {e} "
                       f"[{_f.filename.rsplit('/', 1)[-1]}:{_f.lineno} in {_f.name}: {_f.line}]")
