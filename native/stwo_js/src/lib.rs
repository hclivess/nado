//! NADO's Stwo join-split (doc/stwo-migration.md section 5.1): the NODE-SIDE VERIFIER, plus the prover behind the
//! `prover` cargo feature.
//!
//! The statement, the AIR, the zero-knowledge construction, the transcript and the proof format are the ones of the
//! phase-0 ZK prototype `stwo_zk` (with both fixes of its zkproof/ARGUMENT.md section 9: the ROUND carries gated by
//! `s_real` (L0) and the second FRI mask RND2 at 2w (L4)), moved here without change: this file holds the code the
//! verifier needs (the AIR evaluators, the public-input sum, the transcript and `verify_js`), `prover.rs` the rest.
//!
//! WHY TWO HALVES. Stwo's prover needs nightly Rust (`portable_simd`); its verifier does not. A fleet node builds this
//! crate with whatever stable `cargo` it has, so the default build must pull NO `prover` feature anywhere in the
//! dependency graph (stwo with `default-features = false, features = ["std"]`, stwo-constraint-framework with
//! `default-features = false`). The `prover` feature (nightly) exists for the wallet's WASM prover and for the tests.
//! tests/test_stwo_js_verifier_builds_on_stable_without_the_prover.py pins that the default build stays prover-free.
//!
//! The ZK construction, in one place (see the prototype's RESULTS.md "ZK" section and zkproof/ARGUMENT.md):
//!
//!  (1) RANDOM ROWS. Every component (JS, ROUND, XOR) has R real rows at coset rows [0, R), one BLIND row at R, and
//!      uniformly random M31 rows after it, at least 3Q + 8 of them (Q = n_queries), so that every column polynomial
//!      has more free degrees of freedom than the verifier sees evaluations of it (Q openings at the lifted query
//!      point + Q x (offsets) evaluations hidden inside each opened composition value + 4 x (offsets) for the OODS
//!      samples, which are QM31). Every constraint and every lookup that would reach a random row is gated off by a
//!      preprocessed selector, the ROUND add-with-carry checks included; the only ungated constraint is the fixed
//!      BLAKE2s IV in JS (a public constant column).
//!  (2) ZK LOGUP. The interaction trace is our own: one QM31 column S_j per lookup entry (S_j * d_j = m_j, gated to the
//!      accumulated rows) and one running-sum column D (chained over rows [0, R], D = 0 at the last row, D = claimed at
//!      the blind row), so S_j and D are FREE on random rows.
//!  (3) BLINDED CLAIMED SUMS. The blind rows carry a chain of random QM31 tuples under their own tag (JS emits t1,
//!      ROUND consumes t1 and emits t2, XOR consumes t2), so each published claimed sum gets an independent uniform
//!      1/(z - t) term and only their total (fixed by the public inputs) is meaningful.
//!  (4) UNSPLIT COMPOSITION, committed whole (4 coordinate columns of size 2N) and sampled at pi(w) for the OODS point w.
//!  (5) FRI MASK. Two uniformly random QM31 columns of the composition size, RND sampled at w and RND2 at 2w.
//!  (6) HIDING MERKLE LEAVES. 8 unsampled random columns at the full lifted size in each committed tree.
//!
//! The C ABI (`nado_stwo_js_verify`, `nado_stwo_js_aux`, `nado_stwo_js_abi_version`) is at the end of this file and is
//! bound by execnode/stark/stwo_js_native.py.

#![allow(clippy::too_many_arguments)]

use itertools::{Itertools, chain};
use num_traits::{One, Zero};
use stwo::core::air::{Component, Components};
use stwo::core::channel::{Blake2sChannel, Channel};
use stwo::core::circle::CirclePoint;
use stwo::core::fields::FieldExpOps;
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::{SECURE_EXTENSION_DEGREE, SecureField};
use stwo::core::fri::FriConfig;
use stwo::core::pcs::{CommitmentSchemeVerifier, PcsConfig};
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::{Blake2sMerkleChannel, Blake2sMerkleHasher};
use stwo::core::verifier::VerificationError;
use stwo_constraint_framework::preprocessed_columns::PreProcessedColumnId;
use stwo_constraint_framework::{
    EvalAtRow, FrameworkComponent, FrameworkEval, INTERACTION_TRACE_IDX, InfoEvaluator, ORIGINAL_TRACE_IDX, Relation,
    RelationEntry, TraceLocationAllocator, relation,
};

#[cfg(feature = "prover")]
mod prover;
#[cfg(feature = "prover")]
pub use prover::*;

pub mod wire;

// ------------------------------------------------------------------------------------------------ parameters

// ------------------------------------------------------------------------------------------------ parameters

pub const D: usize = 48; // the live wide pool depth (ZK_HARDEN_HEIGHT onward)
pub const N_ROUNDS: usize = 10;
/// real rows per component
pub const R_JS: usize = 5 + D; // owner, cm_in, D levels, nf, out1, out2
pub const R_ROUND: usize = R_JS * N_ROUNDS;
pub const R_XOR: usize = 256 + 64 + 4; // (w, a, b) for w = 4, 3, 1
pub const N_SALT: usize = 8; // unsampled random columns per tree: 8 x 31 = 248 bits per leaf
pub const N_RND: usize = SECURE_EXTENSION_DEGREE; // FRI mask: one QM31 column
/// Second FRI mask column, sampled at pi(w) = 2w (0 = absent).
// ZK INVARIANT (zkproof/ARGUMENT.md L4, found by zkcheck 2026-10-11): the FRI input F = F0 + T(RND) is masked only
// along the directions T can reach: with RND sampled at w alone those are H_w (one QM31 direction short of L_{N-2})
// minus the Galois conjugates sigma(w), sigma^3(w) at which the revealed RND(w) pins RND: 3 QM31 directions of F0
// stayed unmasked. A second mask sampled at a different point (2w) covers them; zkcheck verifies the span.
pub const N_RND2: usize = SECURE_EXTENSION_DEGREE;

const TAG_ROUND: u32 = 1;
const TAG_XOR: u32 = 2;
const TAG_PUB: u32 = 3;
const TAG_BLIND: u32 = 4;
const DOM_OWNER: u32 = 21;
const DOM_CM: u32 = 22;
const DOM_NF: u32 = 23;

relation!(Rel, 97);

