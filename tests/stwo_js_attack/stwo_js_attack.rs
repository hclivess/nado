//! Adversarial harness for the Stwo join-split verifier (review 2026-10-11). Built by
//! tests/test_stwo_js_every_post_proof_mutation_and_cheat_is_refused.py into a TEMP copy of native/stwo_js as
//! src/bin/stwo_js_attack.rs (feature `prover`, nightly) — never into the checkout.
//! Prints one line per case: `CASE <name> rc=<code>`; the Python test asserts on them.
//! $NADO_ATTACK_CFG: the node config under attack (lib.rs NODE_CFGS id, default NODE_CFG_340) — the honest proof is made
//! at it and every verification requires it, so each config gets the whole battery (STWO_JS_128_HEIGHT).
use nado_stwo_js::*;
use stwo::core::fields::qm31::SecureField;
use num_traits::One;

fn cfg_id() -> u32 {
    std::env::var("NADO_ATTACK_CFG").ok().map(|s| s.parse().expect("NADO_ATTACK_CFG")).unwrap_or(NODE_CFG_340)
}

fn rc(bytes: &[u8], p: &Public, dest: &[u8]) -> i32 {
    verify_node(bytes, words_digest(&p.root), words_digest(&p.nf), words_digest(&p.cm1), words_digest(&p.cm2), p.pv, p.fee, dest, cfg_id()).0
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let mode = a.get(1).map(String::as_str).unwrap_or("mutate");
    let dest = b"ndo1-attack-destination";
    let seed = [7u8; 32];
    let w = fixture_b();
    let cfg = node_config_of(cfg_id()).expect("a lib.rs NODE_CFGS id");
    let (p, proof, _) = prove_js(&w, aux_of(dest), cfg, false, seed).expect("prove");
    let honest = wire::encode(&proof);
    println!("CASE honest rc={}", rc(&honest, &p, dest));
    let one = SecureField::one();
    let enc = |f: &dyn Fn(&mut JsProof)| {
        let mut q = wire::decode(&honest).unwrap();
        f(&mut q);
        wire::encode(&q)
    };
    let case = |name: &str, b: Vec<u8>| println!("CASE {name} rc={}", rc(&b, &p, dest));
    if mode == "mutate" {
        for i in 0..3 {
            case(&format!("claimed{i}+1"), enc(&|q| q.claimed[i] += one));
        }
        case("claimed0+x,claimed1-x", enc(&|q| { q.claimed[0] += one; q.claimed[1] -= one; }));
        case("claimed0+x,claimed2-x", enc(&|q| { q.claimed[0] += one; q.claimed[2] -= one; }));
        case("claimed-extra", enc(&|q| q.claimed.push(SecureField::default())));
        for t in 0..4 {
            case(&format!("commitment{t}"), enc(&|q| q.stark.0.commitments[t].0[0] ^= 1));
        }
        for t in 0..4 {
            case(&format!("sampled{t}"), enc(&|q| {
                let c = q.stark.0.sampled_values[t].iter_mut().find(|c| !c.is_empty()).unwrap();
                c[0] += one;
            }));
            case(&format!("sampled{t}-last"), enc(&|q| {
                let c = q.stark.0.sampled_values[t].iter_mut().rev().find(|c| !c.is_empty()).unwrap();
                c[0] += one;
            }));
            case(&format!("queried{t}"), enc(&|q| {
                let c = &mut q.stark.0.queried_values[t][0];
                c[0] = c[0] + stwo::core::fields::m31::BaseField::one();
            }));
            case(&format!("queried{t}-salt"), enc(&|q| {
                let c = q.stark.0.queried_values[t].last_mut().unwrap();
                c[0] = c[0] + stwo::core::fields::m31::BaseField::one();
            }));
            case(&format!("decommit{t}-pop"), enc(&|q| { q.stark.0.decommitments[t].hash_witness.pop(); }));
            case(&format!("decommit{t}-push"), enc(&|q| {
                let x = q.stark.0.decommitments[t].hash_witness[0];
                q.stark.0.decommitments[t].hash_witness.push(x);
            }));
        }
        case("pow+1", enc(&|q| q.stark.0.proof_of_work = q.stark.0.proof_of_work.wrapping_add(1)));
        case("fri-first-commit", enc(&|q| q.stark.0.fri_proof.first_layer.commitment.0[0] ^= 1));
        case("fri-first-witness", enc(&|q| q.stark.0.fri_proof.first_layer.fri_witness[0] += one));
        case("fri-first-witness-push", enc(&|q| q.stark.0.fri_proof.first_layer.fri_witness.push(one)));
        case("fri-inner0-witness", enc(&|q| q.stark.0.fri_proof.inner_layers[0].fri_witness[0] += one));
        case("fri-inner-last-pop", enc(&|q| { q.stark.0.fri_proof.inner_layers.pop(); }));
        case("fri-last-poly", enc(&|q| q.stark.0.fri_proof.last_layer_poly[0] += one));
        case("cfg-queries-1", enc(&|q| q.stark.0.config.fri_config.n_queries -= 1));
        case("cfg-pow-0", enc(&|q| q.stark.0.config.pow_bits = 0));
        case("cfg-blowup-1", enc(&|q| q.stark.0.config.fri_config.log_blowup_factor = 1));
        case("cfg-lift+1", enc(&|q| q.stark.0.config.min_lifting_log_size += 1));
        case("cfg-lastlayer-1", enc(&|q| q.stark.0.config.fri_config.log_last_layer_degree_bound = 1));
        case("cfg-foldstep-2", enc(&|q| q.stark.0.config.fri_config.fold_step = 2));
        // THE OODS GRIND (lib.rs NODE128_OODS_POW_BITS): a nonce that does not meet the bits, on a config that grinds,
        // is refused before the OODS point is drawn. On a config without a grind the nonce is not on the wire.
        if oods_pow_bits(cfg) > 0 {
            case("oods-nonce+1", enc(&|q| q.oods_nonce = q.oods_nonce.wrapping_add(1)));
            case("oods-nonce-zero", enc(&|q| q.oods_nonce = 0));
        }
        // a proof honestly made at a CHEAPER config (1/80/20): the verifier must refuse it outright
        let cheap = config(1, 80, 20);
        let (p2, pr2, _) = prove_js(&w, aux_of(dest), cheap, false, [9u8; 32]).expect("prove cheap");
        println!("CASE cheaper-config rc={}", rc(&wire::encode(&pr2), &p2, dest));
        // a proof honestly made at the OTHER node config — valid for its own height, never for this one's: the height
        // chooses the config, so neither the cheaper nor the costlier node config is the prover's to pick
        let other = NODE_CFGS.iter().find(|c| c.0 != cfg_id()).map(|c| config(c.1, c.2, c.3)).unwrap();
        let (p3, pr3, _) = prove_js(&w, aux_of(dest), other, false, [13u8; 32]).expect("prove other");
        println!("CASE other-node-config rc={}", rc(&wire::encode(&pr3), &p3, dest));
        for (name, ch) in [("ShiftClaimed", Cheat::ShiftClaimed), ("ForgeLookup", Cheat::ForgeLookup)] {
            match prove_js_cheat(&w, aux_of(dest), cfg, false, [11u8; 32], ch) {
                Ok((pc, prc, _)) => println!("CASE cheat-{name} rc={}", rc(&wire::encode(&prc), &pc, dest)),
                Err(e) => println!("CASE cheat-{name} rc=prover-refused({e:?})"),
            }
        }
    } else if mode == "flip" {
        // THE FREE-CELL PROBE (Cheat::Flip; Zcash Orchard's bug class): one cell of a real row tampered in EVERY
        // original-trace column of JS and ROUND, and the XOR multiplicity column, each proven by a prover that skips
        // its own checks. Every one must be refused; an accepted one is a cell the circuit does not constrain.
        // THREE COLUMN CLASSES ARE PROBED WHERE THEY BITE (the first run of 2026-10-27 accepted 68 +1 flips, every one in
        // these classes, none changing a constrained value — each verified against the AIR):
        //  - JS held-register range pieces (pv, fee, sm: the 36 columns before the blinding): range-checked on row 0
        //    ONLY (s_first) because the registers are held equal on every real row (s_hold) — dead cells elsewhere, so
        //    they are probed on row 0;
        //  - ROUND add3 carry helpers (bl, bh of each add3: 64 + 98 g + {2, 3, 48, 49}): the carry is DERIVED from the sum
        //    and pinned; the helper bit is non-unique when the carry is 1 (bl in {0,1} and cl - bl in {0,1} both hold), so a
        //    +1 flip can be legal — they are probed with +2, which no constraint admits;
        //  - ZK blinding columns (the last 4 of JS, the last 8 of ROUND): random by design, no part of the statement —
        //    excluded, by exact count.
        let (wj, wr) = witness_widths(cfg);
        println!("CASE widths js={wj} round={wr}");
        let (js_blind, rd_blind, js_held) = (4usize, 8usize, 12 * 3usize);
        let carry = |c: usize| c >= 64 && c < wr - rd_blind && [2, 3, 48, 49].contains(&((c - 64) % 98));
        let mut probes: Vec<(u8, usize, usize, u32)> = vec![];
        for c in 0..wj - js_blind {
            let row = if c >= wj - js_blind - js_held { 0 } else { (c * 37 + 5) % R_JS };
            probes.push((0, c, row, 1));
        }
        for c in 0..wr - rd_blind {
            probes.push((1, c, (c * 37 + 5) % R_ROUND, if carry(c) { 2 } else { 1 }));
        }
        probes.push((2, 0, 7 % R_XOR, 1));
        println!("CASE excluded js_blind={js_blind} round_blind={rd_blind} carry_plus2={}", (0..wr).filter(|c| carry(*c)).count());
        for (comp, col, row, delta) in probes {
            let ch = Cheat::Flip { comp, col: col as u16, row: row as u16, delta };
            let r = std::panic::catch_unwind(|| prove_js_cheat(&w, aux_of(dest), cfg, false, [17u8; 32], ch));
            match r {
                Ok(Ok((pc, prc, _))) => println!("CASE flip-{comp}-{col}-{row} rc={}", rc(&wire::encode(&prc), &pc, dest)),
                Ok(Err(e)) => println!("CASE flip-{comp}-{col}-{row} rc=prover-refused({e:?})"),
                Err(_) => println!("CASE flip-{comp}-{col}-{row} rc=prover-panicked"),
            }
        }
    } else if mode == "struct" {
        // structurally inconsistent proofs: each must be REFUSED (rc 2/3/4), never accepted, never abort the process
        case("queried1-drop-column", enc(&|q| { q.stark.0.queried_values[1].pop(); }));
        case("queried1-short-column", enc(&|q| { q.stark.0.queried_values[1][0].pop(); }));
        case("queried-drop-tree", enc(&|q| { q.stark.0.queried_values.0.pop(); }));
        case("decommit-drop-tree", enc(&|q| { q.stark.0.decommitments.0.pop(); }));
        case("sampled-drop-tree", enc(&|q| { q.stark.0.sampled_values.0.pop(); }));
        case("commitments-5", enc(&|q| { let c = q.stark.0.commitments[3]; q.stark.0.commitments.0.push(c); }));
        case("fri-no-inner", enc(&|q| { q.stark.0.fri_proof.inner_layers.clear(); }));
        case("fri-witness-empty", enc(&|q| { q.stark.0.fri_proof.first_layer.fri_witness.clear(); }));
        case("claimed-empty", enc(&|q| { q.claimed.clear(); }));
        // a declared length of 2^60 claimed sums in a few bytes: must be refused without allocating it
        let mut b = honest.clone();
        b[..8].copy_from_slice(&(1u64 << 60).to_le_bytes());
        case("huge-len-prefix", b);
        // 16 MiB + 1: refused by the cap before decoding
        case("over-cap", vec![0u8; wire::MAX_PROOF_BYTES + 1]);
        // the largest proof the cap admits, padded with hash witnesses: refused, and how long it takes
        let big = enc(&|q| {
            let x = q.stark.0.decommitments[1].hash_witness[0];
            while bincode::serialized_size(&(&q.claimed, &q.stark)).unwrap() + 32 * 1024 < wire::MAX_PROOF_BYTES as u64 {
                for _ in 0..1024 { q.stark.0.decommitments[1].hash_witness.push(x); }
            }
        });
        let t = std::time::Instant::now();
        let r = rc(&big, &p, dest);
        println!("CASE max-size-padded rc={r} bytes={} ms={}", big.len(), t.elapsed().as_millis());
        let t = std::time::Instant::now();
        let r = rc(&honest, &p, dest);
        println!("CASE honest-timing rc={r} bytes={} ms={}", honest.len(), t.elapsed().as_millis());
    } else if mode == "dump" {
        // for the node binding (ctypes -> nado_stwo_js_verify): the honest proof, one that makes the verifier panic,
        // and the public inputs, so the Python test can check a panic comes back as a refusal and the caller lives
        let out = a.get(2).expect("dump <dir>");
        std::fs::write(format!("{out}/honest.bin"), &honest).unwrap();
        std::fs::write(format!("{out}/panic.bin"), enc(&|q| { q.stark.0.queried_values[1].pop(); })).unwrap();
        let h = |w: &[u32; 8]| words_digest(w).iter().map(|b| format!("{b:02x}")).collect::<String>();
        std::fs::write(format!("{out}/public.json"), format!(
            "{{\"root\": \"{}\", \"nf\": \"{}\", \"cm1\": \"{}\", \"cm2\": \"{}\", \"unshield\": {}, \"fee\": {}, \"dest\": \"{}\"}}",
            h(&p.root), h(&p.nf), h(&p.cm1), h(&p.cm2), p.pv, p.fee, std::str::from_utf8(dest).unwrap())).unwrap();
        println!("CASE dumped");
    } else if mode == "fuzz" {
        // byte flips and truncations: never RC_OK, and the process must survive every one (no abort across FFI)
        let n: usize = a.get(2).map(|s| s.parse().unwrap()).unwrap_or(300);
        let mut x: u64 = 0x9E3779B97F4A7C15;
        let mut next = || { x ^= x << 13; x ^= x >> 7; x ^= x << 17; x };
        let (mut ok, mut counts) = (0, [0usize; 5]);
        for i in 0..n {
            let mut b = honest.clone();
            if i % 4 == 3 {
                let l = (next() as usize) % b.len();
                b.truncate(l);
            } else {
                let k = (next() as usize) % b.len();
                b[k] ^= 1 << (next() % 8);
            }
            let r = rc(&b, &p, dest);
            if r == RC_OK && b != honest { ok += 1; }
            counts[r as usize] += 1;
        }
        println!("CASE fuzz n={n} accepted_mutants={ok} rc_counts={counts:?}");
    }
}
