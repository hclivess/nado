//! The settlement circuit's VM component (Goldilocks retirement G4, doc/stwo/g4-settlement-statement.md section 4 step
//! 3): a Stwo proof that each call of a span, run on zkvm2 (the gen-29 VM, reference: crate::vm), produces exactly the
//! io log the statement states, ending in RET. The io log is the interface: what the storage and records components
//! consume (a later step wires them by lookup); here it is public, as the gen-28 settle proof's `cid_io` was.
//!
//! LAYOUT. One row per executed instruction (a CPU row), plus three tables:
//!   * TAB — the programs (prog, pc, op, d, s, imm) and the calls' data (CTX, ACTX, ARG values), PREPROCESSED from the
//!     statement and recomputed by the verifier, with a witness multiplicity;
//!   * RANGE16 — every value below 2^16, preprocessed, witness multiplicity;
//!   * upstream's BLAKE2s scheduler / rounds / XOR tables, consumed by HABS rows (one compression each) and used for
//!     byte range checks (b ^ 0 = b on the XOR-8 table, as path.rs does).
//!
//! THE MACHINE STATE IS CHAINED BY LOGUP, NOT BY ADJACENT ROWS: a row consumes the tuple (call, clk, pc, prog, ioc, r0..r7,
//! h) and produces the next one (clk + 1). The verifier produces each call's initial state (clk 0, pc 0, the args in
//! r0..r7, h = 0) and consumes its END tuple (n_steps, the io count), which only a RET row emits. So the rows of a call
//! form one path from its start to a RET: a branch would need a state produced twice (only the start is, once, by the
//! verifier), and a closed cycle would need clk to return to itself mod p, impossible below 2^31 rows. Row order is free,
//! so there are no masks at offsets and no wrap-around rows to guard.
//!
//! WORDS are 16 limbs of 16 bits (least significant first). Every value a row INTRODUCES is range-checked where it is
//! introduced (res, the adder's free operand, the MUL/DIV/HABS bytes, the carries); every other value is a copy of one
//! (registers, io fields) or a public input, so all words in the machine are canonical by induction from the verifier's
//! initial state. That is what lets the limb equations below hold over the integers, not just mod p:
//!   ADD/SUB/EQ/LT    one 16-limb adder AX + AY = AZ + 2^256 cout, a boolean carry per limb (|terms| < 2^17);
//!   MUL/DIVMOD       byte convolution a * b + c = p (64 bytes), each column sum < 2^22, carries < 2^16;
//!   NEZ/EQ/JNZ/...   a word is zero iff its 16 limbs sum to zero (16 x 2^16 < p, all non-negative).
//! Every constraint is degree <= 3 (selector x two witness terms): log + 1, as path.rs.
//!
//! REVERTS (2026-10-27). A call the statement says reverts ends in a REVERT row instead of a RET: its opcode one-hot is
//! all zero and a revert one-hot (`rsel`, crate::vm::revert) names the instruction and why it fails, so no opcode
//! constraint applies and each kind's own constraint proves the failure: REQUIRE / DIVMOD / DIVMODW / ASEL on a zero
//! operand (the zero test), NOTB / RANGE / ARG outside their small range (rb: the high limbs' sum is invertible, or the low
//! limb minus the bound is range-checked), OOB (no instruction; the pc is the program's length from TAB), OOG (no
//! instruction; clk is GAS_LIMIT). The row emits END_REVERT (cix, gas, kind, io count) instead of a next state, and the
//! verifier consumes it for exactly the calls the statement says revert. PAY / ABURN (an asset overspend) and BHASH /
//! BEACON (a chain read not available) depend on state the circuit does not hold: their REVERT row proves the step and
//! emits its io entry, and the verifier judges that entry (execnode/settle_b2.py Oracle._walk).
//!
//! WHAT IT DOES NOT CHECK (the consumer of the io log does): BHASH/BEACON values (L1's chain reads), SLOAD values (the
//! replayed state), ABAL and asset spends (the ledger), and the four judged reverts above.

use std::collections::HashMap;
use std::ops::{Add, Neg, Sub};
use std::simd::u32x16;

use itertools::{Itertools, chain, multiunzip};
use num_traits::Zero;
use stwo::core::air::Component;
use stwo::core::channel::{Blake2sChannel, Channel};
use stwo::core::fields::FieldExpOps;
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::SecureField;
use stwo::core::pcs::{CommitmentSchemeVerifier, PcsConfig, TreeVec};
use stwo::core::poly::circle::CanonicCoset;
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::{Blake2sMerkleChannel, Blake2sMerkleHasher};
use stwo::core::verifier::{VerificationError, verify};
use stwo::prover::backend::simd::SimdBackend;
use stwo::prover::backend::simd::column::BaseColumn;
use stwo::prover::backend::simd::m31::{LOG_N_LANES, PackedBaseField};
use stwo::prover::backend::simd::qm31::PackedSecureField;
use stwo::prover::poly::BitReversedOrder;
use stwo::prover::poly::circle::{CircleEvaluation, PolyOps};
use stwo::prover::{CommitmentSchemeProver, ComponentProver, prove};
use stwo_constraint_framework::preprocessed_columns::PreProcessedColumnId;
use stwo_constraint_framework::{
    EvalAtRow, FrameworkComponent, FrameworkEval, InfoEvaluator, LogupTraceGenerator, PREPROCESSED_TRACE_IDX, Relation,
    RelationEntry, TraceLocationAllocator, relation,
};

use super::preprocessed_columns::XorTable;
use super::round::{BlakeRoundComponent, BlakeRoundEval, RoundElements, blake_round_info};
use super::scheduler::{self, BlakeElements, BlakeInput, BlakeSchedulerComponent, BlakeSchedulerEval, blake_scheduler_info};
use super::xor_table::{xor4, xor7, xor8, xor9, xor12};
use super::{BlakeXorElements, ROUND_LOG_SPLIT, XorAccums, round};
use crate::csmt_ref::{h0, rounds, v_init};
use crate::vm::{self, N_OPS, NUM_REGS, PERSON_HASH, Step, VmStatement, W, op};

pub use super::settle::node_config;

// ---------------------------------------------------------------------------------------------------------------
// relations and tags

pub const STATE_W: usize = 6 + NUM_REGS * 16 + 16;
pub const TAB_W: usize = 23;
pub const IO_W: usize = 3 + 32;
relation!(StateElements, STATE_W);
relation!(TabElements, TAB_W);
relation!(IoElements, IO_W);
relation!(RangeElements, 1);

const TAG_STATE: u32 = 1;
const TAG_END: u32 = 2;
/// a reverted call's end: (cix, its gas, the revert kind in the pc slot, prog, its io count)
const TAG_REVERT: u32 = 3;
const TAB_PROG: u32 = 1;
const TAB_DATA: u32 = 2;
/// (prog, its length): an OOB row's pc must equal it
const TAB_LEN: u32 = 3;
const DATA_CTX: u32 = 0;
const DATA_ACTX: u32 = 1;
const DATA_ARG: u32 = 2;
/// (cix, NARGS, 0, the arg count): an ARG revert's index must reach it
const DATA_NARGS: u32 = 3;

// ---------------------------------------------------------------------------------------------------------------
// the CPU row's columns: ONE definition, read by the constraint evaluator and written by the trace generator

/// What the generic constraint / lookup code needs of a value: E::F when evaluating, BaseField when building the trace.
pub trait Fe:
    FieldExpOps + Clone + Zero + Add<Self, Output = Self> + Sub<Self, Output = Self> + Neg<Output = Self> + From<BaseField>
{
}
impl<T> Fe for T where
    T: FieldExpOps + Clone + Zero + Add<T, Output = T> + Sub<T, Output = T> + Neg<Output = T> + From<BaseField>
{
}

fn k<T: Fe>(x: u32) -> T {
    T::from(BaseField::from_u32_unchecked(x))
}

#[derive(Clone)]
pub struct Cols<T> {
    active: T,
    cix: T,
    clk: T,
    pc: T,
    prog: T,
    ioc: T,
    sel: Vec<T>,
    dsel: Vec<T>,
    ssel: Vec<T>,
    imm: Vec<T>,
    regs: Vec<Vec<T>>,
    h: Vec<T>,
    rd: Vec<T>,
    rs: Vec<T>,
    res: Vec<T>,
    nregs: Vec<Vec<T>>,
    nh: Vec<T>,
    npc: T,
    ax: Vec<T>,
    ay: Vec<T>,
    az: Vec<T>,
    cy: Vec<T>,
    /// nz_rd, inv_rd, nz_rs, inv_rs, nz_x, inv_x
    nz: Vec<T>,
    rem: Vec<T>,
    rq: T,
    ab: Vec<T>,
    bb: Vec<T>,
    cb: Vec<T>,
    pb: Vec<T>,
    mc: Vec<T>,
    out: Vec<T>,
    /// per digest word i (0..8), per 16-bit half j (0..2): ah, bh, tl, th, dl, dh
    dg: Vec<T>,
    io_a: Vec<T>,
    io_b: Vec<T>,
    cidx: T,
    /// REVERTS (crate::vm::revert): a one-hot over the instruction-level kinds, in place of the opcode one-hot
    rsel: Vec<T>,
    /// a pc past the method's end; the step budget spent (neither executes an instruction)
    oob: T,
    oog: T,
    /// the "outside a small range" test of NOTB / RANGE / ARG reverts: rb = 1, the low limb minus the bound is the
    /// range-checked rr; rb = 0, the high limbs' sum is nonzero (m = it, rinv its inverse)
    rb: T,
    m: T,
    rinv: T,
    rr: T,
    /// the call's arg count (an ARG revert) and the program's length (an OOB row), both looked up in TAB
    nargs: T,
    plen: T,
}

fn take<T>(it: &mut impl Iterator<Item = T>, n: usize) -> Vec<T> {
    (0..n).map(|_| it.next().expect("column count")).collect()
}

