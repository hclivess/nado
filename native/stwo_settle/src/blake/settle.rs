//! Prove / verify a SEQUENTIAL BATCH of compressed-tree writes (update, insert, delete; path.rs) (doc/stwo/g4-settlement-statement.md): upstream's
//! BLAKE2s scheduler + rounds + XOR tables, plus the path component (path.rs) that consumes the scheduler's compressions.
//! The fixed XOR tables dominate one update's cost, so a span's updates share one trace.
//!
//! SOUNDNESS CHOICES made here, each one load-bearing:
//!  * the statement (every write's op, depths, key, value hashes, neighbour key, both roots) is mixed into the transcript BEFORE any
//!    lookup element is drawn, so a prover cannot pick a statement after seeing the challenges;
//!  * the verifier rebuilds the path's preprocessed columns from the shapes alone and checks every claimed sum plus the
//!    public terms it computes itself total ZERO, returning an error (upstream's example asserted);
//!  * the verifier chains the batch natively: update i's new root is update i+1's old root, so the proof covers ONE
//!    sequence of states from the first old root to the last new root, not K unrelated updates;
//!  * the verifier checks each shape natively: a split's depth is the first bit where the key and its neighbour differ,
//!    the absent value hashes are zero, the depths fit a 256-bit key;
//!  * the verifier refuses a proof whose PcsConfig is weaker than the node's (upstream's example accepted 5 bits).

use std::simd::u32x16;

use itertools::{Itertools, chain, multiunzip};
use num_traits::{One, Zero};
use stwo::core::air::Component;
use stwo::core::channel::{Blake2sChannel, Channel};
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::SecureField;
use stwo::core::fields::FieldExpOps;
use stwo::core::pcs::{CommitmentSchemeVerifier, PcsConfig, TreeVec};
use stwo::core::poly::circle::CanonicCoset;
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::{Blake2sMerkleChannel, Blake2sMerkleHasher};
use stwo::core::verifier::{VerificationError, verify};
use stwo::prover::backend::simd::SimdBackend;
use stwo::prover::backend::simd::column::BaseColumn;
use stwo::prover::backend::simd::m31::{LOG_N_LANES, PackedBaseField};
use stwo::prover::backend::simd::qm31::PackedSecureField;
use stwo::prover::backend::Column;
use stwo::prover::poly::BitReversedOrder;
use stwo::prover::poly::circle::{CircleEvaluation, PolyOps};
use stwo::prover::{CommitmentSchemeProver, ComponentProver, prove};
use stwo_constraint_framework::{
    FrameworkEval, LogupTraceGenerator, ORIGINAL_TRACE_IDX, PREPROCESSED_TRACE_IDX, Relation, TraceLocationAllocator,
};

pub use super::path::Op;
use super::path::{
    N_PUB, P_DIR, P_KEY, P_KEY2, P_LVL, P_OPEN, P_OPEN_DST, P_REAL, P_ROOT_NEW, P_ROOT_OLD, P_SPLIT, P_SPLIT_SRC, P_UPD,
    P_VH_NEW, P_VH_OLD, PathComponent, PathEval, PubElements, SEL, Shape, Slot, TAG_DIR, TAG_KEY, TAG_KEY2,
    TAG_LINK_OPEN, TAG_LINK_SPLIT, TAG_ROOT_NEW, TAG_ROOT_OLD, TAG_VH_NEW, TAG_VH_OLD, batch_rows, pos,
    preprocessed_logical, preprocessed_values, sel_id, slots,
};
use super::preprocessed_columns::XorTable;
use super::round::{BlakeRoundComponent, BlakeRoundEval, RoundElements, blake_round_info};
use super::scheduler::{self, BlakeElements, BlakeInput, BlakeSchedulerComponent, BlakeSchedulerEval, blake_scheduler_info};
use super::xor_table::{xor4, xor7, xor8, xor9, xor12};
use super::{BlakeXorElements, N_ROUNDS, ROUND_LOG_SPLIT, XorAccums, round};
use crate::csmt_ref::{PERSON_LEAF, PERSON_NODE, bit, compress, h0, rounds, v_init};

/// The node's settlement proof configuration (the one stwo_js's node_config uses: 340 bits).
pub fn node_config() -> PcsConfig {
    PcsConfig { pow_bits: 20, fri_config: stwo::core::fri::FriConfig::new(0, 2, 160, 1), min_lifting_log_size: 0 }
}

