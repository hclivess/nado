//! ZK probe of the wallet's Stwo join-split prover (tests/test_a_stwo_proof_reveals_nothing_about_its_witness.py).
//! Built as an extra bin in a TEMP copy of native/stwo_js (the crate itself is not changed, so the shipped WASM's source
//! digest is untouched). Prints one JSON object. Every number is measured on real proofs at the node config:
//!
//!   seeds      two proofs of ONE witness under two seeds: every committed root (T1-T3), every claimed sum and (almost)
//!              every opened value differ — the randomness is used everywhere, nothing is a function of the witness alone
//!   wire       the wire bytes of a proof contain none of the witness's secrets as a byte string (nsk, rho, v_in, the
//!              output owners and rho) — the prover's debug trace is never serialized
//!   witness    opened values (queried T1-T3, OODS samples, FRI witnesses, claimed sums) equal to a secret 16-bit limb of
//!              the witness: the count against its chance expectation, and the count of small (< 2^16) opened values
//!              against theirs (a leaked trace row is mostly 16-bit limbs and nibbles)
//!   salts      every opened salt value of T1-T3 (8 columns per tree) is distinct within a proof and across two proofs
//!   l0         lemma L0 re-checked: every free-row cell of the original and interaction traces resampled uniformly (the
//!              public IV columns and the interaction's last row kept) and every constraint still holds
//!   rank       lemmas L2/L3 re-checked per column class (component, tree, offsets): the M31 functionals the verifier sees
//!              of one column (lifted openings, the in-composition points, OODS coordinates), restricted to the FREE rows,
//!              have full row rank, so the revealed values are uniform whatever the real rows hold. Each class's point
//!              bookkeeping is re-verified against the proof's own opened and OODS values first.
//! Usage: stwo_zk_probe [n_proofs_for_rank]

use itertools::Itertools;
use nado_stwo_js::*;
use num_traits::{One, Zero};
use stwo::core::circle::CirclePoint;
use stwo::core::fields::m31::BaseField;
use stwo::core::fields::qm31::SecureField;
use stwo::core::poly::circle::CanonicCoset;
use stwo::core::utils::bit_reverse_index;
use stwo::prover::backend::simd::SimdBackend;
use stwo::prover::backend::simd::column::BaseColumn;
use stwo::prover::poly::BitReversedOrder;
use stwo::prover::poly::circle::CircleEvaluation;
use std::collections::HashSet;

fn seed(tag: u8) -> [u8; 32] {
    let mut s = os_seed();
    s[0] ^= tag; // still fresh: os bytes
    s
}

fn secrets(w: &Witness) -> HashSet<u32> {
    let mut s = HashSet::new();
    let mut w32 = |x: u32| {
        s.insert(x & 0xffff);
        s.insert(x >> 16);
    };
    for x in w.nsk { w32(x) }
    for x in owner_of(&w.nsk) { w32(x) }
    for v in [w.v_in, w.rho, w.v1, w.v2, w.r1, w.r2] {
        w32(v as u32);
        w32((v >> 32) as u32);
    }
    for x in w.o1.iter().chain(w.o2.iter()) { w32(*x) }
    for sb in &w.sibs { for x in sb { w32(*x) } }
    // tiny values occur by construction everywhere (dirs, nibbles, carries): only limbs >= 2^8 are distinguishing
    s.retain(|&x| x >= 256);
    s
}

fn wire_contains(hay: &[u8], needle: &[u8]) -> bool {
    hay.windows(needle.len()).any(|w| w == needle)
}

