//! The PROVER half (cargo feature `prover`, nightly Rust): witness and trace generation, the random rows, the ZK
//! interaction trace, the ZK protocol tail `prove_zk`, the fixtures, the WASM harness and the read-only hooks the
//! prototype's zkproof/zkcheck uses. Moved unchanged from the phase-0 prototype `stwo_zk`; the verifier half it pairs
//! with is in lib.rs. Never compiled into the node's library (the default build has no `prover` feature).

use super::*;
use stwo::core::ColumnVec;
use rand_chacha::ChaCha20Rng;
use rand_core::{RngCore, SeedableRng};
use stwo::core::pcs::TreeVec;
use stwo::core::poly::circle::CanonicCoset;
use stwo::core::utils::{bit_reverse_index, coset_index_to_circle_domain_index};
use stwo::prover::backend::simd::SimdBackend;
use stwo::prover::backend::simd::column::BaseColumn;
use stwo::prover::backend::Column;
use stwo::prover::poly::BitReversedOrder;
use stwo::prover::poly::circle::{CircleEvaluation, PolyOps};
use stwo::prover::{CommitmentSchemeProver, ComponentProver, ComponentProvers};
use stwo_constraint_framework::relation_tracker::{RelationTrackerEntry, add_to_relation_entries};
use stwo_constraint_framework::PREPROCESSED_TRACE_IDX;

// JS rows (moved from the parameters block: only the trace writer uses them)
const ROW_OWNER: usize = 0;
const ROW_CMIN: usize = 1;
const ROW_MERK0: usize = 2;
const ROW_NF: usize = D + 2;
const ROW_OUT1: usize = D + 3;
const ROW_OUT2: usize = D + 4;

fn msg_owner(nsk: &[u32; 8]) -> [u32; 16] {
    let mut m = [0u32; 16];
    m[0] = DOM_OWNER;
    m[1..9].copy_from_slice(nsk);
    m
}
fn msg_cm(v: u64, owner: &[u32; 8], rho: u64) -> [u32; 16] {
    let mut m = [0u32; 16];
    m[0] = DOM_CM;
    m[1] = lo(v);
    m[2] = hi(v);
    m[3..11].copy_from_slice(owner);
    m[11] = lo(rho);
    m[12] = hi(rho);
    m
}
fn msg_nf(nsk: &[u32; 8], rho: u64) -> [u32; 16] {
    let mut m = [0u32; 16];
    m[0] = DOM_NF;
    m[1..9].copy_from_slice(nsk);
    m[9] = lo(rho);
    m[10] = hi(rho);
    m
}
fn msg_node(l: &[u32; 8], r: &[u32; 8]) -> [u32; 16] {
    let mut m = [0u32; 16];
    m[..8].copy_from_slice(l);
    m[8..].copy_from_slice(r);
    m
}
pub fn owner_of(nsk: &[u32; 8]) -> [u32; 8] {
    hash(&msg_owner(nsk))
}
pub fn commit(v: u64, owner: &[u32; 8], rho: u64) -> [u32; 8] {
    hash(&msg_cm(v, owner, rho))
}
pub fn nullifier(nsk: &[u32; 8], rho: u64) -> [u32; 8] {
    hash(&msg_nf(nsk, rho))
}
pub fn node(l: &[u32; 8], r: &[u32; 8]) -> [u32; 8] {
    hash(&msg_node(l, r))
}
pub fn tree_path(leaves: &[[u32; 8]], idx: usize, depth: usize) -> (Vec<[u32; 8]>, Vec<u32>, [u32; 8]) {
    let mut empty = [0u32; 8];
    let mut level: Vec<[u32; 8]> = leaves.to_vec();
    let mut i = idx;
    let (mut sibs, mut dirs) = (vec![], vec![]);
    for _ in 0..depth {
        let sib = i ^ 1;
        sibs.push(if sib < level.len() { level[sib] } else { empty });
        dirs.push((i & 1) as u32);
        let next = (0..level.len().div_ceil(2))
            .map(|k| {
                let l = level[2 * k];
                let r = if 2 * k + 1 < level.len() { level[2 * k + 1] } else { empty };
                node(&l, &r)
            })
            .collect_vec();
        empty = node(&empty, &empty);
        level = next;
        i >>= 1;
    }
    (sibs, dirs, level[0])
}

#[derive(Clone, Debug)]
pub struct Witness {
    pub nsk: [u32; 8],
    pub v_in: u64,
    pub rho: u64,
    pub sibs: Vec<[u32; 8]>,
    pub dirs: Vec<u32>,
    pub v1: u64,
    pub o1: [u32; 8],
    pub r1: u64,
    pub v2: u64,
    pub o2: [u32; 8],
    pub r2: u64,
    pub pv: u64,
    pub fee: u64,
}


/// The R_JS real messages, the dir bit of each row and the public outputs.
fn messages(w: &Witness) -> (Vec<[u32; 16]>, Vec<u32>, Public) {
    assert_eq!(w.sibs.len(), D);
    let mut msgs = vec![[0u32; 16]; R_JS];
    let mut dirs = vec![0u32; R_JS];
    msgs[ROW_OWNER] = msg_owner(&w.nsk);
    let owner = hash(&msgs[ROW_OWNER]);
    msgs[ROW_CMIN] = msg_cm(w.v_in, &owner, w.rho);
    let mut cur = hash(&msgs[ROW_CMIN]);
    for k in 0..D {
        let r = ROW_MERK0 + k;
        dirs[r] = w.dirs[k];
        msgs[r] = if w.dirs[k] == 1 { msg_node(&w.sibs[k], &cur) } else { msg_node(&cur, &w.sibs[k]) };
        cur = hash(&msgs[r]);
    }
    msgs[ROW_NF] = msg_nf(&w.nsk, w.rho);
    msgs[ROW_OUT1] = msg_cm(w.v1, &w.o1, w.r1);
    msgs[ROW_OUT2] = msg_cm(w.v2, &w.o2, w.r2);
    let public = Public {
        root: cur,
        nf: hash(&msgs[ROW_NF]),
        cm1: hash(&msgs[ROW_OUT1]),
        cm2: hash(&msgs[ROW_OUT2]),
        pv: w.pv,
        fee: w.fee,
        aux: [0; 8],
    };
    (msgs, dirs, public)
}

// ------------------------------------------------------------------------------------------------ trace writer (mirror)

