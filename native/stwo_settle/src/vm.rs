//! Scalar reference of execnode/zkvm2.py, the generation-29 contract VM, for the settlement circuit's VM component
//! (blake/vm.rs; doc/stwo/g4-settlement-statement.md section 4 step 3). It runs a method IO-DRIVEN: every value the VM
//! reads from outside (SLOAD, BHASH, BEACON, ABAL) is taken from the call's io log in order, and every entry the run
//! emits must equal the log's next one. So a run here needs no storage, chain or asset ledger: the io log IS the
//! interface, exactly as the statement makes it public, and the prover's witness is a function of the statement.
//!
//! What zkvm2 reverts on and how a successful run here relates to it:
//!   NOTB on a non-bit, RANGE >= 2^62, a zero divisor, REQUIRE 0, ARG out of range, ASEL of asset 0, the gas limit, a
//!   pc off the method's end: refused here (Err), and the circuit has no row that could prove them;
//!   BHASH / BEACON not available, an asset move beyond the holding: those depend on chain and ledger state the
//!   consumer of the io log checks (chain reads by L1, asset effects by the records half). NOT checked here.
//! A REVERTING call is out of this component's scope for now (its statement would have to prove the failing condition;
//! see the doc's open items).

use crate::csmt_ref::compress;

/// A 256-bit word, little-endian 64-bit limbs.
pub type W = [u64; 4];
pub const ZERO: W = [0; 4];

pub const GAS_LIMIT: usize = 131070;
pub const MAX_ARGS: usize = 1024;
pub const NUM_REGS: usize = 8;
pub const PERSON_HASH: &[u8; 8] = b"NADOvmH1";

/// zkvm2.OPS, in order: the opcode id is the index (FROZEN at the reroll, append-only).
pub const OPS: [&str; 34] = [
    "NOP", "MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "RANGE", "DIVMOD", "LO32", "JMP", "JNZ",
    "REQUIRE", "CTX", "HINIT", "HABS", "HOUT", "SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET", "ARG", "DIVMODW",
    "ASEL", "AMINT", "ABURN", "ABAL", "ACTX", "ARENOUNCE",
];
pub mod op {
    pub const NOP: usize = 0;
    pub const MOVI: usize = 1;
    pub const MOV: usize = 2;
    pub const ADD: usize = 3;
    pub const SUB: usize = 4;
    pub const MUL: usize = 5;
    pub const EQ: usize = 6;
    pub const NEZ: usize = 7;
    pub const NOTB: usize = 8;
    pub const LT: usize = 9;
    pub const RANGE: usize = 10;
    pub const DIVMOD: usize = 11;
    pub const LO32: usize = 12;
    pub const JMP: usize = 13;
    pub const JNZ: usize = 14;
    pub const REQUIRE: usize = 15;
    pub const CTX: usize = 16;
    pub const HINIT: usize = 17;
    pub const HABS: usize = 18;
    pub const HOUT: usize = 19;
    pub const SLOAD: usize = 20;
    pub const SSTORE: usize = 21;
    pub const PAY: usize = 22;
    pub const BHASH: usize = 23;
    pub const BEACON: usize = 24;
    pub const RET: usize = 25;
    pub const ARG: usize = 26;
    pub const DIVMODW: usize = 27;
    pub const ASEL: usize = 28;
    pub const AMINT: usize = 29;
    pub const ABURN: usize = 30;
    pub const ABAL: usize = 31;
    pub const ACTX: usize = 32;
    pub const ARENOUNCE: usize = 33;
}
pub const N_OPS: usize = 34;

/// execnode/zkvm.py's io kinds (zkvm2 imports them unchanged)
pub mod io {
    pub const SLOAD: u32 = 1;
    pub const SSTORE: u32 = 2;
    pub const PAY: u32 = 3;
    pub const BHASH: u32 = 4;
    pub const BEACON: u32 = 5;
    pub const RET: u32 = 6;
    pub const ASEL: u32 = 7;
    pub const AMINT: u32 = 8;
    pub const ABURN: u32 = 9;
    pub const ABAL: u32 = 10;
    pub const ARENOUNCE: u32 = 11;
}