impl<T: Clone> Cols<T> {
    /// THE COLUMN ORDER (from_iter and flat must list the fields identically).
    fn from_iter(it: &mut impl Iterator<Item = T>) -> Self {
        let one = |it: &mut dyn Iterator<Item = T>| it.next().expect("column count");
        let active = one(it);
        let cix = one(it);
        let clk = one(it);
        let pc = one(it);
        let prog = one(it);
        let ioc = one(it);
        let sel = take(it, N_OPS);
        let dsel = take(it, NUM_REGS);
        let ssel = take(it, NUM_REGS);
        let imm = take(it, 16);
        let regs = (0..NUM_REGS).map(|_| take(it, 16)).collect();
        let h = take(it, 16);
        let rd = take(it, 16);
        let rs = take(it, 16);
        let res = take(it, 16);
        let nregs = (0..NUM_REGS).map(|_| take(it, 16)).collect();
        let nh = take(it, 16);
        let npc = one(it);
        let ax = take(it, 16);
        let ay = take(it, 16);
        let az = take(it, 16);
        let cy = take(it, 16);
        let nz = take(it, 6);
        let rem = take(it, 16);
        let rq = one(it);
        let ab = take(it, 32);
        let bb = take(it, 32);
        let cb = take(it, 32);
        let pb = take(it, 64);
        let mc = take(it, 64);
        let out = take(it, 32);
        let dg = take(it, 96);
        let io_a = take(it, 16);
        let io_b = take(it, 16);
        let cidx = one(it);
        let rsel = take(it, vm::revert::N_OP);
        let (oob, oog, rb, m, rinv, rr, nargs, plen) = (one(it), one(it), one(it), one(it), one(it), one(it), one(it), one(it));
        Cols {
            active, cix, clk, pc, prog, ioc, sel, dsel, ssel, imm, regs, h, rd, rs, res, nregs, nh, npc, ax, ay, az, cy,
            nz, rem, rq, ab, bb, cb, pb, mc, out, dg, io_a, io_b, cidx, rsel, oob, oog, rb, m, rinv, rr, nargs, plen,
        }
    }
    fn flat(&self) -> Vec<T> {
        let mut v = vec![self.active.clone(), self.cix.clone(), self.clk.clone(), self.pc.clone(), self.prog.clone(),
                         self.ioc.clone()];
        v.extend(self.sel.iter().cloned());
        v.extend(self.dsel.iter().cloned());
        v.extend(self.ssel.iter().cloned());
        v.extend(self.imm.iter().cloned());
        for r in &self.regs {
            v.extend(r.iter().cloned());
        }
        v.extend(self.h.iter().cloned());
        v.extend(self.rd.iter().cloned());
        v.extend(self.rs.iter().cloned());
        v.extend(self.res.iter().cloned());
        for r in &self.nregs {
            v.extend(r.iter().cloned());
        }
        v.extend(self.nh.iter().cloned());
        v.push(self.npc.clone());
        v.extend(self.ax.iter().cloned());
        v.extend(self.ay.iter().cloned());
        v.extend(self.az.iter().cloned());
        v.extend(self.cy.iter().cloned());
        v.extend(self.nz.iter().cloned());
        v.extend(self.rem.iter().cloned());
        v.push(self.rq.clone());
        v.extend(self.ab.iter().cloned());
        v.extend(self.bb.iter().cloned());
        v.extend(self.cb.iter().cloned());
        v.extend(self.pb.iter().cloned());
        v.extend(self.mc.iter().cloned());
        v.extend(self.out.iter().cloned());
        v.extend(self.dg.iter().cloned());
        v.extend(self.io_a.iter().cloned());
        v.extend(self.io_b.iter().cloned());
        v.push(self.cidx.clone());
        v.extend(self.rsel.iter().cloned());
        v.extend([self.oob.clone(), self.oog.clone(), self.rb.clone(), self.m.clone(), self.rinv.clone(), self.rr.clone(),
                  self.nargs.clone(), self.plen.clone()]);
        v
    }
}

pub const N_COLS: usize = 6 + N_OPS + 2 * NUM_REGS + 16 + NUM_REGS * 16 + 16 + 48 + NUM_REGS * 16 + 16 + 1 + 64 + 6 + 16
    + 1 + 32 * 3 + 64 * 2 + 32 + 96 + 32 + 1 + vm::revert::N_OP + 8;

impl<T: Fe> Cols<T> {
    fn s(&self, o: usize) -> T {
        self.sel[o].clone()
    }
    fn g(&self, ops: &[usize]) -> T {
        ops.iter().fold(T::zero(), |a, &o| a + self.sel[o].clone())
    }
    fn sdiv(&self) -> T {
        self.g(&[op::DIVMOD, op::DIVMODW])
    }
    /// the immediate as a small number: jump targets and CTX indices (validate_method keeps both below 2^17)
    fn immn(&self) -> T {
        self.imm[0].clone() + self.imm[1].clone() * k::<T>(65536)
    }
    fn r(&self, kind: u32) -> T {
        self.rsel[kind as usize].clone()
    }
    /// any revert: an instruction's own, OOB or OOG (the row ends its call without a next state)
    fn term(&self) -> T {
        self.rsel.iter().fold(T::zero(), |a, x| a + x.clone()) + self.oob.clone() + self.oog.clone()
    }
    /// the reverts that emit their step's io entry (crate::vm::revert: the verifier judges it)
    fn rv_emit(&self) -> T {
        RV_EMIT.iter().fold(T::zero(), |a, &k| a + self.r(k))
    }
    fn emit(&self) -> T {
        self.g(&IO_OPS) + self.rv_emit()
    }
    fn kind(&self) -> T {
        IO_OPS.iter().fold(T::zero(), |a, &o| a + self.sel[o].clone() * k::<T>(vm::io_kind(o)))
            + RV_EMIT.iter().fold(T::zero(), |a, &kd| a + self.r(kd) * k::<T>(vm::io_kind(vm::revert::OP[kd as usize])))
    }
    fn word_of_bytes(b: &[T], l: usize) -> T {
        b[2 * l].clone() + b[2 * l + 1].clone() * k::<T>(256)
    }
    /// digest byte j (BLAKE2s output order) from the dg columns: word j/4, half (j%4)/2, low or high byte
    fn dbyte(&self, j: usize) -> T {
        let (i, half, hi) = (j / 4, (j % 4) / 2, j % 2);
        self.dg[(i * 2 + half) * 6 + 4 + hi].clone()
    }
    /// limb l of the new hash state: the digest read big-endian
    fn dig(&self, l: usize) -> T {
        self.dbyte(31 - 2 * l) + self.dbyte(30 - 2 * l) * k::<T>(256)
    }
    /// message limb (16-bit) n of the HABS compression: h then rs, each 32 bytes big-endian, as 16 LE words
    fn msg(&self, n: usize) -> T {
        let (w, half) = (n / 2, n % 2);
        let (b, w) = if w < 8 { (&self.ab, w) } else { (&self.bb, w - 8) };
        let base = 31 - 4 * w - 2 * half;
        b[base].clone() + b[base - 1].clone() * k::<T>(256)
    }
}

const RV_EMIT: [u32; 4] = [vm::revert::PAY, vm::revert::ABURN, vm::revert::BHASH, vm::revert::BEACON];
const IO_OPS: [usize; 11] =
    [op::SLOAD, op::SSTORE, op::PAY, op::BHASH, op::BEACON, op::RET, op::ASEL, op::AMINT, op::ABURN, op::ABAL, op::ARENOUNCE];
/// ops that write nothing: res = rd keeps r[d]
const KEEP: [usize; 14] = [
    op::NOP, op::RANGE, op::JMP, op::JNZ, op::REQUIRE, op::HINIT, op::HABS, op::SSTORE, op::PAY, op::RET, op::ASEL,
    op::AMINT, op::ABURN, op::ARENOUNCE,
];