#[derive(Default)]
struct Row {
    c: Vec<u32>,
}
impl Row {
    fn push(&mut self, x: u32) {
        self.c.push(x);
    }
    fn u32(&mut self, x: u32) {
        self.push(x & 0xffff);
        self.push(x >> 16);
    }
    fn split(&mut self, limb: u32, w: &[u32]) {
        let mut off = 0;
        for wi in &w[..w.len() - 1] {
            self.push((limb >> off) & ((1 << wi) - 1));
            off += wi;
        }
    }
    fn add2(&mut self, a: u32, b: u32) -> u32 {
        let s = a.wrapping_add(b);
        self.u32(s);
        s
    }
    fn add3(&mut self, a: u32, b: u32, c: u32) -> u32 {
        let s = a.wrapping_add(b).wrapping_add(c);
        self.u32(s);
        // carry bits (see add3 in the AIR): bl = cl >> 1, bh = ch >> 1, so cl - bl and ch - bh are in {0, 1}
        let cl = ((a & 0xffff) + (b & 0xffff) + (c & 0xffff)) >> 16;
        let ch = ((a >> 16) + (b >> 16) + (c >> 16) + cl) >> 16;
        self.push(cl >> 1);
        self.push(ch >> 1);
        s
    }
    fn xor_rotr(&mut self, a: u32, b: u32, r: u32) -> u32 {
        let w = widths(r);
        for limb in [a & 0xffff, a >> 16, b & 0xffff, b >> 16] {
            self.split(limb, w);
        }
        for x in [(a ^ b) & 0xffff, (a ^ b) >> 16] {
            let mut off = 0;
            for wi in w {
                self.push((x >> off) & ((1 << wi) - 1));
                off += wi;
            }
        }
        (a ^ b).rotate_right(r)
    }
    fn g(&mut self, v: &mut [u32; 16], [a, b, c, d]: [usize; 4], m0: u32, m1: u32) {
        v[a] = self.add3(v[a], v[b], m0);
        v[d] = self.xor_rotr(v[a], v[d], 16);
        v[c] = self.add2(v[c], v[d]);
        v[b] = self.xor_rotr(v[b], v[c], 12);
        v[a] = self.add3(v[a], v[b], m1);
        v[d] = self.xor_rotr(v[a], v[d], 8);
        v[c] = self.add2(v[c], v[d]);
        v[b] = self.xor_rotr(v[b], v[c], 7);
    }
    fn nibble_range(&mut self, limb: u32) {
        self.split(limb, NIB);
    }
}

/// uniformly random M31 element (as u32 < P)
pub fn rm<R: RngCore + ?Sized>(rng: &mut R) -> u32 {
    loop {
        let x = rng.next_u32() & 0x7fff_ffff;
        if x != 0x7fff_ffff {
            return x;
        }
    }
}
fn rqm(rng: &mut impl RngCore) -> SecureField {
    SecureField::from_m31_array(std::array::from_fn(|_| m31(rm(rng))))
}

/// A random ROUND row: every cell uniform M31. ZK INVARIANT: the add-with-carry constraints are gated (see add2), so a
/// random row satisfies every constraint whatever its cells; do NOT go back to rows "built over M31 with valid carries"
/// (a cross-column relation with a 1.6-bit residual, which the opened values expose).
fn rnd_round_row(rng: &mut impl RngCore, width: usize) -> Vec<u32> {
    (0..width).map(|_| rm(rng)).collect()
}

pub fn pos(r: usize, log: u32) -> usize {
    bit_reverse_index(coset_index_to_circle_domain_index(r, log), log)
}
fn to_storage(rows: &[Vec<u32>], log: u32) -> Vec<Vec<BaseField>> {
    let n = 1usize << log;
    assert_eq!(rows.len(), n);
    let ncols = rows[0].len();
    let mut cols = vec![vec![BaseField::zero(); n]; ncols];
    for (r, row) in rows.iter().enumerate() {
        assert_eq!(row.len(), ncols, "ragged row");
        let p = pos(r, log);
        for (c, v) in row.iter().enumerate() {
            cols[c][p] = m31(*v);
        }
    }
    cols
}
fn evals(cols: &[Vec<BaseField>], log: u32) -> ColumnVec<CircleEvaluation<SimdBackend, BaseField, BitReversedOrder>> {
    let domain = CanonicCoset::new(log).circle_domain();
    cols.iter().map(|c| CircleEvaluation::new(domain, c.iter().copied().collect::<BaseColumn>())).collect()
}
fn rnd_cols(rng: &mut impl RngCore, n: usize, log: u32) -> Vec<Vec<BaseField>> {
    (0..n).map(|_| (0..1usize << log).map(|_| m31(rm(rng))).collect()).collect()
}


fn js_selectors(log: u32) -> Vec<Vec<u32>> {
    let n = 1usize << log;
    (0..n)
        .map(|r| {
            let real = r < R_JS;
            let merk = (ROW_MERK0..ROW_MERK0 + D).contains(&r);
            let tag = match r {
                x if x == ROW_MERK0 + D - 1 => 1,
                x if x == ROW_NF => 2,
                x if x == ROW_OUT1 => 3,
                x if x == ROW_OUT2 => 4,
                _ => 0,
            };
            vec![
                (r == ROW_OWNER) as u32,
                (r == ROW_CMIN) as u32,
                merk as u32,
                (r == ROW_NF) as u32,
                (r == ROW_OUT1) as u32,
                (r == ROW_OUT2) as u32,
                (tag != 0) as u32,
                tag,
                real as u32,
                (r == R_JS) as u32,
                (r == n - 1) as u32,
                (r + 1 < R_JS) as u32, // hold: register transitions r -> r+1 inside the real rows
            ]
        })
        .collect()
}
fn plain_selectors(log: u32, r_real: usize) -> Vec<Vec<u32>> {
    let n = 1usize << log;
    (0..n).map(|r| vec![(r < r_real) as u32, (r == r_real) as u32, (r == n - 1) as u32]).collect()
}
fn xor_index_small(w: u32, a: u32, b: u32) -> usize {
    match w {
        4 => (a * 16 + b) as usize,
        3 => 256 + (a * 8 + b) as usize,
        1 => 320 + (a * 2 + b) as usize,
        _ => panic!("xor width"),
    }
}
fn xor_table_rows(log: u32) -> Vec<Vec<u32>> {
    let n = 1usize << log;
    let mut rows = vec![vec![0u32; 4]; n];
    for w in [4u32, 3, 1] {
        let k = 1u32 << w;
        for a in 0..k {
            for b in 0..k {
                rows[xor_index_small(w, a, b)] = vec![w, a, b, a ^ b];
            }
        }
    }
    let sel = plain_selectors(log, R_XOR);
    rows.into_iter().zip(sel).map(|(mut t, s)| {
        t.extend(s);
        t
    }).collect()
}

