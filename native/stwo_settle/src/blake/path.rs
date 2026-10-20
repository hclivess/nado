//! The settlement PATH component: a BATCH of compressed-tree writes (value update, insert, delete), each proven as the
//! old path to the old root and the new path to the new root, over upstream's BLAKE2s components
//! (doc/stwo/g4-settlement-statement.md). The batch is SEQUENTIAL: each write's siblings are against the tree the
//! previous one left, and the verifier chains the roots natively (settle.rs verify_batch).
//!
//! SOUNDNESS IS BY INDUCTION ON CANONICAL TREES. The first old root is L1's (canonical by construction: genesis, the
//! carry, or a previous proven span). Every op below maps a canonical tree to the canonical tree of the new key set, and
//! the only freedom a prover has is the SHAPE it claims; each shape choice is pinned:
//!   UPDATE          k present: old leaf(k, vh_old) and new leaf(k, vh_new) at depth d over the SAME siblings.
//!   INSERT_EMPTY    k absent, its walk ends at EMPTY at depth d: EMPTY -> leaf(k, vh_new), same siblings. (The old root
//!                   forces the EMPTY: no internal or leaf hash is 32 zero bytes.)
//!   INSERT_SPLIT    k absent, its walk ends at another key's leaf k2 at depth da: k and k2 now share the prefix down to
//!                   their first differing bit j = db - 1, so the new leaf(k) sits at db with siblings: the old ones
//!                   above da, EMPTY at levels da..j-1, leaf(k2) at j. j is the first differing bit: checked natively
//!                   (k2 is public here; with the records component it becomes an in-circuit bit check).
//!   DELETE_EMPTY    k's leaf at depth d whose sibling at d-1 is an INTERNAL node: leaf -> EMPTY, same siblings. The
//!                   sibling is OPENED as node(l, r) by one compression, so a leaf sibling cannot be passed off as
//!                   internal (that would leave EMPTY beside a leaf: non-canonical).
//!   DELETE_COLLAPSE k's leaf at depth db whose sibling at j = db-1 is a LEAF k2: k2 moves up to depth da, the shortest
//!                   prefix it alone owns: the old siblings at levels da..j-1 are EMPTY, and the sibling at da-1 is
//!                   NONZERO (checked in-circuit; stopping beside an EMPTY would be non-canonical). It is INSERT_SPLIT
//!                   read backwards.
//!
//! LAYOUT: per write, a block of PAIRS of rows (slot A, slot B), one pair per depth from the deepest leaf up to the root,
//! so a node row's child is always TWO rows up (masks at -2) and slot B's row shares its sibling with slot A's row just
//! above (mask -1). Slot B carries the DEEP side (the one ending at depth db), slot A the shallow side (ending at da):
//!   UPDATE / INSERT_* : A = old, B = new;   DELETE_* : A = new, B = old.
//! Slot A is a pad below its own start. Links that are not adjacent (the split sibling, the opening) are LogUp tuples
//! emitted +1 by the source row and -1 by the destination row on the same relation, so they cancel exactly when they
//! agree. An *_EMPTY write at depth > 0 starts with one extra pair (the opening row, a pad).
//!
//! PUBLIC INPUTS enter as LogUp terms this component emits with multiplicity -1 and the verifier adds back natively
//! (settle.rs public_sum): the keys, the value hashes, each level's direction bit (the deep key's bit there), the roots.
//! Every tuple carries the write's index (preprocessed `upd`), so no row can lend a value to another write.

use itertools::Itertools;
use num_traits::{One, Zero};
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::SecureField;
use stwo_constraint_framework::preprocessed_columns::PreProcessedColumnId;
use stwo_constraint_framework::{EvalAtRow, FrameworkComponent, FrameworkEval, ORIGINAL_TRACE_IDX, RelationEntry, relation};

use super::scheduler::BlakeElements;
use super::{BlakeXorElements, Fu32};
use crate::csmt_ref::{PERSON_LEAF, PERSON_NODE, h0, v_init};

/// Public tuple width: a tag, the write's index, then up to 16 felts (8 words as 16-bit limbs).
pub const N_PUB: usize = 18;
relation!(PubElements, N_PUB);