/// every opened M31 value of a proof (queried T1..T3, sampled coords, fri witnesses, claimed sums), except the JS
/// st[0] columns of T1 (the public BLAKE2s start state, a constant column: its 16-bit limbs are opened by design)
fn opened_values(p: &JsProof) -> Vec<u32> {
    let mut v = vec![];
    let st = &p.stark.0;
    let public = |t: usize, c: usize| t == 1 && js_public_cols().contains(&c); // JS is the first component of T1
    for t in 1..st.queried_values.len() {
        for (c, col) in st.queried_values[t].iter().enumerate() { if public(t, c) { continue } for x in col { v.push(x.0) } }
    }
    for t in 1..st.sampled_values.len() {
        for (c, col) in st.sampled_values[t].iter().enumerate() { if public(t, c) { continue } for x in col { for c in x.to_m31_array() { v.push(c.0) } } }
    }
    for l in std::iter::once(&st.fri_proof.first_layer).chain(st.fri_proof.inner_layers.iter()) {
        for x in &l.fri_witness { for c in x.to_m31_array() { v.push(c.0) } }
    }
    for x in &p.claimed { for c in x.to_m31_array() { v.push(c.0) } }
    v
}

/// where the small (< 2^16) opened values sit: (tree, column) -> count, for queried values and OODS samples
fn small_by_column(p: &JsProof) -> Vec<String> {
    let st = &p.stark.0;
    let mut out = vec![];
    for t in 1..st.queried_values.len() {
        for (c, col) in st.queried_values[t].iter().enumerate() {
            let k = col.iter().filter(|x| x.0 < (1 << 16)).count();
            if k > 2 { out.push(format!("q{t}:{c}={k}")); }
        }
        for (c, col) in st.sampled_values[t].iter().enumerate() {
            let k = col.iter().flat_map(|x| x.to_m31_array()).filter(|x| x.0 < (1 << 16)).count();
            if k > 2 { out.push(format!("s{t}:{c}={k}")); }
        }
    }
    out
}

fn salts(p: &JsProof) -> Vec<u32> {
    let st = &p.stark.0;
    let mut v = vec![];
    for t in 1..4 {
        let q = &st.queried_values[t];
        for col in &q[q.len() - N_SALT..] { for x in col { v.push(x.0) } }
    }
    v
}

fn interp(storage: &[BaseField], s: u32) -> stwo::prover::poly::circle::CircleCoefficients<SimdBackend> {
    CircleEvaluation::<SimdBackend, BaseField, BitReversedOrder>::new(
        CanonicCoset::new(s).circle_domain(),
        storage.iter().copied().collect::<BaseColumn>(),
    )
    .interpolate()
}

/// rank over M31 (Gaussian elimination, rows x cols)
fn rank(mut m: Vec<Vec<BaseField>>) -> usize {
    let (nr, nc) = (m.len(), if m.is_empty() { 0 } else { m[0].len() });
    let mut r = 0;
    for c in 0..nc {
        let Some(pr) = (r..nr).find(|&i| !m[i][c].is_zero()) else { continue };
        m.swap(r, pr);
        let inv = m[r][c].inverse();
        for t in c..nc { m[r][t] *= inv; }
        for i in r + 1..nr {
            if !m[i][c].is_zero() {
                let f = m[i][c];
                for t in c..nc { let s = m[r][t] * f; m[i][t] -= s; }
            }
        }
        r += 1;
        if r == nr { break; }
    }
    r
}

struct ClassResult {
    name: String,
    functionals: usize,
    free_rows: usize,
    rank_free: usize,
    rank_all: usize,
    bookkeeping_ok: bool,
}

