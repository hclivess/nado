//! The settlement VM proof as files (G4; execnode/settle_b2.py calls this):
//!   vm_settle prove  STATEMENT PROOF_OUT    prove the statement (vm::parse_statement's text), write the proof bytes
//!   vm_settle verify STATEMENT PROOF        verify; prints `OK` or `REFUSED <reason>`, exit 0 either way
//! Any other outcome (a missing file, a statement that does not parse) prints `ERROR <reason>` and exits 2, so a
//! caller can tell a refusal from a broken invocation.
use std::time::Instant;

use nado_stwo_settle::blake::vm_air::{Tamper, node_config, prove_vm, verify_vm};
use nado_stwo_settle::{vm, wire};

fn fail(msg: String) -> ! {
    println!("ERROR {msg}");
    std::process::exit(2)
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() != 4 || !(a[1] == "prove" || a[1] == "verify") {
        fail("usage: vm_settle prove|verify STATEMENT PROOF".into());
    }
    let text = std::fs::read_to_string(&a[2]).unwrap_or_else(|e| fail(format!("statement: {e}")));
    let st = vm::parse_statement(&text).unwrap_or_else(|e| fail(format!("statement: {e}")));
    let cfg = node_config();
    if a[1] == "prove" {
        let t = Instant::now();
        let proof = prove_vm(&st, cfg, Tamper::None).unwrap_or_else(|e| fail(format!("prover refused: {e}")));
        let bytes = wire::encode(&proof);
        std::fs::write(&a[3], &bytes).unwrap_or_else(|e| fail(format!("write: {e}")));
        println!("PROVED bytes={} prove_ms={:.0}", bytes.len(), t.elapsed().as_secs_f64() * 1e3);
        return;
    }
    let bytes = std::fs::read(&a[3]).unwrap_or_else(|e| fail(format!("proof: {e}")));
    let proof = match wire::decode(&bytes) {
        Ok(p) => p,
        Err(e) => {
            println!("REFUSED decode {e:?}");
            return;
        }
    };
    match verify_vm(&st, proof, cfg) {
        Ok(()) => println!("OK"),
        Err(e) => println!("REFUSED {e:?}"),
    }
}