/// Random rows needed after the blind row, per component: the verifier sees, per column, Q lifted openings,
/// Q x |offsets| evaluations inside the opened composition values and 4 x |offsets| M31 coordinates of the OODS
/// samples; the widest columns (the running sum D, digest and register columns) have 2 offsets: 3Q + 8.
pub fn random_rows_needed(n_queries: usize) -> usize {
    3 * n_queries + 8
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Sizes {
    pub log_js: u32,
    pub log_round: u32,
    pub log_xor: u32,
}
impl Sizes {
    pub fn new(n_queries: usize) -> Self {
        let k = random_rows_needed(n_queries);
        // rows: R real + 1 blind + k free random + 1 last (D = 0)
        let lg = |r: usize| ((r + 2 + k).next_power_of_two().ilog2()).max(4);
        Sizes { log_js: lg(R_JS), log_round: lg(R_ROUND), log_xor: lg(R_XOR).max(9) }
    }
    pub fn log_max(&self) -> u32 {
        self.log_js.max(self.log_round).max(self.log_xor)
    }
    /// The composition polynomial's log size (constraints have degree <= 3): committed unsplit.
    pub fn log_comp(&self) -> u32 {
        self.log_max() + 1
    }
}

pub const IV: [u32; 8] =
    [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19];
pub const SIGMA: [[usize; 16]; 10] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];
const G_IDX: [[usize; 4]; 8] = [
    [0, 4, 8, 12],
    [1, 5, 9, 13],
    [2, 6, 10, 14],
    [3, 7, 11, 15],
    [0, 5, 10, 15],
    [1, 6, 11, 12],
    [2, 7, 8, 13],
    [3, 4, 9, 14],
];
const NIB: &[u32] = &[4, 4, 4, 4];

const fn widths(r: u32) -> &'static [u32] {
    match r {
        16 | 12 | 8 => &[4, 4, 4, 4],
        7 => &[4, 3, 4, 4, 1],
        _ => panic!("rotation"),
    }
}

pub fn h0() -> [u32; 8] {
    let mut h = IV;
    h[0] ^= 0x0101_0020;
    h
}
pub fn v_init() -> [u32; 16] {
    let h = h0();
    [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], IV[0], IV[1], IV[2], IV[3], IV[4] ^ 64, IV[5], !IV[6], IV[7]]
}

// ------------------------------------------------------------------------------------------------ scalar BLAKE2s

fn g_scalar(v: &mut [u32; 16], [a, b, c, d]: [usize; 4], x: u32, y: u32) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(12);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(8);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(7);
}
fn round_scalar(v: &mut [u32; 16], m: &[u32; 16], r: usize) {
    for (k, idx) in G_IDX.iter().enumerate() {
        g_scalar(v, *idx, m[SIGMA[r][2 * k]], m[SIGMA[r][2 * k + 1]]);
    }
}
pub fn compress(m: &[u32; 16]) -> ([[u32; 16]; 11], [u32; 8]) {
    let mut st = [[0u32; 16]; 11];
    let mut v = v_init();
    st[0] = v;
    for r in 0..N_ROUNDS {
        round_scalar(&mut v, m, r);
        st[r + 1] = v;
    }
    let h = h0();
    let d = std::array::from_fn(|i| h[i] ^ v[i] ^ v[i + 8]);
    (st, d)
}
pub fn hash(m: &[u32; 16]) -> [u32; 8] {
    compress(m).1
}
fn lo(x: u64) -> u32 {
    x as u32
}
fn hi(x: u64) -> u32 {
    (x >> 32) as u32
}

#[derive(Clone, Debug, PartialEq)]
pub struct Public {
    pub root: [u32; 8],
    pub nf: [u32; 8],
    pub cm1: [u32; 8],
    pub cm2: [u32; 8],
    pub pv: u64,
    pub fee: u64,
    pub aux: [u32; 8],
}
impl Public {
    fn mix_into(&self, ch: &mut impl Channel) {
        let words = chain![self.root, self.nf, self.cm1, self.cm2, [lo(self.pv), hi(self.pv), lo(self.fee), hi(self.fee)], self.aux]
            .collect_vec();
        ch.mix_u32s(&words);
        ch.mix_u64(D as u64);
    }
}

// ------------------------------------------------------------------------------------------------ constraint helpers

#[derive(Clone)]
struct Fu<F: Clone> {
    l: F,
    h: F,
}
impl<F: Clone> Fu<F> {
    fn limb(&self, i: usize) -> F {
        if i == 0 { self.l.clone() } else { self.h.clone() }
    }
    fn felts(&self) -> [F; 2] {
        [self.l.clone(), self.h.clone()]
    }
}
pub fn m31(x: u32) -> BaseField {
    BaseField::from_u32_unchecked(x)
}
fn cst<E: EvalAtRow>(x: u32) -> E::F {
    E::F::from(m31(x))
}
fn ef<E: EvalAtRow>(x: E::F) -> E::EF {
    E::EF::from(x)
}

/// Lookup entries of one row, collected in evaluation order and finalised by `finish_logup`.
struct Lk<E: EvalAtRow> {
    v: Vec<(E::EF, Vec<E::F>)>,
}
impl<E: EvalAtRow> Lk<E> {
    fn new() -> Self {
        Self { v: vec![] }
    }
    fn push(&mut self, m: E::EF, vals: Vec<E::F>) {
        self.v.push((m, vals));
    }
}