/// Every constraint of a CPU row (each must be zero).
fn cpu_constraints<T: Fe>(c: &Cols<T>) -> Vec<T> {
    let mut z: Vec<T> = vec![];
    let one = T::one;
    let bool_ = |x: &T| x.clone() * (x.clone() - T::one());
    let a = c.active.clone();
    z.push(bool_(&a));
    // the opcode and register selectors: one-hot on an active row that executes an instruction, all zero on padding.
    // A REVERT row takes its op from the revert one-hot instead (rsel), so no opcode constraint applies to it; OOB and
    // OOG rows execute nothing at all (no op, no registers).
    let term = c.term();
    let noins = c.oob.clone() + c.oog.clone();
    for x in chain![c.rsel.iter(), [&c.oob, &c.oog, &c.rb]] {
        z.push(bool_(x));
    }
    z.push(bool_(&term));
    for (v, want) in [(&c.sel, a.clone() - term.clone()), (&c.dsel, a.clone() - noins.clone()), (&c.ssel, a.clone() - noins.clone())] {
        for x in v.iter() {
            z.push(bool_(x));
        }
        z.push(v.iter().fold(T::zero(), |s, x| s + x.clone()) - want);
    }
    // rd, rs: the selected registers
    for l in 0..16 {
        let pick = |sel: &[T]| (0..NUM_REGS).fold(T::zero(), |s, i| s + sel[i].clone() * c.regs[i][l].clone());
        z.push(c.rd[l].clone() - pick(&c.dsel));
        z.push(c.rs[l].clone() - pick(&c.ssel));
    }
    // the register file after the row: r[d] = res; DIVMOD's remainder into r7 (validate_method: d != 7 there)
    let sdiv = c.sdiv();
    for i in 0..NUM_REGS {
        for l in 0..16 {
            let mut e = c.nregs[i][l].clone() - c.regs[i][l].clone()
                - c.dsel[i].clone() * (c.res[l].clone() - c.regs[i][l].clone());
            if i == 7 {
                e = e - sdiv.clone() * (c.rem[l].clone() - c.regs[7][l].clone());
            }
            z.push(e);
        }
    }
    // the hash state: HINIT clears it, HABS absorbs rs, everything else keeps it
    for l in 0..16 {
        z.push(c.nh[l].clone() - c.h[l].clone() + c.s(op::HINIT) * c.h[l].clone()
            - c.s(op::HABS) * (c.dig(l) - c.h[l].clone()));
    }
    // the next pc: pc + 1, or the target on JMP / a taken JNZ
    let (nz_rd, inv_rd, nz_rs, inv_rs, nz_x, inv_x) =
        (c.nz[0].clone(), c.nz[1].clone(), c.nz[2].clone(), c.nz[3].clone(), c.nz[4].clone(), c.nz[5].clone());
    let step = c.pc.clone() + one();
    z.push(a.clone() * (c.npc.clone() - step.clone())
        - (c.s(op::JMP) + c.s(op::JNZ) * nz_rs.clone()) * (c.immn() - step));
    // the adder AX + AY = AZ + 2^256 cout
    for l in 0..16 {
        let cin = if l == 0 { T::zero() } else { c.cy[l - 1].clone() };
        z.push(c.ax[l].clone() + c.ay[l].clone() + cin - c.az[l].clone() - c.cy[l].clone() * k::<T>(65536));
        z.push(bool_(&c.cy[l]));
    }
    let cout = c.cy[15].clone();
    // zero tests: a word is zero iff its limbs sum to zero (canonical limbs)
    for (w, nz, inv) in [(&c.rd, &nz_rd, &inv_rd), (&c.rs, &nz_rs, &inv_rs), (&c.ax, &nz_x, &inv_x)] {
        let sum = w.iter().fold(T::zero(), |s, x| s + x.clone());
        z.push(bool_(nz));
        z.push((one() - nz.clone()) * sum.clone());
        z.push(nz.clone() * (sum * inv.clone() - one()));
    }
    // what each op writes
    let keep = c.g(&KEEP);
    let bits = c.g(&[op::EQ, op::LT, op::NEZ, op::NOTB]);
    let cmp = c.g(&[op::EQ, op::LT]);
    let alim = |l: usize| Cols::<T>::word_of_bytes(&c.ab, l);
    let blim = |l: usize| Cols::<T>::word_of_bytes(&c.bb, l);
    let clim = |l: usize| Cols::<T>::word_of_bytes(&c.cb, l);
    let plo = |l: usize| Cols::<T>::word_of_bytes(&c.pb, l);
    for l in 0..16 {
        let (rd, rs, res) = (c.rd[l].clone(), c.rs[l].clone(), c.res[l].clone());
        z.push(keep.clone() * (res.clone() - rd.clone()));
        z.push(c.s(op::MOVI) * (res.clone() - c.imm[l].clone()));
        z.push(c.s(op::MOV) * (res.clone() - rs.clone()));
        z.push(c.s(op::HOUT) * (res.clone() - c.h[l].clone()));
        z.push(c.s(op::ADD) * (c.ax[l].clone() - rd.clone()));
        z.push(c.s(op::ADD) * (c.ay[l].clone() - rs.clone()));
        z.push(c.s(op::ADD) * (c.az[l].clone() - res.clone()));
        z.push(c.s(op::SUB) * (c.ax[l].clone() - res.clone()));
        z.push(c.s(op::SUB) * (c.ay[l].clone() - rs.clone()));
        z.push(c.s(op::SUB) * (c.az[l].clone() - rd.clone()));
        z.push(cmp.clone() * (c.ay[l].clone() - rs.clone()));
        z.push(cmp.clone() * (c.az[l].clone() - rd.clone()));
        if l >= 1 {
            z.push(bits.clone() * res.clone());
            z.push(c.s(op::NOTB) * rd.clone());
            z.push(c.s(op::ARG) * rs.clone());
        }
        if l >= 2 {
            z.push(c.s(op::LO32) * res.clone());
        } else {
            z.push(c.s(op::LO32) * (res.clone() - rd.clone()));
        }
        if l >= 4 {
            z.push(c.s(op::RANGE) * rd.clone());
        }
        // DIVMOD: rd = q * rs + rem, rem < rs (the adder: (rem - rs) + rs carries out iff rem < rs)
        z.push(sdiv.clone() * (alim(l) - res.clone()));
        z.push(sdiv.clone() * (blim(l) - rs.clone()));
        z.push(sdiv.clone() * (clim(l) - c.rem[l].clone()));
        z.push(sdiv.clone() * (plo(l) - rd.clone()));
        z.push(sdiv.clone() * (c.ay[l].clone() - rs.clone()));
        z.push(sdiv.clone() * (c.az[l].clone() - c.rem[l].clone()));
        // MUL: res = rd * rs mod 2^256
        z.push(c.s(op::MUL) * (alim(l) - rd.clone()));
        z.push(c.s(op::MUL) * (blim(l) - rs.clone()));
        z.push(c.s(op::MUL) * (plo(l) - res.clone()));
        // HABS: the compression's message is h || rs
        z.push(c.s(op::HABS) * (alim(l) - c.h[l].clone()));
        z.push(c.s(op::HABS) * (blim(l) - rs.clone()));
        // the io entry's fields
        let reads = c.g(&[op::SLOAD, op::BHASH, op::BEACON, op::ABAL]);
        let w2 = c.g(&[op::SSTORE, op::PAY, op::AMINT, op::ABURN]);
        let r1 = c.g(&[op::RET, op::ASEL]);
        z.push(reads.clone() * (c.io_a[l].clone() - rs.clone()));
        z.push(reads * (c.io_b[l].clone() - res.clone()));
        z.push(w2.clone() * (c.io_a[l].clone() - rd.clone()));
        z.push(w2 * (c.io_b[l].clone() - rs.clone()));
        z.push(r1.clone() * (c.io_a[l].clone() - rs.clone()));
        z.push(r1 * c.io_b[l].clone());
        z.push(c.s(op::ARENOUNCE) * (c.io_a[l].clone() - rd.clone()));
        z.push(c.s(op::ARENOUNCE) * c.io_b[l].clone());
    }
    z.push(c.s(op::EQ) * (c.res[0].clone() - one() + nz_x));
    z.push(c.s(op::LT) * (c.res[0].clone() - cout.clone()));
    z.push(c.s(op::NEZ) * (c.res[0].clone() - nz_rd));
    z.push(c.s(op::NOTB) * (c.res[0].clone() - one() + c.rd[0].clone()));
    z.push(c.s(op::NOTB) * bool_(&c.rd[0]));
    z.push(c.s(op::RANGE) * (c.rq.clone() - c.rd[3].clone() * k::<T>(4)));
    z.push(c.g(&[op::REQUIRE, op::ASEL]) * (nz_rs.clone() - one()));
    z.push(sdiv.clone() * (cout - one()));
    z.push((c.s(op::CTX) + c.s(op::ACTX)) * (c.cidx.clone() - c.immn()) + c.s(op::ARG) * (c.cidx.clone() - c.rs[0].clone()));
    for kb in 32..64 {
        z.push(sdiv.clone() * c.pb[kb].clone()); // the quotient times the divisor fits the word
    }
    for kb in 0..32 {
        z.push(c.s(op::MUL) * c.cb[kb].clone());
    }
    // the byte convolution a * b + c = p, column by column with carries
    let gm = c.s(op::MUL) + sdiv;
    for kc in 0..64usize {
        let mut s = T::zero();
        for i in kc.saturating_sub(31)..=kc.min(31) {
            s = s + c.ab[i].clone() * c.bb[kc - i].clone();
        }
        if kc < 32 {
            s = s + c.cb[kc].clone();
        }
        if kc > 0 {
            s = s + c.mc[kc - 1].clone();
        }
        z.push(gm.clone() * (s - c.pb[kc].clone() - c.mc[kc].clone() * k::<T>(256)));
    }
    z.push(gm * c.mc[63].clone());

    // ---- REVERTS (crate::vm::revert). Each kind proves its instruction FAILS on these operands; the row then ends the
    // call (cpu_lookups: END_REVERT instead of a next state).
    use vm::revert as rk;
    // REQUIRE / DIVMOD / DIVMODW / ASEL: rs is zero
    z.push((c.r(rk::REQUIRE) + c.r(rk::DIVMOD) + c.r(rk::DIVMODW) + c.r(rk::ASEL)) * nz_rs.clone());
    // NOTB (rd not 0 or 1), RANGE (rd >= 2^62), ARG (rs >= the arg count): either the high limbs are not all zero (rb = 0:
    // their sum m has an inverse; canonical limbs, so the sum is zero iff they are), or the low limb minus the bound is
    // in [0, 2^16) (rb = 1: rr, range-checked; below the bound it would be p minus something, outside the range)
    let hs = |w: &[T], from: usize| w[from..].iter().fold(T::zero(), |s, x| s + x.clone());
    let g3 = c.r(rk::NOTB) + c.r(rk::RANGE) + c.r(rk::ARG);
    let x = c.r(rk::NOTB) * hs(&c.rd, 1) + c.r(rk::RANGE) * hs(&c.rd, 4) + c.r(rk::ARG) * hs(&c.rs, 1);
    z.push(c.m.clone() - c.rb.clone() - (one() - c.rb.clone()) * x);
    z.push(g3.clone() * (c.m.clone() * c.rinv.clone() - one()));
    z.push((one() - g3.clone()) * c.rinv.clone());
    z.push((one() - g3) * c.rb.clone());
    z.push(c.rr.clone() - c.rb.clone() * (c.r(rk::NOTB) * (c.rd[0].clone() - k::<T>(2))
        + c.r(rk::RANGE) * (c.rd[3].clone() - k::<T>(1 << 14)) + c.r(rk::ARG) * (c.rs[0].clone() - c.nargs.clone())));
    z.push((one() - c.r(rk::ARG)) * c.nargs.clone());
    // OOB: the pc is the method's length (jumps stay inside it, so only a fall-through gets past the end)
    z.push(c.oob.clone() * (c.pc.clone() - c.plen.clone()));
    z.push((one() - c.oob.clone()) * c.plen.clone());
    // OOG: the run has spent the whole budget (zkvm2 checks it before the next fetch)
    z.push(c.oog.clone() * (c.clk.clone() - k::<T>(vm::GAS_LIMIT as u32)));
    // the io entry a reverting PAY / ABURN / BHASH / BEACON emits: as the op would (PAY d s), or the key read (BHASH s, 0)
    let rw = c.r(rk::PAY) + c.r(rk::ABURN);
    let rmiss = c.r(rk::BHASH) + c.r(rk::BEACON);
    for l in 0..16 {
        z.push(rw.clone() * (c.io_a[l].clone() - c.rd[l].clone()));
        z.push(rw.clone() * (c.io_b[l].clone() - c.rs[l].clone()));
        z.push(rmiss.clone() * (c.io_a[l].clone() - c.rs[l].clone()));
        z.push(rmiss.clone() * c.io_b[l].clone());
    }
    z
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Rel {
    State,
    Tab,
    Io,
    Blake,
    Xor8,
    Range,
}

/// Every lookup of a CPU row, in the order the evaluator adds them: (numerator, relation, values).
fn cpu_lookups<T: Fe>(c: &Cols<T>) -> Vec<(T, Rel, Vec<T>)> {
    let mut v: Vec<(T, Rel, Vec<T>)> = vec![];
    let regs = |r: &Vec<Vec<T>>| r.iter().flat_map(|x| x.iter().cloned()).collect_vec();
    let a = c.active.clone();
    let ret = c.s(op::RET);
    let emit = c.emit();
    // the machine state: consume this row's, produce the next (or the END tuple on RET)
    let st = |tag: u32, clk: T, pc: T, ioc: T, r: Vec<T>, h: Vec<T>| {
        let mut t = vec![k::<T>(tag), c.cix.clone(), clk, pc, c.prog.clone(), ioc];
        t.extend(r);
        t.extend(h);
        t
    };
    v.push((-a.clone(), Rel::State, st(TAG_STATE, c.clk.clone(), c.pc.clone(), c.ioc.clone(), regs(&c.regs), c.h.clone())));
    let clk1 = c.clk.clone() + T::one();
    let ioc1 = c.ioc.clone() + emit.clone();
    let term = c.term();
    v.push((a.clone() - ret.clone() - term.clone(), Rel::State,
            st(TAG_STATE, clk1.clone(), c.npc.clone(), ioc1.clone(), regs(&c.nregs), c.nh.clone())));
    v.push((ret, Rel::State, st(TAG_END, clk1.clone(), T::zero(), ioc1.clone(), vec![T::zero(); NUM_REGS * 16], vec![T::zero(); 16])));
    // a REVERT ends the call: its gas (the reverting step counts; an OOG row executes nothing) and its kind
    let kind = (0..vm::revert::N_OP).fold(T::zero(), |s, j| s + c.rsel[j].clone() * k::<T>(j as u32))
        + c.oob.clone() * k::<T>(vm::revert::OOB) + c.oog.clone() * k::<T>(vm::revert::OOG);
    v.push((term, Rel::State, st(TAG_REVERT, clk1 - c.oog.clone(), kind, ioc1, vec![T::zero(); NUM_REGS * 16], vec![T::zero(); 16])));
    // the instruction at (prog, pc): its op from the opcode one-hot, or from the revert one-hot on a revert row
    let num = |sel: &[T]| (0..sel.len()).fold(T::zero(), |s, i| s + sel[i].clone() * k::<T>(i as u32));
    let rop = (0..vm::revert::N_OP).fold(T::zero(), |s, j| s + c.rsel[j].clone() * k::<T>(vm::revert::OP[j] as u32));
    let mut ins = vec![k::<T>(TAB_PROG), c.prog.clone(), c.pc.clone(), num(&c.sel) + rop, num(&c.dsel), num(&c.ssel)];
    ins.extend(c.imm.iter().cloned());
    ins.push(T::zero());
    v.push((-(a - c.oob.clone() - c.oog.clone()), Rel::Tab, ins));
    // an OOB row's program length; an ARG revert's arg count
    let mut len = vec![k::<T>(TAB_LEN), c.prog.clone(), c.plen.clone()];
    len.resize(TAB_W, T::zero());
    v.push((-c.oob.clone(), Rel::Tab, len));
    let mut na = vec![k::<T>(TAB_DATA), c.cix.clone(), k::<T>(DATA_NARGS), T::zero(), c.nargs.clone()];
    na.resize(TAB_W, T::zero());
    v.push((-c.r(vm::revert::ARG), Rel::Tab, na));
    // the call's data: CTX / ACTX / ARG -> res
    let dk = c.s(op::ACTX) * k::<T>(DATA_ACTX) + c.s(op::ARG) * k::<T>(DATA_ARG) + c.s(op::CTX) * k::<T>(DATA_CTX);
    let mut d = vec![k::<T>(TAB_DATA), c.cix.clone(), dk, c.cidx.clone()];
    d.extend(c.res.iter().cloned());
    d.resize(TAB_W, T::zero());
    v.push((-c.g(&[op::CTX, op::ACTX, op::ARG]), Rel::Tab, d));
    // the io entry this row emits
    let mut e = vec![c.cix.clone(), c.ioc.clone(), c.kind()];
    e.extend(c.io_a.iter().cloned());
    e.extend(c.io_b.iter().cloned());
    v.push((-emit, Rel::Io, e));
    // HABS: one BLAKE2s compression (start state by person, the output state, the message)
    let sh = c.s(op::HABS);
    let vi = v_init(PERSON_HASH);
    let mut b: Vec<T> = (0..16).flat_map(|j| [sh.clone() * k::<T>(vi[j] & 0xffff), sh.clone() * k::<T>(vi[j] >> 16)]).collect();
    b.extend(c.out.iter().cloned());
    b.extend((0..32).map(|n| c.msg(n)));
    v.push((-sh.clone(), Rel::Blake, b));
    // digest = out[i] ^ out[i+8] ^ h0[i], bytewise through XOR-8
    let hc = h0(PERSON_HASH);
    for i in 0..8 {
        for j in 0..2 {
            let base = (i * 2 + j) * 6;
            let (ah, bh, tl, th, dl, dh) = (c.dg[base].clone(), c.dg[base + 1].clone(), c.dg[base + 2].clone(),
                                            c.dg[base + 3].clone(), c.dg[base + 4].clone(), c.dg[base + 5].clone());
            let al = c.out[2 * i + j].clone() - ah.clone() * k::<T>(256);
            let bl = c.out[2 * (i + 8) + j].clone() - bh.clone() * k::<T>(256);
            let cw = (hc[i] >> (16 * j)) & 0xffff;
            let (cl, ch) = (sh.clone() * k::<T>(cw & 0xff), sh.clone() * k::<T>(cw >> 8));
            v.push((T::one(), Rel::Xor8, vec![al, bl, tl.clone()]));
            v.push((T::one(), Rel::Xor8, vec![ah, bh, th.clone()]));
            v.push((T::one(), Rel::Xor8, vec![tl, cl, dl]));
            v.push((T::one(), Rel::Xor8, vec![th, ch, dh]));
        }
    }
    // bytes, range-checked (b ^ 0 = b)
    for x in chain![c.ab.iter(), c.bb.iter(), c.cb.iter(), c.pb.iter()] {
        v.push((T::one(), Rel::Xor8, vec![x.clone(), T::zero(), x.clone()]));
    }
    // 16-bit values
    for x in chain![c.res.iter(), c.ax.iter(), c.mc.iter(), [&c.rq, &c.rr]] {
        v.push((-T::one(), Rel::Range, vec![x.clone()]));
    }
    v
}

// ---------------------------------------------------------------------------------------------------------------
// the components

pub struct CpuEval {
    pub log_size: u32,
    pub state: StateElements,
    pub tab: TabElements,
    pub io: IoElements,
    pub range: RangeElements,
    pub blake: BlakeElements,
    pub xor: BlakeXorElements,
    pub claimed_sum: SecureField,
}
pub type CpuComponent = FrameworkComponent<CpuEval>;

impl FrameworkEval for CpuEval {
    fn log_size(&self) -> u32 {
        self.log_size
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        self.log_size + 1 // every constraint is degree <= 3 (module comment)
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let flat: Vec<E::F> = (0..N_COLS).map(|_| e.next_trace_mask()).collect();
        let c = Cols::from_iter(&mut flat.into_iter());
        for x in cpu_constraints(&c) {
            e.add_constraint(x);
        }
        for (num, rel, vals) in cpu_lookups(&c) {
            let n = E::EF::from(num);
            match rel {
                Rel::State => e.add_to_relation(RelationEntry::new(&self.state, n, &vals)),
                Rel::Tab => e.add_to_relation(RelationEntry::new(&self.tab, n, &vals)),
                Rel::Io => e.add_to_relation(RelationEntry::new(&self.io, n, &vals)),
                Rel::Blake => e.add_to_relation(RelationEntry::new(&self.blake, n, &vals)),
                Rel::Xor8 => e.add_to_relation(RelationEntry::new(&self.xor.xor8, n, &vals)),
                Rel::Range => e.add_to_relation(RelationEntry::new(&self.range, n, &vals)),
            }
        }
        e.finalize_logup_in_pairs();
        e
    }
}

fn tab_id(i: usize) -> PreProcessedColumnId {
    PreProcessedColumnId { id: format!("vm_tab_{i}") }
}
fn range_id() -> PreProcessedColumnId {
    PreProcessedColumnId { id: "vm_range16".to_string() }
}

/// The statement's table (programs, then the calls' data): +mult x each row.
pub struct TabEval {
    pub log_size: u32,
    pub tab: TabElements,
    pub claimed_sum: SecureField,
}
pub type TabComponent = FrameworkComponent<TabEval>;
impl FrameworkEval for TabEval {
    fn log_size(&self) -> u32 {
        self.log_size
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        self.log_size + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let vals: Vec<E::F> = (0..TAB_W).map(|i| e.get_preprocessed_column(tab_id(i))).collect();
        let mult = e.next_trace_mask();
        e.add_to_relation(RelationEntry::new(&self.tab, E::EF::from(mult), &vals));
        e.finalize_logup_in_pairs();
        e
    }
}

pub const RANGE_LOG: u32 = 16;
pub const MAX_BLAKE_LOG: u32 = 22;
pub struct RangeEval {
    pub range: RangeElements,
    pub claimed_sum: SecureField,
}
pub type RangeComponent = FrameworkComponent<RangeEval>;
impl FrameworkEval for RangeEval {
    fn log_size(&self) -> u32 {
        RANGE_LOG
    }
    fn max_constraint_log_degree_bound(&self) -> u32 {
        RANGE_LOG + 1
    }
    fn evaluate<E: EvalAtRow>(&self, mut e: E) -> E {
        let v = e.get_preprocessed_column(range_id());
        let mult = e.next_trace_mask();
        e.add_to_relation(RelationEntry::new(&self.range, E::EF::from(mult), &[v]));
        e.finalize_logup_in_pairs();
        e
    }
}

// ---------------------------------------------------------------------------------------------------------------
// the witness

fn f(x: u32) -> BaseField {
    BaseField::from_u32_unchecked(x)
}
fn fw(w: &W) -> Vec<BaseField> {
    vm::limbs16(w).iter().map(|x| f(*x)).collect()
}

/// limbwise a + b = c + 2^256 cout: the carries
fn carries(a: &W, b: &W) -> Vec<u32> {
    let (la, lb) = (vm::limbs16(a), vm::limbs16(b));
    let mut c = 0u32;
    (0..16)
        .map(|l| {
            let t = la[l] + lb[l] + c;
            c = t >> 16;
            c
        })
        .collect()
}

/// The CPU row of one step, as field values. (A padding row is all zero.)
fn cpu_row(s: &Step) -> Cols<BaseField> {
    use vm::revert as rk;
    // a revert row executes no opcode's semantics (o = none below); OOB/OOG rows execute no instruction at all
    let terminal = matches!(s.revert, Some(rk::OOB) | Some(rk::OOG));
    let o = if s.revert.is_some() { usize::MAX } else { s.ins.op };
    let (rd, rs) = if terminal { (vm::ZERO, vm::ZERO) } else { (s.regs[s.ins.d], s.regs[s.ins.s]) };
    let onehot = |n: usize, i: usize| (0..n).map(|j| f((j == i) as u32)).collect_vec();
    // the adder's operands, by op
    let z = vm::ZERO;
    let (ax, ay, az) = match o {
        op::ADD => (rd, rs, s.res),
        op::SUB => (s.res, rs, rd),
        op::EQ | op::LT => (vm::sub(&rd, &rs), rs, rd),
        op::DIVMOD | op::DIVMODW => (vm::sub(&s.rem, &rs), rs, s.rem),
        _ => (z, z, z),
    };
    let cy = carries(&ax, &ay);
    let nzinv = |w: &W| {
        let sum: u32 = vm::limbs16(w).iter().sum();
        if sum == 0 { (f(0), f(0)) } else { (f(1), f(sum).inverse()) }
    };
    let (nzd, invd) = nzinv(&rd);
    let (nzs, invs) = nzinv(&rs);
    let (nzx, invx) = nzinv(&ax);
    // the byte convolution's operands: MUL a=rd b=rs c=0; DIV a=q b=rs c=rem; HABS a=h b=rs (no product)
    let (am, bm, cm) = match o {
        op::MUL => (rd, rs, z),
        op::DIVMOD | op::DIVMODW => (s.res, rs, s.rem),
        op::HABS => (s.h, rs, z),
        _ => (z, z, z),
    };
    let conv = matches!(o, op::MUL | op::DIVMOD | op::DIVMODW);
    let (ab, bb, cb) = (vm::bytes_le(&am), vm::bytes_le(&bm), vm::bytes_le(&cm));
    let mut pb = [0u32; 64];
    let mut mc = [0u32; 64];
    if conv {
        let mut carry = 0u64;
        for kc in 0..64usize {
            let mut t = carry;
            for i in kc.saturating_sub(31)..=kc.min(31) {
                t += ab[i] as u64 * bb[kc - i] as u64;
            }
            if kc < 32 {
                t += cb[kc] as u64;
            }
            pb[kc] = (t & 0xff) as u32;
            carry = t >> 8;
            mc[kc] = carry as u32;
        }
    }
    // HABS: the compression's output state and the digest bytes
    let (out, dgv) = if o == op::HABS {
        let m = vm::absorb_msg(&s.h, &rs);
        let out = rounds(v_init(PERSON_HASH), &m);
        let hc = h0(PERSON_HASH);
        let mut dg = vec![];
        for i in 0..8 {
            for j in 0..2 {
                let a = (out[i] >> (16 * j)) & 0xffff;
                let b = (out[i + 8] >> (16 * j)) & 0xffff;
                let cw = (hc[i] >> (16 * j)) & 0xffff;
                let (tl, th) = ((a & 0xff) ^ (b & 0xff), (a >> 8) ^ (b >> 8));
                dg.extend([a >> 8, b >> 8, tl, th, tl ^ (cw & 0xff), th ^ (cw >> 8)]);
            }
        }
        (out.iter().flat_map(|x| [x & 0xffff, x >> 16]).collect_vec(), dg)
    } else {
        (vec![0u32; 32], vec![0u32; 96])
    };
    let (io_a, io_b) = s.emitted.map(|e| (e.a, e.b)).unwrap_or((z, z));
    let cidx = match o {
        op::CTX | op::ACTX => s.ins.imm[0] as u32,
        op::ARG => rs[0] as u32,
        _ => 0,
    };
    let fu = |v: &[u32]| v.iter().map(|x| f(*x)).collect_vec();
    // the revert columns (nargs / plen are the caller's: Step does not carry them)
    let rkind = s.revert.filter(|&k| (k as usize) < rk::N_OP);
    let hs = |w: &W, from: usize| vm::limbs16(w)[from..].iter().sum::<u32>();
    let (rb, m, rinv, rr) = match rkind {
        Some(k) if k == rk::NOTB || k == rk::RANGE || k == rk::ARG => {
            let (hi, lo) = match k {
                rk::NOTB => (hs(&rd, 1), vm::limbs16(&rd)[0] as i64 - 2),
                rk::RANGE => (hs(&rd, 4), vm::limbs16(&rd)[3] as i64 - (1 << 14)),
                _ => (hs(&rs, 1), vm::limbs16(&rs)[0] as i64), // minus nargs: set by the caller (prove_vm)
            };
            if hi != 0 { (f(0), f(hi), f(hi).inverse(), f(0)) } else { (f(1), f(1), f(1), f(lo.max(0) as u32)) }
        }
        _ => (f(0), f(0), f(0), f(0)),
    };
    let rsel = (0..rk::N_OP).map(|j| f((rkind == Some(j as u32)) as u32)).collect_vec();
    let zeros = |n: usize| vec![f(0); n];
    Cols {
        active: f(1),
        cix: f(s.cix as u32),
        clk: f(s.clk as u32),
        pc: f(s.pc as u32),
        prog: f(0), // set by the caller (the call's program index)
        ioc: f(s.ioc as u32),
        sel: if s.revert.is_some() { zeros(N_OPS) } else { onehot(N_OPS, o) },
        dsel: if terminal { zeros(NUM_REGS) } else { onehot(NUM_REGS, s.ins.d) },
        ssel: if terminal { zeros(NUM_REGS) } else { onehot(NUM_REGS, s.ins.s) },
        imm: if terminal { fw(&vm::ZERO) } else { fw(&s.ins.imm) },
        regs: s.regs.iter().map(fw).collect(),
        h: fw(&s.h),
        rd: fw(&rd),
        rs: fw(&rs),
        res: fw(&s.res),
        nregs: s.regs_next.iter().map(fw).collect(),
        nh: fw(&s.h_next),
        npc: f(s.pc_next as u32),
        ax: fw(&ax),
        ay: fw(&ay),
        az: fw(&az),
        cy: fu(&cy),
        nz: vec![nzd, invd, nzs, invs, nzx, invx],
        rem: fw(&s.rem),
        rq: f(if o == op::RANGE { vm::limbs16(&rd)[3] * 4 } else { 0 }),
        ab: fu(&ab),
        bb: fu(&bb),
        cb: fu(&cb),
        pb: fu(&pb),
        mc: fu(&mc),
        out: fu(&out),
        dg: fu(&dgv),
        io_a: fw(&io_a),
        io_b: fw(&io_b),
        cidx: f(cidx),
        rsel,
        oob: f((s.revert == Some(rk::OOB)) as u32),
        oog: f((s.revert == Some(rk::OOG)) as u32),
        rb,
        m,
        rinv,
        rr,
        nargs: f(0),
        plen: f(0),
    }
}

/// A step's row in the context of its call: the program index, and what a revert row reads from the call (the arg count)
/// or its program (the length). The ONE row builder for the prover, the constraint debugger and the probe.
fn step_row(st: &VmStatement, call: &vm::Call, s: &Step) -> Cols<BaseField> {
    let mut r = cpu_row(s);
    r.prog = f(call.prog as u32);
    if s.revert == Some(vm::revert::ARG) {
        r.nargs = f(call.args.len() as u32);
        if r.rb == f(1) {
            r.rr -= r.nargs; // the low limb minus the arg count (cpu_row left the limb)
        }
    }
    if s.revert == Some(vm::revert::OOB) {
        r.plen = f(st.progs[call.prog].len() as u32);
    }
    r
}

/// a step's label in debug output and the probe: the op, or the revert kind
fn step_label(s: &Step) -> String {
    match s.revert {
        Some(vm::revert::OOB) => "OOB".into(),
        Some(vm::revert::OOG) => "OOG".into(),
        Some(_) => format!("{}!REVERT", vm::OPS[s.ins.op]),
        None => vm::OPS[s.ins.op].into(),
    }
}

fn zero_row() -> Cols<BaseField> {
    Cols::from_iter(&mut std::iter::repeat_n(BaseField::zero(), N_COLS))
}

/// TEST ONLY: a dishonest prover's witness. Each breaks exactly one thing the honest run does, on the first row it fits,
/// and leaves the rest of the trace as the honest one: the circuit must refuse it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tamper {
    None,
    /// a MUL whose result is off by one (the low limb)
    MulResult,
    /// a taken JNZ that falls through instead (pc + 1)
    JnzNotTaken,
    /// an ADD that also changes a register it does not name
    StrayWrite,
    /// HABS absorbs into a different hash state than the compression's digest
    HashState,
    /// an LT that answers the opposite
    LtFlipped,
    /// a REVERT where the instruction does not fail (vm::run_forced builds the revert row the statement asks for)
    ForceRevert,
}

