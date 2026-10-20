//! The settlement PATH component: a BATCH of compressed-tree key updates, each one old leaf -> old root and new leaf ->
//! new root over the SAME siblings, proven over upstream's BLAKE2s components (doc/stwo/g4-settlement-statement.md).
//! Updates sit back to back, each in its own block of rows; the preprocessed `settle_upd` column numbers them and every
//! public tuple carries that number, so a row cannot lend its key, value or root to another update. The batch is
//! SEQUENTIAL: update i+1's siblings are against the tree after update i, and the verifier chains the roots natively
//! (settle.rs verify_batch: root_new[i] == root_old[i+1]).
//!
//! WITHIN AN UPDATE, ONE ROW PER COMPRESSION, interleaved old/new by level, so a row's child digest is always two rows up
//! (an update's first node row reads its own leaf row: the -1 / -2 masks never reach the previous update on a gated row):
//!   rows 0, 1          the old and the new LEAF: message = key (8 words) || value hash (8 words), person NADOcsL1
//!   rows 2k+2, 2k+3    the old and the new NODE at level d-1-k: message = (child, sibling) ordered by the key's bit
//!                      at that level, person NADOcsN1
//! Each real row CONSUMES the scheduler's published compression (start state, output state, message): the start state
//! is the personalization's constant (by row type), so the scheduler row must be exactly that compression. The digest is
//! output[i] ^ output[i+8] ^ h0[i], computed bytewise through the XOR-8 table (which also range-checks every byte), and
//! every message limb is split into bytes and range-checked the same way (siblings are witness; upstream's rounds
//! assume range-checked messages). Old and new node rows at a level share the sibling and the direction bit.
//!
//! PUBLIC INPUTS enter as LogUp terms this component emits with multiplicity -1 and the verifier adds back natively
//! (settle.rs public_sum): the key (from both leaf rows), the old and new value hashes, each level's direction bit
//! (= the key's bit there), and the old and new roots. A proof whose rows say anything else leaves a nonzero total.

use itertools::Itertools;
use num_traits::{One, Zero};
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::SecureField;
use stwo_constraint_framework::preprocessed_columns::PreProcessedColumnId;
use stwo_constraint_framework::{EvalAtRow, FrameworkComponent, FrameworkEval, ORIGINAL_TRACE_IDX, RelationEntry, relation};

use super::scheduler::BlakeElements;
use super::{BlakeXorElements, Fu32};
use crate::csmt_ref::{PERSON_LEAF, PERSON_NODE, h0, v_init};

/// Public tuple width: a tag, the update's index, then up to 16 felts (8 words as 16-bit limbs).
pub const N_PUB: usize = 18;
relation!(PubElements, N_PUB);

pub const TAG_KEY: u32 = 1;
pub const TAG_VH_OLD: u32 = 2;
pub const TAG_VH_NEW: u32 = 3;
pub const TAG_DIR: u32 = 4;
pub const TAG_ROOT_OLD: u32 = 5;
pub const TAG_ROOT_NEW: u32 = 6;

/// The preprocessed columns (a function of the batch's depths only): selectors, the level and the update index.
pub const SEL: [&str; 9] = [
    "settle_sel_real",
    "settle_sel_leaf_old",
    "settle_sel_leaf_new",
    "settle_sel_node_old",
    "settle_sel_node_new",
    "settle_sel_root_old",
    "settle_sel_root_new",
    "settle_lvl",
    "settle_upd",
];

pub fn sel_id(name: &str) -> PreProcessedColumnId {
    PreProcessedColumnId { id: name.to_string() }
}

/// Rows a depth-`d` update uses (old and new leaf, then old and new node per level).
pub const fn real_rows(d: usize) -> usize {
    2 * d + 2
}

/// Rows a batch uses.
pub fn batch_rows(depths: &[usize]) -> usize {
    depths.iter().map(|d| real_rows(*d)).sum()
}