/// Real rows of the JS component (R_JS of them), honest values.
fn js_rows(msgs: &[[u32; 16]], dirs: &[u32], w: &Witness, rng: &mut impl RngCore) -> Vec<Vec<u32>> {
    let h = h0();
    let limbs64 = |x: u64| [(x & 0xffff) as u32, ((x >> 16) & 0xffff) as u32, ((x >> 32) & 0xffff) as u32, (x >> 48) as u32];
    let (vin, pv, v1, v2, fee) = (limbs64(w.v_in), limbs64(w.pv), limbs64(w.v1), limbs64(w.v2), limbs64(w.fee));
    let (mut sm, mut cs, mut cr) = ([0u32; 4], [0u32; 4], [0u32; 4]);
    let (mut c1, mut c2) = (0u32, 0u32);
    for k in 0..4 {
        let a = vin[k] + c1;                                // input side: v_in alone (lib.rs conservation invariant)
        let b = v1[k] + v2[k] + fee[k] + pv[k] + c2;        // output side: the unshield pv leaves with the outputs and fee
        sm[k] = a & 0xffff;
        cs[k] = a >> 16;
        cr[k] = b >> 16;
        c1 = cs[k];
        c2 = cr[k];
    }
    let cb0 = cr.map(|x| x & 1);
    let cb1 = cr.map(|x| x >> 1);
    let mut out = vec![];
    for (r, msg) in msgs.iter().enumerate() {
        let mut row = Row::default();
        let (states, _) = compress(msg);
        for x in msg {
            row.u32(*x);
        }
        for s in &states {
            for x in s {
                row.u32(*x);
            }
        }
        let v = states[N_ROUNDS];
        for i in 0..8 {
            for limb in 0..2 {
                let a = (v[i] >> (16 * limb)) & 0xffff;
                let b = (v[i + 8] >> (16 * limb)) & 0xffff;
                let hn = (h[i] >> (16 * limb)) & 0xffff;
                row.split(a, NIB);
                row.split(b, NIB);
                let pw = NIB[0];
                for k in 0..NIB.len() {
                    row.push(((a ^ b) >> (pw as usize * k)) & ((1 << pw) - 1));
                }
                for k in 0..NIB.len() {
                    row.push(((a ^ b ^ hn) >> (pw as usize * k)) & ((1 << pw) - 1));
                }
            }
        }
        for x in w.nsk {
            row.u32(x);
        }
        for x in [lo(w.rho), hi(w.rho)] {
            row.u32(x);
        }
        for arr in [vin, v1, v2, pv, fee, sm, cs, cr, cb0, cb1] {
            for x in arr {
                row.push(x);
            }
        }
        row.push(dirs[r]);
        for x in msg {
            row.nibble_range(x & 0xffff);
            row.nibble_range(x >> 16);
        }
        for x in chain![pv, fee, sm] {
            row.nibble_range(x);
        }
        for _ in 0..4 {
            row.push(rm(rng)); // blind columns: unused (multiplicity 0) on real rows
        }
        out.push(row.c);
    }
    out
}
/// Column range of the JS original trace holding st[0] (fixed to the BLAKE2s start state on every row).
const JS_ST0: std::ops::Range<usize> = 32..64;
/// Column of the first nsk register limb in the JS original trace (zktest reads it).
pub const JS_NSK_COL: usize = 32 + 11 * 32 + 16 * 14;
pub const JS_NREG: usize = 16 + 4 + 4 * 12; // nsk, rho, vin, v1, v2, pv, fee, sm, cs, cr, cb0, cb1

fn round_rows(inputs: &[([u32; 16], [u32; 16])], rng: &mut impl RngCore) -> Vec<Vec<u32>> {
    inputs
        .iter()
        .map(|(v0, m)| {
            let mut row = Row::default();
            let mut v = *v0;
            for x in v0 {
                row.u32(*x);
            }
            for x in m {
                row.u32(*x);
            }
            for (k, idx) in G_IDX.iter().enumerate() {
                row.g(&mut v, *idx, m[2 * k], m[2 * k + 1]);
            }
            for _ in 0..8 {
                row.push(rm(rng));
            }
            row.c
        })
        .collect()
}

#[derive(Default, Debug, Clone)]
pub struct Timings {
    pub witness_trace_ms: f64,
    pub commit_ms: f64,
    pub interaction_ms: f64,
    pub prove_ms: f64,
}

/// The ZK interaction trace of one component: S_j = m_j / d_j on rows [0, R] (0 where m_j = 0), uniform QM31 after;
/// D = running sum over rows [0, R], D(N-1) = 0, uniform QM31 on rows (R, N-1). Returns base columns and claimed = D(R).
fn interaction_zk(
    rel: &Rel,
    entries: &[RelationTrackerEntry],
    log: u32,
    r_real: usize,
    rng: &mut impl RngCore,
) -> (Vec<Vec<BaseField>>, SecureField) {
    let n = 1usize << log;
    assert_eq!(entries.len() % n, 0);
    let per = entries.len() / n;
    let mut row_of = vec![0usize; n];
    for r in 0..n {
        row_of[pos(r, log)] = r;
    }
    let mut s_cols: Vec<Vec<SecureField>> = vec![vec![SecureField::zero(); n]; per];
    let mut rowsum = vec![SecureField::zero(); n]; // by coset row
    for i in 0..n {
        let r = row_of[i];
        for j in 0..per {
            let en = &entries[i * per + j];
            let v = if r <= r_real {
                if en.mult.0 == 0 {
                    SecureField::zero()
                } else {
                    SecureField::from(en.mult) * <Rel as Relation<BaseField, SecureField>>::combine(rel, &en.values).inverse()
                }
            } else {
                rqm(rng)
            };
            s_cols[j][i] = v;
            if r <= r_real {
                rowsum[r] += v;
            }
        }
    }
    let mut dcol = vec![SecureField::zero(); n];
    let mut acc = SecureField::zero();
    for r in 0..=r_real {
        acc += rowsum[r];
        dcol[pos(r, log)] = acc;
    }
    let claimed = acc;
    for r in r_real + 1..n - 1 {
        dcol[pos(r, log)] = rqm(rng);
    }
    let mut out = vec![];
    for col in s_cols.iter().chain([&dcol]) {
        let coords: Vec<[BaseField; 4]> = col.iter().map(|x| x.to_m31_array()).collect();
        for c in 0..4 {
            out.push(coords.iter().map(|a| a[c]).collect());
        }
    }
    (out, claimed)
}

pub fn now_ms() -> f64 {
    #[cfg(target_arch = "wasm32")]
    {
        0.0
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64() * 1e3
    }
}

/// 32 bytes from the OS (native only).
#[cfg(not(target_arch = "wasm32"))]
pub fn os_seed() -> [u8; 32] {
    use std::io::Read;
    let mut s = [0u8; 32];
    std::fs::File::open("/dev/urandom").unwrap().read_exact(&mut s).unwrap();
    s
}

