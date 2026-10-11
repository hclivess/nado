//! Test prover (feature `prover`): proves one of the two fixture join-splits at the pinned node config and writes
//!   <out>/proof.bin    the wire bytes (src/wire.rs)
//!   <out>/public.json  {"root","nf","cm1","cm2": 64-hex, "unshield", "fee": int, "dest": str}
//! Usage: stwo_js_prove <a|b> <dest> <out_dir> [seed: 64-hex]   (no seed: 32 bytes from /dev/urandom)

use nado_stwo_js::*;

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    // `stwo_js_prove preroot`: the preprocessed root recomputed from the column builders (the pin test compares it with
    // lib.rs NODE_PREPROCESSED_ROOT), as 64-hex on stdout.
    if a.get(1).map(String::as_str) == Some("preroot") {
        println!("{}", hex(&preprocessed_root(node_config())));
        return;
    }
    if a.len() < 4 {
        eprintln!("usage: stwo_js_prove <a|b> <dest> <out_dir> [seed-hex]");
        std::process::exit(2);
    }
    // `zeropre`: a FORGERY (Cheat::ZeroPre) — fixture a's witness, but an all-zero preprocessed tree and public inputs
    // the witness never produced (nf, outputs, unshield 10^18). The verifier must refuse it.
    let forge = a[1] == "zeropre";
    let w = match a[1].as_str() {
        "a" | "zeropre" => fixture(),
        "b" => fixture_b(),
        "mint" => fixture_mint(),
        _ => panic!("fixture a, b, mint or zeropre"),
    };
    let dest = a[2].as_bytes();
    let seed: [u8; 32] = match a.get(4) {
        Some(s) => std::array::from_fn(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()),
        None => os_seed(),
    };
    let (public, proof, tm) = if forge {
        prove_js_cheat(&w, aux_of(dest), node_config(), false, seed, Cheat::ZeroPre).expect("forge")
    } else {
        prove_js(&w, aux_of(dest), node_config(), false, seed).expect("prove")
    };
    let bytes = wire::encode(&proof);
    std::fs::create_dir_all(&a[3]).unwrap();
    std::fs::write(format!("{}/proof.bin", a[3]), &bytes).unwrap();
    let json = format!(
        "{{\"root\": \"{}\", \"nf\": \"{}\", \"cm1\": \"{}\", \"cm2\": \"{}\", \"unshield\": {}, \"fee\": {}, \"dest\": \"{}\"}}\n",
        hex(&words_digest(&public.root)),
        hex(&words_digest(&public.nf)),
        hex(&words_digest(&public.cm1)),
        hex(&words_digest(&public.cm2)),
        public.pv,
        public.fee,
        a[2].replace('\\', "\\\\").replace('"', "\\\"")
    );
    std::fs::write(format!("{}/public.json", a[3]), json).unwrap();
    eprintln!("proved: {} bytes, prove {:.0} ms", bytes.len(), tm.witness_trace_ms + tm.commit_ms + tm.interaction_ms + tm.prove_ms);
}