/// The table rows (programs, then each call's data), in order, as TAB_W values each.
fn table_rows(st: &VmStatement) -> Vec<Vec<u32>> {
    let mut rows = vec![];
    for (p, prog) in st.progs.iter().enumerate() {
        for (pc, ins) in prog.iter().enumerate() {
            let mut r = vec![TAB_PROG, p as u32, pc as u32, ins.op as u32, ins.d as u32, ins.s as u32];
            r.extend(vm::limbs16(&ins.imm));
            r.push(0);
            rows.push(r);
        }
        let mut r = vec![TAB_LEN, p as u32, prog.len() as u32];
        r.resize(TAB_W, 0);
        rows.push(r);
    }
    for (cix, call) in st.calls.iter().enumerate() {
        let mut data = |kind: u32, idx: usize, w: &W| {
            let mut r = vec![TAB_DATA, cix as u32, kind, idx as u32];
            r.extend(vm::limbs16(w));
            r.resize(TAB_W, 0);
            rows.push(r);
        };
        for (i, w) in call.ctx.iter().enumerate() {
            data(DATA_CTX, i, w);
        }
        for (i, w) in call.actx.iter().enumerate() {
            data(DATA_ACTX, i, w);
        }
        for (i, w) in call.args.iter().enumerate() {
            data(DATA_ARG, i, w);
        }
        data(DATA_NARGS, 0, &vm::from_u64(call.args.len() as u64));
    }
    rows
}

