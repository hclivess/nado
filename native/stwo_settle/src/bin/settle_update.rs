//! Prove + verify a SEQUENTIAL BATCH of compressed-tree key updates, then try forged statements against the honest
//! proof. Input: one line per update, in order, each against the tree the previous one left:
//! `key_hex vh_old_hex vh_new_hex sib1,sib2,...` (32-byte hex each, siblings root first). Output (one line per item):
//!   ROOTS <first old root hex> <last new root hex>   the statement the witness proves (the chain's two ends)
//!   HONEST ok|<error>                                the honest proof verifies
//!   FORGE <name> refused|ACCEPTED                    each forged statement against the honest proof
//!   TIME updates=<K> rows=<..> prove_ms=<..> verify_ms=<..> proof_bytes=<..>
use std::io::{self, BufRead};
use std::time::Instant;

use nado_stwo_settle::blake::settle::{Statement, Update, debug_path_constraints, debug_upstream_blake, node_config, prove_batch, verify_batch};
use nado_stwo_settle::csmt_ref::{bytes, words};

fn h32(s: &str) -> [u8; 32] {
    let v: Vec<u8> = (0..32).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect();
    v.try_into().unwrap()
}
fn hex(w: &[u32; 8]) -> String {
    bytes(w).iter().map(|b| format!("{b:02x}")).collect()
}

fn main() {
    let mut us = vec![];
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        if line.trim().is_empty() {
            continue;
        }
        let p: Vec<&str> = line.split(' ').collect();
        let sibs: Vec<[u32; 8]> =
            if p.len() > 3 && !p[3].is_empty() { p[3].split(',').map(|s| words(&h32(s))).collect() } else { vec![] };
        us.push(Update { key: words(&h32(p[0])), vh_old: words(&h32(p[1])), vh_new: words(&h32(p[2])), sibs });
    }
    if std::env::var("SETTLE_UPSTREAM").is_ok() {
        debug_upstream_blake();
        return;
    }
    if std::env::var("SETTLE_DEBUG").is_ok() {
        debug_path_constraints(&us);
        return;
    }
    let cfg = node_config();
    let t = Instant::now();
    let (st, proof) = prove_batch(&us, cfg);
    let prove_ms = t.elapsed().as_secs_f64() * 1e3;
    let k = st.updates.len();
    println!("ROOTS {} {}", hex(&st.updates[0].root_old), hex(&st.updates[k - 1].root_new));
    let size = proof.stark.size_estimate();
    let t = Instant::now();
    let honest = verify_batch(&st, proof.clone(), cfg);
    let verify_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("HONEST {}", match &honest { Ok(()) => "ok".to_string(), Err(e) => format!("{e:?}") });

    let flip = |w: &[u32; 8]| { let mut x = *w; x[3] ^= 1; x };
    let edit = |f: &dyn Fn(&mut Statement)| { let mut s = st.clone(); f(&mut s); s };
    let last = k - 1;
    let mut forged: Vec<(String, Statement)> = vec![];
    // every field of the first and the last update (one and the same when k == 1)
    for (tag, i) in [("first", 0), ("last", last)] {
        forged.push((format!("{tag}.new_root"), edit(&|s| s.updates[i].root_new = flip(&s.updates[i].root_new))));
        forged.push((format!("{tag}.old_root"), edit(&|s| s.updates[i].root_old = flip(&s.updates[i].root_old))));
        forged.push((format!("{tag}.key"), edit(&|s| s.updates[i].key = flip(&s.updates[i].key))));
        forged.push((format!("{tag}.vh_new"), edit(&|s| s.updates[i].vh_new = flip(&s.updates[i].vh_new))));
        forged.push((format!("{tag}.vh_old"), edit(&|s| s.updates[i].vh_old = flip(&s.updates[i].vh_old))));
        forged.push((format!("{tag}.swapped_roots"), edit(&|s| {
            let u = &mut s.updates[i];
            std::mem::swap(&mut u.root_old, &mut u.root_new);
        })));
    }
    if k >= 2 {
        // a consistent chain through a WRONG intermediate root: only the in-circuit roots can refuse it
        forged.push(("intermediate_root".into(), edit(&|s| {
            let x = flip(&s.updates[0].root_new);
            s.updates[0].root_new = x;
            s.updates[1].root_old = x;
        })));
        // values moved between updates: the update index in every public tuple refuses it
        forged.push(("vh_new_moved_between_updates".into(), edit(&|s| {
            let (a, b) = (s.updates[0].vh_new, s.updates[1].vh_new);
            s.updates[0].vh_new = b;
            s.updates[1].vh_new = a;
        })));
        forged.push(("dropped_last_update".into(), edit(&|s| { s.updates.pop(); })));
        forged.push(("updates_reordered".into(), edit(&|s| s.updates.swap(0, 1))));
    }
    for (name, fst) in forged {
        let r = verify_batch(&fst, proof.clone(), cfg);
        println!("FORGE {name} {}", match r { Err(e) => format!("refused {e:?}"), Ok(()) => "ACCEPTED".into() });
    }
    let rows: usize = st.updates.iter().map(|u| 2 * u.depth + 2).sum();
    println!("TIME updates={k} rows={rows} prove_ms={prove_ms:.0} verify_ms={verify_ms:.1} proof_bytes={size}");
}