/// One write's witness. Absent value hashes (an insert's old, a delete's new) are zero.
#[derive(Clone, Debug)]
pub struct Update {
    pub op: Op,
    pub key: [u32; 8],
    pub vh_old: [u32; 8],
    pub vh_new: [u32; 8],
    /// the SHALLOW side's siblings, root first (csmt.Tree.prove): for UPDATE and *_EMPTY the path's own siblings; for
    /// the split kinds the siblings above the neighbour's leaf. Its length is the shallow depth da.
    pub sibs: Vec<[u32; 8]>,
    /// split kinds: the neighbour leaf (k2 and its value hash) and the deep leaf's depth db (first differing bit + 1)
    pub k2: [u32; 8],
    pub vh2: [u32; 8],
    pub db: usize,
    /// *_EMPTY at depth > 0: the two children of sibs[da-1], which is an internal node
    pub open: ([u32; 8], [u32; 8]),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UpdateStatement {
    pub op: Op,
    pub da: usize,
    pub db: usize,
    pub key: [u32; 8],
    pub vh_old: [u32; 8],
    pub vh_new: [u32; 8],
    /// the neighbour key of a split kind (zero otherwise)
    pub k2: [u32; 8],
    pub root_old: [u32; 8],
    pub root_new: [u32; 8],
}
impl UpdateStatement {
    pub fn shape(&self) -> Shape {
        Shape { op: self.op, da: self.da, db: self.db }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Statement {
    pub updates: Vec<UpdateStatement>,
}
impl Statement {
    fn mix_into(&self, ch: &mut impl Channel) {
        ch.mix_u64(self.updates.len() as u64);
        for u in &self.updates {
            ch.mix_u64(u.op as u64);
            ch.mix_u64(u.da as u64);
            ch.mix_u64(u.db as u64);
            for w in [u.key, u.vh_old, u.vh_new, u.k2, u.root_old, u.root_new] {
                ch.mix_u32s(&w);
            }
        }
    }
    pub fn shapes(&self) -> Vec<Shape> {
        self.updates.iter().map(|u| u.shape()).collect()
    }
}

#[derive(Clone)]
pub struct BatchProof {
    pub log_size: u32,
    pub sums: Vec<SecureField>,
    pub stark: StarkProof<Blake2sMerkleHasher>,
}

/// What a row hashes.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Hash {
    None,
    Leaf,
    Node,
}

/// One path row's witness: its compression's message, what it hashes, the direction bit and sibling (node rows), and the
/// inverse of the sibling's limb sum (the nonzero check).
#[derive(Clone)]
struct Row {
    m: [u32; 16],
    hash: Hash,
    dir: u32,
    sib: [u32; 8],
    inv: u32,
    /// the round output, when it is not the compression's (only a Tamper sets it)
    out: Option<[u32; 16]>,
}
const PAD: Row = Row { m: [0; 16], hash: Hash::None, dir: 0, sib: [0; 8], inv: 0, out: None };

/// TEST ONLY: a dishonest prover's witness, each one breaking exactly ONE shape constraint of path.rs while keeping every
/// hash chain consistent, so the only thing that can refuse it is that constraint (tests/test_a_stwo_proof_of_a_tree_
/// update_proves_csmt_roots_and_refuses_forgeries.py). Applied to every write it fits.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tamper {
    None,
    /// the new tree's top sibling differs from the old tree's (P_SHARED): a write that also rewrites another subtree
    SharedSibling,
    /// a split's EMPTY sibling is not empty (P_ESIB): an insert that also invents a subtree
    EmptySibling,
    /// a split's sibling is not the neighbour's leaf (the SPLIT link): an insert that also rewrites the neighbour
    SplitLink,
    /// an EMPTY start that is not 32 zero bytes (P_EMPTY): an insert that deletes a whole subtree
    EmptyStart,
}

fn cat(a: &[u32; 8], b: &[u32; 8]) -> [u32; 16] {
    std::array::from_fn(|i| if i < 8 { a[i] } else { b[i - 8] })
}

fn limb_sum_inv(w: &[u32; 8]) -> u32 {
    let s: u32 = w.iter().map(|x| (x & 0xffff) + (x >> 16)).sum();
    if s == 0 { 0 } else { f(s).inverse().0 }
}

/// The rows of one write, walking path.rs `slots` (the same walk the verifier's preprocessed columns make), and the
/// statement they prove.
fn rows_of(u: &Update, tamper: Tamper) -> (Vec<Row>, UpdateStatement) {
    let op = u.op;
    let da = u.sibs.len();
    let db = if op.split_kind() { u.db } else { da };
    let sh = Shape { op, da, db };
    let empty = [0u32; 8];
    let junk = [0x5eed_0001u32, 2, 3, 4, 5, 6, 7, 8];
    let b_sib = |l: usize| -> [u32; 8] {
        if l < da {
            if tamper == Tamper::SharedSibling && l == 0 { junk } else { u.sibs[l] }
        } else if l + 1 < db {
            if tamper == Tamper::EmptySibling { junk } else { empty }
        } else {
            let vh2 = if tamper == Tamper::SplitLink { junk } else { u.vh2 };
            compress(PERSON_LEAF, &cat(&u.k2, &vh2)) // the split level: the neighbour's leaf
        }
    };
    let (a_key, a_vh) = if op == Op::Update { (u.key, u.vh_old) } else { (u.k2, u.vh2) };
    let b_vh = if op.b_is_old() { u.vh_old } else { u.vh_new };
    let node_row = |h: &[u32; 8], sib: [u32; 8], l: usize| -> Row {
        let dir = bit(&u.key, l);
        let m = if dir == 1 { cat(&sib, h) } else { cat(h, &sib) };
        Row { m, hash: Hash::Node, dir, sib, inv: limb_sum_inv(&sib), out: None }
    };
    let (mut a, mut b) = (empty, empty);
    let mut rows = vec![];
    for s in slots(&sh) {
        let r = match s {
            Slot::AEmpty if tamper == Tamper::EmptyStart => {
                Row { out: Some(std::array::from_fn(|i| if i < 8 { junk[i] } else { 0 })), ..PAD }
            }
            Slot::Pad | Slot::AEmpty => PAD,
            Slot::Open => Row { m: cat(&u.open.0, &u.open.1), hash: Hash::Node, ..PAD },
            Slot::ALeaf => Row { m: cat(&a_key, &a_vh), hash: Hash::Leaf, ..PAD },
            Slot::BLeaf => Row { m: cat(&u.key, &b_vh), hash: Hash::Leaf, ..PAD },
            Slot::ANode(l) => node_row(&a, u.sibs[l], l),
            Slot::BNode(l) => node_row(&b, b_sib(l), l),
        };
        let h = match r.hash {
            Hash::None => r.out.map(|o| std::array::from_fn(|i| o[i] ^ o[i + 8])).unwrap_or(empty),
            Hash::Leaf => compress(PERSON_LEAF, &r.m),
            Hash::Node => compress(PERSON_NODE, &r.m),
        };
        match s {
            Slot::ALeaf | Slot::ANode(_) => a = h,
            Slot::BLeaf | Slot::BNode(_) => b = h,
            _ => {}
        }
        rows.push(r);
    }
    let (root_old, root_new) = if op.b_is_old() { (b, a) } else { (a, b) };
    let st = UpdateStatement {
        op,
        da,
        db,
        key: u.key,
        vh_old: if matches!(op, Op::InsertEmpty | Op::InsertSplit) { empty } else { u.vh_old },
        vh_new: if op.b_is_old() { empty } else { u.vh_new },
        k2: if op.split_kind() { u.k2 } else { empty },
        root_old,
        root_new,
    };
    (rows, st)
}

fn batch_of(us: &[Update], tamper: Tamper) -> (Vec<Row>, Statement) {
    let mut rows = vec![];
    let mut updates = vec![];
    for u in us {
        let (r, st) = rows_of(u, tamper);
        rows.extend(r);
        updates.push(st);
    }
    (rows, Statement { updates })
}

fn log_size_for(shapes: &[Shape]) -> u32 {
    (batch_rows(shapes).next_power_of_two().trailing_zeros()).max(LOG_N_LANES)
}

type Evals = Vec<CircleEvaluation<SimdBackend, BaseField, BitReversedOrder>>;

fn evals(cols: Vec<Vec<BaseField>>, log: u32) -> Evals {
    let dom = CanonicCoset::new(log).circle_domain();
    cols.into_iter().map(|c| CircleEvaluation::new(dom, c.into_iter().collect::<BaseColumn>())).collect()
}

fn f(x: u32) -> BaseField {
    BaseField::from_u32_unchecked(x)
}

fn path_preprocessed(shapes: &[Shape], log: u32) -> Evals {
    evals(preprocessed_values(shapes, log).into_iter().map(|c| c.into_iter().map(f).collect()).collect(), log)
}

/// One row's every lookup entry in the order PathEval adds them: (numerator, the relation's values) — so the interaction
/// trace pairs them exactly as finalize_logup_in_pairs does.
enum Rel {
    Blake,
    Xor8,
    Pub,
}

fn path_row_entries(r: &Row, sel: &[u32]) -> (Vec<u32>, Vec<(i64, Rel, Vec<u32>)>) {
    let mut cols: Vec<u32> = vec![];
    let mut ents: Vec<(i64, Rel, Vec<u32>)> = vec![];
    let m = r.m;
    let (v0, hc) = match r.hash {
        Hash::None => ([0u32; 16], [0u32; 8]),
        Hash::Leaf => (v_init(PERSON_LEAF), h0(PERSON_LEAF)),
        Hash::Node => (v_init(PERSON_NODE), h0(PERSON_NODE)),
    };
    let out = r.out.unwrap_or_else(|| if r.hash == Hash::None { [0u32; 16] } else { rounds(v0, &m) });
    let limbs = |w: &[u32]| w.iter().flat_map(|x| [x & 0xffff, x >> 16]).collect_vec();
    cols.extend(limbs(&m));
    cols.extend(limbs(&out));
    ents.push((-(sel[P_REAL] as i64), Rel::Blake, chain![limbs(&v0), limbs(&out), limbs(&m)].collect()));
    for x in limbs(&m) {
        let (lo, hi) = (x & 0xff, x >> 8);
        cols.push(hi);
        ents.push((1, Rel::Xor8, vec![lo, 0, lo]));
        ents.push((1, Rel::Xor8, vec![hi, 0, hi]));
    }
    let mut dg = [0u32; 8];
    for i in 0..8 {
        for limb in 0..2 {
            let a = (out[i] >> (16 * limb)) & 0xffff;
            let b = (out[i + 8] >> (16 * limb)) & 0xffff;
            let c = (hc[i] >> (16 * limb)) & 0xffff;
            let (al, ah, bl, bh, cl, ch) = (a & 0xff, a >> 8, b & 0xff, b >> 8, c & 0xff, c >> 8);
            let (tl, th) = (al ^ bl, ah ^ bh);
            let (dl, dh) = (tl ^ cl, th ^ ch);
            cols.extend([ah, bh, tl, th, dl, dh]);
            ents.push((1, Rel::Xor8, vec![al, bl, tl]));
            ents.push((1, Rel::Xor8, vec![ah, bh, th]));
            ents.push((1, Rel::Xor8, vec![tl, cl, dl]));
            ents.push((1, Rel::Xor8, vec![th, ch, dh]));
            dg[i] |= (dl | (dh << 8)) << (16 * limb);
        }
    }
    cols.push(r.dir);
    cols.extend(limbs(&r.sib));
    cols.push(r.inv);
    let upd = sel[P_UPD];
    let tup = |tag: u32, vals: Vec<u32>| {
        let mut t = vec![tag, upd];
        t.extend(vals);
        t.resize(N_PUB, 0);
        t
    };
    let src_tag = sel[P_SPLIT_SRC] * TAG_LINK_SPLIT + sel[P_OPEN] * TAG_LINK_OPEN;
    let dst_tag = sel[P_SPLIT] * TAG_LINK_SPLIT + sel[P_OPEN_DST] * TAG_LINK_OPEN;
    ents.push(((sel[P_SPLIT_SRC] + sel[P_OPEN]) as i64, Rel::Pub, tup(src_tag, limbs(&dg))));
    ents.push((-((sel[P_SPLIT] + sel[P_OPEN_DST]) as i64), Rel::Pub, tup(dst_tag, limbs(&r.sib))));
    let neg = |i: usize| -(sel[i] as i64);
    ents.push((neg(P_KEY), Rel::Pub, tup(TAG_KEY, limbs(&m[0..8]))));
    ents.push((neg(P_KEY2), Rel::Pub, tup(TAG_KEY2, limbs(&m[0..8]))));
    ents.push((neg(P_VH_OLD), Rel::Pub, tup(TAG_VH_OLD, limbs(&m[8..16]))));
    ents.push((neg(P_VH_NEW), Rel::Pub, tup(TAG_VH_NEW, limbs(&m[8..16]))));
    ents.push((neg(P_DIR), Rel::Pub, tup(TAG_DIR, vec![sel[P_LVL], r.dir])));
    ents.push((neg(P_ROOT_OLD), Rel::Pub, tup(TAG_ROOT_OLD, limbs(&dg))));
    ents.push((neg(P_ROOT_NEW), Rel::Pub, tup(TAG_ROOT_NEW, limbs(&dg))));
    (cols, ents)
}

fn signed(x: i64) -> BaseField {
    if x >= 0 { f(x as u32) } else { -f((-x) as u32) }
}

struct PathTrace {
    trace: Evals,
    /// per row: the entries (numerator, relation, values) — for the interaction trace
    entries: Vec<Vec<(i64, Rel, Vec<u32>)>>,
}

fn path_trace(rows: &[Row], shapes: &[Shape], log: u32, xor: &mut XorAccums) -> PathTrace {
    let n = 1usize << log;
    let sels = preprocessed_logical(shapes, log);
    // built per LOGICAL row, then placed at its storage index (path.rs pos): the masks at -1 / -2 are coset steps
    let mut cols: Vec<Vec<BaseField>> = vec![];
    let mut entries: Vec<Vec<(i64, Rel, Vec<u32>)>> = (0..n).map(|_| vec![]).collect();
    let mut xa: Vec<Vec<(u32, u32)>> = vec![vec![]; n];
    for r in 0..n {
        let p = pos(r, log);
        let sel: Vec<u32> = sels.iter().map(|c| c[r]).collect();
        let (row_cols, ents) = path_row_entries(rows.get(r).unwrap_or(&PAD), &sel);
        if cols.is_empty() {
            cols = vec![vec![BaseField::zero(); n]; row_cols.len()];
        }
        for (c, v) in cols.iter_mut().zip(row_cols) {
            c[p] = f(v);
        }
        xa[p] = ents.iter().filter(|e| matches!(e.1, Rel::Xor8)).map(|e| (e.2[0], e.2[1])).collect();
        entries[p] = ents;
    }
    // the XOR-8 table's multiplicities: every lookup on every row (padding rows look up zeros, a valid entry)
    for vr in 0..(n >> LOG_N_LANES) {
        for j in 0..xa[0].len() {
            let a = u32x16::from_array(std::array::from_fn(|l| xa[(vr << LOG_N_LANES) + l][j].0));
            let b = u32x16::from_array(std::array::from_fn(|l| xa[(vr << LOG_N_LANES) + l][j].1));
            xor.add_input(8, a, b);
        }
    }
    PathTrace { trace: evals(cols, log), entries }
}

fn path_interaction(
    pt: &PathTrace,
    log: u32,
    blake: &BlakeElements,
    xor: &BlakeXorElements,
    pubs: &PubElements,
) -> (Evals, SecureField) {
    let mut lg = LogupTraceGenerator::new(log);
    let n_ent = pt.entries[0].len();
    let packed = |vr: usize, j: usize| -> (PackedSecureField, PackedSecureField) {
        let lane = |l: usize| &pt.entries[(vr << LOG_N_LANES) + l][j];
        let num = PackedSecureField::from(PackedBaseField::from_array(std::array::from_fn(|l| signed(lane(l).0))));
        let rel = &lane(0).1;
        let width = lane(0).2.len();
        let vals: Vec<PackedBaseField> =
            (0..width).map(|k| PackedBaseField::from_array(std::array::from_fn(|l| f(lane(l).2[k])))).collect();
        let den: PackedSecureField = match rel {
            Rel::Blake => blake.combine(&vals),
            Rel::Xor8 => xor.xor8.combine(&vals),
            Rel::Pub => pubs.combine(&vals),
        };
        (num, den)
    };
    let mut j = 0;
    while j < n_ent {
        let mut col = lg.new_col();
        for vr in 0..(1usize << (log - LOG_N_LANES)) {
            let (n0, d0) = packed(vr, j);
            if j + 1 < n_ent {
                let (n1, d1) = packed(vr, j + 1);
                col.write_frac(vr, n0 * d1 + n1 * d0, d0 * d1);
            } else {
                col.write_frac(vr, n0, d0);
            }
        }
        col.finalize_col();
        j += 2;
    }
    lg.finalize_last()
}

fn preprocessed_ids() -> Vec<stwo_constraint_framework::preprocessed_columns::PreProcessedColumnId> {
    let mut ids = vec![];
    for (w, e) in [(12, 4), (9, 2), (8, 2), (7, 2), (4, 0)] {
        for c in 0..3 {
            ids.push(XorTable::new(w, e, c).id());
        }
    }
    ids.extend(SEL.iter().map(|n| sel_id(n)));
    ids
}

struct Components {
    scheduler: BlakeSchedulerComponent,
    rounds: Vec<BlakeRoundComponent>,
    xor12: xor12::XorTableComponent<12, 4>,
    xor9: xor9::XorTableComponent<9, 2>,
    xor8: xor8::XorTableComponent<8, 2>,
    xor7: xor7::XorTableComponent<7, 2>,
    xor4: xor4::XorTableComponent<4, 0>,
    path: PathComponent,
}

struct Elements {
    blake: BlakeElements,
    round: RoundElements,
    xor: BlakeXorElements,
    pubs: PubElements,
}

impl Components {
    fn new(log: u32, el: &Elements, sums: &[SecureField]) -> Self {
        let alloc = &mut TraceLocationAllocator::new_with_preprocessed_columns(&preprocessed_ids());
        let s = |i: usize| sums[i];
        let scheduler = BlakeSchedulerComponent::new(
            alloc,
            BlakeSchedulerEval {
                log_size: log,
                blake_lookup_elements: el.blake.clone(),
                round_lookup_elements: el.round.clone(),
                claimed_sum: s(0),
            },
            s(0),
        );
        let rounds = ROUND_LOG_SPLIT
            .iter()
            .enumerate()
            .map(|(i, l)| {
                BlakeRoundComponent::new(
                    alloc,
                    BlakeRoundEval {
                        log_size: log + l,
                        xor_lookup_elements: el.xor.clone(),
                        round_lookup_elements: el.round.clone(),
                        claimed_sum: s(1 + i),
                    },
                    s(1 + i),
                )
            })
            .collect();
        let k = 1 + ROUND_LOG_SPLIT.len();
        Self {
            scheduler,
            rounds,
            xor12: xor12::XorTableComponent::new(alloc, xor12::XorTableEval { lookup_elements: el.xor.xor12.clone(), claimed_sum: s(k) }, s(k)),
            xor9: xor9::XorTableComponent::new(alloc, xor9::XorTableEval { lookup_elements: el.xor.xor9.clone(), claimed_sum: s(k + 1) }, s(k + 1)),
            xor8: xor8::XorTableComponent::new(alloc, xor8::XorTableEval { lookup_elements: el.xor.xor8.clone(), claimed_sum: s(k + 2) }, s(k + 2)),
            xor7: xor7::XorTableComponent::new(alloc, xor7::XorTableEval { lookup_elements: el.xor.xor7.clone(), claimed_sum: s(k + 3) }, s(k + 3)),
            xor4: xor4::XorTableComponent::new(alloc, xor4::XorTableEval { lookup_elements: el.xor.xor4.clone(), claimed_sum: s(k + 4) }, s(k + 4)),
            path: PathComponent::new(
                alloc,
                PathEval { log_size: log, blake: el.blake.clone(), xor: el.xor.clone(), pubs: el.pubs.clone(), claimed_sum: s(k + 5) },
                s(k + 5),
            ),
        }
    }
    fn components(&self) -> Vec<&dyn Component> {
        chain![
            [&self.scheduler as &dyn Component],
            self.rounds.iter().map(|c| c as &dyn Component),
            [&self.xor12 as &dyn Component, &self.xor9, &self.xor8, &self.xor7, &self.xor4, &self.path]
        ]
        .collect()
    }
    fn provers(&self) -> Vec<&dyn ComponentProver<SimdBackend>> {
        chain![
            [&self.scheduler as &dyn ComponentProver<SimdBackend>],
            self.rounds.iter().map(|c| c as &dyn ComponentProver<SimdBackend>),
            [
                &self.xor12 as &dyn ComponentProver<SimdBackend>,
                &self.xor9,
                &self.xor8,
                &self.xor7,
                &self.xor4,
                &self.path
            ]
        ]
        .collect()
    }
}

fn log_sizes(log: u32) -> TreeVec<Vec<u32>> {
    let mut sizes = vec![];
    sizes.push(blake_scheduler_info().mask_offsets.as_cols_ref().map_cols(|_| log));
    for l in ROUND_LOG_SPLIT {
        sizes.push(blake_round_info().mask_offsets.as_cols_ref().map_cols(|_| log + l));
    }
    sizes.push(xor12::trace_sizes::<12, 4>());
    sizes.push(xor9::trace_sizes::<9, 2>());
    sizes.push(xor8::trace_sizes::<8, 2>());
    sizes.push(xor7::trace_sizes::<7, 2>());
    sizes.push(xor4::trace_sizes::<4, 0>());
    let path_info = PathEval {
        log_size: log,
        blake: BlakeElements::dummy(),
        xor: BlakeXorElements::dummy(),
        pubs: PubElements::dummy(),
        claimed_sum: SecureField::zero(),
    }
    .evaluate(stwo_constraint_framework::InfoEvaluator::empty());
    sizes.push(path_info.mask_offsets.as_cols_ref().map_cols(|_| log));
    let mut out = TreeVec::concat_cols(sizes.into_iter());
    let mut pre: Vec<u32> = vec![];
    for (w, e) in [(12, 4), (9, 2), (8, 2), (7, 2), (4, 0)] {
        for c in 0..3 {
            pre.push(XorTable::new(w, e, c).column_bits());
        }
    }
    pre.extend(SEL.iter().map(|_| log));
    out[PREPROCESSED_TRACE_IDX] = pre;
    out
}

/// Prove a sequential batch of key updates (each one's siblings against the tree the previous one left). Returns the
/// statement it proves (the roots computed from the witness) and the proof.
pub fn prove_batch(us: &[Update], config: PcsConfig) -> (Statement, BatchProof) {
    prove_tampered(us, config, Tamper::None).expect("honest batch proves")
}

/// prove_batch with a dishonest witness (Tamper::None is the honest prover). The prover's own consistency check may
/// refuse a witness that breaks a constraint (the Err); otherwise the proof goes to the verifier like any other.
pub fn prove_tampered(us: &[Update], config: PcsConfig, tamper: Tamper) -> Result<(Statement, BatchProof), String> {
    let (rows, stmt) = batch_of(us, tamper);
    let shapes = stmt.shapes();
    let log = log_size_for(&shapes);
    const XOR_TABLE_MAX_LOG_SIZE: u32 = 16;
    let log_max = (log + *ROUND_LOG_SPLIT.iter().max().unwrap()).max(XOR_TABLE_MAX_LOG_SIZE);
    let twiddles = SimdBackend::precompute_twiddles(
        CanonicCoset::new(log_max + 1 + config.fri_config.log_blowup_factor).circle_domain().half_coset,
    );
    let channel = &mut Blake2sChannel::default();
    config.mix_into(channel);
    stmt.mix_into(channel);
    let mut cs = CommitmentSchemeProver::<SimdBackend, Blake2sMerkleChannel>::new(config, &twiddles);
    cs.set_store_polynomials_coefficients();   // the path constraints (degree 3) evaluate on a larger domain than the trace

    // preprocessed: the XOR tables, then the path's selectors (a function of the shapes)
    let mut tb = cs.tree_builder();
    tb.extend_evals(
        chain![
            XorTable::new(12, 4, 0).generate_constant_trace(),
            XorTable::new(9, 2, 0).generate_constant_trace(),
            XorTable::new(8, 2, 0).generate_constant_trace(),
            XorTable::new(7, 2, 0).generate_constant_trace(),
            XorTable::new(4, 0, 0).generate_constant_trace(),
            path_preprocessed(&shapes, log),
        ]
        .collect_vec(),
    );
    tb.commit(channel);

    // scheduler inputs: every path row that hashes, multiplicity 1; padding lanes default (multiplicity 0). The
    // scheduler's row order is its own: the lookup matches a multiset.
    let hashed: Vec<&Row> = rows.iter().filter(|r| r.hash != Hash::None).collect();
    let mut inputs = vec![];
    for chunk in hashed.chunks(1 << LOG_N_LANES) {
        let lane = |l: usize, w: usize, m: bool| -> u32 {
            chunk
                .get(l)
                .map(|r| if m { r.m[w] } else if r.hash == Hash::Leaf { v_init(PERSON_LEAF)[w] } else { v_init(PERSON_NODE)[w] })
                .unwrap_or(0)
        };
        inputs.push(BlakeInput {
            v: std::array::from_fn(|w| u32x16::from_array(std::array::from_fn(|l| lane(l, w, false)))),
            m: std::array::from_fn(|w| u32x16::from_array(std::array::from_fn(|l| lane(l, w, true)))),
            mult: u32x16::from_array(std::array::from_fn(|l| if l < chunk.len() { 1 } else { 0 })),
        });
    }
    let (sched_trace, sched_lookup, round_inputs) = scheduler::gen_trace(log, &inputs);
    let mut xor_acc = XorAccums::default();
    let mut rest = &round_inputs[..];
    let (round_traces, round_lookup): (Vec<_>, Vec<_>) = multiunzip(ROUND_LOG_SPLIT.map(|l| {
        let (cur, r) = rest.split_at(1 << (log - LOG_N_LANES + l));
        rest = r;
        round::generate_trace(log + l, cur, &mut xor_acc)
    }));
    let pt = path_trace(&rows, &shapes, log, &mut xor_acc);
    let (x12, xl12) = xor12::generate_trace(xor_acc.xor12);
    let (x9, xl9) = xor9::generate_trace(xor_acc.xor9);
    let (x8, xl8) = xor8::generate_trace(xor_acc.xor8);
    let (x7, xl7) = xor7::generate_trace(xor_acc.xor7);
    let (x4, xl4) = xor4::generate_trace(xor_acc.xor4);
    channel.mix_u64(log as u64);
    let mut tb = cs.tree_builder();
    tb.extend_evals(chain![sched_trace, round_traces.into_iter().flatten(), x12, x9, x8, x7, x4, pt.trace.clone()].collect_vec());
    tb.commit(channel);

    let el = Elements {
        blake: BlakeElements::draw(channel),
        round: RoundElements::draw(channel),
        xor: BlakeXorElements::draw(channel),
        pubs: PubElements::draw(channel),
    };
    let (s_tr, s_sum) = scheduler::gen_interaction_trace(log, sched_lookup, &el.round, &el.blake);
    let (r_tr, r_sums): (Vec<_>, Vec<_>) = multiunzip(
        ROUND_LOG_SPLIT
            .iter()
            .zip(round_lookup)
            .map(|(l, ld)| round::generate_interaction_trace(log + l, ld, &el.xor, &el.round)),
    );
    let (i12, s12) = xor12::generate_interaction_trace(xl12, &el.xor.xor12);
    let (i9, s9) = xor9::generate_interaction_trace(xl9, &el.xor.xor9);
    let (i8, s8) = xor8::generate_interaction_trace(xl8, &el.xor.xor8);
    let (i7, s7) = xor7::generate_interaction_trace(xl7, &el.xor.xor7);
    let (i4, s4) = xor4::generate_interaction_trace(xl4, &el.xor.xor4);
    let (p_tr, p_sum) = path_interaction(&pt, log, &el.blake, &el.xor, &el.pubs);
    let sums: Vec<SecureField> = chain![[s_sum], r_sums, [s12, s9, s8, s7, s4, p_sum]].collect();
    let mut tb = cs.tree_builder();
    tb.extend_evals(chain![s_tr, r_tr.into_iter().flatten(), i12, i9, i8, i7, i4, p_tr].collect_vec());
    channel.mix_felts(&sums);
    tb.commit(channel);

    let comps = Components::new(log, &el, &sums);
    let stark = prove::<SimdBackend, Blake2sMerkleChannel>(&comps.provers(), channel, cs).map_err(|e| format!("{e:?}"))?;
    Ok((stmt, BatchProof { log_size: log, sums, stark }))
}

/// The public LogUp terms the verifier adds itself: +1/combine(tuple) for every tuple the path component consumes.
fn public_sum(st: &Statement, pubs: &PubElements) -> SecureField {
    let limbs = |w: &[u32; 8]| w.iter().flat_map(|x| [x & 0xffff, x >> 16]).collect_vec();
    let term = |t: Vec<BaseField>| -> SecureField {
        <PubElements as Relation<BaseField, SecureField>>::combine(pubs, &t).inverse()
    };
    let mut s = SecureField::zero();
    for (i, u) in st.updates.iter().enumerate() {
        let tup = |tag: u32, vals: Vec<u32>| -> Vec<BaseField> {
            let mut t = vec![tag, i as u32];
            t.extend(vals);
            t.resize(N_PUB, 0);
            t.into_iter().map(f).collect()
        };
        // what path.rs row_sel emits per op: an UPDATE's two leaves both carry the key and one value hash each; an
        // insert's deep leaf carries the new value, a delete's the old; a split's shallow leaf carries the neighbour key
        let n_key = if u.op == Op::Update { 2 } else { 1 };
        s += term(tup(TAG_KEY, limbs(&u.key))) * SecureField::from(f(n_key));
        if u.op.split_kind() {
            s += term(tup(TAG_KEY2, limbs(&u.k2)));
        }
        if u.op == Op::Update || u.op.b_is_old() {
            s += term(tup(TAG_VH_OLD, limbs(&u.vh_old)));
        }
        if u.op == Op::Update || !u.op.b_is_old() {
            s += term(tup(TAG_VH_NEW, limbs(&u.vh_new)));
        }
        for level in 0..u.db {
            s += term(tup(TAG_DIR, vec![level as u32, bit(&u.key, level)]));
        }
        s += term(tup(TAG_ROOT_OLD, limbs(&u.root_old)));
        s += term(tup(TAG_ROOT_NEW, limbs(&u.root_new)));
    }
    s
}

/// The commitment of the preprocessed trace (XOR tables + the path selectors of a batch of these shapes) under `config`
/// — what an honest proof's commitments[0] is. Computed with the prover's machinery from the statement alone.
pub fn preprocessed_root(shapes: &[Shape], config: PcsConfig) -> <Blake2sMerkleHasher as stwo::core::vcs_lifted::merkle_hasher::MerkleHasherLifted>::Hash {
    let log = log_size_for(shapes);
    let log_max = (log + *ROUND_LOG_SPLIT.iter().max().unwrap()).max(16);
    let twiddles = SimdBackend::precompute_twiddles(
        CanonicCoset::new(log_max + 1 + config.fri_config.log_blowup_factor).circle_domain().half_coset,
    );
    let channel = &mut Blake2sChannel::default();
    let mut cs = CommitmentSchemeProver::<SimdBackend, Blake2sMerkleChannel>::new(config, &twiddles);
    let mut tb = cs.tree_builder();
    tb.extend_evals(
        chain![
            XorTable::new(12, 4, 0).generate_constant_trace(),
            XorTable::new(9, 2, 0).generate_constant_trace(),
            XorTable::new(8, 2, 0).generate_constant_trace(),
            XorTable::new(7, 2, 0).generate_constant_trace(),
            XorTable::new(4, 0, 0).generate_constant_trace(),
            path_preprocessed(shapes, log),
        ]
        .collect_vec(),
    );
    tb.commit(channel);
    cs.roots()[0]
}

#[derive(Debug)]
pub enum VerifyError {
    Preprocessed,
    WeakConfig,
    Shape,
    /// an update's new root is not the next update's old root
    Chain,
    Sum,
    Stark(VerificationError),
}

/// A write's shape is one the tree can have, and its unused fields are zero (one encoding per statement):
///   UPDATE and *_EMPTY: da == db; the split kinds: da < db <= 256 and db - 1 is the FIRST bit where the key and the
///   neighbour differ (they agree above it). This is the check that pins an insert's split depth; the circuit pins the
///   rest.
fn shape_ok(u: &UpdateStatement) -> bool {
    let z = [0u32; 8];
    if u.db > 256 || u.da > u.db {
        return false;
    }
    let absent_ok = match u.op {
        Op::Update => true,
        Op::InsertEmpty | Op::InsertSplit => u.vh_old == z,
        Op::DeleteEmpty | Op::DeleteCollapse => u.vh_new == z,
    };
    if !absent_ok {
        return false;
    }
    if u.op.split_kind() {
        u.da < u.db
            && (0..u.db - 1).all(|i| bit(&u.key, i) == bit(&u.k2, i))
            && bit(&u.key, u.db - 1) != bit(&u.k2, u.db - 1)
    } else {
        u.da == u.db && u.k2 == z
    }
}

/// Verify that `proof` proves `st`: the batch's layout, the node's config, the root chain, every sum plus the public
/// terms zero, the STARK. Never panics on a malformed proof it can recognize; returns why it refused.
pub fn verify_batch(st: &Statement, proof: BatchProof, config: PcsConfig) -> Result<(), VerifyError> {
    if proof.stark.config != config {
        return Err(VerifyError::WeakConfig);
    }
    if st.updates.is_empty() || !st.updates.iter().all(shape_ok) {
        return Err(VerifyError::Shape);
    }
    if st.updates.windows(2).any(|w| w[0].root_new != w[1].root_old) {
        return Err(VerifyError::Chain);
    }
    let shapes = st.shapes();
    let log = log_size_for(&shapes);
    if proof.log_size != log || proof.sums.len() != 1 + ROUND_LOG_SPLIT.len() + 6 {
        return Err(VerifyError::Shape);
    }
    let channel = &mut Blake2sChannel::default();
    config.mix_into(channel);
    st.mix_into(channel);
    let mut cs = CommitmentSchemeVerifier::<Blake2sMerkleChannel>::new(config);
    let sizes = log_sizes(log);
    if proof.stark.commitments.len() < 3 {
        return Err(VerifyError::Shape);
    }
    // THE PREPROCESSED COLUMNS ARE OURS, NOT THE PROVER'S: the XOR tables and the path's selectors are constants of the
    // shapes, so their commitment is recomputed here and a proof carrying any other is refused. Upstream's example took
    // commitments[0] from the proof unchecked — a prover could commit a fake XOR table or selectors that switch every
    // constraint off. (stwo_js pins the same thing as NODE_PREPROCESSED_ROOT.)
    if proof.stark.commitments[0] != preprocessed_root(&shapes, config) {
        return Err(VerifyError::Preprocessed);
    }
    cs.commit(proof.stark.commitments[0], &sizes[0], channel);
    channel.mix_u64(log as u64);
    cs.commit(proof.stark.commitments[1], &sizes[1], channel);
    let el = Elements {
        blake: BlakeElements::draw(channel),
        round: RoundElements::draw(channel),
        xor: BlakeXorElements::draw(channel),
        pubs: PubElements::draw(channel),
    };
    channel.mix_felts(&proof.sums);
    cs.commit(proof.stark.commitments[2], &sizes[2], channel);
    let total: SecureField = proof.sums.iter().copied().sum::<SecureField>() + public_sum(st, &el.pubs);
    if total != SecureField::zero() {
        return Err(VerifyError::Sum);
    }
    let comps = Components::new(log, &el, &proof.sums);
    verify(&comps.components(), channel, &mut cs, proof.stark).map_err(VerifyError::Stark)
}

#[allow(dead_code)]
fn _uses() -> (SecureField, BaseColumn) {
    (SecureField::one(), BaseColumn::zeros(1))
}

#[allow(dead_code)]
const _ROUNDS: usize = N_ROUNDS;
#[allow(dead_code)]
fn _ids() -> usize {
    ORIGINAL_TRACE_IDX
}

/// DEBUG: evaluate the path component's constraints on its own trace for `us` (random lookup elements), panicking with
/// the first failing row and constraint index — the tool for "ConstraintsNotSatisfied".
pub fn debug_path_constraints(us: &[Update]) {
    use stwo_constraint_framework::assert_constraints_on_trace;
    let (rows, stmt) = batch_of(us, Tamper::None);
    let shapes = stmt.shapes();
    let log = log_size_for(&shapes);
    let mut xa = XorAccums::default();
    let pt = path_trace(&rows, &shapes, log, &mut xa);
    let ch = &mut Blake2sChannel::default();
    let el = Elements {
        blake: BlakeElements::draw(ch),
        round: RoundElements::draw(ch),
        xor: BlakeXorElements::draw(ch),
        pubs: PubElements::draw(ch),
    };
    let (itr, sum) = path_interaction(&pt, log, &el.blake, &el.xor, &el.pubs);
    let pre: Vec<Vec<BaseField>> =
        preprocessed_values(&shapes, log).into_iter().map(|c| c.into_iter().map(f).collect()).collect();
    let orig: Vec<Vec<BaseField>> = pt.trace.iter().map(|e| e.values.to_cpu()).collect();
    let inter: Vec<Vec<BaseField>> = itr.iter().map(|e| e.values.to_cpu()).collect();
    let tv = TreeVec::new(vec![pre.iter().collect_vec(), orig.iter().collect_vec(), inter.iter().collect_vec()]);
    let ev = PathEval { log_size: log, blake: el.blake.clone(), xor: el.xor.clone(), pubs: el.pubs.clone(), claimed_sum: sum };
    assert_constraints_on_trace(&tv, log, |e| { ev.evaluate(e); }, sum);
    eprintln!("path constraints hold on every row (claimed sum {sum:?})");
}

/// DEBUG: upstream's own benchmark proof (independent compressions, no path) through the vendored, modified scheduler.
pub fn debug_upstream_blake() {
    let p = super::air::prove_blake::<Blake2sMerkleChannel>(10, PcsConfig::default());
    match super::air::verify_blake::<Blake2sMerkleChannel>(p) {
        Ok(()) => eprintln!("upstream blake proof (modified scheduler): verifies"),
        Err(e) => eprintln!("upstream blake proof (modified scheduler): REFUSED {e:?}"),
    }
}