fn rank_classes(p: &JsProof) -> Vec<ClassResult> {
    let cfg = probe_cfg();
    let sz = Sizes::new(cfg.fri_config.n_queries);
    let dbg = p.dbg.as_ref().unwrap();
    let lc = sz.log_comp();
    let lt = cfg.min_lifting_log_size;
    let dom = CanonicCoset::new(lt).circle_domain();
    let offs = component_offsets(&sz);
    let names = ["JS", "ROUND", "XOR"];
    let mut out = vec![];
    for (tree, tname) in [(1usize, "orig"), (2usize, "interaction")] {
        let mut base = 0usize;
        for (c, (s, oo, io)) in offs.iter().enumerate() {
            let cols = if tree == 1 { oo } else { io };
            let s = *s;
            let n = 1usize << s;
            let r_real = R_REAL[c];
            let mut seen: Vec<Vec<isize>> = vec![];
            for (k, o) in cols.iter().enumerate() {
                let gcol = base + k;
                if tree == 1 && c == 0 && js_public_cols().contains(&k) { continue; }
                if seen.contains(o) { continue; }
                seen.push(o.clone());
                let colv = &dbg.trees[tree][gcol];
                assert_eq!(dbg.tree_logs[tree][gcol], s);
                let fa = interp(colv, s);
                let step = CanonicCoset::new(s).step();
                let mut pts: Vec<(CirclePoint<SecureField>, bool)> = vec![]; // (point, is_qm31)
                let mut ok = true;
                for (i, &q) in dbg.queries.iter().enumerate() {
                    let x = dom.at(bit_reverse_index(q, lt));
                    let po = x.repeated_double(lc - s).into_ef();
                    ok &= fa.eval_at_point(po) == SecureField::from(p.stark.0.queried_values[tree][gcol][i]);
                    pts.push((po, false));
                    for &kk in o {
                        pts.push(((x.repeated_double(lc - 1 - s) + step.mul_signed(kk)).into_ef(), false));
                    }
                }
                let wz = dbg.oods.repeated_double(lc - s);
                for (j, &kk) in o.iter().enumerate() {
                    let pt = wz + step.mul_signed(kk).into_ef();
                    ok &= fa.eval_at_point(pt) == p.stark.0.sampled_values[tree][gcol][j];
                    pts.push((pt, true));
                }
                // free rows: (R, n) for the original trace, (R, n-1) for the interaction (D's last row is public 0)
                let hi = if tree == 2 { n - 1 } else { n };
                let free: Vec<usize> = (r_real + 1..hi).collect();
                let nf = pts.iter().map(|(_, q)| if *q { 4 } else { 1 }).sum::<usize>();
                // M over every row [0, hi): rows = functionals, cols = coset rows (Lagrange basis evaluated at the points)
                let all: Vec<usize> = (0..hi).collect();
                let mut m = vec![vec![BaseField::zero(); all.len()]; nf];
                for (j, &r) in all.iter().enumerate() {
                    let mut u = vec![BaseField::zero(); n];
                    u[pos(r, s)] = BaseField::one();
                    let f = interp(&u, s);
                    let mut row = 0;
                    for (pt, q) in &pts {
                        let v = f.eval_at_point(*pt).to_m31_array();
                        if *q { for t in 0..4 { m[row + t][j] = v[t]; } row += 4; } else { m[row][j] = v[0]; row += 1; }
                    }
                }
                let rank_all = rank(m.clone());
                let mf: Vec<Vec<BaseField>> = m.iter().map(|row| free.iter().map(|&r| row[r]).collect()).collect();
                let rk = rank(mf);
                out.push(ClassResult {
                    name: format!("{} {} offsets {:?}", names[c], tname, o),
                    functionals: nf,
                    free_rows: free.len(),
                    rank_free: rk,
                    rank_all,
                    bookkeeping_ok: ok,
                });
            }
            base += cols.len();
        }
    }
    out
}