#[derive(Debug)]
pub enum ProveError {
    /// the witness does not satisfy the AIR (LogUp imbalance or the DEEP-ALI identity fails)
    NotAJoinSplit(&'static str),
}

/// Malicious-prover modes for the soundness tests of the ZK LogUp (the prover's own sanity check is skipped).
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Cheat {
    No,
    /// move x from JS's claimed sum to ROUND's (the total, which the verifier checks, is unchanged)
    ShiftClaimed,
    /// commit a JS range-check piece that is not in the xor table, with the interaction column computed for the
    /// honest piece (so the LogUp sums still balance)
    ForgeLookup,
}
/// Column of the first nibble piece of message word 0, low limb (its range check is an xor-table lookup).
pub const JS_NIB0_COL: usize = JS_NSK_COL + JS_NREG + 1;

/// Prove one join-split in zero knowledge. `seed`: 32 fresh random bytes (never reuse one).
pub fn prove_js(w: &Witness, aux: [u32; 8], cfg: PcsConfig, check: bool, seed: [u8; 32]) -> Result<(Public, JsProof, Timings), ProveError> {
    prove_js_cheat(w, aux, cfg, check, seed, Cheat::No)
}
pub fn prove_js_cheat(
    w: &Witness,
    aux: [u32; 8],
    cfg: PcsConfig,
    check: bool,
    seed: [u8; 32],
    cheat: Cheat,
) -> Result<(Public, JsProof, Timings), ProveError> {
    let q = cfg.fri_config.n_queries;
    let sz = Sizes::new(q);
    assert_eq!(cfg, config(cfg.fri_config.log_blowup_factor, q, cfg.pow_bits), "use zk::config()");
    let rng = &mut ChaCha20Rng::from_seed(seed);
    let mut tm = Timings::default();
    let t0 = now_ms();
    let (msgs, dirs, mut public) = messages(w);
    public.aux = aux;

    // JS: R_JS real rows, then random rows (uniform M31 everywhere except the public BLAKE2s start state)
    let mut js_r = js_rows(&msgs, &dirs, w, rng);
    let width = js_r[0].len();
    let vi = v_init();
    let st0: Vec<u32> = vi.iter().flat_map(|x| [x & 0xffff, x >> 16]).collect();
    let blind1: [u32; 4] = std::array::from_fn(|_| rm(rng));
    let blind2: [u32; 4] = std::array::from_fn(|_| rm(rng));
    while js_r.len() < 1 << sz.log_js {
        let mut row: Vec<u32> = (0..width).map(|_| rm(rng)).collect();
        row[JS_ST0].copy_from_slice(&st0);
        if js_r.len() == R_JS {
            row[width - 4..].copy_from_slice(&blind1);
        }
        js_r.push(row);
    }
    let js = to_storage(&js_r, sz.log_js);
    let js_r = js_r;

    // ROUND: the 530 real rounds, then random M31 rounds
    let mut rin = vec![];
    for msg in &msgs {
        let (states, _) = compress(msg);
        for r in 0..N_ROUNDS {
            rin.push((states[r], SIGMA[r].map(|k| msg[k])));
        }
    }
    let mut rd_r = round_rows(&rin, rng);
    let rwidth = rd_r[0].len();
    while rd_r.len() < 1 << sz.log_round {
        let mut row = rnd_round_row(rng, rwidth);
        if rd_r.len() == R_ROUND {
            row[rwidth - 8..rwidth - 4].copy_from_slice(&blind1);
            row[rwidth - 4..].copy_from_slice(&blind2);
        }
        rd_r.push(row);
    }
    let rd = to_storage(&rd_r, sz.log_round);

    let sel_js = to_storage(&js_selectors(sz.log_js), sz.log_js);
    let sel_rd = to_storage(&plain_selectors(sz.log_round, R_ROUND), sz.log_round);
    let xt = to_storage(&xor_table_rows(sz.log_xor), sz.log_xor);
    let pre: Vec<Vec<BaseField>> = chain![sel_js.iter().cloned(), sel_rd.iter().cloned(), xt.iter().cloned()].collect();

    // relation entries -> xor multiplicities (real rows only: every other row has multiplicity 0)
    let zero3 = [SecureField::zero(); 3];
    let dummy = Comps::new(&sz, &Rel::dummy(), &zero3, true);
    let nx = 1usize << sz.log_xor;
    let mut orig: Vec<Vec<BaseField>> = chain![js.iter().cloned(), rd.iter().cloned()].collect();
    for _ in 0..5 {
        orig.push(vec![BaseField::zero(); nx]); // placeholders: xor mult + 4 blind columns
    }
    let e_js = add_to_relation_entries(&dummy.js, &tv(&pre, &orig));
    let e_rd = add_to_relation_entries(&dummy.round, &tv(&pre, &orig));
    let mut mult = vec![0u32; nx];
    for en in chain![e_js.iter(), e_rd.iter()] {
        if en.values[0] == m31(TAG_XOR) && en.mult.0 != 0 {
            assert_eq!(en.mult, m31(1));
            let [w_, a, b] = [en.values[1].0, en.values[2].0, en.values[3].0];
            assert!(en.values[4].0 == a ^ b, "xor lookup not in table: {w_} {a} {b}");
            mult[xor_index_small(w_, a, b)] += 1;
        }
    }
    let xr: Vec<Vec<u32>> = (0..nx)
        .map(|r| {
            let mut row = vec![if r < R_XOR { mult[r] } else { rm(rng) }];
            for k in 0..4 {
                row.push(if r == R_XOR { blind2[k] } else { rm(rng) });
            }
            row
        })
        .collect();
    let xm = to_storage(&xr, sz.log_xor);
    let base = orig.len() - 5;
    for k in 0..5 {
        orig[base + k] = xm[k].clone();
    }
    let e_xs = add_to_relation_entries(&dummy.xor, &tv(&pre, &orig));
    let mut js = js;
    if cheat == Cheat::ForgeLookup {
        js[JS_NIB0_COL][pos(0, sz.log_js)] += m31(16); // entries (and so the interaction) keep the honest piece
    }
    tm.witness_trace_ms = now_ms() - t0;

    // protocol
    let t1 = now_ms();
    let lc = sz.log_comp();
    let lb = cfg.fri_config.log_blowup_factor;
    let twiddles = SimdBackend::precompute_twiddles(CanonicCoset::new(lc + lb).circle_domain().half_coset);
    let ch = &mut Blake2sChannel::default();
    cfg.mix_into(ch);
    public.mix_into(ch);
    let mut cs = CommitmentSchemeProver::<SimdBackend, Blake2sMerkleChannel>::new(cfg, &twiddles);
    let mut tb = cs.tree_builder();
    tb.extend_evals(chain![evals(&sel_js, sz.log_js), evals(&sel_rd, sz.log_round), evals(&xt, sz.log_xor)].collect_vec());
    tb.commit(ch);
    let salt1 = rnd_cols(rng, N_SALT, lc);
    let mut tb = cs.tree_builder();
    tb.extend_evals(
        chain![
            evals(&js, sz.log_js),
            evals(&rd, sz.log_round),
            evals(&xm, sz.log_xor),
            evals(&salt1, lc)
        ]
        .collect_vec(),
    );
    tb.commit(ch);
    tm.commit_ms = now_ms() - t1;

    let t2 = now_ms();
    let rel = Rel::draw(ch);
    let (i_js, c_js) = interaction_zk(&rel, &e_js, sz.log_js, R_JS, rng);
    let (i_rd, c_rd) = interaction_zk(&rel, &e_rd, sz.log_round, R_ROUND, rng);
    let (i_xs, c_xs) = interaction_zk(&rel, &e_xs, sz.log_xor, R_XOR, rng);
    let mut claimed = vec![c_js, c_rd, c_xs];
    if cheat == Cheat::ShiftClaimed {
        let x = SecureField::from_m31_array([m31(12345), m31(1), m31(2), m31(3)]);
        claimed[0] += x;
        claimed[1] -= x;
    }
    let total: SecureField = claimed.iter().copied().sum::<SecureField>() + public_sum(&rel, &public);
    if !total.is_zero() {
        return Err(ProveError::NotAJoinSplit("LogUp does not balance"));
    }
    ch.mix_felts(&claimed);
    if check {
        let comps = Comps::new(&sz, &rel, &claimed, false);
        let int_all: Vec<Vec<BaseField>> = chain![i_js.iter().cloned(), i_rd.iter().cloned(), i_xs.iter().cloned()].collect();
        let full = TreeVec::new(vec![pre.clone(), orig.clone(), int_all]);
        check_component(&comps.js, &comps.js.eval_ref(), &full, sz.log_js);
        check_component(&comps.round, &comps.round.eval_ref(), &full, sz.log_round);
        check_component(&comps.xor, &comps.xor.eval_ref(), &full, sz.log_xor);
        eprintln!("check: every constraint and the ZK LogUp chain hold on the trace (random rows included)");
    }
    let salt2 = rnd_cols(rng, N_SALT, lc);
    let mut tb = cs.tree_builder();
    tb.extend_evals(
        chain![
            evals(&i_js, sz.log_js),
            evals(&i_rd, sz.log_round),
            evals(&i_xs, sz.log_xor),
            evals(&salt2, lc)
        ]
        .collect_vec(),
    );
    tb.commit(ch);
    tm.interaction_ms = now_ms() - t2;

    let t3 = now_ms();
    let comps = Comps::new(&sz, &rel, &claimed, false);
    let (stark, oods, queries, comp_tree, comp_coeff) = prove_zk(&comps.provers(), ch, cs, rng, cheat == Cheat::No)?;
    tm.prove_ms = now_ms() - t3;
    let ts = tree_log_sizes(&sz);
    let trees = vec![
        pre,
        chain![js.iter().cloned(), rd.iter().cloned(), xm.iter().cloned(), salt1].collect_vec(),
        chain![i_js, i_rd, i_xs, salt2].collect_vec(),
        comp_tree,
    ];
    let tree_logs = vec![ts[0].clone(), ts[1].clone(), ts[2].clone(), vec![lc; trees[3].len()]];
    for t in 0..4 {
        assert_eq!(trees[t].len(), tree_logs[t].len(), "debug tree {t} layout");
    }
    let dbg = Debug { oods, queries, js_rows: js_r, trees, tree_logs, comp_coeff: comp_coeff, rel };
    Ok((public, JsProof { claimed, stark, dbg: Some(dbg) }, tm))
}

trait EvalRef<E> {
    fn eval_ref(&self) -> &E;
}
impl<E: FrameworkEval> EvalRef<E> for FrameworkComponent<E> {
    fn eval_ref(&self) -> &E {
        self
    }
}

fn tv<'a>(pre: &'a [Vec<BaseField>], orig: &'a [Vec<BaseField>]) -> TreeVec<Vec<&'a Vec<BaseField>>> {
    TreeVec::new(vec![pre.iter().collect_vec(), orig.iter().collect_vec()])
}

fn check_component<E: FrameworkEval + Sync>(c: &FrameworkComponent<E>, ev_: &E, full: &TreeVec<Vec<Vec<BaseField>>>, log: u32) {
    let locs = c.trace_locations();
    let pre_idx = c.preprocessed_column_indices();
    let pre = pre_idx.iter().map(|i| &full[PREPROCESSED_TRACE_IDX][*i]).collect_vec();
    let o = &locs[ORIGINAL_TRACE_IDX];
    let it = &locs[INTERACTION_TRACE_IDX];
    let orig = full[ORIGINAL_TRACE_IDX][o.col_start..o.col_end].iter().collect_vec();
    let int = full[INTERACTION_TRACE_IDX][it.col_start..it.col_end].iter().collect_vec();
    let tv = TreeVec::new(vec![pre, orig, int]);
    stwo_constraint_framework::assert_constraints_on_trace(&tv, log, |ev| {
        ev_.evaluate(ev);
    }, SecureField::zero());
}

/// The ZK tail of the protocol (replaces stwo::prover::prove): composition committed UNSPLIT together with the FRI
/// mask RND and the salt columns; OODS point w; trace columns sampled at their lifted mask points around w, the
/// composition at pi(w) = 2w, RND at w.
fn prove_zk(
    components: &[&dyn ComponentProver<SimdBackend>],
    ch: &mut Blake2sChannel,
    mut cs: CommitmentSchemeProver<'_, SimdBackend, Blake2sMerkleChannel>,
    rng: &mut impl RngCore,
    sanity: bool,
) -> Result<(StarkProof<Blake2sMerkleHasher>, CirclePoint<SecureField>, Vec<usize>, Vec<Vec<BaseField>>, SecureField), ProveError> {
    let n_pre = cs.trees[PREPROCESSED_TRACE_IDX].polynomials.len();
    let cps = ComponentProvers { components: components.to_vec(), n_preprocessed_columns: n_pre };
    let random_coeff = ch.draw_secure_felt();
    let comp = {
        let trace = cs.trace();
        cps.compute_composition_polynomial(random_coeff, &trace, cs.twiddles, cs.config.fri_config.log_blowup_factor)
    };
    let lc = comp.log_size();
    assert_eq!(lc, cps.components().composition_log_degree_bound());
    let comp_polys = comp.into_coordinate_polys();
    let dom = CanonicCoset::new(lc).circle_domain();
    let mut comp_tree: Vec<Vec<BaseField>> = comp_polys.iter().map(|p| p.evaluate(dom).values.to_cpu()).collect();
    let rnd = rnd_cols(rng, N_RND + N_RND2 + N_SALT, lc);
    comp_tree.extend(rnd.iter().cloned());
    let mut tb = cs.tree_builder();
    tb.extend_polys(comp_polys);
    tb.extend_evals(evals(&rnd, lc));
    tb.commit(ch);
    let w = CirclePoint::<SecureField>::get_random_point(ch);
    let mut sp = cps.components().mask_points(w, lc, false);
    sp[ORIGINAL_TRACE_IDX].extend(vec![vec![]; N_SALT]);
    sp[INTERACTION_TRACE_IDX].extend(vec![vec![]; N_SALT]);
    sp.push(composition_tree_points(w));
    let ext = cs.prove_values(sp, ch);
    let queries = ext.aux.unsorted_query_locations.iter().copied().sorted().dedup().collect_vec();
    let proof = StarkProof(ext.proof);
    let got = composition_at(&proof).ok_or(ProveError::NotAJoinSplit("structure"))?;
    if sanity && got != cps.components().eval_composition_polynomial_at_point(w, &proof.sampled_values, random_coeff, lc) {
        return Err(ProveError::NotAJoinSplit("DEEP-ALI identity fails: constraints not satisfied"));
    }
    Ok((proof, w, queries, comp_tree, random_coeff))
}

pub fn fixture() -> Witness {
    let nsk: [u32; 8] = [0xCAFE, 1, 2, 3, 4, 5, 6, 7];
    let o1 = owner_of(&[0xB0B, 0, 0, 0, 0, 0, 0, 0]);
    let o2 = owner_of(&nsk);
    let (v_in, rho) = (1000u64, 0x1111u64);
    let cm_in = commit(v_in, &o2, rho);
    let leaves = [commit(5, &o1, 1), commit(6, &o1, 2), commit(7, &o1, 3), cm_in, commit(8, &o1, 4)];
    let (sibs, dirs, _root) = tree_path(&leaves, 3, D);
    Witness { nsk, v_in, rho, sibs, dirs, v1: 700, o1, r1: 0x2222, v2: 300, o2, r2: 0x3333, pv: 0, fee: 0 }
}
/// The MINT witness: fixture b balanced the OLD way (v1 + v2 + fee = v_in + pv) while pv is still paid out as the
/// unshield — outputs AND an exit worth pv more than the input. tests/test_stwo_js_honest_proof_... proves it must be
/// refused (lib.rs conservation invariant).
pub fn fixture_mint() -> Witness {
    let mut w = fixture_b();
    w.v2 = w.v_in + w.pv - w.fee - w.v1;
    w
}
pub fn pool_root_of_fixture() -> [u32; 8] {
    let nsk: [u32; 8] = [0xCAFE, 1, 2, 3, 4, 5, 6, 7];
    let o1 = owner_of(&[0xB0B, 0, 0, 0, 0, 0, 0, 0]);
    let o2 = owner_of(&nsk);
    let cm_in = commit(1000, &o2, 0x1111);
    let leaves = [commit(5, &o1, 1), commit(6, &o1, 2), commit(7, &o1, 3), cm_in, commit(8, &o1, 4)];
    tree_path(&leaves, 3, D).2
}

/// A second, unrelated witness (other key, rho, values, tree position, fee and public value) for the ZK test.
pub fn fixture_b() -> Witness {
    let nsk: [u32; 8] = [0x1234_5678, 0x9abc_def0, 0x0f0f_0f0f, 0xdead_beef, 0x0bad_f00d, 0x7777_7777, 0x2468_ace0, 0x1357_9bdf];
    let o1 = owner_of(&[0xFEED, 9, 9, 9, 9, 9, 9, 9]);
    let o2 = owner_of(&[0xBEEF, 1, 1, 1, 1, 1, 1, 1]);
    let owner = owner_of(&nsk);
    let (v_in, rho) = (0x0123_4567_89ab_cdefu64 & ((1 << 61) - 1), 0x5eed_5eed_5eedu64);
    let cm_in = commit(v_in, &owner, rho);
    let mut leaves: Vec<[u32; 8]> = (0..11).map(|i| commit(i * 3 + 1, &o1, i)).collect();
    leaves[10] = cm_in;
    let (sibs, dirs, _) = tree_path(&leaves, 10, D);
    let fee = 77u64;
    let pv = 5000u64;
    let v1 = v_in / 3;
    let v2 = v_in - pv - fee - v1;                          // v_in = v1 + v2 + fee + pv: pv is the unshield
    Witness { nsk, v_in, rho, sibs, dirs, v1, o1, r1: 0xaaaa_bbbb, v2, o2, r2: 0xcccc_dddd, pv, fee }
}

// ------------------------------------------------------------------------------------------------ the wallet's WASM ABI

/// Bytes of one packed witness (`wallet_witness`): nsk 32 | v_in 8 | rho 8 | sibs D x 32 | dirs D x 1 | v1 8 | o1 32 |
/// r1 8 | v2 8 | o2 32 | r2 8 | unshield 8 | fee 8. Integers little-endian; digests are the 32 BLAKE2s bytes (the 64-hex
/// form execnode/shielded_stwo.py carries), read as 8 little-endian u32 words exactly as `digest_words`.
pub const WALLET_WITNESS_BYTES: usize = 32 + 8 + 8 + D * 32 + D + 8 + 32 + 8 + 8 + 32 + 8 + 8 + 8;

/// Decode the wallet's packed witness. None: wrong length, a dir that is not 0/1, or values that do not conserve
/// (v_in = v1 + v2 + fee + unshield over the integers, no u64 wrap) — refused BEFORE any proving work, because the
/// prover's own LogUp check would only notice after the expensive trace, and a non-conserving witness is never honest.
pub fn wallet_witness(b: &[u8]) -> Option<Witness> {
    if b.len() != WALLET_WITNESS_BYTES {
        return None;
    }
    let mut o = 0usize;
    let mut take = |n: usize| {
        let s = &b[o..o + n];
        o += n;
        s
    };
    let dg = |s: &[u8]| -> [u32; 8] { digest_words(&<[u8; 32]>::try_from(s).unwrap()) };
    let u64le = |s: &[u8]| u64::from_le_bytes(<[u8; 8]>::try_from(s).unwrap());
    let nsk = dg(take(32));
    let v_in = u64le(take(8));
    let rho = u64le(take(8));
    let sibs: Vec<[u32; 8]> = (0..D).map(|_| dg(take(32))).collect();
    let dirs: Vec<u32> = take(D).iter().map(|&x| x as u32).collect();
    let v1 = u64le(take(8));
    let o1 = dg(take(32));
    let r1 = u64le(take(8));
    let v2 = u64le(take(8));
    let o2 = dg(take(32));
    let r2 = u64le(take(8));
    let pv = u64le(take(8));
    let fee = u64le(take(8));
    if dirs.iter().any(|&d| d > 1) {
        return None;
    }
    let out = v1.checked_add(v2)?.checked_add(fee)?.checked_add(pv)?;
    if out != v_in {
        return None;
    }
    Some(Witness { nsk, v_in, rho, sibs, dirs, v1, o1, r1, v2, o2, r2, pv, fee })
}

/// The wallet's output record: root | nf | cm1 | cm2 (32 bytes each, `words_digest`) | unshield u64 | fee u64 | the
/// proof's wire bytes (src/wire.rs) — everything the exec layer's `stwo_js` bundle carries except the destination.
pub fn wallet_output(public: &Public, proof: &JsProof) -> Vec<u8> {
    let mut out = Vec::new();
    for d in [&public.root, &public.nf, &public.cm1, &public.cm2] {
        out.extend_from_slice(&words_digest(d));
    }
    out.extend_from_slice(&public.pv.to_le_bytes());
    out.extend_from_slice(&public.fee.to_le_bytes());
    out.extend_from_slice(&wire::encode(proof));
    out
}

/// Result codes of the wallet ABI (in addition to lib.rs RC_OK / RC_BAD_ARGS / RC_REJECTED).
pub const RC_NO_SEED: i32 = 5;
pub const RC_SEED_REUSED: i32 = 6;
pub const RC_NOT_A_JOINSPLIT: i32 = 7;

/// Seed bookkeeping shared by the WASM ABI and its native tests: a seed is accepted once, never all-zero, never twice.
/// THE ZERO-KNOWLEDGE OF A PROOF IS ITS SEED: every random row, mask and salt is ChaCha20 of it, so two proofs from one
/// seed share their randomness and their difference is a function of the two witnesses alone. A wallet that passes a
/// constant (an uninitialised buffer, a failed getRandomValues) must get a refusal, never a proof.
#[derive(Default)]
pub struct SeedBook {
    fresh: Option<[u8; 32]>,
    used: Vec<[u8; 32]>,
}
impl SeedBook {
    pub fn offer(&mut self, s: [u8; 32]) -> i32 {
        if s == [0u8; 32] {
            return RC_NO_SEED;
        }
        if self.used.contains(&s) || self.fresh == Some(s) {
            return RC_SEED_REUSED;
        }
        self.fresh = Some(s);
        RC_OK
    }
    /// The fresh seed, consumed: a second proof needs a second offer.
    pub fn take(&mut self) -> Option<[u8; 32]> {
        let s = self.fresh.take()?;
        self.used.push(s);
        Some(s)
    }
}

/// Prove one wallet witness with a seed from `book` at the pinned node config -> (rc, output record).
pub fn wallet_prove(book: &mut SeedBook, witness: &[u8], dest: &[u8]) -> (i32, Vec<u8>) {
    let Some(w) = wallet_witness(witness) else { return (RC_NOT_A_JOINSPLIT, vec![]) };
    let Some(seed) = book.take() else { return (RC_NO_SEED, vec![]) };
    match prove_js(&w, aux_of(dest), node_config(), false, seed) {
        Ok((public, proof, _)) => (RC_OK, wallet_output(&public, &proof)),
        Err(_) => (RC_NOT_A_JOINSPLIT, vec![]),
    }
}

/// The wallet's WASM exports (static/stark/stwo_js.js drives them from a Worker). No imports: a panic is a trap, and
/// the JS side drops the instance after one. Memory crosses as (pointer, length) pairs from `stwo_alloc`.
#[cfg(target_arch = "wasm32")]
mod wasm {
    use super::*;
    use std::sync::Mutex;
    static SEEDS: Mutex<Option<SeedBook>> = Mutex::new(None);
    static OUT: Mutex<Vec<u8>> = Mutex::new(Vec::new());