fn log_for(n: usize) -> u32 {
    (n.max(1).next_power_of_two().trailing_zeros()).max(LOG_N_LANES)
}

/// The sizes of the statement's components: (cpu, table, scheduler) logs.
fn logs(st: &VmStatement) -> (u32, u32, u32) {
    // an out-of-gas call has one row past its gas (the terminal row, which executes nothing)
    let steps: usize = st.calls.iter().map(|c| c.n_steps + (c.revert == Some(vm::revert::OOG)) as usize).sum();
    (log_for(steps), log_for(table_rows(st).len()), LOG_N_LANES)
}

type Evals = Vec<CircleEvaluation<SimdBackend, BaseField, BitReversedOrder>>;

fn evals(cols: Vec<Vec<BaseField>>, log: u32) -> Evals {
    let dom = CanonicCoset::new(log).circle_domain();
    cols.into_iter().map(|c| CircleEvaluation::new(dom, c.into_iter().collect::<BaseColumn>())).collect()
}

fn preprocessed_ids(_tlog: u32) -> Vec<PreProcessedColumnId> {
    let mut ids = vec![];
    for (w, ex) in [(12, 4), (9, 2), (8, 2), (7, 2), (4, 0)] {
        for c in 0..3 {
            ids.push(XorTable::new(w, ex, c).id());
        }
    }
    ids.extend((0..TAB_W).map(tab_id));
    ids.push(range_id());
    ids
}

fn preprocessed_evals(st: &VmStatement, tlog: u32) -> Evals {
    let rows = table_rows(st);
    let n = 1usize << tlog;
    let tab: Vec<Vec<BaseField>> =
        (0..TAB_W).map(|i| (0..n).map(|r| f(rows.get(r).map(|x| x[i]).unwrap_or(0))).collect()).collect();
    let range: Vec<Vec<BaseField>> = vec![(0..1u32 << RANGE_LOG).map(f).collect()];
    chain![
        XorTable::new(12, 4, 0).generate_constant_trace(),
        XorTable::new(9, 2, 0).generate_constant_trace(),
        XorTable::new(8, 2, 0).generate_constant_trace(),
        XorTable::new(7, 2, 0).generate_constant_trace(),
        XorTable::new(4, 0, 0).generate_constant_trace(),
        evals(tab, tlog),
        evals(range, RANGE_LOG),
    ]
    .collect()
}