pub const TAG_KEY: u32 = 1;
pub const TAG_VH_OLD: u32 = 2;
pub const TAG_VH_NEW: u32 = 3;
pub const TAG_DIR: u32 = 4;
pub const TAG_ROOT_OLD: u32 = 5;
pub const TAG_ROOT_NEW: u32 = 6;
pub const TAG_KEY2: u32 = 7;
/// internal links (emitted +1 and -1 inside the component; the verifier adds nothing for them)
pub const TAG_LINK_SPLIT: u32 = 8;
pub const TAG_LINK_OPEN: u32 = 9;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Update = 1,
    InsertEmpty = 2,
    DeleteEmpty = 3,
    InsertSplit = 4,
    DeleteCollapse = 5,
}
impl Op {
    pub fn empty_kind(self) -> bool {
        matches!(self, Op::InsertEmpty | Op::DeleteEmpty)
    }
    pub fn split_kind(self) -> bool {
        matches!(self, Op::InsertSplit | Op::DeleteCollapse)
    }
    /// slot B (the deep side) is the OLD tree's path for deletes, the NEW tree's otherwise
    pub fn b_is_old(self) -> bool {
        matches!(self, Op::DeleteEmpty | Op::DeleteCollapse)
    }
}

/// A write's shape: what the verifier knows before the proof (the statement fixes it, the preprocessed columns follow).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Shape {
    pub op: Op,
    /// the shallow side's terminal depth (slot A)
    pub da: usize,
    /// the deep side's leaf depth (slot B); == da except for the split kinds
    pub db: usize,
}

/// What one row of a write's block is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Slot {
    Pad,
    Open,
    AEmpty,
    ALeaf,
    ANode(usize),
    BLeaf,
    BNode(usize),
}

/// The rows of one write, in order. The prover's witness and the verifier's preprocessed columns both walk this.
pub fn slots(sh: &Shape) -> Vec<Slot> {
    let mut out = vec![];
    if sh.op.empty_kind() && sh.da > 0 {
        out.extend([Slot::Open, Slot::Pad]);
    }
    for l in (0..=sh.db).rev() {
        out.push(if l > sh.da {
            Slot::Pad
        } else if l == sh.da {
            if sh.op.empty_kind() { Slot::AEmpty } else { Slot::ALeaf }
        } else {
            Slot::ANode(l)
        });
        out.push(if l == sh.db { Slot::BLeaf } else { Slot::BNode(l) });
    }
    out
}

/// The preprocessed columns, in this order (indices P_*): selectors, then the level and the write's index.
pub const SEL: [&str; 20] = [
    "settle_real",
    "settle_leaf",
    "settle_node",
    "settle_open",
    "settle_empty",
    "settle_shared",
    "settle_esib",
    "settle_split",
    "settle_split_src",
    "settle_open_dst",
    "settle_nz",
    "settle_lvl",
    "settle_upd",
    "settle_dir",
    "settle_key",
    "settle_key2",
    "settle_vh_old",
    "settle_vh_new",
    "settle_root_old",
    "settle_root_new",
];
pub const P_REAL: usize = 0;
pub const P_LEAF: usize = 1;
pub const P_NODE: usize = 2;
pub const P_OPEN: usize = 3;
pub const P_EMPTY: usize = 4;
pub const P_SHARED: usize = 5;
pub const P_ESIB: usize = 6;
pub const P_SPLIT: usize = 7;
pub const P_SPLIT_SRC: usize = 8;
pub const P_OPEN_DST: usize = 9;
pub const P_NZ: usize = 10;
pub const P_LVL: usize = 11;
pub const P_UPD: usize = 12;
pub const P_DIR: usize = 13;
pub const P_KEY: usize = 14;
pub const P_KEY2: usize = 15;
pub const P_VH_OLD: usize = 16;
pub const P_VH_NEW: usize = 17;
pub const P_ROOT_OLD: usize = 18;
pub const P_ROOT_NEW: usize = 19;

pub fn sel_id(name: &str) -> PreProcessedColumnId {
    PreProcessedColumnId { id: name.to_string() }
}