fn rd_u32<E: EvalAtRow>(e: &mut E) -> Fu<E::F> {
    let l = e.next_trace_mask();
    let h = e.next_trace_mask();
    Fu { l, h }
}
fn split<E: EvalAtRow>(e: &mut E, limb: E::F, w: &[u32]) -> Vec<E::F> {
    let mut out = vec![];
    let mut acc = limb;
    let mut off = 0;
    for wi in &w[..w.len() - 1] {
        let p = e.next_trace_mask();
        acc = acc - p.clone() * m31(1 << off);
        out.push(p);
        off += wi;
    }
    out.push(acc * m31(1 << off).inverse());
    out
}
fn xor_lk<E: EvalAtRow>(lk: &mut Lk<E>, m: &E::F, w: u32, a: E::F, b: E::F, c: E::F) {
    lk.push(ef::<E>(m.clone()), vec![cst::<E>(TAG_XOR), cst::<E>(w), a, b, c]);
}
const INV16: u32 = 1 << 15;
// ZK INVARIANT (zkproof/ARGUMENT.md L0, found by zkcheck 2026-10-11): every add-with-carry constraint is GATED by
// `sel` (= s_real). The first ZK version left them ungated and built random ROUND rows with valid carries in {0,1,2},
// so on EVERY row sum = a + b (+ c) - 2^16 carry: the opened/OODS values of the four columns then reveal evaluations
// of the carry polynomial, whose random-row part has only log2(3) bits per row against 31-bit evaluations, i.e. the
// real rows' carries were information-theoretically determined by the proof. With the gate, random rows are
// unconstrained and uniform in every cell. Never ungate a constraint unless it holds for uniform cells.
fn add2<E: EvalAtRow>(e: &mut E, sel: &E::F, a: Fu<E::F>, b: Fu<E::F>) -> Fu<E::F> {
    let sl = e.next_trace_mask();
    let sh = e.next_trace_mask();
    let cl = (a.l + b.l - sl.clone()) * m31(INV16);
    e.add_constraint(sel.clone() * (cl.clone() * cl.clone() - cl.clone()));
    let ch = (a.h + b.h + cl - sh.clone()) * m31(INV16);
    e.add_constraint(sel.clone() * (ch.clone() * ch.clone() - ch.clone()));
    Fu { l: sl, h: sh }
}
/// carry in {0, 1, 2} as cl - bl in {0, 1} with a committed bit bl: two degree-3 constraints after gating (the
/// ungated cubic cl (cl - 1) (cl - 2) would be degree 4 under the gate).
fn add3<E: EvalAtRow>(e: &mut E, sel: &E::F, a: Fu<E::F>, b: Fu<E::F>, c: Fu<E::F>) -> Fu<E::F> {
    let sl = e.next_trace_mask();
    let sh = e.next_trace_mask();
    let bl = e.next_trace_mask();
    let bh = e.next_trace_mask();
    let cl = (a.l + b.l + c.l - sl.clone()) * m31(INV16);
    e.add_constraint(sel.clone() * bl.clone() * (bl.clone() - E::F::one()));
    let dl = cl.clone() - bl;
    e.add_constraint(sel.clone() * dl.clone() * (dl - E::F::one()));
    let ch = (a.h + b.h + c.h + cl - sh.clone()) * m31(INV16);
    e.add_constraint(sel.clone() * bh.clone() * (bh.clone() - E::F::one()));
    let dh = ch - bh;
    e.add_constraint(sel.clone() * dh.clone() * (dh - E::F::one()));
    Fu { l: sl, h: sh }
}
fn recompose<E: EvalAtRow>(xs: &[E::F], w: &[u32], r: u32) -> (E::F, E::F) {
    let (mut lo_, mut hi_) = (E::F::zero(), E::F::zero());
    let mut off = 0;
    for (x, wi) in xs.iter().zip(w) {
        if off < r {
            lo_ = lo_ + x.clone() * m31(1 << off);
        } else {
            hi_ = hi_ + x.clone() * m31(1 << (off - r));
        }
        off += wi;
    }
    (lo_, hi_)
}
fn xor_rotr<E: EvalAtRow>(e: &mut E, lk: &mut Lk<E>, m: &E::F, a: Fu<E::F>, b: Fu<E::F>, r: u32) -> Fu<E::F> {
    let w = widths(r);
    let apl = split(e, a.l, w);
    let aph = split(e, a.h, w);
    let bpl = split(e, b.l, w);
    let bph = split(e, b.h, w);
    let mut xl = vec![];
    for i in 0..w.len() {
        let c = e.next_trace_mask();
        xor_lk(lk, m, w[i], apl[i].clone(), bpl[i].clone(), c.clone());
        xl.push(c);
    }
    let mut xh = vec![];
    for i in 0..w.len() {
        let c = e.next_trace_mask();
        xor_lk(lk, m, w[i], aph[i].clone(), bph[i].clone(), c.clone());
        xh.push(c);
    }
    let (ll, lh) = recompose::<E>(&xl, w, r);
    let (hl, hh) = recompose::<E>(&xh, w, r);
    let s = m31(1 << (16 - r));
    Fu { l: lh + hl * s, h: hh + ll * s }
}
fn g<E: EvalAtRow>(e: &mut E, lk: &mut Lk<E>, m: &E::F, v: &mut [Fu<E::F>; 16], [a, b, c, d]: [usize; 4], m0: Fu<E::F>, m1: Fu<E::F>) {
    v[a] = add3(e, m, v[a].clone(), v[b].clone(), m0);
    v[d] = xor_rotr(e, lk, m, v[a].clone(), v[d].clone(), 16);
    v[c] = add2(e, m, v[c].clone(), v[d].clone());
    v[b] = xor_rotr(e, lk, m, v[b].clone(), v[c].clone(), 12);
    v[a] = add3(e, m, v[a].clone(), v[b].clone(), m1);
    v[d] = xor_rotr(e, lk, m, v[a].clone(), v[d].clone(), 8);
    v[c] = add2(e, m, v[c].clone(), v[d].clone());
    v[b] = xor_rotr(e, lk, m, v[b].clone(), v[c].clone(), 7);
}
fn nibble_range<E: EvalAtRow>(e: &mut E, lk: &mut Lk<E>, m: &E::F, limb: E::F) {
    let n = split(e, limb, NIB);
    for (x, w) in n.into_iter().zip(NIB) {
        xor_lk(lk, m, *w, x.clone(), E::F::zero(), x);
    }
}
fn read4<E: EvalAtRow>(e: &mut E) -> Vec<E::F> {
    (0..4).map(|_| e.next_trace_mask()).collect()
}

