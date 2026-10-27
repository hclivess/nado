# Phase 0 (doc/stwo-migration.md section 5.0): join-split prover, ours vs a Stwo prototype

> **Provenance.** Written 2026-10-11 in a session scratch directory that was later wiped; restored verbatim from the
> session's record of every write and edit. The scratch sources it cites (`stwo_zk/`, `zkproof/zkcheck.rs`, logs under
> `after/`, `env.sh`) are gone. The ZK construction they prototyped is implemented in `native/stwo_js` and pinned by
> its tests; re-measure against that crate, not against the paths below.

Date: 2026-10-10. Nothing in `/srv/nado-home/nado` was changed for this work, except that two Python bytecode
cache files (`execnode/stark/__pycache__/{soundness,joinsplit_transfer}.cpython-312.pyc`, git-ignored) were written
by the first two Python runs and then deleted again; every later Python run used `PYTHONDONTWRITEBYTECODE=1`.
No node module was imported against the live database (HOME, NADO_EXEC_STATE, NADO_EXEC_DA assigned to a temp dir first).
Nothing was pushed or published.

## Machine and load

- 12 vCPU "AMD EPYC Processor (with IBPB)" (QEMU pc-i440fx-9.0, 2.0 GHz, AVX2, no AVX-512), 47 GiB RAM, Linux 6.8.0-100.
- **Shared and loaded host.** 1-minute load average was 9.1 to 14.8 during every run (it is printed beside each run in
  the logs). All numbers below are therefore pessimistic and noisy; medians of 5 are given where it was cheap to repeat.
- Core budget: every Stwo prove is **single-threaded** (built without the `parallel` feature) unless marked; one
  4-thread run (`--features parallel`, `RAYON_NUM_THREADS=4`) is reported; builds used `cargo -j4`. Our JS prover is
  single-threaded by construction (one JS thread).
- Node v22.23.0; headless Chromium 154 (snap) driven by selenium 4.44.
- No phone was available: **no phone numbers exist in this report.** Steps for the operator are at the end.

## The two numbers (same statement, depth 48)