fn l0_resample(p: &JsProof) -> [bool; 3] {
    let cfg = probe_cfg();
    let sz = Sizes::new(cfg.fri_config.n_queries);
    let dbg = p.dbg.as_ref().unwrap();
    let offs = component_offsets(&sz);
    let mut rng_state = os_seed();
    let mut ctr = 0u64;
    let mut rnd = || -> BaseField {
        // ChaCha-free uniform M31 from blake2s(seed || ctr): adequate for a resampling check
        use blake2::Digest;
        loop {
            ctr += 1;
            let mut h = blake2::Blake2s256::new();
            h.update(rng_state);
            h.update(ctr.to_le_bytes());
            let d = h.finalize();
            let x = u32::from_le_bytes([d[0], d[1], d[2], d[3]]) & 0x7fff_ffff;
            if x != 0x7fff_ffff { rng_state[0] ^= d[4]; return m31(x); }
        }
    };
    let pre = dbg.trees[0].clone();
    let mut orig: Vec<Vec<BaseField>> = dbg.trees[1][..dbg.trees[1].len() - N_SALT].to_vec();
    let mut int: Vec<Vec<BaseField>> = dbg.trees[2][..dbg.trees[2].len() - N_SALT].to_vec();
    let (mut bo, mut bi) = (0usize, 0usize);
    for (c, (s, oo, io)) in offs.iter().enumerate() {
        let n = 1usize << *s;
        let r_real = R_REAL[c];
        for k in 0..oo.len() {
            if c == 0 && js_public_cols().contains(&k) { continue; }
            for r in r_real + 1..n { orig[bo + k][pos(r, *s)] = rnd(); }
        }
        for k in 0..io.len() {
            for r in r_real + 1..n - 1 { int[bi + k][pos(r, *s)] = rnd(); }
        }
        bo += oo.len();
        bi += io.len();
    }
    // claimed sums: the proof's own; the relation: the prover's draw
    constraints_hold(&sz, &dbg.rel, &p.claimed, [pre, orig, int])
}

/// The node config under measurement: $NADO_ZK_CFG (lib.rs NODE_CFGS id), default NODE_CFG_340 — the test runs every
/// node config, since the random-row count and the trace sizes follow the query count (STWO_JS_128_HEIGHT).
fn probe_cfg() -> stwo::core::pcs::PcsConfig {
    let id = std::env::var("NADO_ZK_CFG").ok().map(|s| s.parse().expect("NADO_ZK_CFG")).unwrap_or(NODE_CFG_340);
    node_config_of(id).expect("a lib.rs NODE_CFGS id")
}