/// ZK LogUp. `track`: the relation-tracker pass (trace generation) only records the entries. Otherwise: one QM31
/// column S_j per entry with (S_j * d_j - m_j) * s_acc = 0, and the running sum D chained over the accumulated rows
/// [0, R] (s_acc = s_real + s_blind), D = 0 on the last row, D = claimed on the blind row. Rows after the blind row
/// leave every S_j and D unconstrained, which is what lets them be uniformly random.
fn finish_logup<E: EvalAtRow>(
    mut e: E,
    rel: &Rel,
    lk: Lk<E>,
    track: bool,
    s_real: E::F,
    s_blind: E::F,
    s_last: E::F,
    claimed: SecureField,
) -> E {
    if track {
        for (m, v) in lk.v {
            e.add_to_relation(RelationEntry::new(rel, m, &v));
        }
        // a no-op for the relation tracker; keeps InfoEvaluator's built-in logup finalised when a tracking
        // component is constructed (its interaction allocation is never used)
        e.finalize_logup_in_pairs();
        return e;
    }
    let s_acc = s_real + s_blind.clone();
    let mut sum = E::EF::zero();
    for (m, v) in lk.v {
        let [s] = e.next_extension_interaction_mask(INTERACTION_TRACE_IDX, [0]);
        let d: E::EF = <Rel as Relation<E::F, E::EF>>::combine(rel, &v);
        e.add_constraint((s.clone() * d - m) * s_acc.clone());
        sum = sum + s;
    }
    let [dp, dc] = e.next_extension_interaction_mask(INTERACTION_TRACE_IDX, [-1, 0]);
    e.add_constraint((dc.clone() - dp - sum) * s_acc);
    e.add_constraint(dc.clone() * s_last);
    e.add_constraint((dc - E::EF::from(claimed)) * s_blind);
    e
}

// ------------------------------------------------------------------------------------------------ components

fn pid(name: &str) -> PreProcessedColumnId {
    PreProcessedColumnId { id: format!("zk_{name}") }
}
const JS_SEL: [&str; 12] =
    ["js_first", "js_cmin", "js_merk", "js_nf", "js_out1", "js_out2", "js_pubsel", "js_pubtag", "js_real", "js_blind", "js_last", "js_hold"];
const RD_SEL: [&str; 3] = ["rd_real", "rd_blind", "rd_last"];
const XS_SEL: [&str; 7] = ["xs_w", "xs_a", "xs_b", "xs_c", "xs_real", "xs_blind", "xs_last"];

fn preprocessed_ids() -> Vec<PreProcessedColumnId> {
    chain![JS_SEL.iter(), RD_SEL.iter(), XS_SEL.iter()].map(|s| pid(s)).collect()
}
fn preprocessed_log_sizes(sz: &Sizes) -> Vec<u32> {
    chain![[sz.log_js; 12], [sz.log_round; 3], [sz.log_xor; 7]].collect()
}

