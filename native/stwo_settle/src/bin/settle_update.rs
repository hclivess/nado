//! Prove + verify a SEQUENTIAL BATCH of compressed-tree writes, then try forged statements against the honest proof.
//! Input: one line per write, in order, each against the tree the previous one left (32-byte hex values, `-` = none):
//!   `<op> key vh_old vh_new sib1,sib2,... extra`
//! op: U (update), IE / DE (insert into / delete to EMPTY), IS / DC (insert splitting / delete collapsing a neighbour
//! leaf); sibs: the shallow side's siblings, root first; extra: IS / DC `k2,vh2,db`, IE / DE at depth > 0 `l,r` (the
//! children of the deepest sibling), else `-`. Output (one line per item):
//!   ROOTS <first old root hex> <last new root hex>   the statement the witness proves (the chain's two ends)
//!   HONEST ok|<error>|prover_refused <error>         the honest proof verifies (with SETTLE_TAMPER=<name> the witness
//!                                                    is a dishonest one, path.rs settle::Tamper, and nothing else runs)
//!   FORGE <name> refused|ACCEPTED                    each forged statement against the honest proof
//!   TIME updates=<K> rows=<..> prove_ms=<..> verify_ms=<..> proof_bytes=<..>
use std::io::{self, BufRead};
use std::time::Instant;

use nado_stwo_settle::blake::path::batch_rows;
use nado_stwo_settle::blake::settle::{
    Op, Statement, Tamper, Update, debug_path_constraints, debug_upstream_blake, node_config, prove_tampered, verify_batch,
};
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
        let w = |s: &str| if s == "-" { [0u32; 8] } else { words(&h32(s)) };
        fn list(s: &str) -> Vec<&str> {
            if s == "-" || s.is_empty() { vec![] } else { s.split(',').collect() }
        }
        let op = match p[0] {
            "U" => Op::Update,
            "IE" => Op::InsertEmpty,
            "DE" => Op::DeleteEmpty,
            "IS" => Op::InsertSplit,
            "DC" => Op::DeleteCollapse,
            x => panic!("unknown op {x}"),
        };
        let sibs: Vec<[u32; 8]> = list(p[4]).into_iter().map(w).collect();
        let extra = list(p[5]);
        let z = [0u32; 8];
        let (k2, vh2, db, open) = if op.split_kind() {
            (w(extra[0]), w(extra[1]), extra[2].parse().unwrap(), (z, z))
        } else if op.empty_kind() && !extra.is_empty() {
            (z, z, sibs.len(), (w(extra[0]), w(extra[1])))
        } else {
            (z, z, sibs.len(), (z, z))
        };
        us.push(Update { op, key: w(p[1]), vh_old: w(p[2]), vh_new: w(p[3]), sibs, k2, vh2, db, open });
    }
    if std::env::var("SETTLE_UPSTREAM").is_ok() {
        debug_upstream_blake();
        return;
    }
    if std::env::var("SETTLE_DEBUG").is_ok() {
        debug_path_constraints(&us);
        return;
    }
    // MEASUREMENT ONLY: SETTLE_CFG="pow,log_blowup,queries,fold_step" proves and verifies under another PcsConfig (the
    // parameter study in doc/stwo/g4-settlement-statement.md); unset, the node's config.
    let cfg = match std::env::var("SETTLE_CFG") {
        Ok(v) => {
            let x: Vec<u32> = v.split(',').map(|t| t.parse().unwrap()).collect();
            stwo::core::pcs::PcsConfig {
                pow_bits: x[0],
                fri_config: stwo::core::fri::FriConfig::new(0, x[1], x[2] as usize, x[3]),
                min_lifting_log_size: 0,
            }
        }
        Err(_) => node_config(),
    };
    let t = Instant::now();
    let tamper = match std::env::var("SETTLE_TAMPER").as_deref() {
        Ok("shared_sibling") => Tamper::SharedSibling,
        Ok("empty_sibling") => Tamper::EmptySibling,
        Ok("split_link") => Tamper::SplitLink,
        Ok("empty_start") => Tamper::EmptyStart,
        Ok(x) => panic!("unknown tamper {x}"),
        Err(_) => Tamper::None,
    };
    let (st, proof) = match prove_tampered(&us, cfg, tamper) {
        Ok(x) => x,
        Err(e) => {
            println!("HONEST prover_refused {e}");
            return;
        }
    };
    let prove_ms = t.elapsed().as_secs_f64() * 1e3;
    let k = st.updates.len();
    println!("ROOTS {} {}", hex(&st.updates[0].root_old), hex(&st.updates[k - 1].root_new));
    let size = proof.stark.size_estimate();
    let t = Instant::now();
    let honest = verify_batch(&st, proof.clone(), cfg);
    let verify_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("HONEST {}", match &honest { Ok(()) => "ok".to_string(), Err(e) => format!("{e:?}") });
    if tamper != Tamper::None {
        return;
    }

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
    // a split's neighbour key, past the bits the shape check reads: only the in-circuit tuple refuses it
    if let Some(i) = st.updates.iter().position(|u| u.op.split_kind()) {
        forged.push(("neighbour_key".into(), edit(&|s| s.updates[i].k2[7] ^= 1)));
        forged.push(("split_depth".into(), edit(&|s| s.updates[i].db += 1)));
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
    let rows = batch_rows(&st.shapes());
    println!("TIME updates={k} rows={rows} prove_ms={prove_ms:.0} verify_ms={verify_ms:.1} proof_bytes={size}");
}