/// One row's preprocessed values.
pub fn row_sel(sh: &Shape, upd: usize, s: Slot) -> [u32; 20] {
    let mut v = [0u32; 20];
    v[P_UPD] = upd as u32;
    let op = sh.op;
    let a_old = !op.b_is_old();
    let root = |v: &mut [u32; 20], old: bool| v[if old { P_ROOT_OLD } else { P_ROOT_NEW }] = 1;
    match s {
        Slot::Pad => {}
        Slot::Open => {
            v[P_REAL] = 1;
            v[P_OPEN] = 1;
        }
        Slot::AEmpty => {
            v[P_EMPTY] = 1;
            v[P_LVL] = sh.da as u32;
            if sh.da == 0 {
                root(&mut v, a_old);
            }
        }
        Slot::ALeaf => {
            v[P_REAL] = 1;
            v[P_LEAF] = 1;
            v[P_LVL] = sh.da as u32;
            if op == Op::Update {
                v[P_KEY] = 1;
                v[P_VH_OLD] = 1;
            } else {
                v[P_KEY2] = 1;
                v[P_SPLIT_SRC] = 1;
            }
            if sh.da == 0 {
                root(&mut v, a_old);
            }
        }
        Slot::ANode(l) => {
            v[P_REAL] = 1;
            v[P_NODE] = 1;
            v[P_LVL] = l as u32;
            if l + 1 == sh.da {
                if op.split_kind() {
                    v[P_NZ] = 1;
                }
                if op.empty_kind() {
                    v[P_OPEN_DST] = 1;
                }
            }
            if l == 0 {
                root(&mut v, a_old);
            }
        }
        Slot::BLeaf => {
            v[P_REAL] = 1;
            v[P_LEAF] = 1;
            v[P_LVL] = sh.db as u32;
            v[P_KEY] = 1;
            v[if op.b_is_old() { P_VH_OLD } else { P_VH_NEW }] = 1;
            if sh.db == 0 {
                root(&mut v, !a_old);
            }
        }
        Slot::BNode(l) => {
            v[P_REAL] = 1;
            v[P_NODE] = 1;
            v[P_DIR] = 1;
            v[P_LVL] = l as u32;
            if l < sh.da {
                v[P_SHARED] = 1;
            } else if l + 1 < sh.db {
                v[P_ESIB] = 1;
            } else {
                v[P_SPLIT] = 1; // l == db - 1 on a split kind (UPDATE/EMPTY kinds have da == db: l < da always)
            }
            if l == 0 {
                root(&mut v, !a_old);
            }
        }
    }
    v
}

/// Rows a batch of these shapes uses.
pub fn batch_rows(shapes: &[Shape]) -> usize {
    shapes.iter().map(|s| slots(s).len()).sum()
}

/// Stwo stores a column in bit-reversed CIRCLE-DOMAIN order, and a mask offset (the -1 / -2 this component reads) is a
/// step along the coset, not along the storage index: logical row r lives at storage index pos(r). Every column this
/// component owns is written through it (the selectors here, the trace in settle.rs).
pub fn pos(r: usize, log: u32) -> usize {
    use stwo::core::utils::{bit_reverse_index, coset_index_to_circle_domain_index};
    bit_reverse_index(coset_index_to_circle_domain_index(r, log), log)
}

/// The preprocessed column VALUES for a batch of these shapes in a component of `1 << log_size` rows, in SEL order, in
/// STORAGE order (logical row r at pos(r)).
pub fn preprocessed_values(shapes: &[Shape], log_size: u32) -> Vec<Vec<u32>> {
    let logical = preprocessed_logical(shapes, log_size);
    let n = 1usize << log_size;
    logical
        .iter()
        .map(|c| {
            let mut out = vec![0u32; n];
            for (r, v) in c.iter().enumerate() {
                out[pos(r, log_size)] = *v;
            }
            out
        })
        .collect()
}

/// The same columns in LOGICAL row order (row 0 = write 0's first row ...).
pub fn preprocessed_logical(shapes: &[Shape], log_size: u32) -> Vec<Vec<u32>> {
    let n = 1usize << log_size;
    let mut cols = vec![vec![0u32; n]; SEL.len()];
    let mut row = 0;
    for (u, sh) in shapes.iter().enumerate() {
        for s in slots(sh) {
            let v = row_sel(sh, u, s);
            for (c, x) in cols.iter_mut().zip(v) {
                c[row] = x;
            }
            row += 1;
        }
    }
    cols
}

fn cst<E: EvalAtRow>(x: u32) -> E::F {
    E::F::from(BaseField::from_u32_unchecked(x))
}

pub struct PathEval {
    pub log_size: u32,
    pub blake: BlakeElements,
    pub xor: BlakeXorElements,
    pub pubs: PubElements,
    pub claimed_sum: SecureField,
}
pub type PathComponent = FrameworkComponent<PathEval>;