pub struct JsEval {
    pub log: u32,
    pub rel: Rel,
    pub claimed: SecureField,
    pub track: bool,
}
impl FrameworkEval for JsEval {
    fn log_size(&self) -> u32 {
        self.log
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        self.log + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let rel = &self.rel;
        let mut lk = Lk::<E>::new();
        let s: Vec<E::F> = JS_SEL.iter().map(|n| e.get_preprocessed_column(pid(n))).collect();
        let (s_first, s_cmin, s_merk, s_nf, s_out1, s_out2, s_pub, s_tag) =
            (s[0].clone(), s[1].clone(), s[2].clone(), s[3].clone(), s[4].clone(), s[5].clone(), s[6].clone(), s[7].clone());
        let (s_real, s_blind, s_last, s_hold) = (s[8].clone(), s[9].clone(), s[10].clone(), s[11].clone());

        let m: [Fu<E::F>; 16] = std::array::from_fn(|_| rd_u32(&mut e));
        let st: Vec<[Fu<E::F>; 16]> = (0..=N_ROUNDS).map(|_| std::array::from_fn(|_| rd_u32(&mut e))).collect();

        // the fixed BLAKE2s start state: ungated (a random row carries it too; it is a public constant)
        let vi = v_init();
        for j in 0..16 {
            e.add_constraint(st[0][j].l.clone() - cst::<E>(vi[j] & 0xffff));
            e.add_constraint(st[0][j].h.clone() - cst::<E>(vi[j] >> 16));
        }
        for r in 0..N_ROUNDS {
            let vals = chain![
                [cst::<E>(TAG_ROUND)],
                st[r].iter().flat_map(|x| x.felts()),
                st[r + 1].iter().flat_map(|x| x.felts()),
                SIGMA[r].iter().flat_map(|k| m[*k].felts())
            ]
            .collect_vec();
            lk.push(ef::<E>(s_real.clone()), vals);
        }
        let h = h0();
        let mut dcur: Vec<[E::F; 2]> = vec![];
        let mut dprev: Vec<[E::F; 2]> = vec![];
        for i in 0..8 {
            let mut cur2 = [E::F::zero(), E::F::zero()];
            let mut prev2 = [E::F::zero(), E::F::zero()];
            for limb in 0..2 {
                let an = split(&mut e, st[N_ROUNDS][i].limb(limb), NIB);
                let bn = split(&mut e, st[N_ROUNDS][i + 8].limb(limb), NIB);
                let mut xs = vec![];
                for k in 0..NIB.len() {
                    let c = e.next_trace_mask();
                    xor_lk(&mut lk, &s_real, NIB[k], an[k].clone(), bn[k].clone(), c.clone());
                    xs.push(c);
                }
                let hn = (h[i] >> (16 * limb)) & 0xffff;
                let pw = NIB[0];
                for k in 0..NIB.len() {
                    let [dp, dc] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0]);
                    xor_lk(&mut lk, &s_real, pw, xs[k].clone(), cst::<E>((hn >> (pw as usize * k)) & ((1 << pw) - 1)), dc.clone());
                    cur2[limb] = cur2[limb].clone() + dc * m31(1 << (pw as usize * k));
                    prev2[limb] = prev2[limb].clone() + dp * m31(1 << (pw as usize * k));
                }
            }
            dcur.push(cur2);
            dprev.push(prev2);
        }
        // witness registers: constant over the REAL rows only (s_hold), free on the random rows
        let reg = |e: &mut E, n: usize| -> Vec<E::F> {
            (0..n)
                .map(|_| {
                    let [c, nx] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [0, 1]);
                    e.add_constraint(s_hold.clone() * (nx - c.clone()));
                    c
                })
                .collect()
        };
        let nsk = reg(&mut e, 16);
        let rho = reg(&mut e, 4);
        let vin = reg(&mut e, 4);
        let v1 = reg(&mut e, 4);
        let v2 = reg(&mut e, 4);
        let pv = reg(&mut e, 4);
        let fee = reg(&mut e, 4);
        let sm = reg(&mut e, 4);
        let cs = reg(&mut e, 4);
        let cr = reg(&mut e, 4);
        let cb0 = reg(&mut e, 4);
        let cb1 = reg(&mut e, 4);
        let dir = e.next_trace_mask();
        for j in 0..16 {
            for limb in 0..2 {
                nibble_range(&mut e, &mut lk, &s_real, m[j].limb(limb));
            }
        }
        // registers are constant over the real rows, so their range checks are needed once (row 0)
        for x in chain![pv.iter(), fee.iter(), sm.iter()] {
            nibble_range(&mut e, &mut lk, &s_first, x.clone());
        }

        let word = |v: &[E::F], k: usize| Fu { l: v[2 * k].clone(), h: v[2 * k + 1].clone() };
        let dword = |d: &[[E::F; 2]], k: usize| Fu { l: d[k][0].clone(), h: d[k][1].clone() };
        let eq = |e: &mut E, sel: &E::F, a: &Fu<E::F>, b: &Fu<E::F>| {
            e.add_constraint(sel.clone() * (a.l.clone() - b.l.clone()));
            e.add_constraint(sel.clone() * (a.h.clone() - b.h.clone()));
        };
        let eqc = |e: &mut E, sel: &E::F, a: &Fu<E::F>, c: u32| {
            e.add_constraint(sel.clone() * (a.l.clone() - cst::<E>(c & 0xffff)));
            e.add_constraint(sel.clone() * (a.h.clone() - cst::<E>(c >> 16)));
        };
        eqc(&mut e, &s_first, &m[0], DOM_OWNER);
        for k in 0..8 {
            eq(&mut e, &s_first, &m[1 + k], &word(&nsk, k));
        }
        for j in 9..16 {
            eqc(&mut e, &s_first, &m[j], 0);
        }
        eqc(&mut e, &s_cmin, &m[0], DOM_CM);
        eq(&mut e, &s_cmin, &m[1], &word(&vin, 0));
        eq(&mut e, &s_cmin, &m[2], &word(&vin, 1));
        for k in 0..8 {
            eq(&mut e, &s_cmin, &m[3 + k], &dword(&dprev, k));
        }
        eq(&mut e, &s_cmin, &m[11], &word(&rho, 0));
        eq(&mut e, &s_cmin, &m[12], &word(&rho, 1));
        for j in 13..16 {
            eqc(&mut e, &s_cmin, &m[j], 0);
        }
        for k in 0..8 {
            for limb in 0..2 {
                let left = m[k].limb(limb);
                let right = m[8 + k].limb(limb);
                let p = dprev[k][limb].clone();
                e.add_constraint(s_merk.clone() * ((left.clone() - p) + dir.clone() * (right - left)));
            }
        }
        e.add_constraint(s_merk.clone() * dir.clone() * (dir.clone() - E::F::one()));
        eqc(&mut e, &s_nf, &m[0], DOM_NF);
        for k in 0..8 {
            eq(&mut e, &s_nf, &m[1 + k], &word(&nsk, k));
        }
        eq(&mut e, &s_nf, &m[9], &word(&rho, 0));
        eq(&mut e, &s_nf, &m[10], &word(&rho, 1));
        for j in 11..16 {
            eqc(&mut e, &s_nf, &m[j], 0);
        }
        for (sel, v) in [(&s_out1, &v1), (&s_out2, &v2)] {
            eqc(&mut e, sel, &m[0], DOM_CM);
            eq(&mut e, sel, &m[1], &word(v, 0));
            eq(&mut e, sel, &m[2], &word(v, 1));
            for j in 13..16 {
                eqc(&mut e, sel, &m[j], 0);
            }
        }
        // conservation over the integers, checked on row 0 (registers are constant over the real rows).
        // cr in {0..3} as cb0 + 2 cb1 (booleans) keeps every gated constraint at degree <= 3; cr = 3 cannot satisfy
        // the limb equation with 16-bit-range sums, so this is as strong as the old ternary check.
        let two16 = m31(1 << 16);
        let sf = s_first.clone();
        for k in 0..4 {
            let csp = if k == 0 { E::F::zero() } else { cs[k - 1].clone() };
            let crp = if k == 0 { E::F::zero() } else { cr[k - 1].clone() };
            e.add_constraint(sf.clone() * (vin[k].clone() + pv[k].clone() + csp - sm[k].clone() - cs[k].clone() * two16));
            e.add_constraint(sf.clone() * (v1[k].clone() + v2[k].clone() + fee[k].clone() + crp - sm[k].clone() - cr[k].clone() * two16));
            e.add_constraint(sf.clone() * cs[k].clone() * (cs[k].clone() - E::F::one()));
            e.add_constraint(sf.clone() * (cr[k].clone() - cb0[k].clone() - cb1[k].clone() * m31(2)));
            e.add_constraint(sf.clone() * cb0[k].clone() * (cb0[k].clone() - E::F::one()));
            e.add_constraint(sf.clone() * cb1[k].clone() * (cb1[k].clone() - E::F::one()));
        }
        e.add_constraint(sf.clone() * (cs[3].clone() - cr[3].clone()));
        let pub_vf = chain![[cst::<E>(TAG_PUB), cst::<E>(5)], pv.iter().cloned(), fee.iter().cloned()].collect_vec();
        lk.push(-ef::<E>(s_first.clone()), pub_vf);
        let pub_d = chain![[cst::<E>(TAG_PUB), s_tag], dcur.iter().flat_map(|x| x.clone())].collect_vec();
        lk.push(-ef::<E>(s_pub), pub_d);
        // blind chain link 1 (emitted here, consumed by ROUND)
        let bu = read4(&mut e);
        lk.push(ef::<E>(s_blind.clone()), chain![[cst::<E>(TAG_BLIND), cst::<E>(1)], bu].collect());
        finish_logup(e, rel, lk, self.track, s_real, s_blind, s_last, self.claimed)
    }
}