fn main() {
    let n_rank: usize = std::env::args().nth(1).map(|s| s.parse().unwrap()).unwrap_or(1);
    let cfg = probe_cfg();
    let (wa, wb) = (fixture(), fixture_b());
    let (_pa, a1, _) = prove_js(&wa, aux_of(b""), cfg, false, seed(1)).expect("prove a");
    let (_pa2, a2, _) = prove_js(&wa, aux_of(b""), cfg, false, seed(2)).expect("prove a again");
    let dest = b"probe-destination";
    let (_pb, b1, _) = prove_js(&wb, aux_of(dest), cfg, false, seed(3)).expect("prove b");

    // ---- seeds: same witness, two seeds
    let roots_differ = (1..4).all(|t| a1.stark.commitments[t] != a2.stark.commitments[t]);
    let pre_same = a1.stark.commitments[0] == a2.stark.commitments[0];
    let claimed_differ = a1.claimed.iter().zip(a2.claimed.iter()).all(|(x, y)| x != y);
    let sv = |p: &JsProof| p.stark.0.sampled_values.iter().skip(1).flat_map(|t| t.iter().flat_map(|c| c.iter().copied())).collect_vec();
    let (s1, s2) = (sv(&a1), sv(&a2));
    let sampled_equal = s1.iter().zip(s2.iter()).filter(|(x, y)| x == y).count();

    // ---- wire: no secret byte string
    let mut wire_hits = vec![];
    for (name, p, w) in [("a", &a1, &wa), ("b", &b1, &wb)] {
        let bytes = wire::encode(p);
        let mut needles: Vec<(String, Vec<u8>)> = vec![
            ("nsk".into(), w.nsk.iter().flat_map(|x| x.to_le_bytes()).collect()),
            ("owner".into(), owner_of(&w.nsk).iter().flat_map(|x| x.to_le_bytes()).collect()),
            ("rho".into(), w.rho.to_le_bytes().to_vec()),
            ("v_in".into(), w.v_in.to_le_bytes().to_vec()),
            ("o1".into(), w.o1.iter().flat_map(|x| x.to_le_bytes()).collect()),
            ("o2".into(), w.o2.iter().flat_map(|x| x.to_le_bytes()).collect()),
            ("r1".into(), w.r1.to_le_bytes().to_vec()),
            ("r2".into(), w.r2.to_le_bytes().to_vec()),
        ];
        // the nsk as the trace holds it: 16 M31 limbs, u32 LE each
        needles.push(("nsk-limbs".into(), w.nsk.iter().flat_map(|x| [(x & 0xffff), (x >> 16)]).flat_map(|x| x.to_le_bytes()).collect()));
        for (k, nd) in needles {
            if wire_contains(&bytes, &nd) { wire_hits.push(format!("{name}:{k}")); }
        }
    }

    // ---- witness: opened values equal to secret limbs; small values
    let mut wit_rows = vec![];
    for (name, p, w) in [("a", &a1, &wa), ("b", &b1, &wb)] {
        let ov = opened_values(p);
        let sec = secrets(w);
        let hits = ov.iter().filter(|x| sec.contains(x)).count();
        let matched: Vec<u32> = ov.iter().filter(|x| sec.contains(x)).copied().sorted().dedup().collect();
        eprintln!("proof {name}: matched secret values {:x?}", matched);
        let small = ov.iter().filter(|&&x| x < (1 << 16)).count();
        let n = ov.len() as f64;
        wit_rows.push(format!(
            "{{\"proof\": \"{name}\", \"opened\": {}, \"secret_limbs\": {}, \"secret_hits\": {hits}, \"secret_hits_expected\": {:.3}, \"small\": {small}, \"small_expected\": {:.3}}}",
            ov.len(), sec.len(), n * sec.len() as f64 / 2147483647.0, n * 65536.0 / 2147483647.0
        ));
    }

    let small_a = small_by_column(&a1);
    // ---- salts
    let (sa, sb) = (salts(&a1), salts(&b1));
    let set_a: HashSet<u32> = sa.iter().copied().collect();
    let set_b: HashSet<u32> = sb.iter().copied().collect();
    let salts_distinct_within = set_a.len() == sa.len() && set_b.len() == sb.len();
    let salts_shared = set_a.intersection(&set_b).count();

    // ---- L0
    let l0 = [l0_resample(&a1), l0_resample(&b1)];

    // ---- rank
    let mut rank_rows = vec![];
    let mut proofs: Vec<&JsProof> = vec![&a1, &b1];
    let extra: Vec<JsProof> = (2..n_rank).map(|i| prove_js(&wa, aux_of(b""), cfg, false, seed(10 + i as u8)).unwrap().1).collect();
    proofs.extend(extra.iter());
    for (i, p) in proofs.iter().take(n_rank.max(1)).enumerate() {
        for c in rank_classes(p) {
            rank_rows.push(format!(
                "{{\"proof\": {i}, \"class\": \"{}\", \"functionals\": {}, \"free_rows\": {}, \"rank_free\": {}, \"rank_all\": {}, \"bookkeeping_ok\": {}}}",
                c.name, c.functionals, c.free_rows, c.rank_free, c.rank_all, c.bookkeeping_ok
            ));
        }
    }

    println!(
        "{{\"seeds\": {{\"roots_differ\": {roots_differ}, \"preprocessed_same\": {pre_same}, \"claimed_differ\": {claimed_differ}, \"sampled_total\": {}, \"sampled_equal\": {sampled_equal}}},\n \"small_by_column\": {:?},\n \"wire_hits\": {:?},\n \"witness\": [{}],\n \"salts\": {{\"n_a\": {}, \"distinct_within\": {salts_distinct_within}, \"shared_across\": {salts_shared}}},\n \"l0\": {:?},\n \"rank\": [{}]}}",
        s1.len(), small_a, wire_hits, wit_rows.join(", "), sa.len(), l0, rank_rows.join(",\n  ")
    );
}