| | ours: wallet `static/stark/joinsplit3.js` | Stwo prototype `stwo0/stwo_js` (nibble variant) |
|---|---|---|
| hash | alghash2 (Goldilocks sponge, x^7) | BLAKE2s-256 (one compression per hash) |
| field / challenge field | Goldilocks / GF(p^3) | M31 / QM31 (124 bit) |
| trace | T = 4096 rows x 39 cols, LDE x16 | 4,170 cols, 0.97 M cells total (64 + 512 + 128 + 512 rows) |
| **prove, Node** | **459.8 s** (one run) | **0.51 - 0.75 s** WASM (warm median ~0.54 s, first call 0.75 s) |
| **prove, headless Chromium** | **266.2 s** main thread (as the wallet runs it); renderer peak RSS **3.52 GB**, JS heap 1.85 GB at the end. In a module Worker it **fails**: `RangeError: Maximum call stack size exceeded` (see below) | **0.53 - 0.61 s** warm, **1.7 s** first call (WASM) |
| prove, native x86 1 thread | (no native prover exists) | 0.29 - 0.37 s (baseline x86-64), 0.19 - 0.24 s (`target-cpu=native`) |
| **peak memory** | **4.24 GB RSS** (Node, `/usr/bin/time -v`) | **30 - 32 MiB** WASM linear memory; Node process 105 - 118 MB RSS; native 46 MB RSS |
| proof size | **36.4 MB** as the JSON the wallet submits; ~16.8 MB binary-equivalent (54,493 field elements x 8 B + 510,774 hashes/salts x 32 B) | **1.48 MB** (bincode) at 100-bit config 1/80/20; 0.85 MB at 2/40/20; 0.51 MB at 4/20/20 |
| verify | **3.70 s** (node's Python `shielded.verify_transfer`, 127 MB RSS) | **18 - 20 ms** native, 27 - 43 ms WASM |
| security (NADO's own model, `execnode/stark/soundness.py`) | **157.5 bits provable** (JBR), 332 conjectured: blowup 16 LDE / FRI rate 1/2, 320 queries, 18 grind bits, GF(p^3) | config 1/80/20: Stwo `security_bits()` = 100 (conjectured); NADO model: 97.7 conjectured, ~60 provable |
| zero knowledge | yes (Z1: randomizer cols, random rows, salted leaves) | **NO** in `stwo_js` (upstream Stwo at this commit has no ZK mode); **yes in `stwo_zk`**, see the ZK section below (0.72 - 0.86 s native, 1.4 s WASM, 1.50 MB) |

Ratio at the headline 100-bit config: prove **~600-900x faster** (Node vs Node), memory **~130x lower** in peak
working set (4.2 GB vs ~32 MiB of WASM heap; ~36x by whole-process RSS), proof **~11x smaller** than our
binary-equivalent and ~25x smaller than what the wallet actually submits, verify **~190x faster**.

At a config whose conjectured security matches ours (log_blowup 2, 160 queries, pow 20: 340 conjectured bits, NADO-model
113 provable): native 0.51 - 0.55 s, WASM 0.79 - 1.28 s warm (2.4 s first call) in Node/Chromium, **2.76 MB** proof,
24 - 33 ms native verify. Still ~400x faster and ~6x smaller than ours.

## Our prover: which path is real

- The **wallet proved at the time of measurement** (since replaced by `_onDeviceProveStwo`, the Stwo WASM prover; then: `static/interface.js` `_onDeviceProve3` -> `sstark.prove(...)` of `static/stark/stark.js` with
  `static/stark/joinsplit3.js`), with the proof rules read from `/status` (all live: round2, trace_ldt, full_query) and
  `zk = 8`. That is the path measured.
- The node **does not** prove join-splits: `execnode/stark/joinsplit3.prove_transfer` refuses on a node
  (`NativeMissing: ... proving in Python is not permitted on a node (RUST-ONLY POLICY)`); it is reachable only with
  `NADO_ALLOW_PYTHON_KERNELS=1` for tests. Not timed (a Python-kernel timing describes no prover anyone runs; the repo
  withdrew such numbers before, doc/fri-parameters.md section 4).
- The node **verifies** in Python (`execnode/shielded.verify_transfer` -> `joinsplit3.verify_transfer`): timed above on
  the very proof the JS prover produced, with every rule on. It returned `ok`.

Parameters read from the code (not lowered): `static/stark/fri.js` NUM_QUERIES = 320, GRIND_BITS = 18,
EXT_CHALLENGES = true; `stark.js` LDE blowup = blowupOf(7) = 16, FRI degree bound 8T so FRI rate 1/2;
`joinsplit3.js` ZK_RANDOMIZERS = 8; depth 48 (`A2.treeDepth`, the live wide pool from ZK_HARDEN_HEIGHT).
`execnode/stark/fri.py` NUM_QUERIES = 320, FRI_BLOWUP = 2, GRIND_BITS = 18, `extf.DEGREE` = 3 (GF(p^3); the doc's
fri-parameters.md still says GF(p^2), the code is GF(p^3)).

## Statement proved by the Stwo prototype, and the gaps

Same relation as `execnode/stark/joinsplit3.py` (1 input note, 2 output notes), with BLAKE2s in place of alghash2.
Every hash is a full, standard BLAKE2s-256 of one 64-byte block (h = IV ^ 0x01010020, t = 64, final-block flag; checked
against the `blake2` crate on every run):

    owner = H([21, nsk (8 words = 256 bits), 0 x 7])
    cm_in = H([22, v_in (2 words), owner (8), rho (2), 0 x 3])
    root  = fold(cm_in, 48 siblings, 48 direction bits),  node(l, r) = H([l (8), r (8)])
    nf    = H([23, nsk (8), rho (2), 0 x 5])
    cm_k  = H([22, v_k (2), o_k (8), r_k (2), 0 x 3]),  k = 1, 2   (o_k, r_k free witness)
    v_in + public_value == v_1 + v_2 + fee   over the integers (64-bit values, 16-bit limbs, carry chain, cs3 == cr3)

Public inputs root, nf, cm_1, cm_2, public_value, fee enter through a LogUp public-input sum that the verifier
recomputes; they, the 8-word `aux` (joinsplit3.bind_aux's unshield destination) and the PCS config are mixed into the
Fiat-Shamir channel before the first commitment.

**Constrained** (and checked: `assert_constraints_on_trace` on every component, LogUp balance on prover and verifier):
the 10 BLAKE2s rounds of all 64 compressions (G functions with add2/add3 carry constraints and xor/rotate via lookups
into a (w, a, b, a^b) table for w in {4, 3, 1}); the fixed initial state; the finalisation h ^ v_lo ^ v_hi; every
message limb range-checked to 16 bits; the wiring of each hash's message to the registers and to the previous row's
digest (owner -> cm_in, each membership level, dir bits boolean); register constancy across rows; integer conservation
with range-checked sum limbs and boolean / ternary carries.

**Negative checks run** (each `bench` run): wrong root, fee rewritten +1, aux rewritten -> verifier refuses; an
inflating witness (v_1 + 1) -> the Stwo prover refuses (`ConstraintsNotSatisfied`).

**Not built / not claimed:**
1. **No zero knowledge** (in `stwo_js`; closed in `stwo_zk`, see the ZK section). Upstream Stwo at this commit has no ZK mode (no trace masking, no salted leaves, no
   randomised composition). Openings at 80 queries reveal evaluations of columns holding nsk, rho and the values. A
   shielded pool cannot ship this; ZK has to be added (masking polynomials / random rows + salted Merkle leaves, the
   equivalent of our Z1) inside Stwo or in a fork, and its cost is NOT in these numbers.
2. Different digests: BLAKE2s, not alghash2, so this is the reroll design of section 4.2, not a drop-in.
3. Unaudited prototype. The BLAKE2s round AIR is adapted from `crates/examples/src/blake` (an example, with upstream
   TODOs); the piece-wise xor/rotation decomposition, the finalisation, the wiring and the conservation gadget are new
   code written for this measurement. An adversarial-prover review has not been done; only honest proofs and the four
   negative cases above were exercised.
4. Value range: values are u64 with exact integer conservation; ours range-checks to [0, 2^61) (C-3). The 2^61 bound
   could be added as one extra limb constraint; it does not change the cost.
5. Note position is not bound (same as ours: nf = H(nsk, rho) only).
6. Padding: rows 53..63 are 11 extra real BLAKE2s compressions of a zero message (power-of-two trace); unwired.

A second variant (`--features byte`: 8-bit xor pieces, a 2^16-row xor8 table) was measured and rejected: trace width
falls to 2,683 columns but the big table makes it 4x slower (1.2 s native) and the proof is only 20 % smaller (1.18 MB).

A 4-thread native run (`--features parallel`, RAYON_NUM_THREADS=4) was **slower** on this loaded host (median 0.73 s vs
0.30 s single-threaded): the trace is too small (under 1 M cells) for rayon to pay off when the cores are contended.

## Side finding in the wallet at the time (since fixed: `airDigest` now uses `b2b32Parts`, static/stark/stark.js)

`static/stark/stark.js` `airDigest` calls `b2b32(...parts)`, spreading every periodic-column value as a separate
argument: at depth 48 that is 25 x 4096 + ~100 = ~102,500 arguments. It works under Node's default stack and on the
desktop Chrome main thread, but overflows a Chrome module Worker (`RangeError: Maximum call stack size exceeded`) and
reproduces in Node with `--stack-size=300`. Phone browsers' main-thread stacks may be smaller than desktop's, so the
wallet's depth-48 prover may fail on a phone *before* the memory question even arises. Passing the array (or hashing
incrementally) instead of spreading it would remove this; it is a wallet change for whoever owns it.

## Security parameters, side by side

Stwo `PcsConfig::security_bits()` = pow_bits + log_blowup x n_queries (the conjectured / ethSTARK-style count).
Applying NADO's own calculator (`soundness.conjectured_bits` / `achieved`, with E = 124 for QM31) to the Stwo configs:

| config (log_blowup / queries / pow) | Stwo security_bits | NADO model conjectured | NADO model provable | proof | native prove (1 thr) | WASM prove (Node, warm) |
|---|---|---|---|---|---|---|
| 1 / 80 / 20 | 100 | 97.7 | 59.9 | 1.48 MB | 0.29 - 0.37 s | 0.51 - 0.63 s |
| 2 / 40 / 20 | 100 | 98.4 | 60.0 | 0.85 MB | 0.40 - 0.44 s | 0.48 - 0.56 s |
| 3 / 27 / 19 | 100 | 98.6 | 59.5 | 0.63 MB | 0.63 - 0.64 s | - |
| 4 / 20 / 20 | 100 | 98.8 | 60.0 | 0.51 MB | 1.13 - 1.27 s | - |
| 1 / 70 / 26 (StarkWare's base-prover shape) | 96 | 94.0 | 60.9 | 1.26 MB | 13.3 s (pow 26 grind, 1 thread) | - |
| 2 / 160 / 20 (conjectured matched to ours) | 340 | 333.7 | 113.4 | 2.76 MB | 0.51 - 0.55 s | 0.91 - 1.25 s |
| **2 / 56 / 20** (STWO_JS_128_HEIGHT, 2026-10-26) | 132 | 129.8 | 75.9 | 1.12 - 1.14 MB | native verify 8 ms (vs 15 ms at 2/160/20) | 0.89 - 1.42 s incl. self-verify (vs 1.70 - 1.75 s) |
| 4 / 80 / 20 | 340 | 335.0 | 101.6 | 1.56 MB | 0.97 - 1.08 s | - |
| **ours** (16x LDE, rate 1/2, 320 q, 18 grind, GF(p^3)) | - | **332.2** | **157.5** | 16.8 MB bin / 36.4 MB JSON | - | 459.8 s (JS) |

The 2/56/20 row is the node config from STWO_JS_128_HEIGHT (dormant on gen 28, live from block 1 on gen 29), measured on
the production crate after the change: `soundness.achieved(2, 1, 124, 56, 20, 18)` for the bits (the same calculator
reproduces the 2/40/20 and 2/160/20 rows above), proof sizes from
tests/test_stwo_js_honest_proof_verifies_and_forged_public_inputs_are_refused.py and the attack harness, the WASM time
from the shipped `static/vendor/stwo_js.wasm` in Node (three runs, this server). 54 queries (Stwo's own "128") would be
125.9 by NADO's model; 56 is the least count at which both say >= 128. Its provable figure (75.9) is the same footing as
the settlement proofs at 2/54/20.

**The OODS term (corrected 2026-10-27).** The columns above are FRI query terms. A Stwo proof also draws one out-of-domain
point over QM31, a Schwartz-Zippel term of ~124 - log_comp = ~113 bits at log_comp 11 that no query count changes. So
2/160/20 was in fact capped near **113** conjectured bits, not 333.7, and 2/56/20 would be too. The 128-bit node config
therefore adds a **16-bit proof-of-work grind before the OODS point** (`NODE128_OODS_POW_BITS`, the same change as
upstream starkware-libs/proving f0bf0195), lifting that term to ~129: its overall figure is ~129 conjectured. Found by
the 2026-10-27 incident survey; pinned by tests/test_stwo_js_honest_proof_verifies_and_forged_public_inputs_are_refused.py
and the attack harness (`oods-nonce+1`, `oods-nonce-zero` refused).

Under NADO's provable (Johnson-bound) model the QM31 challenge field caps Stwo at ~113 provable bits whatever the
query count (commit-phase term), versus our 157.5 from a 192-bit challenge field. On the conjectured count, which is what
StarkWare runs production on (96 bits), 2/160/20 matches ours.

## Reproduce

    S=/tmp/claude-0/-srv-nado-home-nado/b29f85a1-871e-4363-acf6-95b559f11592/scratchpad/stwo0
    # toolchain (into the scratch dir, not ~/.rustup): the nightly Stwo's rust-toolchain.toml names
    RUSTUP_HOME=$S/rustup CARGO_HOME=$S/cargo rustup toolchain install nightly-2026-01-15 --profile minimal -c rust-src -t wasm32-unknown-unknown
    . $S/env.sh                       # PATH to that toolchain, CARGO_BUILD_JOBS=4, RAYON_NUM_THREADS=4
    cd $S/stwo_js
    cargo build --release -j4                                                     # native, 1 thread
    ./target/release/bench 1 1 80 20 1                                            # 1 proof + full constraint/LogUp check
    $S/run_bench.sh | tee $S/results_stwo_bench.log                               # the whole matrix (native + WASM in Node)
    RUSTFLAGS="-C target-cpu=native" cargo build --release -j4 --target-dir target-native   # AVX2 native
    cargo build --release -j4 --features parallel --target-dir target-par         # 4 threads (RAYON_NUM_THREADS=4)
    cargo build --release -j4 --features byte --target-dir target-byte           # 8-bit-piece variant
    RUSTFLAGS="-C target-feature=+simd128" cargo build --release -j4 --lib --target wasm32-unknown-unknown
    cp target/wasm32-unknown-unknown/release/stwo_js.wasm $S/web/
    cd $S/web && node run_node.mjs 5 1 80 20                                      # WASM in Node (no imports, no wasm-bindgen)
    python3 -m http.server 18731 --bind 127.0.0.1 &                               # serves web/ (static -> repo static, read-only)
    python3 browser_bench.py "http://127.0.0.1:18731/stwo.html?auto=1&lb=1&q=80&pow=20&n=5" 240
    python3 browser_bench.py "http://127.0.0.1:18731/ours.html" 1700              # our JS prover in a module Worker

    # ours, Node (from the repo root, read-only; writes only into the scratch dir)
    cd /srv/nado-home/nado
    NADO_PROOF_ROUND2=1 NADO_PROOF_TRACE_LDT=1 NADO_PROOF_FULL_QUERY=1 /usr/bin/time -v \
        node tests/joinsplit3_js_crosscheck.mjs $S/ours/js_proof_d48.json 48
    PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v python3 $S/ours/verify_ours.py $S/ours/js_proof_d48.json

Pinned: Stwo `https://github.com/starkware-libs/stwo` rev `826591c6c371376810ca8213b5812d5daf6d5092` (2026-08-13,
"Update readme to point to proving repo": development has since moved to `starkware-libs/proving`), toolchain
nightly-2026-01-15 (rustc 1.94.0-nightly 86a49fd71), `Cargo.lock` sha256 `ec0074c9...914e`. WASM artifact:
`web/stwo_js.wasm`, 1,423,687 B (379,829 B gzip -9), sha256 `fc0213d1...89f7`.

Raw logs: `results_stwo_bench.log`, `ours/node_d48.log`, `ours/chromium_ours_main.log` (main thread), `ours/chromium_ours.log` (Worker, stack overflow); the JS proof itself is
`ours/js_proof_d48.json`.

## Running it on a phone (operator steps; not done here)

The WASM build has no imports and needs no wasm-bindgen: `web/stwo.html` + `web/stwo_js.wasm` are the whole thing.

1. On a machine on the same LAN as the phone: `cd $S/web && python3 -m http.server 8000 --bind 0.0.0.0`
   (or copy those two files to any static host you control; keep it private, it is a benchmark).
2. On the phone (mid-range Android in Chrome; iPhone in Safari; and desktop Chrome for reference) open
   `http://<lan-ip>:8000/stwo.html`, choose a config, tap **Run 5 times**. Each line prints prove ms, verify ms, proof
   bytes and WASM memory. The first line includes compile tier-up; report it and the median of the rest.
   `stwo.html?auto=1&lb=1&q=80&pow=20&n=5` runs without a tap.
3. Our prover on the same phone: serve the same `web/` directory (it contains a `static` symlink to the repo's
   `static/`, so copy that directory's contents if serving from another machine) and open `ours.html`. Expect several
   minutes at least and a ~4 GB working set on desktop; a tab that reloads or dies is an out-of-memory result, which is
   itself the measurement. Read peak memory from `chrome://inspect` (Android, USB debugging) or Safari Web Inspector
   (iPhone) while it runs.
4. Native on Android (optional): `rustup target add aarch64-linux-android`, build `bench` with the NDK linker
   (`CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=<ndk>/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang`),
   `adb push target/aarch64-linux-android/release/bench /data/local/tmp/ && adb shell /data/local/tmp/bench 5 1 80 20`.
   Not tried here.

## Conclusion (2026-10-10, before the ZK work; see the ZK section for the update)

On this host, for the same join-split statement at depth 48, the Stwo prototype proves in about half a second as WASM
(Node or headless Chromium, single thread) against 266 s (Chromium) / 460 s (Node) for the wallet's current JS prover,
with ~32 MiB of WASM heap against a 3.5 - 4.2 GB working set, a 0.5 - 2.8 MB proof against 16.8 MB binary-equivalent
(36 MB as submitted), and 20 ms native verification against 3.7 s in the node's Python verifier: faster and smaller by
two to three orders of magnitude on time and memory and about one order on size, which is the section 5.0 go criterion on
desktop. Three things keep this from being a "go" by itself: (1) the prototype is **not zero-knowledge**, because
upstream Stwo at the pinned commit has no ZK mode, and a shielded pool cannot ship without it, so the masking cost must be
built and re-measured before the phase is decided; (2) under NADO's own provable-soundness model the QM31 challenge field
caps Stwo at ~113 bits versus our 157.5 (on the conjectured count Stwo matches ours at 2/160/20, still 0.5 s native,
~1 s WASM, 2.8 MB); (3) there is no phone measurement: the operator has to run `web/stwo.html` (and `web/ours.html`) on a
mid-range Android and an iPhone, where the current prover's ~4 GB footprint and the airDigest stack overflow suggest it
may not complete at all. The circuit is an unaudited measurement prototype, not a candidate implementation.

## Phone-class proxy (2026-10-11, measured by the session, not on a phone)

Headless Chromium 154 with Lighthouse's mobile CPU profile (`Emulation.setCPUThrottlingRate` 4x), a 412x915 mobile
viewport and a V8 heap cap (`--js-flags=--max-old-space-size=N`). Script: `web/phone_bench.py <url> <timeout> <rate> <heapMiB>`,
pages served from `web/` on 127.0.0.1 only. A PROXY: x86 slowed down, no ARM, no thermal throttling, no Android memory killer.

| one join-split, depth 48 | heap cap 1 GiB (mid-range tab) | heap cap 2 GiB (high-end tab) |
|---|---|---|
| ours, `static/stark/joinsplit3.js` main thread | **tab crashed after 94 s**, peak RSS 1193 MiB | **tab crashed after 132 s**, peak RSS 2282 MiB |
| Stwo prototype 1/80/20 (non-ZK), WASM | prove 1.29-2.32 s, verify 39-178 ms, peak RSS 196 MiB, 1.42 MB proof | — |
| Stwo prototype 2/160/20 (non-ZK), WASM | prove 2.35-3.64 s, verify 126-352 ms, peak RSS 195 MiB, 2.80 MB proof | — |

Logs: `phoneproxy/ours_1g.log`, `phoneproxy/ours_2g.log`; Stwo numbers printed by the bench (window.RESULT).
Reading: today's wallet cannot produce a shielded proof inside a phone-sized tab; the Stwo prover fits with ~10x margin.


## ZK (2026-10-11): `stwo_zk`, the same statement in zero knowledge

`stwo0/stwo_zk` is a copy of `stwo_js` (same statement, same pinned Stwo `826591c6`, same toolchain, **no Stwo fork**)
whose protocol is made zero-knowledge. `stwo_js` is untouched, so the non-ZK numbers above stay reproducible (they
were re-run in the same session as the ZK ones for the overhead table below).

### Does upstream have a ZK mechanism we could reuse? No, not one that fits

- **Stwo core (pinned `826591c6`, and `starkware-libs/proving` main `1e4425a7`, 2026-10-01, crates/stwo):** no ZK
  mode. No salted/hiding Merkle leaves, no trace randomisation, no masking of the composition or the FRI input
  (grep for zk / blind / mask / salt / hiding: only the Fiat-Shamir `channel_salt`, which is a public transcript
  input, not a hiding salt).
- **StarkWare's privacy prover (`crates/privacy_prove`, `starknet-innovation/proving` branch provably-fast-frontier
  `cb63e35e`; same code on `starkware-libs/proving` main `1e4425a7`):** zero knowledge comes from **recursion plus
  random rows**, not from Stwo. The private Cairo execution is proved by an ordinary (non-ZK) Stwo proof that is never
  published; a *circuit verifier* of that proof is then proved, and only that outer proof is published. Before
  proving the outer circuit, `circuit_common::finalize::add_zk_blinding(context, seed, n)` appends `n` **valid random
  rows** to every circuit component (qm31_ops, eq, triple_xor, m31_to_u32, blake_g_gate), with
  `n = n_queries + NON_QUERY_INFO_LEAK` and `NON_QUERY_INFO_LEAK = 10` ("2 OODS queries, 4 each since their answers are
  in QM31, + 2 M31s extra for safety", `crates/cairo_verifier/src/verify.rs`). The ChaCha20 seed is the inner proof's
  trace root (`privacy_prove/src/lib.rs`: `cairo_proof...commitments.0[1]`). There are no salted leaves, the
  composition is still committed in two halves, and the FRI input is not masked; the random rows are *valid* rows
  (they satisfy the AIR and take part in the lookups), so the per-component claimed sums get random terms. Observations
  (not verified beyond reading): (a) the blinding for range-restricted columns (u32 limbs of blake_g_gate / triple_xor
  rows) has 16 bits of entropy per cell against 31 bits revealed per evaluation, so `n_queries + 10` random rows do not
  give an information-theoretic hiding count for those columns; (b) the composition halves' values at the query points
  are not recomputable by the verifier and are not masked. Reusing this would mean adopting their recursion stack
  (Cairo VM + circuit verifier), which is a different architecture from section 4.2, not a drop-in for our AIR.
- **SNIP-36 (`starknet-innovation/snip-36-prover-backend` `67f00ae0`, 2026-10-08; skill `agentic/skills/snip-36`):**
  **not zero-knowledge.** It runs the plain `stwo-run-and-prove` binary (`crates/snip36-core/src/config.rs`
  `prover_bin()`), `PROVING_UTILS_REV 0a97f45a`, with `sample-input/prover_params.json` = log_blowup 1, **n_queries 3,
  pow_bits 0** (a sample config with ~4 bits of conjectured soundness) and no blinding step; it does not use
  `privacy_prove`. "Without revealing private inputs" means the private inputs stay off-chain on a backend prover (the
  skill says the prover needs ~18 GB RAM and must not run in a browser, and warns that fee estimation would leak the
  private calldata to an RPC node) - the proof itself is an ordinary Stwo proof whose openings carry the witness.

So the construction below is ours, written against Stwo's public prover/verifier pieces (`ComponentProvers::
compute_composition_polynomial`, `CommitmentSchemeProver::prove_values`, `CommitmentSchemeVerifier::verify_values`,
`Components::mask_points / eval_composition_polynomial_at_point`) with a custom `prove_zk` / `verify_js` tail.

### Our current prover's scheme (for a like-for-like comparison)

`execnode/stark/joinsplit3.py` + `stark.py` (`zk=8`, review Z1 of 2026-09-23), mirrored by the wallet's
`static/stark/stark.js` / `joinsplit3.js`:
- **random rows:** `RANDOM_ROWS = 2 * NUM_QUERIES + 16` uniformly random rows after the real ones; every constraint
  that reaches them (register holds, path holds, the conservation row check) is gated by an `ACTIVE` selector;
- **randomizer columns:** `ZK_RANDOMIZERS = next_pow2(max_degree) = 8` unconstrained uniform columns; `stark.prove(zk=8)`
  adds `R(x) = sum_i x^(iT) r_i(x)`, a uniform polynomial covering the composition's whole degree range, to the FRI
  input (`zk_randomizer_add`), committed with the trace before the challenges;
- **salted leaves:** every column leaf is `blake2b(0x03 || value || 32-byte salt)` (`backend.leaf_salted`,
  `merkle.commit_salted`), salts carried in the openings.
Our STARK has no OODS/DEEP step (the verifier recomputes the composition from opened rows) and no LogUp, so it needs
nothing for those; Stwo's DEEP-ALI + LogUp + split composition each needed a piece below.

### The construction implemented (`stwo_zk/src/lib.rs`)

Standard ZK-STARK recipe (Ben-Sasson, Bentov, Horesh, Riabzev, "Scalable, transparent, and post-quantum secure
computational integrity", ePrint 2018/046: hiding commitments + randomised witness + masked low-degree test; Circle
STARKs, Haböck-Levit-Papini, ePrint 2024/278, notes that the optimised variant that interpolates the trace on the trace
domain without randomisation is not ZK), adapted to Stwo's DEEP-ALI, lifting and LogUp:

1. **Random rows, gated constraints.** Each component has R real rows at coset rows [0, R), one blind row at R, then
   uniform M31 rows. JS: R = 53 (was padded with 11 extra real compressions; those are gone); ROUND: R = 530 in one
   component (was 512 + 128 real rows); XOR: R = 324 used table rows. Every constraint and lookup that would reach a
   random row is gated by a preprocessed selector (register holds `s_hold`, conservation / carries / pv-fee-sum range
   checks on row 0 only, lookup multiplicities `s_real`). The only ungated constraints are satisfied by random rows by
   construction: the JS BLAKE2s start state (a public constant column) and ROUND's add-with-carry checks (random ROUND
   rows are built over M31: uniform inputs, pieces and xor outputs, sums = uniform + valid carry x 2^16). The ternary
   check on `cr` was rewritten as two booleans so every gated constraint stays at degree <= 3.
   **Count.** Per column the verifier sees: Q values at the lifted query points; inside each opened composition value,
   the column at `|offsets|` further points per query (the composition is evaluated at the query point at one level
   higher than the lifted trace); and `|offsets|` OODS samples, each a QM31 = 4 M31 functionals. Worst case (offsets
   {-1,0} or {0,1}: registers, digests, the LogUp running sum): **3Q + 8 M31 functionals**, so each component gets
   >= 3Q + 8 free rows (+1 blind, +1 last). Q = 80: JS 2^9, ROUND 2^10, XOR 2^10 (248 needed; 457 / 492 / 698 free).
   Q = 160: all 2^10 (488 needed; 969 / 492 / 698 free). (Upstream's count, `n_queries + 10`, omits the composition
   term because it keeps the split composition; see 3.)
2. **ZK LogUp (own interaction trace).** Stwo's `finalize_logup_in_pairs` forces the fraction columns to 0 and the
   running sum to an arithmetic progression on rows with multiplicity 0, i.e. the whole interaction trace would be a
   function of the witness (Q openings of a 64-row fraction column would solve for all 53 real-row values, each
   1/(z - tuple) with nibble-sized tuples). Replaced by one QM31 column S_j per lookup entry with
   `(S_j * d_j - m_j) * s_acc = 0` (degree 3), and one running sum D with `s_acc * (D - D_prev - sum_j S_j) = 0`,
   `s_last * D = 0`, `s_blind * (D - claimed) = 0`, where s_acc = rows [0, R]. S_j and D are free (uniform) on rows
   after the blind row. Soundness: the chain from D(N-1) = 0 through rows [0, R] forces claimed = the sum of the
   real-row (and blind-row) fractions exactly; random rows never enter it. Cost: one column per entry instead of per
   pair (interaction width 1732 -> 2396 columns).
3. **Composition committed unsplit.** Stwo commits C as two halves; their values at the query points are global
   linear functions of the trace that the verifier cannot recompute (extra, unmasked leakage). C (4 coordinate columns
   of size 2^(L+1)) is committed whole; all trees are lifted to its LDE (`min_lifting_log_size = L + 1 + log_blowup`);
   trace columns are sampled at their lifted mask points around an OODS point w and C at pi(w) = 2w, which is exactly
   Stwo's identity at z = pi(w) (checked by the prover's and the verifier's DEEP-ALI comparison). Every value C reveals
   is then a pointwise function of trace evaluations that 1. already hides (the 3Q term).
4. **FRI mask.** A uniform QM31 column RND of size 2^(L+1), committed with C (before the DEEP/FRI coefficients) and
   sampled at w. Its DEEP quotient is uniform over the whole quotient space conditioned on what is opened of RND, so
   the FRI input is uniform subject to its values at the queried points (which the verifier recomputes from the
   openings): layer roots, fold siblings and the last layer reveal nothing. (Equivalent of our `zk_randomizer_add`;
   here one QM31 column suffices because DEEP already takes a random QM31 combination of every column.)
5. **Blinded claimed sums.** The three per-component claimed LogUp sums are public and, unblinded, witness-dependent
   (the XOR one is a weighted histogram of the witness's nibbles). The blind rows carry a chain of uniform QM31 tuples
   under their own tag (JS emits t1; ROUND consumes t1, emits t2; XOR consumes t2), so the three published sums get
   independent uniform terms +1/d(t1), -1/d(t1)+1/d(t2), -1/d(t2); only their total, fixed by the public inputs, means
   anything. A separate tag means blind tuples can only cancel each other.
6. **Hiding leaves.** 8 unsampled uniform columns at the full lifted size in each of the trace, interaction and
   composition trees: every leaf hash covers 248 fresh random bits (opened leaves reveal theirs, as ours do).

Randomness: ChaCha20 (`rand_chacha 0.3.1`) seeded with 32 bytes from `/dev/urandom` (native) or
`crypto.getRandomValues` via the new `js_seed` export (WASM; `js_prove` returns 0 without a fresh seed and consumes it).

**Not implemented / not claimed:** the 8-bit `byte` variant; a formal proof (below is an argument plus tests); ZK of
the preprocessed tree (public); timing side channels; a constant-time prover; seed handling beyond "fresh per proof";
an adversarial review of the new gating (two malicious-prover cases are tested, see below).

### Evidence (`zktest`, `bench`; logs `zktest_1_80_20.log`, `results_zk_bench.log`)

Soundness, every `bench` run at both configs (unchanged cases + new ones): verifier refuses wrong root, fee +1, aux
(exit) rewritten, public value +1 (LogUp balance); prover refuses the inflating witness v1 + 1 (DEEP-ALI identity
fails); a tampered opened value fails the Merkle root; and two **malicious provers against the new LogUp** are refused
by the verifier (DEEP-ALI failure): `ShiftClaimed` (x moved from JS's claimed sum to ROUND's, total unchanged) and
`ForgeLookup` (a range-check piece not in the xor table committed, interaction computed for the honest piece so the sums
balance). `bench ... check=1` asserts every constraint and the LogUp chain on the full trace, random rows included.

Zero knowledge, config 1/80/20, 100 proofs of witness A (`fixture()`) and 100 of witness B (`fixture_b()`: different
nsk, rho, values, tree position, pv, fee), plus the non-ZK prototype as the **control** (a test that cannot see the
leak in `stwo_js` would prove nothing):

| test | `stwo_zk` | control `stwo_js` |
|---|---|---|
| T1 same witness proved twice | different trace / interaction / composition roots (only the public preprocessed root equal), different claimed sums; the only equal opened values are the public st[0] constants | byte-identical proofs |
| T2 opened register values (nsk, rho, v_in, v1, v2 limbs) equal to the true limb | **0 / 253,856** (A), 0 / 253,440 (B) | **2,368 / 2,368** and 2,528 / 2,528 (every one) |
| T2 fraction of opened JS values < 2^16 (uniform: 3.05e-5) | 2.94e-5 / 2.91e-5 | 0.116 (registers and constant columns open to their value) |
| T3 chi-square vs uniform, 256 bins, z (groups: nsk, rho, values registers, all JS cols, ROUND, interaction, JS OODS coords, claimed sums; 1.2 k - 19 M values each) | all \|z\| <= 3.0 (16 tests) | registers z = 3,300 - 14,000; JS cols 8,500; JS OODS 1,000 |
| T4 A vs B: two-sample chi-square z / Welch t on the mean | all \|z\| <= 2.7, \|t\| <= 1.6 | register means t = -28 to -37 |
| T5 simulation, solved: nsk[0] register of a real proof of A; real rows replaced by B's limb (also by 0 and by a random value) | 248 revealed M31 functionals (Q openings + 2Q inside composition values + 2 QM31 OODS), rank 246, 459 free rows: **solvable; every revealed value reproduced exactly** | (no free rows: the column is the constant) |

What this establishes and what it does not. T5 is the exact statement behind the argument, checked on a real proof:
for this column, the map from the free rows to everything the proof reveals about it has full rank, so for *any*
replacement of the real rows the set of random-row assignments producing the observed values is an affine space of the
same size - the revealed values are identically distributed (uniform) whatever the witness. The construction makes
that true per column by the 3Q + 8 count, and the columns' random rows are independent; RND makes the FRI data a
function of a uniform codeword; the salts make unopened leaves hiding in the random-oracle model; the blind chain makes
the published claimed sums uniform given their total. T1-T4 are empirical: they show no detectable dependence on the
witness in ~10^7 opened values and that the same tests detect the leak instantly in the non-ZK build. **None of this is
a proof of zero knowledge**: there is no written simulator proof, the point bookkeeping for the composition term was
derived from Stwo's lifting code and checked numerically for the opened and OODS points only (the composition-internal
points are derived, not observed), T5 was run for one column type, and the circle-code rank facts rely on the Circle
STARK paper's RS isomorphism. It needs a cryptographer's review before it protects real notes.

### Numbers (same session, same load: 1-minute load 9.7 - 11.8 on 12 vCPU; single core `taskset -c 1`)

| | non-ZK `stwo_js` 1/80/20 | **ZK `stwo_zk` 1/80/20** | non-ZK 2/160/20 | **ZK 2/160/20** |
|---|---|---|---|---|
| trace cells [pre, orig, interaction] | 2.6 k, 574 k, 393 k | 16 k, 1.28 M, 1.81 M | same as left | 23 k, 1.69 M, 2.46 M |
| prove, native 1 thread (5 runs) | 309 - 342 ms (median 342) | **719 - 862 ms (median 862)** | 575 - 632 ms | **1.52 - 1.74 s** |
| prove, WASM in Node (warm, runs 2-5) | 582 - 1,071 ms | **1.41 - 1.75 s** (first 3.6 s) | 943 - 1,079 ms | **2.02 - 2.75 s** (first 5.7 s) |
| prove, headless Chromium 154 (warm) | 0.53 - 0.61 s (yesterday) | **0.92 - 1.73 s** (first 1.83 s) | 0.91 - 1.25 s (yesterday) | **1.70 - 1.82 s** (first 2.51 s) |
| verify, native | 21 - 22 ms | **20 ms** | 33 - 35 ms | **35 - 40 ms** |
| verify, WASM (Node / Chromium) | 33 - 43 ms | 30 - 57 / 25 - 47 ms | 49 - 60 ms | 57 - 66 / 47 - 77 ms |
| proof size | 1.483 MB (Node build 1.417 MB) | **1.50 - 1.52 MB** (varies with query collisions) | 2.76 MB | **2.86 - 2.91 MB** |
| peak memory | native 45 MB RSS; WASM 30 - 32 MiB | **native 115 MB RSS; WASM 87 - 91 MiB; Chromium 216 MiB RSS** | native 56 MB; WASM 43 MiB | **native 188 MB; WASM 150 - 155 MiB; Chromium 285 MiB** |

**ZK overhead:** prove **~2.5x** native at 1/80/20 (median 342 -> 862 ms) and ~2.8x at 2/160/20 (632 ms -> 1.74 s);
~1.5 - 2.5x in WASM; verification unchanged (+0 - 15 %); proof **+1 - 5 %** (more interaction columns, one fewer ROUND
component, salts); memory **~2.5 - 3.5x** (more rows, unsplit composition lifting everything one size up). Where the
time goes (native 1/80/20, median run): witness/random-row generation ~150 ms (ChaCha per cell), commit ~80 ms,
interaction (one inverse per real-row entry) ~185 ms, Stwo prove ~380 ms; none of it is optimised (e.g. a cheaper RNG,
batch inversion, and committing the 2^9-row JS component would cut it).

Against our current wallet prover (459.8 s Node / 266 s Chromium, 4.2 GB, 16.8 MB binary / 36.4 MB JSON, verify 3.7 s),
the ZK Stwo prototype is still **~300x faster in Node, ~150 - 290x in Chromium**, ~25 - 50x smaller in memory (87 MiB
WASM heap), ~11x smaller proof, ~185x faster verification at 1/80/20; at the security-matched 2/160/20: 2.0 - 2.8 s
WASM, 155 MiB, 2.9 MB.

### Reproduce

    S=.../scratchpad/stwo0; . $S/env.sh; cd $S/stwo_zk
    cargo build --release -j4 --features nozk-compare      # bench + zktest (zktest links ../stwo_js as the control)
    ./target/release/bench 1 1 80 20 1                     # one proof + full trace check + all negative cases
    ./target/release/zktest 100 1 80 20                    # T1-T5 (about 4 min single core)
    RUSTFLAGS="-C target-feature=+simd128" cargo build --release -j4 --lib --target wasm32-unknown-unknown
    cp target/wasm32-unknown-unknown/release/stwo_zk.wasm $S/web/
    $S/run_bench_zk.sh | tee $S/results_zk_bench.log       # ZK vs non-ZK, native + Node, both configs
    cd $S/web && python3 -m http.server 18741 --bind 127.0.0.1 &
    python3 browser_bench.py "http://127.0.0.1:18741/stwo.html?auto=1&zk=1&lb=1&q=80&pow=20&n=5" 400

Phone harness: `web/stwo.html` now has a Build selector (non-ZK / zero-knowledge; `?zk=1` selects ZK for `auto` runs,
non-ZK stays the default so earlier URLs mean the same thing) and seeds every ZK proof from `crypto.getRandomValues`;
`web/run_node.mjs` takes the wasm file as a 5th argument. ZK artifact `web/stwo_zk.wasm`: 1,453,869 B (385,973 B gzip -9),
sha256 `d6d8898d871602f3...`, no imports; `stwo_zk/Cargo.lock` sha256 `1160b5ac97e3a9e6...` (Stwo `826591c6`,
rand_chacha 0.3.1, rand_core 0.6.4).

### What blocks adoption

1. **No proof, no review.** The construction is standard in shape but the composition-term count, the gated LogUp and
   the blind chain are ours; it needs a written simulator argument and an outside review before it guards notes.
2. **Stwo has no ZK mode upstream, and StarkWare's own privacy path is recursion through a Cairo verifier circuit**,
   so we would own this protocol tail (`prove_zk` / `verify_js`, ~250 lines) on top of Stwo's public API and re-check
   it on every Stwo upgrade; any upstream change to lifting, mask points or the composition split silently changes the
   counting argument.
3. The circuit is still an unaudited prototype, BLAKE2s not alghash2 (reroll design), and there is still no phone
   measurement (ZK WASM heap 87 - 155 MiB, so memory should not be the obstacle; the operator steps above apply with
   `?zk=1`).

### Phone-class proxy, ZK build (2026-10-11, same method as above: 4x CPU throttle, 1 GiB heap cap, mobile viewport)

| stwo_zk.wasm | prove | verify | proof | peak |
|---|---|---|---|---|
| ZK 1/80/20 | 3.39-8.77 s (median 5.35 s; first call slowest) | 69-217 ms | 1.51 MB | 91 MiB wasm, 218 MiB RSS |
| ZK 2/160/20 | 5.40-6.84 s | 122-220 ms | 2.88 MB | 155 MiB wasm, 282 MiB RSS |

Every proof verified. Against: our wallet prover crashed the tab at both 1 GiB (94 s) and 2 GiB (132 s).

### ZK argument status (2026-10-11, `zkproof/`)

`zkproof/ARGUMENT.md` holds the written argument: the relation, the verifier's full view (field by field), a
simulator in the programmable random-oracle model, and lemmas L0-L5. `zkproof/zkcheck.rs` (the `zkcheck` bin of
`stwo_zk`, `./target/release/zkcheck 1 80 20`) checks each lemma against a real proof, using Stwo's own functions
wherever Stwo defines the object.

**Two real ZK bugs found and fixed.** These supersede items 1 and 4 of "The construction implemented" above.
1. *ROUND carries leaked.* The add-with-carry constraints were not gated, and the random ROUND rows had valid carries.
   So `sum = a + b (+ c) - 2^16 carry` held on every row, and the opened and OODS values exposed evaluations of the
   carry polynomials. Their random part is only 1.6 bits per row, which makes the 64 x 530 real carries
   information-theoretically determined. Practical exploitability was not assessed. The old T5 could not see this
   because it is a relation across columns. **Fix:** the carries are gated by `s_real`. The add3 carry in {0,1,2}
   uses one committed bit per limb (+32 ROUND columns). Random ROUND rows are now all uniform.
2. *The FRI input was not fully masked.* One RND column sampled at w leaves 3 QM31 directions of L_{N-2} unmasked
   (tau_w, and the evaluations at sigma(w) and sigma^3(w)). **Fix:** a second mask RND2 sampled at 2w (+4 columns).
   The masks now cover every direction not fixed by the query values.

zkcheck before the fix (`zkproof/before/zkcheck_1_80_20.log`): L0 FAIL (ROUND), L4 FAIL (3 uncovered directions).
After the fix: **every check passes at both 1/80/20 and 2/160/20** (`zkproof/after/`, 11 proofs per configuration).

| lemma | checked mechanically | result |
|---|---|---|
| L0 free rows are free | every free-row cell (1.9 M / 3.0 M) resampled, all constraints re-asserted | PASS |
| L1 salted leaves | 8 full-size salt columns per tree, last in each leaf, fresh per opened leaf | PASS |
| L2/L3 per column class: rank(free rows) = rank(all rows) | 13 classes; opened, composition-internal and OODS functionals; every opened, OODS and composition value re-derived from the committed columns | PASS; min slack 1/80/20: orig 212, interaction 211; 2/160/20: orig 169, interaction **7** (ROUND D, worst case 4) |
| L3b blinded claimed sums | D(R) = claimed; blind-row increments = +-1/d(t); t -> d(t) bijective | PASS |
| L4 composition + FRI | C_c(2w) recomputed at the 4 conjugates; F from `fri_answers` reproduces `fri_witness`; F in L_{N-2}; masks span (QM31 rank Q'+6) | PASS |
| L5 transcript | exhaustive destructuring of the proof types (a compile error if Stwo adds a field); PoW | PASS |

After the fix: soundness negatives unchanged (`bench ... check=1` at both configs, all 8 cases refused). zktest 100
proofs at 1/80/20: all |z| <= 2.4, |t| <= 1.4, 0 register hits; the control still leaks. Prove time single-core,
interleaved with the pre-fix build under load 6-9: medians 921-1286 ms before vs 977-1412 ms after at 1/80/20, and
1656-3039 ms vs 1674-2506 ms at 2/160/20. The difference is within noise (<~10 %). Proof size +~13 KB.
**`web/stwo_zk.wasm` predates the fix and must be rebuilt before any further phone or browser measurement.**

**Proven by argument:** perfect simulation of everything except the rank event, given true randomness. Total
distance <= eps_rank + O(q 2^lt 2^-248) + 2^-123 + 2^-61.
**Checked mechanically, per transcript:** all of the above, including the Stwo point bookkeeping.
**Assumptions / open:**
- The ROM, with programmable Fiat-Shamir. Blake2s is treated as a random oracle.
- ChaCha20 as a PRG, which makes the guarantee computational.
- **eps_rank is not bounded.** The circle zero bound limits a failure to one lost rank per class. There were no
  failures in 22 x 13 class checks. A probability bound over the challenges is open: Schwartz-Zippel gives only
  ~2^-17.
- Soundness of Stwo's FRI is a separate soundness assumption and is not needed for ZK.
- Timing side channels and seed handling are out of scope.
- An outside review is still required.

**Stwo internals pinned** (ARGUMENT.md section 7; re-check on every upgrade):
- the lifting map and the Merkle index map;
- mask points `w + o g_lc`;
- the composition identity C(2p) = eval at p, with component lifting;
- the DEEP quotient form: conjugate line, consecutive coefficient powers, empty-sample columns excluded, periodicity
  samples;
- the FRI first circle fold with siblings in `fri_witness`;
- leaf hashing order (sorted by size);
- the PoW grind;
- the challenge derivations;
- the proof struct fields.