pub struct RoundEval {
    pub log: u32,
    pub rel: Rel,
    pub claimed: SecureField,
    pub track: bool,
}
impl FrameworkEval for RoundEval {
    fn log_size(&self) -> u32 {
        self.log
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        self.log + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let rel = &self.rel;
        let mut lk = Lk::<E>::new();
        let s: Vec<E::F> = RD_SEL.iter().map(|n| e.get_preprocessed_column(pid(n))).collect();
        let (s_real, s_blind, s_last) = (s[0].clone(), s[1].clone(), s[2].clone());
        let mut v: [Fu<E::F>; 16] = std::array::from_fn(|_| rd_u32(&mut e));
        let input = v.clone();
        let m: [Fu<E::F>; 16] = std::array::from_fn(|_| rd_u32(&mut e));
        for (k, idx) in G_IDX.iter().enumerate() {
            g(&mut e, &mut lk, &s_real, &mut v, *idx, m[2 * k].clone(), m[2 * k + 1].clone());
        }
        let vals = chain![
            [cst::<E>(TAG_ROUND)],
            input.iter().flat_map(|x| x.felts()),
            v.iter().flat_map(|x| x.felts()),
            m.iter().flat_map(|x| x.felts())
        ]
        .collect_vec();
        lk.push(-ef::<E>(s_real.clone()), vals);
        let bv = read4(&mut e);
        lk.push(-ef::<E>(s_blind.clone()), chain![[cst::<E>(TAG_BLIND), cst::<E>(1)], bv].collect());
        let bw = read4(&mut e);
        lk.push(ef::<E>(s_blind.clone()), chain![[cst::<E>(TAG_BLIND), cst::<E>(2)], bw].collect());
        finish_logup(e, rel, lk, self.track, s_real, s_blind, s_last, self.claimed)
    }
}

pub struct XorEval {
    pub log: u32,
    pub rel: Rel,
    pub claimed: SecureField,
    pub track: bool,
}
impl FrameworkEval for XorEval {
    fn log_size(&self) -> u32 {
        self.log
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        self.log + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let mut lk = Lk::<E>::new();
        let p: Vec<E::F> = XS_SEL.iter().map(|n| e.get_preprocessed_column(pid(n))).collect();
        let (s_real, s_blind, s_last) = (p[4].clone(), p[5].clone(), p[6].clone());
        let mult = e.next_trace_mask();
        let vals = vec![cst::<E>(TAG_XOR), p[0].clone(), p[1].clone(), p[2].clone(), p[3].clone()];
        lk.push(-ef::<E>(mult * s_real.clone()), vals);
        let by = read4(&mut e);
        lk.push(-ef::<E>(s_blind.clone()), chain![[cst::<E>(TAG_BLIND), cst::<E>(2)], by].collect());
        finish_logup(e, &self.rel, lk, self.track, s_real, s_blind, s_last, self.claimed)
    }
}

// ------------------------------------------------------------------------------------------------ prove / verify

pub struct JsProof {
    pub claimed: Vec<SecureField>,
    pub stark: StarkProof<Blake2sMerkleHasher>,
    /// prover-side debug data for zktest (never serialized, not part of the proof)
    pub dbg: Option<Debug>,
}
pub struct Debug {
    pub oods: CirclePoint<SecureField>,
    pub queries: Vec<usize>,
    pub js_rows: Vec<Vec<u32>>,
    /// Every committed column, per tree [preprocessed, original + salts, interaction + salts, composition tree], as
    /// evaluations on its own trace domain in Stwo's storage order (bit-reversed circle domain). zkproof/zkcheck reads
    /// these to rebuild every polynomial the verifier sees a value of.
    pub trees: Vec<Vec<Vec<BaseField>>>,
    /// log sizes of those columns
    pub tree_logs: Vec<Vec<u32>>,
    /// the composition random coefficient and the LogUp relation the prover drew
    pub comp_coeff: SecureField,
    pub rel: Rel,
}
impl JsProof {
    pub fn size_bytes(&self) -> usize {
        bincode::serialize(&self.stark).unwrap().len() + self.claimed.len() * 16
    }
}

/// PCS config. Every tree is lifted to the composition polynomial's LDE size (the composition is committed unsplit,
/// one log size above the largest trace column), so `min_lifting_log_size` is fixed by the query count.
pub fn config(log_blowup: u32, n_queries: usize, pow_bits: u32) -> PcsConfig {
    let sz = Sizes::new(n_queries);
    PcsConfig {
        pow_bits,
        fri_config: FriConfig::new(0, log_blowup, n_queries, 1),
        min_lifting_log_size: sz.log_comp() + log_blowup,
    }
}

struct Comps {
    js: FrameworkComponent<JsEval>,
    round: FrameworkComponent<RoundEval>,
    xor: FrameworkComponent<XorEval>,
}
impl Comps {
    fn new(sz: &Sizes, rel: &Rel, claimed: &[SecureField], track: bool) -> Self {
        let alloc = &mut TraceLocationAllocator::new_with_preprocessed_columns(&preprocessed_ids());
        let js = FrameworkComponent::new(alloc, JsEval { log: sz.log_js, rel: rel.clone(), claimed: claimed[0], track }, claimed[0]);
        let round =
            FrameworkComponent::new(alloc, RoundEval { log: sz.log_round, rel: rel.clone(), claimed: claimed[1], track }, claimed[1]);
        let xor = FrameworkComponent::new(alloc, XorEval { log: sz.log_xor, rel: rel.clone(), claimed: claimed[2], track }, claimed[2]);
        Self { js, round, xor }
    }
    #[cfg(feature = "prover")]
    fn provers(&self) -> Vec<&dyn stwo::prover::ComponentProver<stwo::prover::backend::simd::SimdBackend>> {
        vec![&self.js, &self.round, &self.xor]
    }
    fn verifiers(&self) -> Vec<&dyn Component> {
        vec![&self.js, &self.round, &self.xor]
    }
}