impl FrameworkEval for PathEval {
    fn log_size(&self) -> u32 {
        self.log_size
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        // every constraint is degree <= 3 (selector x dir x limb): the quotient by the vanishing polynomial is < 2n, so
        // log + 1, as upstream's components and stwo_js declare it. A degree-4 constraint here breaks the proof — the
        // sibling is a materialized column (sib) for exactly that reason.
        self.log_size + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let s: Vec<E::F> = SEL.iter().map(|n| e.get_preprocessed_column(sel_id(n))).collect();
        let p = |i: usize| s[i].clone();
        let s_hash_node = p(P_NODE) + p(P_OPEN); // rows hashed under NADOcsN1

        let m: Vec<Fu32<E::F>> = (0..16).map(|_| Fu32 { l: e.next_trace_mask(), h: e.next_trace_mask() }).collect();
        let out: Vec<Fu32<E::F>> = (0..16).map(|_| Fu32 { l: e.next_trace_mask(), h: e.next_trace_mask() }).collect();

        // 1. consume the scheduler's compression: (start state by row type, output state, message)
        let vl = v_init(PERSON_LEAF);
        let vn = v_init(PERSON_NODE);
        let start: Vec<E::F> = (0..16)
            .flat_map(|j| {
                [
                    p(P_LEAF) * cst::<E>(vl[j] & 0xffff) + s_hash_node.clone() * cst::<E>(vn[j] & 0xffff),
                    p(P_LEAF) * cst::<E>(vl[j] >> 16) + s_hash_node.clone() * cst::<E>(vn[j] >> 16),
                ]
            })
            .collect();
        let entry: Vec<E::F> = start
            .into_iter()
            .chain(out.iter().flat_map(|x| [x.l.clone(), x.h.clone()]))
            .chain(m.iter().flat_map(|x| [x.l.clone(), x.h.clone()]))
            .collect();
        e.add_to_relation(RelationEntry::new(&self.blake, -E::EF::from(p(P_REAL)), &entry));

        // 2. every message limb split into bytes, each byte range-checked through the XOR-8 table (b ^ 0 = b)
        let byte = BaseField::from_u32_unchecked(256);
        for w in m.iter() {
            for limb in [w.l.clone(), w.h.clone()] {
                let hi = e.next_trace_mask();
                let lo = limb - hi.clone() * E::F::from(byte);
                self.xor.use_relation(&mut e, 8, [&[lo.clone(), E::F::zero(), lo], &[hi.clone(), E::F::zero(), hi]]);
            }
        }

        // 3. digest[i] = out[i] ^ out[i+8] ^ h0[i], bytewise; the digest bytes are masked at [-2, 0] (a node row's child
        //    is two rows up). A row that hashes nothing has constant 0, so an EMPTY row's digest is out[i] ^ out[i+8].
        let hl = h0(PERSON_LEAF);
        let hn = h0(PERSON_NODE);
        let mut dg_cur: Vec<Fu32<E::F>> = vec![];
        let mut dg_prev: Vec<Fu32<E::F>> = vec![];
        for i in 0..8 {
            let mut cur = [E::F::zero(), E::F::zero()];
            let mut prev = [E::F::zero(), E::F::zero()];
            for (limb, (a, b)) in [(out[i].l.clone(), out[i + 8].l.clone()), (out[i].h.clone(), out[i + 8].h.clone())]
                .into_iter()
                .enumerate()
            {
                let ah = e.next_trace_mask();
                let al = a - ah.clone() * E::F::from(byte);
                let bh = e.next_trace_mask();
                let bl = b - bh.clone() * E::F::from(byte);
                let tl = e.next_trace_mask();
                let th = e.next_trace_mask();
                self.xor.use_relation(&mut e, 8, [&[al, bl, tl.clone()], &[ah, bh, th.clone()]]);
                let hword = |h: &[u32; 8]| (h[i] >> (16 * limb)) & 0xffff;
                let cl = p(P_LEAF) * cst::<E>(hword(&hl) & 0xff) + s_hash_node.clone() * cst::<E>(hword(&hn) & 0xff);
                let ch = p(P_LEAF) * cst::<E>(hword(&hl) >> 8) + s_hash_node.clone() * cst::<E>(hword(&hn) >> 8);
                let [dlp, dl] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-2, 0]);
                let [dhp, dh] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-2, 0]);
                self.xor.use_relation(&mut e, 8, [&[tl, cl, dl.clone()], &[th, ch, dh.clone()]]);
                cur[limb] = dl + dh * E::F::from(byte);
                prev[limb] = dlp + dhp * E::F::from(byte);
            }
            dg_cur.push(Fu32 { l: cur[0].clone(), h: cur[1].clone() });
            dg_prev.push(Fu32 { l: prev[0].clone(), h: prev[1].clone() });
        }
        // an EMPTY start is 32 zero bytes
        for d in dg_cur.iter() {
            e.add_constraint(p(P_EMPTY) * d.l.clone());
            e.add_constraint(p(P_EMPTY) * d.h.clone());
        }

        // 4. the direction bit, the sibling column, the inverse for the nonzero check
        let [dirp, dir] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0]);
        let sib: Vec<[E::F; 2]> = (0..16).map(|_| e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0])).collect();
        let inv = e.next_trace_mask();
        e.add_constraint(p(P_NODE) * dir.clone() * (dir.clone() - E::F::one()));
        // a node row's child (two rows up) is the message half the direction bit picks; `sib` is the other half
        let limbs_of = |ws: &[Fu32<E::F>]| ws.iter().flat_map(|x| [x.l.clone(), x.h.clone()]).collect_vec();
        let (left, right) = (limbs_of(&m[0..8]), limbs_of(&m[8..16]));
        let child = limbs_of(&dg_prev);
        for j in 0..16 {
            let picked = left[j].clone() + dir.clone() * (right[j].clone() - left[j].clone());
            e.add_constraint(p(P_NODE) * (picked - child[j].clone()));
            let other = right[j].clone() + dir.clone() * (left[j].clone() - right[j].clone());
            e.add_constraint(p(P_NODE) * (other - sib[j][1].clone()));
            // slot B shares slot A's sibling (the row above) where both trees agree
            e.add_constraint(p(P_SHARED) * (sib[j][1].clone() - sib[j][0].clone()));
            // the deep side's siblings between the two terminal depths are EMPTY
            e.add_constraint(p(P_ESIB) * sib[j][1].clone());
        }
        e.add_constraint(p(P_SHARED) * (dir.clone() - dirp));
        // the shallow side's deepest sibling is nonzero (limbs < 2^16, 16 of them: the sum is zero only if all are)
        let sum = sib.iter().fold(E::F::zero(), |a, x| a + x[1].clone());
        e.add_constraint(p(P_NZ) * (sum * inv - E::F::one()));

        // 5. internal links: the split sibling = the shallow leaf's digest; the opened node = the sibling it opens
        let tup = |tag: E::F, mut vals: Vec<E::F>| {
            let mut t = vec![tag, p(P_UPD)];
            t.append(&mut vals);
            t.resize(N_PUB, E::F::zero());
            t
        };
        let src_tag = p(P_SPLIT_SRC) * cst::<E>(TAG_LINK_SPLIT) + p(P_OPEN) * cst::<E>(TAG_LINK_OPEN);
        let dst_tag = p(P_SPLIT) * cst::<E>(TAG_LINK_SPLIT) + p(P_OPEN_DST) * cst::<E>(TAG_LINK_OPEN);
        let sib_cur = sib.iter().map(|x| x[1].clone()).collect_vec();
        e.add_to_relation(RelationEntry::new(&self.pubs, E::EF::from(p(P_SPLIT_SRC) + p(P_OPEN)), &tup(src_tag, limbs_of(&dg_cur))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_SPLIT) + p(P_OPEN_DST)), &tup(dst_tag, sib_cur)));

        // 6. public terms (the verifier adds the expected tuples back; any difference leaves a nonzero sum)
        let pubt = |tag: u32, vals: Vec<E::F>| tup(cst::<E>(tag), vals);
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_KEY)), &pubt(TAG_KEY, left.clone())));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_KEY2)), &pubt(TAG_KEY2, left)));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_VH_OLD)), &pubt(TAG_VH_OLD, right.clone())));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_VH_NEW)), &pubt(TAG_VH_NEW, right)));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_DIR)), &pubt(TAG_DIR, vec![p(P_LVL), dir])));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_ROOT_OLD)), &pubt(TAG_ROOT_OLD, limbs_of(&dg_cur))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(p(P_ROOT_NEW)), &pubt(TAG_ROOT_NEW, limbs_of(&dg_cur))));

        e.finalize_logup_in_pairs();
        e
    }
}