/// The io kind an opcode emits (0: none).
pub fn io_kind(o: usize) -> u32 {
    match o {
        op::SLOAD => io::SLOAD,
        op::SSTORE => io::SSTORE,
        op::PAY => io::PAY,
        op::BHASH => io::BHASH,
        op::BEACON => io::BEACON,
        op::RET => io::RET,
        op::ASEL => io::ASEL,
        op::AMINT => io::AMINT,
        op::ABURN => io::ABURN,
        op::ABAL => io::ABAL,
        op::ARENOUNCE => io::ARENOUNCE,
        _ => 0,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Instr {
    pub op: usize,
    pub d: usize,
    pub s: usize,
    pub imm: W,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IoEntry {
    pub kind: u32,
    pub a: W,
    pub b: W,
}

/// One call as the statement states it: which method, its inputs, and its whole io log (ending with RET).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Call {
    pub prog: usize,
    pub args: Vec<W>,
    /// CTX 0..3: caller, value, cursor, timestamp
    pub ctx: [W; 4],
    /// ACTX 0..3: the call's asset, the contract's own digest, 0, 0
    pub actx: [W; 4],
    pub io: Vec<IoEntry>,
    /// the number of instructions the run executes (its gas), RET included
    pub n_steps: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VmStatement {
    /// every method the calls run, by index
    pub progs: Vec<Vec<Instr>>,
    pub calls: Vec<Call>,
}

// ---- 256-bit arithmetic

pub fn add(a: &W, b: &W) -> (W, bool) {
    let mut r = ZERO;
    let mut c = 0u128;
    for i in 0..4 {
        let t = a[i] as u128 + b[i] as u128 + c;
        r[i] = t as u64;
        c = t >> 64;
    }
    (r, c != 0)
}

pub fn sub(a: &W, b: &W) -> W {
    let nb = [!b[0], !b[1], !b[2], !b[3]];
    let (t, _) = add(a, &nb);
    add(&t, &[1, 0, 0, 0]).0
}

/// the full 512-bit product, little-endian 64-bit limbs
pub fn mul_full(a: &W, b: &W) -> [u64; 8] {
    let mut r = [0u64; 8];
    for i in 0..4 {
        let mut c = 0u128;
        for j in 0..4 {
            let t = a[i] as u128 * b[j] as u128 + r[i + j] as u128 + c;
            r[i + j] = t as u64;
            c = t >> 64;
        }
        r[i + 4] = c as u64;
    }
    r
}

pub fn lt(a: &W, b: &W) -> bool {
    for i in (0..4).rev() {
        if a[i] != b[i] {
            return a[i] < b[i];
        }
    }
    false
}

pub fn is_zero(a: &W) -> bool {
    *a == ZERO
}

fn shl1(a: &W) -> W {
    [a[0] << 1, (a[1] << 1) | (a[0] >> 63), (a[2] << 1) | (a[1] >> 63), (a[3] << 1) | (a[2] >> 63)]
}

/// (a // b, a % b); b != 0
pub fn divmod(a: &W, b: &W) -> (W, W) {
    let (mut q, mut r) = (ZERO, ZERO);
    for i in (0..256).rev() {
        r = shl1(&r);
        r[0] |= (a[i / 64] >> (i % 64)) & 1;
        if !lt(&r, b) {
            r = sub(&r, b);
            q[i / 64] |= 1 << (i % 64);
        }
    }
    (q, r)
}

pub fn from_u64(x: u64) -> W {
    [x, 0, 0, 0]
}

/// 16 limbs of 16 bits, least significant first (the circuit's register layout)
pub fn limbs16(a: &W) -> [u32; 16] {
    std::array::from_fn(|l| ((a[l / 4] >> (16 * (l % 4))) & 0xffff) as u32)
}

/// 32 bytes, least significant first
pub fn bytes_le(a: &W) -> [u32; 32] {
    std::array::from_fn(|k| ((a[k / 8] >> (8 * (k % 8))) & 0xff) as u32)
}

pub fn from_bytes_be(b: &[u8; 32]) -> W {
    let mut w = ZERO;
    for (k, x) in b.iter().rev().enumerate() {
        w[k / 8] |= (*x as u64) << (8 * (k % 8));
    }
    w
}

pub fn to_bytes_be(a: &W) -> [u8; 32] {
    let le = bytes_le(a);
    std::array::from_fn(|j| le[31 - j] as u8)
}

/// The VM hash's absorb: BLAKE2s-256(h || x, person=NADOvmH1), both 32 bytes big-endian, read back big-endian.
/// One block of 64 bytes = one compression (csmt_ref::compress).
pub fn absorb_msg(h: &W, x: &W) -> [u32; 16] {
    let mut m = [0u8; 64];
    m[..32].copy_from_slice(&to_bytes_be(h));
    m[32..].copy_from_slice(&to_bytes_be(x));
    std::array::from_fn(|i| u32::from_le_bytes(m[4 * i..4 * i + 4].try_into().unwrap()))
}

pub fn absorb(h: &W, x: &W) -> W {
    let d = compress(PERSON_HASH, &absorb_msg(h, x));
    let mut b = [0u8; 32];
    for i in 0..8 {
        b[4 * i..4 * i + 4].copy_from_slice(&d[i].to_le_bytes());
    }
    from_bytes_be(&b)
}

// ---- static checks (zkvm2.validate_code, per method)

/// zkvm2.validate_code's structural rules for one method. The verifier runs this on every program the statement names:
/// the circuit relies on DIVMOD never writing r7 (its remainder's register), on every jump target and CTX/ACTX index
/// fitting the two low limbs of the immediate, and on the ASEL pairing.
pub fn validate_method(prog: &[Instr]) -> Result<(), String> {
    if prog.is_empty() || prog.len() > GAS_LIMIT {
        return Err("empty method or longer than GAS_LIMIT".into());
    }
    let mut no_jump = vec![];
    for (i, ins) in prog.iter().enumerate() {
        if ins.op >= N_OPS || ins.d >= NUM_REGS || ins.s >= NUM_REGS {
            return Err(format!("invalid instruction at {i}"));
        }
        let small = ins.imm[1] == 0 && ins.imm[2] == 0 && ins.imm[3] == 0;
        if (ins.op == op::JMP || ins.op == op::JNZ) && !(small && (ins.imm[0] as usize) < prog.len()) {
            return Err(format!("jump target out of range at {i}"));
        }
        if (ins.op == op::DIVMOD || ins.op == op::DIVMODW) && ins.d == 7 {
            return Err(format!("DIVMOD dest r7 at {i}"));
        }
        if (ins.op == op::CTX || ins.op == op::ACTX) && !(small && ins.imm[0] <= 3) {
            return Err(format!("CTX index out of range at {i}"));
        }
        if ins.op == op::ASEL {
            if i + 1 >= prog.len() || !(prog[i + 1].op == op::PAY || prog[i + 1].op == op::AMINT) {
                return Err(format!("ASEL at {i} not followed by PAY or AMINT"));
            }
            no_jump.push(i + 1);
        }
        if ins.op == op::AMINT && !(i >= 1 && prog[i - 1].op == op::ASEL) {
            return Err(format!("AMINT at {i} not preceded by ASEL"));
        }
    }
    for ins in prog {
        if (ins.op == op::JMP || ins.op == op::JNZ) && no_jump.contains(&(ins.imm[0] as usize)) {
            return Err("jump onto an asset spend".into());
        }
    }
    Ok(())
}

// ---- the run

/// One executed instruction, with the machine state before it and what it changed: the circuit's row.
#[derive(Clone, Debug)]
pub struct Step {
    pub cix: usize,
    pub clk: usize,
    pub pc: usize,
    pub ins: Instr,
    pub regs: [W; NUM_REGS],
    pub h: W,
    pub ioc: usize,
    /// the value written to r[d] (r[d] itself when the op writes nothing)
    pub res: W,
    /// DIVMOD's remainder (into r7)
    pub rem: W,
    pub regs_next: [W; NUM_REGS],
    pub h_next: W,
    pub pc_next: usize,
    pub emitted: Option<IoEntry>,
}

/// Run `call` io-driven (module comment) and return its steps. Err names why the run is not a successful one.
pub fn run(prog: &[Instr], call: &Call, cix: usize) -> Result<Vec<Step>, String> {
    if call.args.len() > MAX_ARGS {
        return Err("too many args".into());
    }
    let mut regs: [W; NUM_REGS] = std::array::from_fn(|i| call.args.get(i).copied().unwrap_or(ZERO));
    let mut h = ZERO;
    let mut pc = 0usize;
    let mut ioc = 0usize;
    let mut steps = vec![];
    loop {
        if steps.len() >= GAS_LIMIT {
            return Err("gas limit exceeded".into());
        }
        let ins = *prog.get(pc).ok_or("pc off the method's end")?;
        let (rd, rs) = (regs[ins.d], regs[ins.s]);
        let mut res = rd;
        let mut rem = ZERO;
        let mut h_next = h;
        let mut pc_next = pc + 1;
        let mut emitted: Option<IoEntry> = None;
        let read = |kind: u32, a: W| -> Result<W, String> {
            let e = call.io.get(ioc).ok_or("io log too short")?;
            if e.kind != kind || e.a != a {
                return Err(format!("io entry {ioc} is not this read"));
            }
            Ok(e.b)
        };
        match ins.op {
            op::NOP => {}
            op::MOVI => res = ins.imm,
            op::MOV => res = rs,
            op::ADD => res = add(&rd, &rs).0,
            op::SUB => res = sub(&rd, &rs),
            op::MUL => {
                let p = mul_full(&rd, &rs);
                res = [p[0], p[1], p[2], p[3]];
            }
            op::EQ => res = from_u64((rd == rs) as u64),
            op::NEZ => res = from_u64(!is_zero(&rd) as u64),
            op::NOTB => {
                if !(rd == ZERO || rd == from_u64(1)) {
                    return Err("NOTB on a non-bit".into());
                }
                res = from_u64(1 - rd[0]);
            }
            op::LT => res = from_u64(lt(&rd, &rs) as u64),
            op::RANGE => {
                if !lt(&rd, &from_u64(1 << 62)) {
                    return Err("RANGE failed".into());
                }
            }
            op::DIVMOD | op::DIVMODW => {
                if is_zero(&rs) {
                    return Err("division by zero".into());
                }
                let (q, r) = divmod(&rd, &rs);
                res = q;
                rem = r;
            }
            op::LO32 => res = [rd[0] & 0xffff_ffff, 0, 0, 0],
            op::JMP => pc_next = ins.imm[0] as usize,
            op::JNZ => {
                if !is_zero(&rs) {
                    pc_next = ins.imm[0] as usize;
                }
            }
            op::REQUIRE => {
                if is_zero(&rs) {
                    return Err("REQUIRE failed".into());
                }
            }
            op::CTX => res = call.ctx[ins.imm[0] as usize],
            op::ACTX => res = call.actx[ins.imm[0] as usize],
            op::HINIT => h_next = ZERO,
            op::HABS => h_next = absorb(&h, &rs),
            op::HOUT => res = h,
            op::SLOAD | op::BHASH | op::BEACON | op::ABAL => {
                let k = io_kind(ins.op);
                res = read(k, rs)?;
                emitted = Some(IoEntry { kind: k, a: rs, b: res });
            }
            op::SSTORE | op::PAY | op::AMINT | op::ABURN => {
                emitted = Some(IoEntry { kind: io_kind(ins.op), a: rd, b: rs });
            }
            op::RET | op::ASEL => {
                if ins.op == op::ASEL && is_zero(&rs) {
                    return Err("ASEL of asset 0".into());
                }
                emitted = Some(IoEntry { kind: io_kind(ins.op), a: rs, b: ZERO });
            }
            op::ARENOUNCE => emitted = Some(IoEntry { kind: io::ARENOUNCE, a: rd, b: ZERO }),
            op::ARG => {
                if !(rs[1] == 0 && rs[2] == 0 && rs[3] == 0 && (rs[0] as usize) < call.args.len()) {
                    return Err("ARG index out of range".into());
                }
                res = call.args[rs[0] as usize];
            }
            _ => return Err("unknown op".into()),
        }
        if let Some(e) = emitted {
            if call.io.get(ioc) != Some(&e) {
                return Err(format!("io entry {ioc} differs from what the run emits"));
            }
            ioc += 1;
        }
        let mut regs_next = regs;
        regs_next[ins.d] = res;
        if ins.op == op::DIVMOD || ins.op == op::DIVMODW {
            regs_next[7] = rem;
            regs_next[ins.d] = res;
        }
        let ioc_before = if emitted.is_some() { ioc - 1 } else { ioc };
        steps.push(Step {
            cix,
            clk: steps.len(),
            pc,
            ins,
            regs,
            h,
            ioc: ioc_before,
            res,
            rem,
            regs_next,
            h_next,
            pc_next,
            emitted,
        });
        if ins.op == op::RET {
            break;
        }
        regs = regs_next;
        h = h_next;
        pc = pc_next;
    }
    if ioc != call.io.len() {
        return Err("io log longer than the run".into());
    }
    if steps.len() != call.n_steps {
        return Err(format!("the run takes {} steps, the statement says {}", steps.len(), call.n_steps));
    }
    Ok(steps)
}