/// [preprocessed, original (+ salts), interaction (+ salts)] column log sizes.
fn tree_log_sizes(sz: &Sizes) -> [Vec<u32>; 3] {
    let d = Rel::dummy();
    let z = SecureField::zero();
    let infos: Vec<(InfoEvaluator, u32)> = vec![
        (JsEval { log: sz.log_js, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_js),
        (RoundEval { log: sz.log_round, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_round),
        (XorEval { log: sz.log_xor, rel: d, claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_xor),
    ];
    let per = |t: usize| {
        let mut v = infos.iter().flat_map(|(i, l)| std::iter::repeat_n(*l, i.mask_offsets[t].len())).collect_vec();
        v.extend(std::iter::repeat_n(sz.log_comp(), N_SALT));
        v
    };
    [preprocessed_log_sizes(sz), per(ORIGINAL_TRACE_IDX), per(INTERACTION_TRACE_IDX)]
}

fn public_sum(rel: &Rel, p: &Public) -> SecureField {
    let limbs64 = |x: u64| (0..4).map(move |k| m31(((x >> (16 * k)) & 0xffff) as u32));
    let dl = |d: &[u32; 8]| d.iter().flat_map(|x| [m31(x & 0xffff), m31(x >> 16)]).collect_vec();
    let mut tuples: Vec<Vec<BaseField>> = vec![chain![[m31(TAG_PUB), m31(5)], limbs64(p.pv), limbs64(p.fee)].collect()];
    for (tag, d) in [(1, &p.root), (2, &p.nf), (3, &p.cm1), (4, &p.cm2)] {
        tuples.push(chain![[m31(TAG_PUB), m31(tag)], dl(d)].collect());
    }
    tuples.iter().map(|t| <Rel as Relation<BaseField, SecureField>>::combine(rel, t).inverse()).sum()
}

fn composition_tree_points(w: CirclePoint<SecureField>) -> Vec<Vec<CirclePoint<SecureField>>> {
    chain![
        vec![vec![w.repeated_double(1)]; SECURE_EXTENSION_DEGREE],
        vec![vec![w]; N_RND],
        vec![vec![w.repeated_double(1)]; N_RND2],
        vec![vec![]; N_SALT]
    ]
    .collect()
}
fn composition_at(proof: &StarkProof<Blake2sMerkleHasher>) -> Option<SecureField> {
    let last = proof.sampled_values.last()?;
    if last.len() != SECURE_EXTENSION_DEGREE + N_RND + N_RND2 + N_SALT {
        return None;
    }
    let ev: Vec<SecureField> =
        last[..SECURE_EXTENSION_DEGREE].iter().map(|c| if c.len() == 1 { Some(c[0]) } else { None }).collect::<Option<_>>()?;
    Some(SecureField::from_partial_evals(ev.try_into().ok()?))
}

pub fn verify_js(public: &Public, proof: JsProof, cfg: PcsConfig) -> Result<(), String> {
    let q = cfg.fri_config.n_queries;
    if cfg != config(cfg.fri_config.log_blowup_factor, q, cfg.pow_bits) {
        return Err("not a zk config".into());
    }
    if proof.stark.config != cfg {
        return Err("unexpected PCS config".into());
    }
    if proof.claimed.len() != 3 || proof.stark.commitments.len() != 4 {
        return Err("bad proof structure".into());
    }
    let sz = Sizes::new(q);
    let ch = &mut Blake2sChannel::default();
    cfg.mix_into(ch);
    public.mix_into(ch);
    let sizes = tree_log_sizes(&sz);
    let cs = &mut CommitmentSchemeVerifier::<Blake2sMerkleChannel>::new(cfg);
    cs.commit(proof.stark.commitments[0], &sizes[0], ch);
    cs.commit(proof.stark.commitments[1], &sizes[1], ch);
    let rel = Rel::draw(ch);
    let total: SecureField = proof.claimed.iter().copied().sum::<SecureField>() + public_sum(&rel, public);
    if !total.is_zero() {
        return Err("public inputs do not balance the LogUp sum".into());
    }
    ch.mix_felts(&proof.claimed);
    cs.commit(proof.stark.commitments[2], &sizes[2], ch);
    let comps = Comps::new(&sz, &rel, &proof.claimed, false);
    let components = Components { components: comps.verifiers(), n_preprocessed_columns: sizes[0].len() };
    let lc = components.composition_log_degree_bound();
    assert_eq!(lc, sz.log_comp());
    let random_coeff = ch.draw_secure_felt();
    cs.commit(proof.stark.commitments[3], &[lc; SECURE_EXTENSION_DEGREE + N_RND + N_RND2 + N_SALT], ch);
    let w = CirclePoint::<SecureField>::get_random_point(ch);
    let mut sp = components.mask_points(w, lc, false);
    sp[ORIGINAL_TRACE_IDX].extend(vec![vec![]; N_SALT]);
    sp[INTERACTION_TRACE_IDX].extend(vec![vec![]; N_SALT]);
    sp.push(composition_tree_points(w));
    // structure: one sampled value per sample point, per column, per tree (checked before any indexing)
    if proof.stark.sampled_values.len() != sp.len()
        || sp.iter().zip(proof.stark.sampled_values.iter()).any(|(a, b)| {
            a.len() != b.len() || a.iter().zip(b.iter()).any(|(x, y)| x.len() != y.len())
        })
    {
        return Err("sampled values do not match the sample points".into());
    }
    let got = composition_at(&proof.stark).ok_or("bad composition samples")?;
    if got != components.eval_composition_polynomial_at_point(w, &proof.stark.sampled_values, random_coeff, lc) {
        return Err(format!("{}", VerificationError::OodsNotMatching));
    }
    cs.verify_values(sp, proof.stark.0, ch).map_err(|e: VerificationError| format!("{e}"))
}

// ------------------------------------------------------------------------------------------------ node binding

/// THE PcsConfig A NODE ACCEPTS: log_blowup 2, 160 queries, 20 grinding bits, the config whose conjectured security
/// matches the current wallet prover's (Stwo security_bits() = 340; NADO's soundness model: 333.7 conjectured, 113.4
/// provable, capped by the QM31 challenge field). The proof carries its own config and `verify_js` refuses one that
/// differs from this, so a prover cannot pick a cheaper one. ZK slack at this config (zkproof/ARGUMENT.md section 8):
/// the tightest column class, the ROUND running sum D, has a worst-case slack of 4 free rows (measured minimum 7); a
/// larger query count or more ROUND real rows would need ROUND at 2^11 rows. CHANGING THIS IS A CONSENSUS CHANGE.
pub const NODE_LOG_BLOWUP: u32 = 2;
pub const NODE_N_QUERIES: usize = 160;
pub const NODE_POW_BITS: u32 = 20;

pub fn node_config() -> PcsConfig {
    config(NODE_LOG_BLOWUP, NODE_N_QUERIES, NODE_POW_BITS)
}

/// Domain tag of the unshield-destination binding (see `aux_of`).
pub const AUX_DOMAIN: &[u8] = b"NADO/stwo-js/aux/v1\x00";

/// The 8-word `aux` public input from the unshield destination address (UTF-8 bytes; empty for a private transfer):
/// BLAKE2s-256(AUX_DOMAIN || dest), as 8 little-endian u32 words. The prototype mixes `aux` into the transcript before
/// the first commitment; this fixes what the 8 words ARE, so the wallet and the node derive them the same way. Any
/// other destination is a different transcript, so a proof cannot be redirected.
pub fn aux_of(dest: &[u8]) -> [u32; 8] {
    use blake2::Digest;
    let mut h = blake2::Blake2s256::new();
    h.update(AUX_DOMAIN);
    h.update(dest);
    let d = h.finalize();
    std::array::from_fn(|i| u32::from_le_bytes([d[4 * i], d[4 * i + 1], d[4 * i + 2], d[4 * i + 3]]))
}

/// A 32-byte BLAKE2s digest -> the circuit's 8 u32 words (little-endian, the BLAKE2s output byte order).
pub fn digest_words(b: &[u8; 32]) -> [u32; 8] {
    std::array::from_fn(|i| u32::from_le_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]]))
}
/// The inverse of `digest_words`.
pub fn words_digest(w: &[u32; 8]) -> [u8; 32] {
    let mut out = [0u8; 32];
    for i in 0..8 {
        out[4 * i..4 * i + 4].copy_from_slice(&w[i].to_le_bytes());
    }
    out
}

