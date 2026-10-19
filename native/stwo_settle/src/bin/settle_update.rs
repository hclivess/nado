//! Prove + verify ONE compressed-tree key update, then try forged statements. Input: one line
//! `key_hex vh_old_hex vh_new_hex sib1,sib2,...` (32-byte hex each, siblings root first). Output (one line per item):
//!   ROOTS <old_root_hex> <new_root_hex>      the statement the witness proves
//!   HONEST ok|<error>                       the honest proof verifies
//!   FORGE <name> refused|ACCEPTED           each forged statement against the honest proof
//!   TIME prove_ms=<..> verify_ms=<..> proof_bytes=<..>
use std::io::{self, BufRead};
use std::time::Instant;

use nado_stwo_settle::blake::settle::{Statement, Update, debug_path_constraints, debug_upstream_blake, node_config, prove_update, verify_update};
use nado_stwo_settle::csmt_ref::{bytes, words};

fn h32(s: &str) -> [u8; 32] {
    let v: Vec<u8> = (0..32).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect();
    v.try_into().unwrap()
}
fn hex(w: &[u32; 8]) -> String {
    bytes(w).iter().map(|b| format!("{b:02x}")).collect()
}

fn main() {
    let line = io::stdin().lock().lines().next().unwrap().unwrap();
    let p: Vec<&str> = line.split(' ').collect();
    let sibs: Vec<[u32; 8]> =
        if p.len() > 3 && !p[3].is_empty() { p[3].split(',').map(|s| words(&h32(s))).collect() } else { vec![] };
    let u = Update { key: words(&h32(p[0])), vh_old: words(&h32(p[1])), vh_new: words(&h32(p[2])), sibs };
    if std::env::var("SETTLE_UPSTREAM").is_ok() {
        debug_upstream_blake();
        return;
    }
    if std::env::var("SETTLE_DEBUG").is_ok() {
        debug_path_constraints(&u);
        return;
    }
    let cfg = node_config();
    let t = Instant::now();
    let (st, proof) = prove_update(&u, cfg);
    let prove_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("ROOTS {} {}", hex(&st.root_old), hex(&st.root_new));
    let size = proof.stark.size_estimate();
    let t = Instant::now();
    let honest = verify_update(&st, proof, cfg);
    let verify_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("HONEST {}", match &honest { Ok(()) => "ok".to_string(), Err(e) => format!("{e:?}") });
    let flip = |w: &[u32; 8]| { let mut x = *w; x[3] ^= 1; x };
    let forged: Vec<(&str, Statement)> = vec![
        ("new_root", Statement { root_new: flip(&st.root_new), ..st.clone() }),
        ("old_root", Statement { root_old: flip(&st.root_old), ..st.clone() }),
        ("key", Statement { key: flip(&st.key), ..st.clone() }),
        ("vh_new", Statement { vh_new: flip(&st.vh_new), ..st.clone() }),
        ("vh_old", Statement { vh_old: flip(&st.vh_old), ..st.clone() }),
        ("swapped_roots", Statement { root_old: st.root_new, root_new: st.root_old, ..st.clone() }),
    ];
    for (name, fst) in forged {
        // a fresh honest proof per attempt (verify consumes it); the forged STATEMENT is what is checked
        let (_s, pr) = prove_update(&u, cfg);
        let r = verify_update(&fst, pr, cfg);
        println!("FORGE {name} {}", if r.is_err() { "refused" } else { "ACCEPTED" });
    }
    println!("TIME prove_ms={prove_ms:.0} verify_ms={verify_ms:.1} proof_bytes={size}");
}
