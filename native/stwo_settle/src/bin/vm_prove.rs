//! Prove + verify the execution of a list of zkvm2 calls (blake/vm_air.rs), then try forged statements against the
//! honest proof. Input (stdin), 256-bit values as 64 hex digits, big-endian:
//!   PROG <n>                       a method; then n lines   I <op id> <d> <s> <imm>
//!   CALL <prog index> <n_steps>    a call; then             ARGS <v>...   CTX <4 v>   ACTX <4 v>   IO <kind> <a> <b> (each)
//! Output (one line per item):
//!   HONEST ok|<error>|prover_refused <error>   (with VM_TAMPER=<name> the witness is a dishonest one, vm_air::Tamper,
//!                                              and nothing else runs)
//!   FORGE <name> refused|ACCEPTED              each forged statement against the honest proof
//!   TIME calls=<..> steps=<..> prove_ms=<..> verify_ms=<..> proof_bytes=<..>
use std::io::{self, Read};
use std::time::Instant;

use nado_stwo_settle::blake::vm_air::{self, Tamper, debug_cpu_constraints, node_config, probe_free_cells, prove_vm, verify_vm};
use nado_stwo_settle::vm::{self, VmStatement, W};

fn parse() -> VmStatement {
    let mut text = String::new();
    io::stdin().read_to_string(&mut text).expect("stdin");
    vm::parse_statement(&text).expect("statement")
}