struct Elements {
    blake: BlakeElements,
    round: RoundElements,
    xor: BlakeXorElements,
    state: StateElements,
    tab: TabElements,
    io: IoElements,
    range: RangeElements,
}
impl Elements {
    fn draw(ch: &mut impl Channel) -> Self {
        Self {
            blake: BlakeElements::draw(ch),
            round: RoundElements::draw(ch),
            xor: BlakeXorElements::draw(ch),
            state: StateElements::draw(ch),
            tab: TabElements::draw(ch),
            io: IoElements::draw(ch),
            range: RangeElements::draw(ch),
        }
    }
    fn dummy() -> Self {
        Self {
            blake: BlakeElements::dummy(),
            round: RoundElements::dummy(),
            xor: BlakeXorElements::dummy(),
            state: StateElements::dummy(),
            tab: TabElements::dummy(),
            io: IoElements::dummy(),
            range: RangeElements::dummy(),
        }
    }
    fn combine_packed(&self, rel: Rel, vals: &[PackedBaseField]) -> PackedSecureField {
        match rel {
            Rel::State => self.state.combine(vals),
            Rel::Tab => self.tab.combine(vals),
            Rel::Io => self.io.combine(vals),
            Rel::Blake => self.blake.combine(vals),
            Rel::Xor8 => self.xor.xor8.combine(vals),
            Rel::Range => self.range.combine(vals),
        }
    }
}

struct Components {
    scheduler: BlakeSchedulerComponent,
    rounds: Vec<BlakeRoundComponent>,
    xor12: xor12::XorTableComponent<12, 4>,
    xor9: xor9::XorTableComponent<9, 2>,
    xor8: xor8::XorTableComponent<8, 2>,
    xor7: xor7::XorTableComponent<7, 2>,
    xor4: xor4::XorTableComponent<4, 0>,
    cpu: CpuComponent,
    tab: TabComponent,
    range: RangeComponent,
}

const N_SUMS: usize = 1 + ROUND_LOG_SPLIT.len() + 5 + 3;

impl Components {
    fn new(logs: (u32, u32, u32), tlog: u32, el: &Elements, sums: &[SecureField]) -> Self {
        let (clog, _, blog) = logs;
        let alloc = &mut TraceLocationAllocator::new_with_preprocessed_columns(&preprocessed_ids(tlog));
        let s = |i: usize| sums[i];
        let scheduler = BlakeSchedulerComponent::new(
            alloc,
            BlakeSchedulerEval {
                log_size: blog,
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
                        log_size: blog + l,
                        xor_lookup_elements: el.xor.clone(),
                        round_lookup_elements: el.round.clone(),
                        claimed_sum: s(1 + i),
                    },
                    s(1 + i),
                )
            })
            .collect();
        let kx = 1 + ROUND_LOG_SPLIT.len();
        Self {
            scheduler,
            rounds,
            xor12: xor12::XorTableComponent::new(alloc, xor12::XorTableEval { lookup_elements: el.xor.xor12.clone(), claimed_sum: s(kx) }, s(kx)),
            xor9: xor9::XorTableComponent::new(alloc, xor9::XorTableEval { lookup_elements: el.xor.xor9.clone(), claimed_sum: s(kx + 1) }, s(kx + 1)),
            xor8: xor8::XorTableComponent::new(alloc, xor8::XorTableEval { lookup_elements: el.xor.xor8.clone(), claimed_sum: s(kx + 2) }, s(kx + 2)),
            xor7: xor7::XorTableComponent::new(alloc, xor7::XorTableEval { lookup_elements: el.xor.xor7.clone(), claimed_sum: s(kx + 3) }, s(kx + 3)),
            xor4: xor4::XorTableComponent::new(alloc, xor4::XorTableEval { lookup_elements: el.xor.xor4.clone(), claimed_sum: s(kx + 4) }, s(kx + 4)),
            cpu: CpuComponent::new(
                alloc,
                CpuEval {
                    log_size: clog,
                    state: el.state.clone(),
                    tab: el.tab.clone(),
                    io: el.io.clone(),
                    range: el.range.clone(),
                    blake: el.blake.clone(),
                    xor: el.xor.clone(),
                    claimed_sum: s(kx + 5),
                },
                s(kx + 5),
            ),
            tab: TabComponent::new(alloc, TabEval { log_size: tlog, tab: el.tab.clone(), claimed_sum: s(kx + 6) }, s(kx + 6)),
            range: RangeComponent::new(alloc, RangeEval { range: el.range.clone(), claimed_sum: s(kx + 7) }, s(kx + 7)),
        }
    }
    fn components(&self) -> Vec<&dyn Component> {
        chain![
            [&self.scheduler as &dyn Component],
            self.rounds.iter().map(|c| c as &dyn Component),
            [&self.xor12 as &dyn Component, &self.xor9, &self.xor8, &self.xor7, &self.xor4, &self.cpu, &self.tab, &self.range]
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
                &self.cpu,
                &self.tab,
                &self.range
            ]
        ]
        .collect()
    }
}

fn log_sizes(logs: (u32, u32, u32)) -> TreeVec<Vec<u32>> {
    let (clog, tlog, blog) = logs;
    let mut sizes = vec![];
    sizes.push(blake_scheduler_info().mask_offsets.as_cols_ref().map_cols(|_| blog));
    for l in ROUND_LOG_SPLIT {
        sizes.push(blake_round_info().mask_offsets.as_cols_ref().map_cols(|_| blog + l));
    }
    sizes.push(xor12::trace_sizes::<12, 4>());
    sizes.push(xor9::trace_sizes::<9, 2>());
    sizes.push(xor8::trace_sizes::<8, 2>());
    sizes.push(xor7::trace_sizes::<7, 2>());
    sizes.push(xor4::trace_sizes::<4, 0>());
    let el = Elements::dummy();
    let z = SecureField::zero();
    let cpu = CpuEval {
        log_size: clog,
        state: el.state.clone(),
        tab: el.tab.clone(),
        io: el.io.clone(),
        range: el.range.clone(),
        blake: el.blake.clone(),
        xor: el.xor.clone(),
        claimed_sum: z,
    };
    sizes.push(cpu.evaluate(InfoEvaluator::empty()).mask_offsets.as_cols_ref().map_cols(|_| clog));
    let tab = TabEval { log_size: tlog, tab: el.tab.clone(), claimed_sum: z };
    sizes.push(tab.evaluate(InfoEvaluator::empty()).mask_offsets.as_cols_ref().map_cols(|_| tlog));
    let range = RangeEval { range: el.range.clone(), claimed_sum: z };
    sizes.push(range.evaluate(InfoEvaluator::empty()).mask_offsets.as_cols_ref().map_cols(|_| RANGE_LOG));
    let mut out = TreeVec::concat_cols(sizes.into_iter());
    let mut pre: Vec<u32> = vec![];
    for (w, ex) in [(12, 4), (9, 2), (8, 2), (7, 2), (4, 0)] {
        for c in 0..3 {
            pre.push(XorTable::new(w, ex, c).column_bits());
        }
    }
    pre.extend((0..TAB_W).map(|_| tlog));
    pre.push(RANGE_LOG);
    out[PREPROCESSED_TRACE_IDX] = pre;
    out
}

impl VmStatement {
    fn mix_into(&self, ch: &mut impl Channel) {
        let w = |ch: &mut dyn FnMut(&[u32]), x: &W| ch(&vm::limbs16(x));
        let mut words: Vec<u32> = vec![];
        let mut push = |s: &[u32]| words.extend_from_slice(s);
        push(&[self.progs.len() as u32]);
        for p in &self.progs {
            push(&[p.len() as u32]);
            for i in p {
                push(&[i.op as u32, i.d as u32, i.s as u32]);
                w(&mut push, &i.imm);
            }
        }
        push(&[self.calls.len() as u32]);
        for c in &self.calls {
            push(&[c.prog as u32, c.n_steps as u32, c.args.len() as u32, c.io.len() as u32, c.revert.map_or(0, |k| k + 1)]);
            for x in chain![c.args.iter(), c.ctx.iter(), c.actx.iter()] {
                w(&mut push, x);
            }
            for e in &c.io {
                push(&[e.kind]);
                w(&mut push, &e.a);
                w(&mut push, &e.b);
            }
        }
        ch.mix_u32s(&words);
    }
}

#[derive(Clone)]
pub struct VmProof {
    /// the BLAKE2s scheduler's log size: the number of HABS rows is not public, so the prover states it (any value in
    /// [LOG_N_LANES, MAX_BLAKE_LOG] is sound: a scheduler too small for the HABS rows leaves the LogUp sum nonzero)
    pub blake_log: u32,
    pub sums: Vec<SecureField>,
    pub stark: StarkProof<Blake2sMerkleHasher>,
}

/// One CPU row's entries (numerator, relation, values) as field values, plus the row itself.
type Entries = Vec<(BaseField, Rel, Vec<BaseField>)>;