/// Stwo stores a column in bit-reversed CIRCLE-DOMAIN order, and a mask offset (the -1 / -2 this component reads) is a
/// step along the coset, not along the storage index: logical row r lives at storage index pos(r). Every column this
/// component owns is written through it (the selectors here, the trace in settle.rs).
pub fn pos(r: usize, log: u32) -> usize {
    use stwo::core::utils::{bit_reverse_index, coset_index_to_circle_domain_index};
    bit_reverse_index(coset_index_to_circle_domain_index(r, log), log)
}

/// The preprocessed column VALUES for a batch of updates of these depths in a component of `1 << log_size` rows, in SEL
/// order, in STORAGE order (logical row r at pos(r)).
pub fn preprocessed_values(depths: &[usize], log_size: u32) -> Vec<Vec<u32>> {
    let logical = preprocessed_logical(depths, log_size);
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

/// The same columns in LOGICAL row order (row 0 = update 0's old leaf ...).
pub fn preprocessed_logical(depths: &[usize], log_size: u32) -> Vec<Vec<u32>> {
    let n = 1usize << log_size;
    let mut cols = vec![vec![0u32; n]; SEL.len()];
    let mut base = 0;
    for (u, &d) in depths.iter().enumerate() {
        let r = real_rows(d);
        for i in 0..r {
            let row = base + i;
            cols[0][row] = 1;
            cols[8][row] = u as u32;
            let old = i % 2 == 0;
            if i < 2 {
                cols[if old { 1 } else { 2 }][row] = 1;
                cols[7][row] = d as u32; // a leaf sits at level d
            } else {
                cols[if old { 3 } else { 4 }][row] = 1;
                cols[7][row] = (d - 1 - (i - 2) / 2) as u32;
            }
            if i >= r - 2 {
                cols[if old { 5 } else { 6 }][row] = 1;
            }
        }
        base += r;
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
        // degree-3 constraints (selector x dir x limb): the quotient by the vanishing polynomial is < 2n, so log + 1, as
        // upstream's components and stwo_js declare it
        self.log_size + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let s: Vec<E::F> = SEL.iter().map(|n| e.get_preprocessed_column(sel_id(n))).collect();
        let (s_real, s_leaf_old, s_leaf_new, s_node_old, s_node_new, s_root_old, s_root_new, s_lvl, s_upd) = (
            s[0].clone(), s[1].clone(), s[2].clone(), s[3].clone(), s[4].clone(), s[5].clone(), s[6].clone(), s[7].clone(),
            s[8].clone(),
        );
        let s_leaf = s_leaf_old.clone() + s_leaf_new.clone();
        let s_node = s_node_old.clone() + s_node_new.clone();

        // message: masks at [-1, 0] (the previous row's message carries the shared sibling)
        let m: Vec<[Fu32<E::F>; 2]> = (0..16)
            .map(|_| {
                let [lp, l] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0]);
                let [hp, h] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0]);
                [Fu32 { l: lp, h: hp }, Fu32 { l, h }]
            })
            .collect();
        let mp: Vec<Fu32<E::F>> = m.iter().map(|x| x[0].clone()).collect();
        let m: Vec<Fu32<E::F>> = m.into_iter().map(|x| x[1].clone()).collect();
        let out: Vec<Fu32<E::F>> = (0..16).map(|_| Fu32 { l: e.next_trace_mask(), h: e.next_trace_mask() }).collect();

        // 1. consume the scheduler's compression: (start state by row type, output state, message)
        let vl = v_init(PERSON_LEAF);
        let vn = v_init(PERSON_NODE);
        let start: Vec<E::F> = (0..16)
            .flat_map(|j| {
                [
                    s_leaf.clone() * cst::<E>(vl[j] & 0xffff) + s_node.clone() * cst::<E>(vn[j] & 0xffff),
                    s_leaf.clone() * cst::<E>(vl[j] >> 16) + s_node.clone() * cst::<E>(vn[j] >> 16),
                ]
            })
            .collect();
        let entry: Vec<E::F> = start
            .into_iter()
            .chain(out.iter().flat_map(|x| [x.l.clone(), x.h.clone()]))
            .chain(m.iter().flat_map(|x| [x.l.clone(), x.h.clone()]))
            .collect();
        e.add_to_relation(RelationEntry::new(&self.blake, -E::EF::from(s_real.clone()), &entry));

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
        //    is two rows up)
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
                let cl = s_leaf.clone() * cst::<E>(hword(&hl) & 0xff) + s_node.clone() * cst::<E>(hword(&hn) & 0xff);
                let ch = s_leaf.clone() * cst::<E>(hword(&hl) >> 8) + s_node.clone() * cst::<E>(hword(&hn) >> 8);
                let [dlp, dl] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-2, 0]);
                let [dhp, dh] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-2, 0]);
                self.xor.use_relation(&mut e, 8, [&[tl, cl, dl.clone()], &[th, ch, dh.clone()]]);
                cur[limb] = dl + dh * E::F::from(byte);
                prev[limb] = dlp + dhp * E::F::from(byte);
            }
            dg_cur.push(Fu32 { l: cur[0].clone(), h: cur[1].clone() });
            dg_prev.push(Fu32 { l: prev[0].clone(), h: prev[1].clone() });
        }

        // the direction bit (masked at [-1, 0]: the new row's must equal the old row's at the same level)
        let [dirp, dir] = e.next_interaction_mask(ORIGINAL_TRACE_IDX, [-1, 0]);
        e.add_constraint(s_node.clone() * dir.clone() * (dir.clone() - E::F::one()));

        // 4. a node row's child (two rows up) is the message half the direction bit picks; the sibling is the other
        //    half, and the new row's sibling and direction equal the old row's at the same level
        for k in 0..8 {
            for (left, right, child, lp, rp) in [
                (m[k].l.clone(), m[8 + k].l.clone(), dg_prev[k].l.clone(), mp[k].l.clone(), mp[8 + k].l.clone()),
                (m[k].h.clone(), m[8 + k].h.clone(), dg_prev[k].h.clone(), mp[k].h.clone(), mp[8 + k].h.clone()),
            ] {
                let picked = left.clone() + dir.clone() * (right.clone() - left.clone());
                e.add_constraint(s_node.clone() * (picked - child));
                let sib = right.clone() + dir.clone() * (left - right);
                let sib_prev = rp.clone() + dirp.clone() * (lp - rp);
                e.add_constraint(s_node_new.clone() * (sib - sib_prev));
            }
        }
        e.add_constraint(s_node_new.clone() * (dir.clone() - dirp));

        // 5. public terms (the verifier adds the expected tuples back; any difference leaves a nonzero sum)
        let limbs = |ws: &[Fu32<E::F>]| ws.iter().flat_map(|x| [x.l.clone(), x.h.clone()]).collect_vec();
        let tup = |tag: u32, mut vals: Vec<E::F>| {
            let mut t = vec![cst::<E>(tag), s_upd.clone()];
            t.append(&mut vals);
            t.resize(N_PUB, E::F::zero());
            t
        };
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_leaf.clone()), &tup(TAG_KEY, limbs(&m[0..8]))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_leaf_old), &tup(TAG_VH_OLD, limbs(&m[8..16]))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_leaf_new), &tup(TAG_VH_NEW, limbs(&m[8..16]))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_node_old), &tup(TAG_DIR, vec![s_lvl, dir])));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_root_old), &tup(TAG_ROOT_OLD, limbs(&dg_cur))));
        e.add_to_relation(RelationEntry::new(&self.pubs, -E::EF::from(s_root_new), &tup(TAG_ROOT_NEW, limbs(&dg_cur))));

        e.finalize_logup_in_pairs();
        e
    }
}
