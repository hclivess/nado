# Honest-verifier zero knowledge of the `stwo_zk` join-split prover: argument and mechanical checks

> **Provenance.** Written 2026-10-11 in a session scratch directory that was later wiped; restored verbatim from the
> session's record of every write and edit. The scratch sources it cites (`stwo_zk/`, `zkproof/zkcheck.rs`, logs under
> `after/`, `env.sh`) are gone. The ZK construction they prototyped is implemented in `native/stwo_js` and pinned by
> its tests; re-measure against that crate, not against the paths below.

Status (2026-10-11): this is a proof sketch by an engineer, not a refereed proof. Every lemma has a mechanical check
against the real prover (`zkproof/zkcheck.rs`, built as the `zkcheck` bin of `stwo_zk`). Writing the checks found
**two real zero-knowledge bugs** in the first construction; both are fixed in `stwo_zk/src/lib.rs` and the checks pass on
the fixed version (section 9). One step is not proven for all challenges and is only measured: the per-class rank
condition of L2/L3 (section 5, "open").

Sources: Ben-Sasson, Bentov, Horesh, Riabzev, ePrint 2018/046 (the ZK-STARK recipe: hiding commitments, randomised
witness with more randomness than revealed evaluations, masked low-degree test); Haböck, Levit, Papini, ePrint 2024/278
(Circle STARKs: the FFT space, the zero bound for circle polynomials, the DEEP quotient with the conjugate line, the
first circle-to-line FRI fold). Stwo at `826591c6` for everything the verifier actually sees.

## 1. The relation and the public input

Public input `x` = (`root`, `nf`, `cm1`, `cm2`, `pv`, `fee`, `aux`, depth D = 48), all mixed into the channel first.
Witness `wit` = (`nsk`, `v_in`, `rho`, the 48 Merkle siblings and direction bits, `v1`, `o1`, `r1`, `v2`, `o2`, `r2`).
R(x, wit) holds iff `owner = H(21, nsk)`, `cm_in = H(22, v_in, owner, rho)` is a leaf of the depth-48 tree with root
`root`, `nf = H(23, nsk, rho)`, `cm_i = H(22, v_i, o_i, r_i)`, and `v_in + pv = v1 + v2 + fee` over the integers
(64-bit limbs), H = one BLAKE2s compression. `aux` is bound by the transcript only.

The AIR has three components (rows: R real rows at coset rows [0, R), one blind row at R, uniform rows after):

| | JS | ROUND | XOR |
|---|---|---|---|
| real rows R | 53 | 530 | 324 |
| rows 1/80/20 | 2^9 | 2^10 | 2^10 |
| rows 2/160/20 | 2^10 | 2^10 | 2^10 |
| original columns | 805 (32 public: BLAKE2s IV) | 856 (824 before the fix) | 5 |
| interaction columns (M31) | 1272 (S_j) + 4 (D) | 1100 + 4 | 8 + 4 |

Composition log size `lc` = 11 (N = 2^lc = 2048), lifting log size `lt = lc + log_blowup` = 12 / 13. Commitment trees:
T0 preprocessed (22 public selector/table columns), T1 original (+8 salt columns), T2 interaction (+8 salt), T3 =
[C_0..C_3 (composition coordinates), RND (4), RND2 (4), salt (8)], all of log size lc.

## 2. Model