/// Prove the statement. The witness is the reference run of every call (crate::vm::run), optionally tampered.
pub fn prove_vm(st: &VmStatement, config: PcsConfig, tamper: Tamper) -> Result<VmProof, String> {
    for p in &st.progs {
        vm::validate_method(p)?;
    }
    let mut rows: Vec<Cols<BaseField>> = vec![];
    let mut habs: Vec<[u32; 16]> = vec![];
    let mut tampered = false;
    for (cix, call) in st.calls.iter().enumerate() {
        let prog = st.progs.get(call.prog).ok_or("no such program")?;
        let steps = if tamper == Tamper::ForceRevert { vm::run_forced(prog, call, cix)? } else { vm::run(prog, call, cix)? };
        tampered |= tamper == Tamper::ForceRevert && call.revert.is_some();
        for s in &steps {
            let mut r = step_row(st, call, s);
            if s.revert.is_none() && s.ins.op == op::HABS {
                habs.push(vm::absorb_msg(&s.h, &s.regs[s.ins.s]));
            }
            if !tampered {
                tampered = apply_tamper(&mut r, s, tamper);
            }
            rows.push(r);
        }
    }
    if tamper != Tamper::None && !tampered {
        return Err(format!("tamper {tamper:?} found no row to apply to"));
    }
    let (clog, tlog, _) = logs(st);
    let blog = log_for(habs.len());
    let lg = (clog, tlog, blog);
    let n = 1usize << clog;
    rows.resize(n, zero_row());

    let log_max = [clog + 1, tlog + 1, RANGE_LOG + 1, blog + *ROUND_LOG_SPLIT.iter().max().unwrap() + 1, 17].into_iter().max().unwrap();
    let twiddles = SimdBackend::precompute_twiddles(
        CanonicCoset::new(log_max + config.fri_config.log_blowup_factor).circle_domain().half_coset,
    );
    let channel = &mut Blake2sChannel::default();
    config.mix_into(channel);
    st.mix_into(channel);
    let mut cs = CommitmentSchemeProver::<SimdBackend, Blake2sMerkleChannel>::new(config, &twiddles);
    cs.set_store_polynomials_coefficients();

    let mut tb = cs.tree_builder();
    tb.extend_evals(preprocessed_evals(st, tlog));
    tb.commit(channel);

    // the CPU entries (one generic definition with the evaluator), and the tables' multiplicities from them
    let entries: Vec<Entries> = rows.iter().map(cpu_lookups).collect();
    let tab_rows = table_rows(st);
    let tab_index: HashMap<Vec<u32>, usize> = tab_rows.iter().enumerate().map(|(i, r)| (r.clone(), i)).collect();
    let mut tab_mult = vec![0u32; 1 << tlog];
    let mut range_mult = vec![0u32; 1 << RANGE_LOG];
    let mut xor = XorAccums::default();
    let mut xor_pairs: Vec<Vec<(u32, u32)>> = vec![vec![]; n];
    for (r, ents) in entries.iter().enumerate() {
        for (num, rel, vals) in ents {
            if num.is_zero() {
                continue;
            }
            match rel {
                Rel::Tab => {
                    let key = vals.iter().map(|x| x.0).collect_vec();
                    let i = *tab_index.get(&key).ok_or("a row looks up a table entry the statement does not have")?;
                    tab_mult[i] += 1;
                }
                Rel::Range => {
                    let v = vals[0].0 as usize;
                    if v >= range_mult.len() {
                        return Err("a value outside 16 bits".into());
                    }
                    range_mult[v] += 1;
                }
                Rel::Xor8 => xor_pairs[r].push((vals[0].0, vals[1].0)),
                _ => {}
            }
        }
    }
    for vr in 0..(n >> LOG_N_LANES) {
        for j in 0..xor_pairs[0].len() {
            let a = u32x16::from_array(std::array::from_fn(|l| xor_pairs[(vr << LOG_N_LANES) + l][j].0));
            let b = u32x16::from_array(std::array::from_fn(|l| xor_pairs[(vr << LOG_N_LANES) + l][j].1));
            xor.add_input(8, a, b);
        }
    }

    // scheduler: one compression per HABS row
    let mut inputs = vec![];
    let vi = v_init(PERSON_HASH);
    for chunk in habs.chunks(1 << LOG_N_LANES) {
        inputs.push(BlakeInput {
            v: std::array::from_fn(|w| u32x16::from_array(std::array::from_fn(|l| if l < chunk.len() { vi[w] } else { 0 }))),
            m: std::array::from_fn(|w| u32x16::from_array(std::array::from_fn(|l| chunk.get(l).map(|m| m[w]).unwrap_or(0)))),
            mult: u32x16::from_array(std::array::from_fn(|l| (l < chunk.len()) as u32)),
        });
    }
    let (sched_trace, sched_lookup, round_inputs) = scheduler::gen_trace(blog, &inputs);
    let mut rest = &round_inputs[..];
    let (round_traces, round_lookup): (Vec<_>, Vec<_>) = multiunzip(ROUND_LOG_SPLIT.map(|l| {
        let (cur, r) = rest.split_at(1 << (blog - LOG_N_LANES + l));
        rest = r;
        round::generate_trace(blog + l, cur, &mut xor)
    }));
    let (x12, xl12) = xor12::generate_trace(xor.xor12);
    let (x9, xl9) = xor9::generate_trace(xor.xor9);
    let (x8, xl8) = xor8::generate_trace(xor.xor8);
    let (x7, xl7) = xor7::generate_trace(xor.xor7);
    let (x4, xl4) = xor4::generate_trace(xor.xor4);
    let cpu_cols: Vec<Vec<BaseField>> = {
        let flats = rows.iter().map(|r| r.flat()).collect_vec();
        (0..N_COLS).map(|i| flats.iter().map(|r| r[i]).collect()).collect()
    };
    let tab_trace = evals(vec![tab_mult.iter().map(|x| f(*x)).collect()], tlog);
    let range_trace = evals(vec![range_mult.iter().map(|x| f(*x)).collect()], RANGE_LOG);
    channel.mix_u64(((clog as u64) << 16) | ((tlog as u64) << 8) | blog as u64);
    let mut tb = cs.tree_builder();
    tb.extend_evals(
        chain![sched_trace, round_traces.into_iter().flatten(), x12, x9, x8, x7, x4, evals(cpu_cols, clog), tab_trace,
               range_trace]
        .collect_vec(),
    );
    tb.commit(channel);

    let el = Elements::draw(channel);
    let (s_tr, s_sum) = scheduler::gen_interaction_trace(blog, sched_lookup, &el.round, &el.blake);
    let (r_tr, r_sums): (Vec<_>, Vec<_>) = multiunzip(
        ROUND_LOG_SPLIT.iter().zip(round_lookup).map(|(l, ld)| round::generate_interaction_trace(blog + l, ld, &el.xor, &el.round)),
    );
    let (i12, s12) = xor12::generate_interaction_trace(xl12, &el.xor.xor12);
    let (i9, s9) = xor9::generate_interaction_trace(xl9, &el.xor.xor9);
    let (i8, s8) = xor8::generate_interaction_trace(xl8, &el.xor.xor8);
    let (i7, s7) = xor7::generate_interaction_trace(xl7, &el.xor.xor7);
    let (i4, s4) = xor4::generate_interaction_trace(xl4, &el.xor.xor4);
    let (c_tr, c_sum) = cpu_interaction(&entries, clog, &el);
    let (t_tr, t_sum) = table_interaction(&tab_rows, &tab_mult, tlog, &el);
    let (g_tr, g_sum) = range_interaction(&range_mult, &el);
    let sums: Vec<SecureField> = chain![[s_sum], r_sums, [s12, s9, s8, s7, s4, c_sum, t_sum, g_sum]].collect();
    let mut tb = cs.tree_builder();
    tb.extend_evals(chain![s_tr, r_tr.into_iter().flatten(), i12, i9, i8, i7, i4, c_tr, t_tr, g_tr].collect_vec());
    channel.mix_felts(&sums);
    tb.commit(channel);

    let comps = Components::new(lg, tlog, &el, &sums);
    let stark = prove::<SimdBackend, Blake2sMerkleChannel>(&comps.provers(), channel, cs).map_err(|e| format!("{e:?}"))?;
    Ok(VmProof { blake_log: blog, sums, stark })
}

fn apply_tamper(r: &mut Cols<BaseField>, s: &Step, t: Tamper) -> bool {
    let o = s.ins.op;
    match t {
        Tamper::None => false,
        Tamper::MulResult if o == op::MUL => {
            r.res[0] = r.res[0] + f(1);
            r.nregs[s.ins.d][0] = r.res[0];
            true
        }
        Tamper::JnzNotTaken if o == op::JNZ && s.pc_next != s.pc + 1 => {
            r.npc = f(s.pc as u32 + 1);
            true
        }
        Tamper::StrayWrite if o == op::ADD => {
            let other = (s.ins.d + 1) % NUM_REGS;
            r.nregs[other][0] = r.nregs[other][0] + f(1);
            true
        }
        Tamper::HashState if o == op::HABS => {
            r.nh[0] = r.nh[0] + f(1);
            true
        }
        Tamper::LtFlipped if o == op::LT => {
            r.res[0] = f(1) - r.res[0];
            r.nregs[s.ins.d][0] = r.res[0];
            true
        }
        _ => false,
    }
}

fn pack(vals: impl Fn(usize) -> BaseField) -> PackedBaseField {
    PackedBaseField::from_array(std::array::from_fn(vals))
}