/// Result codes of `nado_stwo_js_verify`.
pub const RC_OK: i32 = 0;
/// a null pointer where bytes were required
pub const RC_BAD_ARGS: i32 = 1;
/// the bytes are not a proof: too large, not the wire format, trailing bytes, a non-canonical field element
pub const RC_MALFORMED: i32 = 2;
/// a well-formed proof the verifier refuses (wrong config, public inputs, OODS, FRI, Merkle, proof of work)
pub const RC_REJECTED: i32 = 3;
/// the verifier panicked on these bytes (refused; a panic on adversarial input is a refusal, never a crash)
pub const RC_PANIC: i32 = 4;

/// Verify one join-split proof against its public inputs with the pinned node config. Pure: no I/O, no globals.
pub fn verify_node(proof: &[u8], root: [u8; 32], nf: [u8; 32], cm1: [u8; 32], cm2: [u8; 32], pv: u64, fee: u64, dest: &[u8]) -> (i32, String) {
    let proof = match wire::decode(proof) {
        Ok(p) => p,
        Err(e) => return (RC_MALFORMED, format!("malformed proof: {e:?}")),
    };
    let public = Public {
        root: digest_words(&root),
        nf: digest_words(&nf),
        cm1: digest_words(&cm1),
        cm2: digest_words(&cm2),
        pv,
        fee,
        aux: aux_of(dest),
    };
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| verify_js(&public, proof, node_config()))) {
        Ok(Ok(())) => (RC_OK, String::new()),
        Ok(Err(e)) => (RC_REJECTED, e),
        Err(_) => (RC_PANIC, "verifier panicked".into()),
    }
}

unsafe fn arr32(p: *const u8) -> Option<[u8; 32]> {
    if p.is_null() {
        return None;
    }
    let mut a = [0u8; 32];
    unsafe { std::ptr::copy_nonoverlapping(p, a.as_mut_ptr(), 32) };
    Some(a)
}

/// C ABI. `root`, `nf`, `cm1`, `cm2`: 32 bytes each. `dest`: the unshield destination's UTF-8 bytes (`dest_len` may be
/// 0). The reason for a refusal is written to `reason` (at most `reason_cap` bytes, not NUL-terminated); its length
/// goes to `*reason_len` when that pointer is not null. Returns one of the RC_* codes. Never unwinds into the caller.
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_js_verify(
    proof: *const u8,
    proof_len: usize,
    root: *const u8,
    nf: *const u8,
    cm1: *const u8,
    cm2: *const u8,
    public_value: u64,
    fee: u64,
    dest: *const u8,
    dest_len: usize,
    reason: *mut u8,
    reason_cap: usize,
    reason_len: *mut usize,
) -> i32 {
    let r = std::panic::catch_unwind(|| {
        if proof.is_null() || (dest.is_null() && dest_len != 0) {
            return (RC_BAD_ARGS, "null pointer".to_string());
        }
        let ins = unsafe { (arr32(root), arr32(nf), arr32(cm1), arr32(cm2)) };
        let (Some(root), Some(nf), Some(cm1), Some(cm2)) = ins else {
            return (RC_BAD_ARGS, "null digest".to_string());
        };
        let pb = unsafe { std::slice::from_raw_parts(proof, proof_len) };
        let db: &[u8] = if dest_len == 0 { &[] } else { unsafe { std::slice::from_raw_parts(dest, dest_len) } };
        verify_node(pb, root, nf, cm1, cm2, public_value, fee, db)
    });
    let (rc, msg) = r.unwrap_or((RC_PANIC, "verifier panicked".into()));
    if !reason.is_null() {
        let n = msg.len().min(reason_cap);
        unsafe { std::ptr::copy_nonoverlapping(msg.as_ptr(), reason, n) };
        if !reason_len.is_null() {
            unsafe { *reason_len = n };
        }
    }
    rc
}

/// C ABI: the 32-byte `aux` digest (`words_digest(aux_of(dest))`) into `out`, for cross-checks.
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_js_aux(dest: *const u8, dest_len: usize, out: *mut u8) -> i32 {
    if out.is_null() || (dest.is_null() && dest_len != 0) {
        return RC_BAD_ARGS;
    }
    let db: &[u8] = if dest_len == 0 { &[] } else { unsafe { std::slice::from_raw_parts(dest, dest_len) } };
    let d = words_digest(&aux_of(db));
    unsafe { std::ptr::copy_nonoverlapping(d.as_ptr(), out, 32) };
    RC_OK
}

/// C ABI: the pinned node config as (log_blowup, n_queries, pow_bits), so the binding can report what it verifies.
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_js_config(out: *mut u32) -> i32 {
    if out.is_null() {
        return RC_BAD_ARGS;
    }
    let c = [NODE_LOG_BLOWUP, NODE_N_QUERIES as u32, NODE_POW_BITS];
    unsafe { std::ptr::copy_nonoverlapping(c.as_ptr(), out, 3) };
    RC_OK
}

/// C ABI version: bumped on any change to the signatures above.
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_js_abi_version() -> u32 {
    1
}