* **Fiat-Shamir in the random-oracle model.** The Blake2s channel (`draw_*`, `mix_*`), the Merkle leaf/node hash and
  the proof-of-work hash are one random oracle H with domain-separated inputs (Stwo's own prefixes/formats). The
  simulator may **program** H at the channel's draw inputs (the standard ZK-in-the-ROM model; e.g. BCS16). The
  distinguisher makes at most q queries to H.
* **Honest-verifier ZK of the non-interactive proof**: there is an efficient S(x) whose output (proof, and S's
  programming of H) is statistically close to a real proof for any witness, against any q-query distinguisher.
* **Randomness.** Statistical closeness below assumes the prover's random cells are truly uniform. The implementation
  draws them from ChaCha20 seeded with 32 fresh OS bytes, so the delivered guarantee is computational (PRG security).

## 3. The verifier's view V (every value it receives)

Counts are from `zkcheck` on real proofs (1/80/20 | 2/160/20).

1. Four tree roots T0..T3 (Blake2s, 32 B each). T0 is public (preprocessed).
2. Three claimed LogUp sums `c_JS, c_ROUND, c_XOR` in QM31 (their sum is fixed by `x` and the LogUp challenges).
3. OODS samples (`sampled_values`), 4,224 QM31 values: for every T0-T2 column, its lifted value at each mask point
   `w + o * g_lc` (o in its mask offsets: {0}, {-1,0} or {0,1}; `w` = the OODS point); for T3, C_c(2w) for c = 0..3,
   RND_c(w), RND2_c(2w). Salt columns: none.
4. Opened leaves (`queried_values`): at each of the Q' distinct query positions (80 | 159), the full lifted row of every
   tree: every column's value **and the 8 salts** (T1-T3), 328,960 | 653,808 M31 values in all; T0 at its own positions.
5. Merkle decommitments of T0-T3: sibling hashes (1,540 | 3,032).
6. FRI: first-layer root, 10 inner-layer roots, the last-layer polynomial (1 coefficient), fold siblings
   (`fri_witness`, 78 + 307 | 157 + 601 QM31) and their Merkle hashes.
7. The proof-of-work nonce.
8. Implicitly, everything the verifier derives: the channel draws (LogUp z, alpha; composition coefficient gamma; w;
   DEEP coefficient alpha_D; FRI fold coefficients; query positions), the DEEP quotient values F(x_q), and the
   composition identity at w.

`zkcheck` destructures `StarkProof` / `CommitmentSchemeProof` / `FriProof` / `FriLayerProof` exhaustively (no `..`), so a
Stwo upgrade that adds a field to the proof fails to compile the check until the field is added to this list (L5).

## 4. Notation and the two Stwo facts everything rests on

* Circle polynomials of log size s live in the FFT space L'_n (n = 2^s) = {f0(x) + y f1(x) : deg f0, f1 < n/2}; Stwo's
  coefficient j is the product of y (bit 0), x (bit 1), pi^(k-1)(x) (bit k), pi(x) = 2x^2 - 1.
  L_{N-2} = {polys of total degree <= N/2 - 1 on the circle} has dimension N - 1 and is spanned by the FFT basis
  elements j < N - 1 (all but the top one).
* **Zero bound** (ePrint 2024/278): a nonzero element of L_n has at most n zeros on the circle (over any extension).
  Consequence used below: evaluations at any t <= n distinct points have rank >= t - 1 on L'_n.
* **Lifting** (Stwo `vcs_lifted`, `pcs`): a column f of log size s is committed/opened as f~(p) = f(pi^(lc-s)(p)) on the
  lifting domain (Merkle index map `((p >> (k+1)) << 1) + (p & 1)`, k = lt - s - log_blowup). Its mask point
  `w + o g_lc` therefore reveals f at `pi^(lc-s)(w) + o g_s`.
* **Composition identity** (`Components::eval_composition_polynomial_at_point`): C(2p) = sum_i alpha^i c_i(trace at
  the lifted masks of p) / Z(p) for every p off the trace coset, so the value of C at a lifting-domain point x = 2 w_x
  is a pointwise function of every column at `pi^(lc-s)(w_x) + o g_s`.

## 5. Lemmas

**L0 (free rows are free).** In every component, every cell of every row after the blind row (except public constant
columns: JS st[0], and D's last row = 0) is sampled uniformly and independently by the prover, and the constraint system
holds for EVERY assignment of those cells. Hence the free-row cells of the whole trace are i.i.d. uniform and independent
of the witness, of the blind tuples and of every other column. *Proof:* every constraint touching a free row is gated by
a preprocessed selector that is 0 there (`s_real`, `s_hold`, `s_first`, `s_acc`, `s_blind`, `s_last`), except the
JS IV constraint, which fixes a public column. *Check:* zkcheck resamples every free-row cell (1.9 M | 3.0 M cells) and
re-runs `assert_constraints_on_trace` on all three components: **PASS** (was FAIL for ROUND before the fix, section 9).

**L1 (hiding leaves; roots simulatable).** Each leaf of T1-T3 is Blake2s over the leaf's lifted row sorted by column
size, ending with 8 salt columns of full lifted size: 8 independent uniform M31 values = 8 log2(2^31 - 1) ~ 248 bits,
fresh per leaf, never sampled at any OODS point and not entering F. In the ROM, the hash of an unopened leaf is a
uniform 256-bit string independent of the leaf's other content unless the distinguisher queried H on that exact input:
probability <= q * 2^lt / 2^248 per tree. Merkle nodes over uniform independent children are uniform, so the root and
all sibling hashes of a tree are distributed identically whatever the unopened leaves contain: the simulator commits to
any rows of its choice with fresh salts. Opened salts reveal nothing (they are fresh uniform). *Check:* tree layout
(8 salt columns, log lc, no samples, in the largest size group so last in the leaf) and the opened salts are distinct
per leaf: **PASS**.

**L2 (witness columns; T1).** Fix a column class (component of log size s, mask offsets O). The view reveals, per
column, exactly these M31-linear functionals of the column's n = 2^s row values:
(a) its lifted opening at each distinct query position: f(pi^(lc-s)(x_q)), Q' values;
(b) inside each opened composition value C(x_q) (an M31 vector, all 4 coordinates opened), the column at the |O| points
`pi^(lc-s)(w_xq) + o g_s`, 2 w_xq = x_q: Q' |O| values (they enter C(x_q) non-linearly, through the constraints; the
lemma covers the joint law of these evaluations, C(x_q) is then a fixed function of them);
(c) the OODS samples f(pi^(lc-s)(w) + o g_s) in QM31: 4 |O| M31 functionals.
Nothing else: C_c(2w) (16 M31) are determined by the trace OODS samples (C at the 4 Galois conjugates of 2w is the
constraint formula on the conjugated samples), the FRI data is a function of F which L4 shows is simulatable, and the
salts and RND columns are independent of the trace.
Write the functionals as a matrix M over the rows; split M = [M_real | M_free]. With the free cells uniform (L0), the
revealed vector M a = M_real a_real + M_free a_free is uniform on M_real a_real + Im(M_free). It is **independent of
the real rows** (witness, blind tuples, D(R) = claimed sum) iff Im(M_free) = Im(M), i.e. **rank(M_free) = rank(M)**;
then it is uniform on Im(M), a set the simulator knows. Different columns are independent (L0). By the zero bound the
real-row restriction can cost at most one rank, and it is zero when the condition holds.
*Count (worst case, no query collisions):* |O| = 1: 2Q + 4; |O| = 2: 3Q + 8; free rows n - R - 1 (D: n - R - 2).

| class (worst case functionals / free rows / slack) | 1/80/20 | 2/160/20 |
|---|---|---|
| JS orig, O = {0} | 164 / 458 / 294 | 324 / 970 / 646 |
| JS orig, O = {-1,0} digests, {0,1} registers | 248 / 458 / 210 | 488 / 970 / 482 |
| ROUND orig, O = {0} | 164 / 493 / 329 | 324 / 493 / 169 |
| XOR orig (mult, blind), O = {0} | 164 / 699 / 535 | 324 / 699 / 375 |

*Check:* for every class zkcheck builds M from the Lagrange vectors of the actual points of the actual proof (each
vector re-verified to reproduce the column's value at that point with Stwo's `eval_at_point`), and computes rank over
all rows and over the free rows; it also re-derives **every** opened value (point map and lifted index map), **every**
OODS value, **every** opened composition value (Stwo's `eval_composition_polynomial_at_point` at the half point) and
the 16 composition OODS coordinates from the committed columns, so the point sets (a)-(c) are measured, not assumed.
Result: **PASS** for every class on every proof checked; measured slack (free rows - rank) in section 8.

**L3 (interaction columns; T2).** Same statement for the LogUp columns, which are our own (`finish_logup`): each S_j
(4 M31 coordinate columns, O = {0}) is constrained only on rows [0, R] (`s_acc`), the running sum D (O = {-1,0}) only
on [0, R] and at row n-1 (= 0, public); free rows (R, n) resp. (R, n-1) are uniform QM31. Worst case:

| class | 1/80/20 | 2/160/20 |
|---|---|---|
| S_j, O = {0} (JS / ROUND / XOR) | 164 / 458, 493, 699 | 324 / 970, 493, 699 |
| D, O = {-1,0} (JS / ROUND / XOR) | 248 / 457, 492, 698 (min slack 209) | 488 / 969, 492, 698 (min slack **4**, ROUND) |

*Check:* as L2: **PASS**.

**L3b (claimed sums).** c_k = D_k(R_k) = U_k + B_k with U_k the real-row LogUp sum and B_JS = 1/d(t1),
B_ROUND = -1/d(t1) + 1/d(t2), B_XOR = -1/d(t2), d(t) = combine(TAG_BLIND, k, t) for uniform t1, t2 in M31^4 that occur
only on the blind rows. t -> d(t) is affine with linear part (alpha^2..alpha^5) acting on M31^4, a bijection onto QM31
iff alpha generates QM31 over M31 (fails with prob <= 2^-62 over the LogUp challenge). So d(t1), d(t2) are independent
uniform, 1/d uniform on QM31* (d = 0 has prob 2^-124 and only aborts), and (c_JS, c_ROUND) is uniform on QM31^2 up to
statistical distance 2^-123, with c_XOR = -c_JS - c_ROUND - public_sum(x, z, alpha). The blind tuples are real-row
content of the blind columns, so by L2 the revealed functionals are independent of them, hence of the claimed sums.
*Check:* D(R_k) = c_k; D(R_k) - D(R_k - 1) equals the formula above with t read from the blind columns (the same t in
the emitting and consuming components); alpha^2..alpha^5 have M31-rank 4: **PASS**.

**L4 (composition and FRI).** (i) The composition tree reveals C_c(x_q) (functions of L2/L3 evaluations, (b)) and
C_c(2w) (functions of OODS samples): nothing new. (ii) The FRI input is
F = sum over (column, sample point z) of alpha_D^k (c_z f~(p) - a y - b) / l_z(p) (Stwo `fri_answers`), and the FRI
transcript (all layer roots, fold siblings, last layer) is a function of F and the public fold coefficients. Write
F = F0 + T(RND) + T'(RND2). Every honest F lies in L_{N-2}. For a mask column set sampled at z (4 M31 columns with
consecutive alpha_D powers, alpha_D generating QM31), T(RND) = c_z (P - interpolant)/l_z with P = sum_c alpha_D^(k+c)
RND_c a bijective image of RND in L'_N(QM31). Conditioned on the revealed RND(z) (which pins P on the whole Galois orbit
z, sigma z, conj z, sigma^3 z, sigma = Frobenius, sigma^2 = Stwo's complex conjugate) and RND(x_q), T(RND) is uniform on
V_z = {G in L_{N-2} : tau_z(G) = 0, G(sigma z) = G(sigma^3 z) = 0, G(x_q) = 0}, where tau_z(G) = [x^{N/2}](l_z G) (the
condition l_z G in L'_N). With masks at z1 = w and z2 = 2w, F is uniform on F0 + V_w + V_2w, and V_w + V_2w = W0 :=
{G in L_{N-2} : G(x_q) = 0} iff the six functionals K_w = (tau_w, ev_sigma w, ev_sigma^3 w), K_2w are independent modulo
the query evaluations. Then F, given the rest of the view, is uniform among elements of L_{N-2} with the verifier-computed
values F(x_q): the simulator samples such an F and runs the FRI prover honestly.
*Checks:* F recomputed with Stwo's `fri_answers` over all 2^lt positions reproduces the proof's first-layer
`fri_witness` (so it is the committed codeword); its FFT coefficients of index >= N-1 vanish (F in L_{N-2});
alpha_D has M31-rank 4; QM31 rank of [E_Q; K_w; K_2w] over a monomial basis of L_{N-2} = Q' + 6 (uncovered directions
0): **PASS**. With the first construction's single mask the same check gives 3 uncovered QM31 directions (FAIL).

**L5 (the rest of the transcript).** The PoW nonce is a deterministic function of the channel digest (Stwo's SIMD
`grind`), so S obtains it by grinding on its own transcript; channel draws are programmed (section 6); T0 is public.
*Check:* exhaustive destructuring of the proof types (compile-time pin), proof verifies: **PASS**.

**Open (stated, not proven).** L2/L3 need rank(M_free) = rank(M) for the challenges of the transcript at hand. zkcheck
verifies it per transcript and found no failure in 22 transcripts x 13 classes (11 per configuration) (section 8); the zero bound limits a
failure to one lost rank per class (so at most one M31-linear functional of the real rows of each column of that class
would be biased), but **no bound on the probability over the challenges is proven**: circle codes are not MDS on
arbitrary point sets, and a Schwartz-Zippel bound over the 4 M31 coordinates of the OODS parameter gives only ~2^-17 per
class, far from the true value but all that is proven. Making this deterministic (e.g. an argument specific to the
standard-position domains these points come from, or a construction in which the randomised part has an MDS structure,
f + v_H r with r of size >= the functional count, which needs columns of size n + k) is the remaining theory item.

## 6. The simulator

S(x, cfg), with H programmable:
1. Sample every channel draw as the verifier would derive it from uniform digests: (z, alpha) for LogUp, gamma, the OODS
   parameter t (w = ((1-t^2)/(1+t^2), 2t/(1+t^2))), alpha_D, the FRI fold coefficients, the query draws.
2. Claimed sums: c_JS, c_ROUND uniform in QM31, c_XOR from the public balance (L3b).
3. A dummy trace: every T1/T2 column with real rows (and the blind row) 0, free rows uniform (D's last row 0, JS st[0]
   the IV). Open it, sample it at the mask points, exactly as the prover does. By L0 + L2/L3 the revealed values have the
   real law (uniform on Im M per column, independent across columns).
4. T3: C_c(x_q) from the composition formula at the half points on the dummy values; C_c(2w) from the formula at the 4
   conjugates of w (so the DEEP-ALI check passes); RND, RND2 fresh uniform columns.
5. F(x_q) by `fri_answers` from those values; F uniform in L_{N-2} with those values (L4); FRI prover on F.
6. Merkle trees T1-T3 over the dummy rows (T3: the opened rows above, any other rows) with fresh salts (L1); T0 honest.
7. PoW: grind on the simulated digest. Program H so that each channel draw returns the value fixed in step 1.

Hybrids: real -> (program the draws; fails only if the distinguisher queried H at a channel input containing a fresh
root: <= q x (#draws) x 2^-248 via L1) -> (unopened leaves replaced: L1) -> (F resampled: identical, L4) -> (trace
replaced by the dummy: identical given the rank condition, L0/L2/L3) -> (claimed sums resampled: 2^-123, L3b) = S.
Total distance <= eps_rank + 3 q 2^lt 2^-248 + q (#draws) 2^-248 + 2^-123 + 2^-61, eps_rank = the open item above.

## 7. Stwo internals the argument depends on (re-check on every Stwo upgrade)

| internal | where (826591c6) | used in | pinned by zkcheck |
|---|---|---|---|
| lifting f~(p) = f(pi^(lc-s)(p)), Merkle index map `((p>>(k+1))<<1)+(p&1)` | `vcs_lifted`, `pcs/utils.rs` | L1, L2(a) | every opened value re-derived both ways |
| mask points `w + o g_lc` from `mask_offsets` | `constraint-framework/component.rs` | L2(c) | every OODS value re-derived |
| composition identity C(2p) = eval at p; components lifted by `max_constraint_log_degree_bound` = log + 1; composition committed by us unsplit at 2w | `air/components.rs`, our `prove_zk` | L2(b), L4(i) | every C(x_q) and C(sigma^k 2w) re-derived |
| DEEP quotient: conjugate line, `c` independent of the value, consecutive alpha_D powers in column order, empty-sample columns excluded, periodicity sample for 2-sample columns | `pcs/quotients.rs`, `constraints.rs` | L4 | F from `fri_answers` matches `fri_witness`; F in L_{N-2} |
| FRI: first layer = circle fold of F on the lt domain, fold step 1, siblings in `fri_witness`, last layer degree 1 | `fri.rs` | L4, L5 | sibling reproduction |
| leaf = Blake2s over the row sorted by column log size | `vcs_lifted/verifier.rs`, `blake2_merkle.rs` | L1 | layout check |
| PoW = deterministic SIMD grind of the digest | `prover/backend/simd/grind.rs` | L5 | - |
| `get_random_point`, `draw_queries` derivations | `circle.rs`, `queries.rs` | section 6 | - |
| proof fields | `proof.rs`, `pcs/quotients.rs`, `fri.rs` | section 3 | exhaustive destructuring (compile error on change) |

## 8. Measured (zkcheck on fresh proofs of the fixture; logs in zkproof/after/)

Rank test over 11 proofs at 1/80/20, 11 proofs at 2/160/20 (the 10-proof loop with the pre-C_c(2w)-check build plus the final run; logs `after/multi_*`, `after/zkcheck_*`). Every class PASSED on every proof (rank over free rows = rank over all rows).

| class | 1/80/20 max rank / min slack | 2/160/20 max rank / min slack |
|---|---|---|
| JS orig offsets [0] | 163 / 295 | 324 / 646 |
| JS orig offsets [-1, 0] | 246 / 212 | 485 / 485 |
| JS orig offsets [0, 1] | 246 / 212 | 485 / 485 |
| ROUND orig offsets [0] | 164 / 329 | 324 / 169 |
| XOR orig offsets [0] | 164 / 535 | 324 / 375 |
| JS interaction offsets [0] | 163 / 295 | 324 / 646 |
| JS interaction offsets [-1, 0] (running sum D) | 246 / 211 | 485 / 484 |
| ROUND interaction offsets [0] | 164 / 329 | 324 / 169 |
| ROUND interaction offsets [-1, 0] (running sum D) | 248 / 244 | 485 / 7 |
| XOR interaction offsets [0] | 164 / 535 | 324 / 375 |
| XOR interaction offsets [-1, 0] (running sum D) | 248 / 450 | 485 / 213 |
| composition tree RND cols [4, 5, 6, 7] | 84 / 1964 | 164 / 1884 |
| composition tree RND cols [8, 9, 10, 11] | 84 / 1964 | 164 / 1884 |

The tight class is the ROUND running sum D at 2/160/20 (worst case slack 4, measured minimum 7): it passes, but a larger query count or more ROUND real rows would need ROUND at 2^11 rows. Before the fix, the same rank test passed for every class (`before/zkcheck_1_80_20.log`) while L0 and L4 failed: the per-column count was never the problem.

## 9. Bugs found by the checks, and the fixes

1. **ROUND carries leaked (L0 FAIL).** The add-with-carry constraints were ungated and random ROUND rows were "built
   over M31 with valid carries" in {0,1,2}, so on every row `sum = a + b (+ c) - 2^16 carry`. The opened and OODS
   values of the four columns (all revealed individually at the same points) then give evaluations of the carry
   polynomial, whose free part has log2(3) bits per row: Q + 4 = 84 M31 evaluations (~2,600 bits) against a free part
   of ~780 bits of entropy, so the 64 x 530 real carries of the BLAKE2s additions were information-theoretically
   determined by the proof (exploitability, a low-density knapsack in dimension ~1,000, not assessed). The per-column
   rank test (old T5) could not see it: it is a cross-column relation. **Fix:** every carry constraint gated by `s_real`;
   the add3 carry in {0,1,2} expressed with one committed bit per limb (`b in {0,1}`, `cl - b in {0,1}`, both degree 3
   under the gate): +32 ROUND columns; random ROUND rows are now all-uniform.
2. **FRI input not fully masked (L4 FAIL).** One mask RND sampled at w only randomises F along V_w, which misses 3 QM31
   directions of L_{N-2} (tau_w and the evaluations at sigma w, sigma^3 w, where the revealed RND(w) pins RND), so
   F0's components along them, functions of the trace (e.g. through C(w) and leading coefficients), were not masked.
   Whether the explicitly opened FRI values exposed them was not measured (the layer roots do, information-
   theoretically). **Fix:** a second mask RND2 sampled at 2w (+4 columns in T3); the six directions are independent
   modulo the query evaluations on every proof checked.