fn cpu_interaction(entries: &[Entries], log: u32, el: &Elements) -> (Evals, SecureField) {
    let mut lg = LogupTraceGenerator::new(log);
    let n_ent = entries[0].len();
    let packed = |vr: usize, j: usize| -> (PackedSecureField, PackedSecureField) {
        let lane = |l: usize| &entries[(vr << LOG_N_LANES) + l][j];
        let num = PackedSecureField::from(pack(|l| lane(l).0));
        let width = lane(0).2.len();
        let vals: Vec<PackedBaseField> = (0..width).map(|kk| pack(|l| lane(l).2[kk])).collect();
        (num, el.combine_packed(lane(0).1, &vals))
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

fn table_interaction(rows: &[Vec<u32>], mult: &[u32], log: u32, el: &Elements) -> (Evals, SecureField) {
    let mut lg = LogupTraceGenerator::new(log);
    let mut col = lg.new_col();
    let val = |r: usize, i: usize| f(rows.get(r).map(|x| x[i]).unwrap_or(0));
    for vr in 0..(1usize << (log - LOG_N_LANES)) {
        let vals: Vec<PackedBaseField> = (0..TAB_W).map(|i| pack(|l| val((vr << LOG_N_LANES) + l, i))).collect();
        let num = PackedSecureField::from(pack(|l| f(mult[(vr << LOG_N_LANES) + l])));
        col.write_frac(vr, num, el.tab.combine(&vals));
    }
    col.finalize_col();
    lg.finalize_last()
}

fn range_interaction(mult: &[u32], el: &Elements) -> (Evals, SecureField) {
    let mut lg = LogupTraceGenerator::new(RANGE_LOG);
    let mut col = lg.new_col();
    for vr in 0..(1usize << (RANGE_LOG - LOG_N_LANES)) {
        let v = pack(|l| f(((vr << LOG_N_LANES) + l) as u32));
        let num = PackedSecureField::from(pack(|l| f(mult[(vr << LOG_N_LANES) + l])));
        col.write_frac(vr, num, el.range.combine(&[v]));
    }
    col.finalize_col();
    lg.finalize_last()
}

/// The commitment of the preprocessed trace for this statement (the XOR tables, its table, the range column).
pub fn preprocessed_root(st: &VmStatement, config: PcsConfig) -> <Blake2sMerkleHasher as stwo::core::vcs_lifted::merkle_hasher::MerkleHasherLifted>::Hash {
    let (_, tlog, _) = logs(st);
    let log_max = [tlog + 1, RANGE_LOG + 1, 17].into_iter().max().unwrap();
    let twiddles = SimdBackend::precompute_twiddles(
        CanonicCoset::new(log_max + config.fri_config.log_blowup_factor).circle_domain().half_coset,
    );
    let channel = &mut Blake2sChannel::default();
    let mut cs = CommitmentSchemeProver::<SimdBackend, Blake2sMerkleChannel>::new(config, &twiddles);
    let mut tb = cs.tree_builder();
    tb.extend_evals(preprocessed_evals(st, tlog));
    tb.commit(channel);
    cs.roots()[0]
}

#[derive(Debug)]
pub enum VmVerifyError {
    WeakConfig,
    /// a program fails zkvm2's static rules, or a call names no program / too many args / too much gas
    Static(String),
    Preprocessed,
    Shape,
    Sum,
    Stark(VerificationError),
}

/// The public LogUp terms: each call's initial state (+1, produced by the verifier), its END (-1, consumed), and every
/// io entry (+1, the CPU consumes each exactly once).
fn public_sum(st: &VmStatement, el: &Elements) -> SecureField {
    let inv = |rel: Rel, t: Vec<u32>| -> SecureField {
        let v: Vec<BaseField> = t.into_iter().map(f).collect();
        let d: SecureField = match rel {
            Rel::State => <StateElements as Relation<BaseField, SecureField>>::combine(&el.state, &v),
            Rel::Io => <IoElements as Relation<BaseField, SecureField>>::combine(&el.io, &v),
            _ => unreachable!(),
        };
        d.inverse()
    };
    let mut s = SecureField::zero();
    for (cix, c) in st.calls.iter().enumerate() {
        let mut init = vec![TAG_STATE, cix as u32, 0, 0, c.prog as u32, 0];
        for i in 0..NUM_REGS {
            init.extend(vm::limbs16(&c.args.get(i).copied().unwrap_or(vm::ZERO)));
        }
        init.extend([0u32; 16]);
        s += inv(Rel::State, init);
        // the call's end: RET's (gas, pc 0), or a revert's (gas, its kind in the pc slot)
        let mut end = match c.revert {
            None => vec![TAG_END, cix as u32, c.n_steps as u32, 0, c.prog as u32, c.io.len() as u32],
            Some(kd) => vec![TAG_REVERT, cix as u32, c.n_steps as u32, kd, c.prog as u32, c.io.len() as u32],
        };
        end.resize(STATE_W, 0);
        s -= inv(Rel::State, end);
        for (j, e) in c.io.iter().enumerate() {
            let mut t = vec![cix as u32, j as u32, e.kind];
            t.extend(vm::limbs16(&e.a));
            t.extend(vm::limbs16(&e.b));
            s += inv(Rel::Io, t);
        }
    }
    s
}

/// Verify that `proof` proves `st`. Never panics on a malformed proof it can recognize; returns why it refused.
pub fn verify_vm(st: &VmStatement, proof: VmProof, config: PcsConfig) -> Result<(), VmVerifyError> {
    if proof.stark.config != config {
        return Err(VmVerifyError::WeakConfig);
    }
    for p in &st.progs {
        vm::validate_method(p).map_err(VmVerifyError::Static)?;
    }
    if st.calls.is_empty() {
        return Err(VmVerifyError::Static("no calls".into()));
    }
    for c in &st.calls {
        // a returning run's io ends in RET, so it is never empty; a reverting run's may be
        if c.prog >= st.progs.len() || c.args.len() > vm::MAX_ARGS || c.n_steps == 0 || c.n_steps > vm::GAS_LIMIT
            || (c.revert.is_none() && c.io.is_empty()) || c.io.len() > c.n_steps
        {
            return Err(VmVerifyError::Static("a call outside the VM's bounds".into()));
        }
    }
    let (clog, tlog, _) = logs(st);
    if proof.sums.len() != N_SUMS || proof.stark.commitments.len() < 3 {
        return Err(VmVerifyError::Shape);
    }
    // the scheduler's size is the prover's (the number of HABS rows is not public): bounded by the CPU's
    let channel = &mut Blake2sChannel::default();
    config.mix_into(channel);
    st.mix_into(channel);
    if proof.stark.commitments[0] != preprocessed_root(st, config) {
        return Err(VmVerifyError::Preprocessed);
    }
    let blog = proof.blake_log;
    if !(LOG_N_LANES..=MAX_BLAKE_LOG).contains(&blog) {
        return Err(VmVerifyError::Shape);
    }
    let lg = (clog, tlog, blog);
    let sizes = log_sizes(lg);
    let mut cs = CommitmentSchemeVerifier::<Blake2sMerkleChannel>::new(config);
    cs.commit(proof.stark.commitments[0], &sizes[0], channel);
    channel.mix_u64(((clog as u64) << 16) | ((tlog as u64) << 8) | blog as u64);
    cs.commit(proof.stark.commitments[1], &sizes[1], channel);
    let el = Elements::draw(channel);
    channel.mix_felts(&proof.sums);
    cs.commit(proof.stark.commitments[2], &sizes[2], channel);
    let total: SecureField = proof.sums.iter().copied().sum::<SecureField>() + public_sum(st, &el);
    if total != SecureField::zero() {
        return Err(VmVerifyError::Sum);
    }
    let comps = Components::new(lg, tlog, &el, &proof.sums);
    verify(&comps.components(), channel, &mut cs, proof.stark).map_err(VmVerifyError::Stark)
}

/// DEBUG: evaluate every CPU constraint on the honest witness (field arithmetic, row by row), naming the first that fails.
pub fn debug_cpu_constraints(st: &VmStatement) -> Result<(), String> {
    for (cix, call) in st.calls.iter().enumerate() {
        let steps = vm::run(&st.progs[call.prog], call, cix)?;
        for s in &steps {
            let r = step_row(st, call, s);
            for (i, x) in cpu_constraints(&r).iter().enumerate() {
                if !x.is_zero() {
                    return Err(format!("call {cix} clk {} pc {} op {}: constraint {i} = {}", s.clk, s.pc, step_label(s), x.0));
                }
            }
        }
    }
    let z = zero_row();
    for (i, x) in cpu_constraints(&z).iter().enumerate() {
        if !x.is_zero() {
            return Err(format!("padding row: constraint {i} = {}", x.0));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------------------------
// the free-cell probe (the stwo_js pattern, tests/test_stwo_js_every_post_proof_mutation...)

fn col_names() -> Vec<String> {
    let v = |p: &str, n: usize| (0..n).map(|i| format!("{p}{i}")).collect_vec();
    let one = |p: &str| p.to_string();
    Cols {
        active: one("active"),
        cix: one("cix"),
        clk: one("clk"),
        pc: one("pc"),
        prog: one("prog"),
        ioc: one("ioc"),
        sel: vm::OPS.iter().map(|o| format!("sel_{o}")).collect(),
        dsel: v("dsel", NUM_REGS),
        ssel: v("ssel", NUM_REGS),
        imm: v("imm", 16),
        regs: (0..NUM_REGS).map(|i| v(&format!("r{i}_"), 16)).collect(),
        h: v("h", 16),
        rd: v("rd", 16),
        rs: v("rs", 16),
        res: v("res", 16),
        nregs: (0..NUM_REGS).map(|i| v(&format!("nr{i}_"), 16)).collect(),
        nh: v("nh", 16),
        npc: one("npc"),
        ax: v("ax", 16),
        ay: v("ay", 16),
        az: v("az", 16),
        cy: v("cy", 16),
        nz: ["nz_rd", "inv_rd", "nz_rs", "inv_rs", "nz_x", "inv_x"].map(String::from).to_vec(),
        rem: v("rem", 16),
        rq: one("rq"),
        ab: v("ab", 32),
        bb: v("bb", 32),
        cb: v("cb", 32),
        pb: v("pb", 64),
        mc: v("mc", 64),
        out: v("out", 32),
        dg: v("dg", 96),
        io_a: v("io_a", 16),
        io_b: v("io_b", 16),
        cidx: one("cidx"),
        rsel: (0..vm::revert::N_OP).map(|j| format!("rsel_{}", vm::OPS[vm::revert::OP[j]])).collect(),
        oob: one("oob"),
        oog: one("oog"),
        rb: one("rb"),
        m: one("m"),
        rinv: one("rinv"),
        rr: one("rr"),
        nargs: one("nargs"),
        plen: one("plen"),
    }
    .flat()
}

/// What a probe found: the perturbations no constraint and no lookup refused, split by whether the row's externally
/// visible behaviour (its State, Io and Tab tuples) changed. `harmful` must be empty; `harmless` lists cells whose
/// value nothing reads on that row (e.g. a MUL byte on an ADD row) — free by design.
pub struct ProbeReport {
    pub probed: usize,
    pub harmful: Vec<String>,
    pub harmless: Vec<String>,
}

/// Perturb every cell of a sample of real rows (up to `per_op` rows of each opcode, plus a padding row) by several
/// deltas, and record each perturbation the row's constraints and lookups would still accept.
pub fn probe_free_cells(st: &VmStatement, per_op: usize) -> Result<ProbeReport, String> {
    let names = col_names();
    assert_eq!(names.len(), N_COLS);
    let tab: std::collections::HashSet<Vec<u32>> = table_rows(st).into_iter().collect();
    let mut sample: Vec<(String, Cols<BaseField>)> = vec![];
    let mut count: HashMap<String, usize> = HashMap::new();
    for (cix, call) in st.calls.iter().enumerate() {
        for s in vm::run(&st.progs[call.prog], call, cix)? {
            let label = step_label(&s);
            let n = count.entry(label.clone()).or_default();
            if *n < per_op {
                *n += 1;
                sample.push((label, step_row(st, call, &s)));
            }
        }
    }
    sample.push(("PAD".into(), zero_row()));
    let p = (1u32 << 31) - 1;
    let deltas = [1u32, p - 1, 2, 256, 65536];
    let valid = |num: &BaseField, rel: Rel, vals: &[BaseField]| -> bool {
        if num.is_zero() {
            return true;
        }
        let u = vals.iter().map(|x| x.0).collect_vec();
        match rel {
            Rel::Range => u[0] < 1 << 16,
            Rel::Xor8 => u[0] < 256 && u[1] < 256 && u[2] == u[0] ^ u[1],
            Rel::Tab => tab.contains(&u),
            Rel::Blake => {
                if u.iter().any(|x| *x >= 1 << 16) {
                    return false;
                }
                let w = |o: usize| -> [u32; 16] { std::array::from_fn(|i| u[o + 2 * i] | (u[o + 2 * i + 1] << 16)) };
                rounds(w(0), &w(64)) == w(32)
            }
            Rel::State | Rel::Io => true,
        }
    };
    let mut rep = ProbeReport { probed: 0, harmful: vec![], harmless: vec![] };
    for (opname, row) in &sample {
        let base = row.flat();
        let lk0 = cpu_lookups(row);
        for c in 0..N_COLS {
            for d in deltas {
                rep.probed += 1;
                let mut v = base.clone();
                v[c] += f(d);
                let r2 = Cols::from_iter(&mut v.into_iter());
                if cpu_constraints(&r2).iter().any(|x| !x.is_zero()) {
                    continue;
                }
                let lk = cpu_lookups(&r2);
                // an entry with a zero numerator on both sides contributes nothing, whatever its values
                let differs = |a: &(BaseField, Rel, Vec<BaseField>), b: &(BaseField, Rel, Vec<BaseField>)| {
                    a.0 != b.0 || (!a.0.is_zero() && a.2 != b.2)
                };
                let ext_changed =
                    lk.iter().zip(&lk0).any(|(a, b)| matches!(a.1, Rel::State | Rel::Io | Rel::Tab) && differs(a, b));
                let stateio_changed =
                    lk.iter().zip(&lk0).any(|(a, b)| matches!(a.1, Rel::State | Rel::Io) && differs(a, b));
                if stateio_changed || !lk.iter().all(|(n, rel, vals)| valid(n, *rel, vals)) {
                    continue; // a State/Io tuple no other row or the verifier matches, or an entry no table holds
                }
                let tag = format!("{opname}:{}{}", names[c], if d == p - 1 { "-1".to_string() } else { format!("+{d}") });
                if ext_changed { rep.harmful.push(tag) } else { rep.harmless.push(tag) }
            }
        }
    }
    Ok(rep)
}