fn main() {
    if std::env::var("VM_PREROOT").is_ok() {
        // the preprocessed commitment at the node config, for vm_air::PREPROCESSED_ROOT (no statement needed)
        let r = nado_stwo_settle::blake::vm_air::preprocessed_root(node_config());
        println!("PREROOT {}", r.0.iter().map(|b| format!("{b:02x}")).collect::<String>());
        return;
    }
    let st = parse();
    if std::env::var("VM_DEBUG").is_ok() {
        match debug_cpu_constraints(&st) {
            Ok(()) => println!("DEBUG every CPU constraint holds on every row"),
            Err(e) => println!("DEBUG {e}"),
        }
        return;
    }
    if let Ok(n) = std::env::var("VM_PROBE") {
        let rep = probe_free_cells(&st, n.parse().unwrap()).expect("probe");
        let mut by: std::collections::BTreeMap<String, usize> = Default::default();
        for h in &rep.harmless {
            let (o, cell) = h.split_once(':').unwrap();
            let col: String = cell.chars().take_while(|c| c.is_ascii_alphabetic() || *c == '_').collect();
            *by.entry(format!("{o}:{col}")).or_default() += 1;
        }
        for (k, v) in &by {
            println!("HARMLESS {k} x{v}");
        }
        for h in &rep.harmful {
            println!("HARMFUL {h}");
        }
        println!("PROBE probed={} accepted_harmless={} accepted_harmful={}", rep.probed, rep.harmless.len(), rep.harmful.len());
        return;
    }
    let tamper = match std::env::var("VM_TAMPER").as_deref() {
        Ok("mul_result") => Tamper::MulResult,
        Ok("jnz_not_taken") => Tamper::JnzNotTaken,
        Ok("stray_write") => Tamper::StrayWrite,
        Ok("hash_state") => Tamper::HashState,
        Ok("lt_flipped") => Tamper::LtFlipped,
        Ok("force_revert") => Tamper::ForceRevert,
        Ok(x) => panic!("unknown tamper {x}"),
        Err(_) => Tamper::None,
    };
    let cfg = node_config();
    let t = Instant::now();
    let proof = match prove_vm(&st, cfg, tamper) {
        Ok(p) => p,
        Err(e) => {
            println!("HONEST prover_refused {e}");
            return;
        }
    };
    let prove_ms = t.elapsed().as_secs_f64() * 1e3;
    let size = proof.stark.size_estimate();
    let t = Instant::now();
    let honest = verify_vm(&st, proof.clone(), cfg);
    let verify_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("HONEST {}", match &honest { Ok(()) => "ok".to_string(), Err(e) => format!("{e:?}") });
    if tamper != Tamper::None {
        return;
    }

    let edit = |f: &dyn Fn(&mut VmStatement)| { let mut s = st.clone(); f(&mut s); s };
    let bump = |x: &W| vm::add(x, &vm::from_u64(1)).0;
    let mut forged: Vec<(String, VmStatement)> = vec![];
    let last = st.calls.len() - 1;
    for (tag, ci) in [("first", 0), ("last", last)] {
        let c = &st.calls[ci];
        // every io entry: its value, its key, its kind; and the log with one dropped, one added, two swapped
        for (j, e) in c.io.iter().enumerate() {
            forged.push((format!("{tag}.io{j}.b"), edit(&|s| s.calls[ci].io[j].b = bump(&s.calls[ci].io[j].b))));
            forged.push((format!("{tag}.io{j}.a"), edit(&|s| s.calls[ci].io[j].a = bump(&s.calls[ci].io[j].a))));
            let other = if e.kind == vm::io::SSTORE { vm::io::PAY } else { vm::io::SSTORE };
            forged.push((format!("{tag}.io{j}.kind"), edit(&|s| s.calls[ci].io[j].kind = other)));
        }
        let n = c.io.len();
        if n >= 2 {
            forged.push((format!("{tag}.io_dropped"), edit(&|s| { s.calls[ci].io.remove(0); })));
            forged.push((format!("{tag}.io_swapped"), edit(&|s| s.calls[ci].io.swap(0, 1))));
        }
        forged.push((format!("{tag}.io_added"), edit(&|s| {
            // a copy of the first entry, or (an empty log: a call that reverts before any io) an SSTORE of 0 to 0
            let e = s.calls[ci].io.first().copied().unwrap_or(vm::IoEntry { kind: vm::io::SSTORE, a: vm::ZERO, b: vm::ZERO });
            s.calls[ci].io.insert(0, e);
        })));
        for i in 0..c.args.len() {
            forged.push((format!("{tag}.arg{i}"), edit(&|s| s.calls[ci].args[i] = bump(&s.calls[ci].args[i]))));
        }
        forged.push((format!("{tag}.arg_appended"), edit(&|s| s.calls[ci].args.push(vm::ZERO))));
        for i in 0..4 {
            forged.push((format!("{tag}.ctx{i}"), edit(&|s| s.calls[ci].ctx[i] = bump(&s.calls[ci].ctx[i]))));
            forged.push((format!("{tag}.actx{i}"), edit(&|s| s.calls[ci].actx[i] = bump(&s.calls[ci].actx[i]))));
        }
        forged.push((format!("{tag}.n_steps+1"), edit(&|s| s.calls[ci].n_steps += 1)));
        forged.push((format!("{tag}.n_steps-1"), edit(&|s| s.calls[ci].n_steps -= 1)));
        if st.progs.len() > 1 {
            forged.push((format!("{tag}.other_program"), edit(&|s| s.calls[ci].prog = (s.calls[ci].prog + 1) % s.progs.len())));
        }
    }
    // the code: every MOVI immediate and every instruction's register of the first program the first call runs
    let p0 = st.calls[0].prog;
    for (pc, ins) in st.progs[p0].iter().enumerate() {
        if ins.op == vm::op::MOVI {
            forged.push((format!("code.movi{pc}"), edit(&|s| s.progs[p0][pc].imm = bump(&s.progs[p0][pc].imm))));
        }
        if !matches!(ins.op, vm::op::DIVMOD | vm::op::DIVMODW) {
            forged.push((format!("code.dreg{pc}"), edit(&|s| s.progs[p0][pc].d = (s.progs[p0][pc].d + 1) % 7)));
        }
    }
    if st.calls.len() >= 2 {
        forged.push(("calls_swapped".into(), edit(&|s| s.calls.swap(0, 1))));
        forged.push(("io_moved_between_calls".into(), edit(&|s| {
            let (a, b) = (s.calls[0].io.clone(), s.calls[1].io.clone());
            s.calls[0].io = b;
            s.calls[1].io = a;
        })));
        forged.push(("call_dropped".into(), edit(&|s| { s.calls.pop(); })));
    }
    for (ci, c) in st.calls.iter().enumerate() {
        if let Some(kd) = c.revert {
            forged.push((format!("call{ci}.revert_kind"), edit(&|s| s.calls[ci].revert = Some((kd + 1) % 13))));
            forged.push((format!("call{ci}.revert_to_return"), edit(&|s| s.calls[ci].revert = None)));
            forged.push((format!("call{ci}.revert_n_steps+1"), edit(&|s| s.calls[ci].n_steps += 1)));
            if !c.io.is_empty() {
                forged.push((format!("call{ci}.revert_io_dropped"), edit(&|s| { s.calls[ci].io.pop(); })));
            }
        } else {
            forged.push((format!("call{ci}.return_to_revert"), edit(&|s| s.calls[ci].revert = Some(vm::revert::REQUIRE))));
        }
    }
    // the PROOF's own data that is not a STARK: the table multiplicities (fixed in the transcript before the lookup
    // challenges). Each mutation of the honest proof must be refused.
    let mut mutants: Vec<(String, vm_air::VmProof)> = vec![];
    if let Some(i) = proof.tab_mult.iter().position(|&m| m > 0) {
        let mut p1 = proof.clone();
        p1.tab_mult[i] += 1;
        mutants.push(("tab_mult+1".into(), p1));
        let mut p2 = proof.clone();
        p2.tab_mult[i] -= 1;
        mutants.push(("tab_mult-1".into(), p2));
        if let Some(j) = proof.tab_mult.iter().position(|&m| m == 0) {
            let mut p3 = proof.clone();
            p3.tab_mult.swap(i, j);
            mutants.push(("tab_mult_moved".into(), p3));
        }
        let mut p4 = proof.clone();
        p4.tab_mult.push(0);
        mutants.push(("tab_mult_extra".into(), p4));
    }
    for (name, mp) in mutants {
        let r = verify_vm(&st, mp, cfg);
        println!("MUTATE {name} {}", if r.is_ok() { "ACCEPTED".to_string() } else { format!("refused {}", short(&format!("{:?}", r.unwrap_err()))) });
    }
    let mut accepted = 0;
    for (name, fst) in &forged {
        if fst == &st {
            continue; // an edit that changes nothing (e.g. a register already that value) is no forgery
        }
        let r = verify_vm(fst, proof.clone(), cfg);
        if r.is_ok() {
            accepted += 1;
        }
        println!("FORGE {name} {}", match r { Err(e) => format!("refused {}", short(&format!("{e:?}"))), Ok(()) => "ACCEPTED".into() });
    }
    let steps: usize = st.calls.iter().map(|c| c.n_steps).sum();
    println!("FORGED total={} accepted={accepted}", forged.len());
    println!("TIME calls={} steps={steps} prove_ms={prove_ms:.0} verify_ms={verify_ms:.1} proof_bytes={size}", st.calls.len());
}

fn short(s: &str) -> String {
    s.chars().take(60).collect()
}