    unsafe fn bytes<'a>(p: *const u8, n: usize) -> &'a [u8] {
        if n == 0 { &[] } else { unsafe { std::slice::from_raw_parts(p, n) } }
    }

    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_abi_version() -> u32 {
        1
    }
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_alloc(n: usize) -> *mut u8 {
        let mut v = Vec::<u8>::with_capacity(n.max(1));
        let p = v.as_mut_ptr();
        std::mem::forget(v);
        p
    }
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_free(p: *mut u8, n: usize) {
        if !p.is_null() {
            drop(unsafe { Vec::from_raw_parts(p, 0, n.max(1)) });
        }
    }
    /// 32 bytes from crypto.getRandomValues. RC_OK, RC_NO_SEED (all zero) or RC_SEED_REUSED (seen by this instance).
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_seed(p: *const u8) -> i32 {
        if p.is_null() {
            return RC_BAD_ARGS;
        }
        let s: [u8; 32] = unsafe { bytes(p, 32) }.try_into().unwrap();
        SEEDS.lock().unwrap().get_or_insert_with(SeedBook::default).offer(s)
    }
    /// Prove the packed witness (`wallet_witness`) bound to `dest` (the unshield address's UTF-8, empty for a private
    /// transfer). RC_OK leaves the record (`wallet_output`) at stwo_out_ptr / stwo_out_len.
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_prove(wit: *const u8, wit_len: usize, dest: *const u8, dest_len: usize) -> i32 {
        if wit.is_null() || (dest.is_null() && dest_len != 0) {
            return RC_BAD_ARGS;
        }
        OUT.lock().unwrap().clear();
        let mut g = SEEDS.lock().unwrap();
        let (rc, out) = wallet_prove(g.get_or_insert_with(SeedBook::default), unsafe { bytes(wit, wit_len) }, unsafe { bytes(dest, dest_len) });
        *OUT.lock().unwrap() = out;
        rc
    }
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_out_ptr() -> *const u8 {
        OUT.lock().unwrap().as_ptr()
    }
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_out_len() -> usize {
        OUT.lock().unwrap().len()
    }
    /// Verify the last output record exactly as a node does (`verify_node`, pinned config) against `dest`: the wallet
    /// checks its own proof before publishing it, so a bad proof never reaches the chain or marks a note spent.
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_verify_out(dest: *const u8, dest_len: usize) -> i32 {
        if dest.is_null() && dest_len != 0 {
            return RC_BAD_ARGS;
        }
        let o = OUT.lock().unwrap();
        if o.len() < 144 {
            return RC_BAD_ARGS;
        }
        let d = |i: usize| -> [u8; 32] { o[32 * i..32 * i + 32].try_into().unwrap() };
        let pv = u64::from_le_bytes(o[128..136].try_into().unwrap());
        let fee = u64::from_le_bytes(o[136..144].try_into().unwrap());
        verify_node(&o[144..], d(0), d(1), d(2), d(3), pv, fee, unsafe { bytes(dest, dest_len) }).0
    }
    /// The 32-byte aux digest of `dest` into `out` (lib.rs aux_of), for the wallet's cross-check.
    #[unsafe(no_mangle)]
    pub extern "C" fn stwo_aux(dest: *const u8, dest_len: usize, out: *mut u8) -> i32 {
        nado_stwo_js_aux(dest, dest_len, out)
    }
}

pub fn shape(n_queries: usize) -> Vec<(usize, usize)> {
    tree_log_sizes(&Sizes::new(n_queries)).iter().map(|t| (t.len(), t.iter().map(|l| 1usize << l).sum())).collect()
}

/// Original-trace column counts (JS, ROUND, XOR), in allocation order.
pub fn orig_layout() -> (usize, usize, usize) {
    let (d, z) = (Rel::dummy(), SecureField::zero());
    let n = |i: InfoEvaluator| i.mask_offsets[ORIGINAL_TRACE_IDX].len();
    (
        n(JsEval { log: 4, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty())),
        n(RoundEval { log: 4, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty())),
        n(XorEval { log: 4, rel: d, claimed: z, track: false }.evaluate(InfoEvaluator::empty())),
    )
}


/// T5 of zktest: the simulation argument, checked numerically on a real proof. For JS original column `col` (a
/// register: offsets 0 and +1), take every value the proof reveals about it: the opened values at the lifted query
/// points, the two OODS samples (QM31 = 4 M31 functionals each) and the 2 evaluations per query hidden inside the
/// opened composition value. Replace the column's REAL rows by `other` (a different witness's value) and solve, over
/// M31, for the random rows so that every one of those revealed values is unchanged. Returns
/// (equations, rank, unknowns, solvable, revealed values re-checked equal).
pub fn hiding_solve(proof: &JsProof, cfg: PcsConfig, col: usize, offsets: &[isize], other: u32) -> (usize, usize, usize, bool, bool) {
    let dbg = proof.dbg.as_ref().unwrap();
    let sz = Sizes::new(cfg.fri_config.n_queries);
    let s = sz.log_js;
    let n = 1usize << s;
    let lc = sz.log_comp();
    let lt = cfg.min_lifting_log_size;
    let a: Vec<BaseField> = (0..n).map(|r| m31(dbg.js_rows[r][col])).collect();
    let interp = |vals: &[BaseField]| {
        let mut st = vec![BaseField::zero(); n];
        for r in 0..n {
            st[pos(r, s)] = vals[r];
        }
        CircleEvaluation::<SimdBackend, BaseField, BitReversedOrder>::new(CanonicCoset::new(s).circle_domain(), st.into_iter().collect::<BaseColumn>())
            .interpolate()
    };
    let fa = interp(&a);
    let step = CanonicCoset::new(s).step();
    let dom = CanonicCoset::new(lt).circle_domain();
    // revealed points: (point, is_qm31, value under A)
    let mut pts: Vec<CirclePoint<SecureField>> = vec![];
    let mut ok_check = true;
    let opened = &proof.stark.0.queried_values[1][col];
    for (i, &p) in dbg.queries.iter().enumerate() {
        let x = dom.at(bit_reverse_index(p, lt));
        let q_open = x.repeated_double(lc - s).into_ef();
        ok_check &= fa.eval_at_point(q_open) == SecureField::from(opened[i]);
        pts.push(q_open);
        for &k in offsets {
            pts.push((x.repeated_double(lc - 1 - s) + step.mul_signed(k)).into_ef());
        }
    }
    let n_base = pts.len();
    let wz = dbg.oods.repeated_double(lc - s);
    for (j, &k) in offsets.iter().enumerate() {
        let pt = wz + step.mul_signed(k).into_ef();
        ok_check &= fa.eval_at_point(pt) == proof.stark.0.sampled_values[1][col][j];
        pts.push(pt);
    }
    assert!(ok_check, "point bookkeeping does not reproduce the proof's revealed values");
    // basis polynomials of the free rows [R_JS, n)
    let free: Vec<usize> = (R_JS..n).collect();
    let k = free.len();
    let unit = |r: usize| {
        let mut v = vec![BaseField::zero(); n];
        v[r] = BaseField::one();
        interp(&v)
    };
    let neq = n_base + 4 * (pts.len() - n_base);
    let mut m = vec![vec![BaseField::zero(); k + 1]; neq];
    let put = |m: &mut Vec<Vec<BaseField>>, colj: usize, poly_vals: Vec<SecureField>| {
        for (i, v) in poly_vals.iter().enumerate() {
            if i < n_base {
                m[i][colj] = v.to_m31_array()[0];
            } else {
                let c = v.to_m31_array();
                for t in 0..4 {
                    m[n_base + 4 * (i - n_base) + t][colj] = c[t];
                }
            }
        }
    };
    for (j, &r) in free.iter().enumerate() {
        let f = unit(r);
        put(&mut m, j, pts.iter().map(|p| f.eval_at_point(*p)).collect());
    }
    // right-hand side: -(B - A) on the real rows
    let mut delta = vec![BaseField::zero(); n];
    for r in 0..R_JS {
        delta[r] = m31(other) - a[r];
    }
    let fd = interp(&delta);
    put(&mut m, k, pts.iter().map(|p| -fd.eval_at_point(*p)).collect());
    // Gaussian elimination over M31
    let mut rank = 0;
    let mut pivots = vec![];
    for c in 0..k {
        let Some(pr) = (rank..neq).find(|&i| !m[i][c].is_zero()) else { continue };
        m.swap(rank, pr);
        let inv = m[rank][c].inverse();
        for t in c..=k {
            m[rank][t] *= inv;
        }
        for i in 0..neq {
            if i != rank && !m[i][c].is_zero() {
                let f = m[i][c];
                for t in c..=k {
                    let sub = m[rank][t] * f;
                    m[i][t] -= sub;
                }
            }
        }
        pivots.push(c);
        rank += 1;
    }
    let solvable = (rank..neq).all(|i| m[i][k].is_zero());
    if !solvable {
        return (neq, rank, k, false, false);
    }
    let mut sol = vec![BaseField::zero(); k];
    for (i, &c) in pivots.iter().enumerate() {
        sol[c] = m[i][k];
    }
    // the alternative column: B on the real rows, A's random rows + the solution on the free rows
    let mut b = a.clone();
    for r in 0..R_JS {
        b[r] = m31(other);
    }
    for (j, &r) in free.iter().enumerate() {
        b[r] += sol[j];
    }
    let fb = interp(&b);
    let same = pts.iter().all(|p| fb.eval_at_point(*p) == fa.eval_at_point(*p));
    (neq, rank, k, true, same)
}


// ------------------------------------------------------------------------------------------------ zkproof/zkcheck hooks
// Read-only views of the protocol for the mechanical ZK checks in ../zkproof (zkcheck). None of these is used by
// prove_js / verify_js.

/// (z, alpha) of the LogUp relation.
pub fn rel_z_alpha(rel: &Rel) -> (SecureField, SecureField) {
    (rel.0.z, rel.0.alpha)
}
/// The blind-chain denominator d(t) for tag k (1 or 2) and the four uniform entries t.
pub fn blind_denominator(rel: &Rel, k: u32, t: [BaseField; 4]) -> SecureField {
    let v = chain![[m31(TAG_BLIND), m31(k)], t].collect_vec();
    <Rel as Relation<BaseField, SecureField>>::combine(rel, &v)
}
/// Per component (JS, ROUND, XOR): the mask offsets of every ORIGINAL and INTERACTION column, in allocation order.
pub fn component_offsets(sz: &Sizes) -> Vec<(u32, Vec<Vec<isize>>, Vec<Vec<isize>>)> {
    let (d, z) = (Rel::dummy(), SecureField::zero());
    let f = |i: InfoEvaluator, log: u32| (log, i.mask_offsets[ORIGINAL_TRACE_IDX].clone(), i.mask_offsets[INTERACTION_TRACE_IDX].clone());
    vec![
        f(JsEval { log: sz.log_js, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_js),
        f(RoundEval { log: sz.log_round, rel: d.clone(), claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_round),
        f(XorEval { log: sz.log_xor, rel: d, claimed: z, track: false }.evaluate(InfoEvaluator::empty()), sz.log_xor),
    ]
}
/// Real-row counts (rows [0, R) real, R = blind) per component.
pub const R_REAL: [usize; 3] = [R_JS, R_ROUND, R_XOR];
/// Columns of the JS original trace that are PUBLIC constants on every row (the BLAKE2s start state st[0]).
pub fn js_public_cols() -> std::ops::Range<usize> {
    JS_ST0
}
/// Run `f` with the verifier's components for these challenges.
pub fn with_components<T>(sz: &Sizes, rel: &Rel, claimed: &[SecureField], f: impl FnOnce(&Components<'_>) -> T) -> T {
    let comps = Comps::new(sz, rel, claimed, false);
    let n_pre = preprocessed_ids().len();
    let components = Components { components: comps.verifiers(), n_preprocessed_columns: n_pre };
    f(&components)
}
/// Assert every constraint and the ZK LogUp chain of each component on a full trace [pre, orig, interaction]
/// (without salt columns). Returns, per component, whether every constraint holds.
pub fn constraints_hold(sz: &Sizes, rel: &Rel, claimed: &[SecureField], full: [Vec<Vec<BaseField>>; 3]) -> [bool; 3] {
    let comps = Comps::new(sz, rel, claimed, false);
    let full = TreeVec::new(full.to_vec());
    let run = |k: usize| {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| match k {
            0 => check_component(&comps.js, &comps.js.eval_ref(), &full, sz.log_js),
            1 => check_component(&comps.round, &comps.round.eval_ref(), &full, sz.log_round),
            _ => check_component(&comps.xor, &comps.xor.eval_ref(), &full, sz.log_xor),
        }))
        .is_ok()
    };
    [run(0), run(1), run(2)]
}
/// The verifier's transcript up to and including the DEEP random coefficient (mirrors verify_js, then the first
/// two steps of CommitmentSchemeVerifier::verify_values). Returns (composition coefficient, w, DEEP coefficient).
pub fn replay_challenges(public: &Public, proof: &JsProof, cfg: PcsConfig) -> (SecureField, CirclePoint<SecureField>, SecureField) {
    let sz = Sizes::new(cfg.fri_config.n_queries);
    let ch = &mut Blake2sChannel::default();
    cfg.mix_into(ch);
    public.mix_into(ch);
    let sizes = tree_log_sizes(&sz);
    let cs = &mut CommitmentSchemeVerifier::<Blake2sMerkleChannel>::new(cfg);
    cs.commit(proof.stark.commitments[0], &sizes[0], ch);
    cs.commit(proof.stark.commitments[1], &sizes[1], ch);
    let _rel = Rel::draw(ch);
    ch.mix_felts(&proof.claimed);
    cs.commit(proof.stark.commitments[2], &sizes[2], ch);
    let comp_coeff = ch.draw_secure_felt();
    cs.commit(proof.stark.commitments[3], &[sz.log_comp(); SECURE_EXTENSION_DEGREE + N_RND + N_RND2 + N_SALT], ch);
    let w = CirclePoint::<SecureField>::get_random_point(ch);
    ch.mix_felts(&proof.stark.sampled_values.clone().flatten_cols());
    let deep = ch.draw_secure_felt();
    (comp_coeff, w, deep)
}
/// Sample points of every committed column (the verifier's `sp` in verify_js).
pub fn sample_points(sz: &Sizes, rel: &Rel, claimed: &[SecureField], w: CirclePoint<SecureField>) -> TreeVec<ColumnVec<Vec<CirclePoint<SecureField>>>> {
    with_components(sz, rel, claimed, |c| {
        let mut sp = c.mask_points(w, sz.log_comp(), false);
        sp[ORIGINAL_TRACE_IDX].extend(vec![vec![]; N_SALT]);
        sp[INTERACTION_TRACE_IDX].extend(vec![vec![]; N_SALT]);
        sp.push(composition_tree_points(w));
        sp
    })
}
