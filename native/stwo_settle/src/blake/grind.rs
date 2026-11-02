//! THE STARK TAIL OF THE SETTLEMENT VM PROOF, WITH A GRIND BEFORE EVERY CHALLENGE THE PROVER COULD RETRY FOR
//! (zk audit 2026-11-02). Upstream's `prove` / `verify` (the pinned rev's prover/mod.rs prove_ex, core/verifier.rs
//! verify_ex, with include_all_preprocessed_columns = false) grind only before the FRI queries. A prover can re-commit
//! a trace and draw again for any challenge that comes straight after a commitment, so each such draw is worth only its
//! own error term, not the 128 bits the query phase gets:
//!
//!   * the LogUp elements (vm_air: after `mix_u32s(tab_mult)`): error ~ N_fractions / |QM31|, about 2^-100 for a span's
//!     2^20+ lookups. INTERACTION_POW_BITS before them (vm_air prove_vm / verify_vm, which own that part of the
//!     transcript);
//!   * the composition coefficient (here): error ~ N_constraints / |QM31|, about 2^-113. COMPOSITION_POW_BITS;
//!   * the OODS point (here): error ~ 2^(composition log degree) / |QM31|, about 2^-102 at a 2^20-row trace.
//!     OODS_POW_BITS, as upstream's `proving` repo added before its OODS draw (f0bf0195) and stwo_js does (lib.rs).
//!
//! Not ground: the DEEP batching coefficient, drawn inside Stwo's PCS (verify_values / prove_values) after the sampled
//! values are mixed; its term, ~ log2(sampled values) below 124, about 114, is the proof's conjectured floor
//! (doc/stwo/g4-settlement-statement.md 3b). Grinding it means carrying a fork of the PCS.
//!
//! Each grind is checked, then mixed, at the same point of the transcript on both sides: the prover's order exactly.
//! INVARIANT: prove_grinding and verify_grinding are one protocol; change the order in one and every honest proof fails.
//! CHANGING ANY OF THESE IS A PROOF-FORMAT AND CONSENSUS CHANGE (the settlement verifier is dormant until
//! protocol.STWO_SETTLE_HEIGHT; after it, a change needs its own gate).

use stwo::core::air::{Component, Components};
use stwo::core::channel::{Blake2sChannel, Channel};
use stwo::core::circle::CirclePoint;
use stwo::core::fields::qm31::{SECURE_EXTENSION_DEGREE, SecureField};
use stwo::core::pcs::CommitmentSchemeVerifier;
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::{Blake2sMerkleChannel, Blake2sMerkleHasher};
use stwo::core::verifier::{COMPOSITION_LOG_SPLIT, PREPROCESSED_TRACE_IDX, VerificationError};
#[cfg(feature = "prover")]
use stwo::core::proof_of_work::GrindOps;
#[cfg(feature = "prover")]
use stwo::prover::backend::simd::SimdBackend;
#[cfg(feature = "prover")]
use stwo::prover::{CommitmentSchemeProver, ComponentProver, ComponentProvers};

/// Before the LogUp elements are drawn (vm_air). 124 - ~20 (log2 of a large span's lookup fractions) + 24 >= 128.
pub const INTERACTION_POW_BITS: u32 = 24;
/// Before the composition coefficient. 124 - ~11 (log2 of the constraint count) + 16 >= 128.
pub const COMPOSITION_POW_BITS: u32 = 16;
/// Before the OODS point. 124 - ~21 (the composition's log degree at the largest trace) + 24 >= 128.
pub const OODS_POW_BITS: u32 = 24;

/// The grinds' nonces, in transcript order after the interaction one (which vm_air handles).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TailNonces {
    pub composition: u64,
    pub oods: u64,
}

/// The split composition's log degree bound: the verifier's max_log_degree_bound at min_lifting_log_size 0 (the node
/// config's; any other is refused by `verify_grinding`, and `prove_grinding` builds only at it).
fn max_log_degree_bound(lc: u32) -> u32 {
    lc - COMPOSITION_LOG_SPLIT
}

/// The composition's value at the OODS point from its sampled left/right coordinate columns (upstream's
/// StarkProof::extract_composition_oods_eval, which is crate-private there; copied unchanged).
fn composition_oods_eval(proof: &StarkProof<Blake2sMerkleHasher>, p: CirclePoint<SecureField>, mld: u32) -> Option<SecureField> {
    let last = proof.sampled_values.last()?;
    let ev: [SecureField; 2 * SECURE_EXTENSION_DEGREE] =
        last.iter().map(|c| if c.len() == 1 { Some(c[0]) } else { None }).collect::<Option<Vec<_>>>()?.try_into().ok()?;
    let (l, r) = ev.split_at(SECURE_EXTENSION_DEGREE);
    let left = SecureField::from_partial_evals(l.try_into().ok()?);
    let right = SecureField::from_partial_evals(r.try_into().ok()?);
    Some(left + p.repeated_double(mld - 1).x * right)
}

/// upstream prove_ex (include_all_preprocessed_columns = false), with the composition and OODS grinds.
#[cfg(feature = "prover")]
pub fn prove_grinding(
    components: &[&dyn ComponentProver<SimdBackend>],
    channel: &mut Blake2sChannel,
    mut cs: CommitmentSchemeProver<'_, SimdBackend, Blake2sMerkleChannel>,
) -> Result<(StarkProof<Blake2sMerkleHasher>, TailNonces), String> {
    if cs.config.min_lifting_log_size != 0 {
        return Err("prove_grinding builds at min_lifting_log_size 0 only".into());
    }
    let n_pre = cs.trees[PREPROCESSED_TRACE_IDX].polynomials.len();
    let cps = ComponentProvers { components: components.to_vec(), n_preprocessed_columns: n_pre };
    let composition = SimdBackend::grind(channel, COMPOSITION_POW_BITS);
    channel.mix_u64(composition);
    let random_coeff = channel.draw_secure_felt();
    let comp = {
        let trace = cs.trace();
        cps.compute_composition_polynomial(random_coeff, &trace, cs.twiddles, cs.config.fri_config.log_blowup_factor)
    };
    let mld = max_log_degree_bound(cps.components().composition_log_degree_bound());
    let mut tb = cs.tree_builder();
    let (left, right) = comp.split_at_mid();
    tb.extend_polys(left.into_coordinate_polys());
    tb.extend_polys(right.into_coordinate_polys());
    tb.commit(channel);
    let oods = SimdBackend::grind(channel, OODS_POW_BITS);
    channel.mix_u64(oods);
    let oods_point = CirclePoint::<SecureField>::get_random_point(channel);
    let mut sp = cps.components().mask_points(oods_point, mld, false);
    sp.push(vec![vec![oods_point]; 2 * SECURE_EXTENSION_DEGREE]);
    let proof = StarkProof(cs.prove_values(sp, channel).proof);
    // the sanity check upstream runs: a witness that breaks a constraint fails here, not at a verifier
    let got = composition_oods_eval(&proof, oods_point, mld).ok_or("unexpected sampled_values structure")?;
    if got != cps.components().eval_composition_polynomial_at_point(oods_point, &proof.sampled_values, random_coeff, mld) {
        return Err("ConstraintsNotSatisfied".into());
    }
    Ok((proof, TailNonces { composition, oods }))
}

/// upstream verify_ex (include_all_preprocessed_columns = false), with the composition and OODS grinds. The caller has
/// committed every tree but the composition's (the last commitment); `commitments.len()` is the caller's to check.
pub fn verify_grinding(
    components: &[&dyn Component],
    channel: &mut Blake2sChannel,
    cs: &mut CommitmentSchemeVerifier<Blake2sMerkleChannel>,
    proof: StarkProof<Blake2sMerkleHasher>,
    nonces: TailNonces,
) -> Result<(), VerificationError> {
    if cs.config.min_lifting_log_size != 0 {
        return Err(VerificationError::InvalidStructure("min_lifting_log_size must be 0".into()));
    }
    let n_pre = cs.trees[PREPROCESSED_TRACE_IDX].column_log_sizes.len();
    let comps = Components { components: components.to_vec(), n_preprocessed_columns: n_pre };
    let mld = max_log_degree_bound(comps.composition_log_degree_bound());
    if !channel.verify_pow_nonce(COMPOSITION_POW_BITS, nonces.composition) {
        return Err(VerificationError::ProofOfWork);
    }
    channel.mix_u64(nonces.composition);
    let random_coeff = channel.draw_secure_felt();
    let last = *proof.commitments.last().ok_or(VerificationError::InvalidStructure("no commitments".into()))?;
    cs.commit(last, &[mld; 2 * SECURE_EXTENSION_DEGREE], channel);
    if !channel.verify_pow_nonce(OODS_POW_BITS, nonces.oods) {
        return Err(VerificationError::ProofOfWork);
    }
    channel.mix_u64(nonces.oods);
    let oods_point = CirclePoint::<SecureField>::get_random_point(channel);
    let mut sp = comps.mask_points(oods_point, mld, false);
    sp.push(vec![vec![oods_point]; 2 * SECURE_EXTENSION_DEGREE]);
    let got = composition_oods_eval(&proof, oods_point, mld)
        .ok_or(VerificationError::InvalidStructure("Unexpected sampled_values structure".into()))?;
    if got != comps.eval_composition_polynomial_at_point(oods_point, &proof.sampled_values, random_coeff, mld) {
        return Err(VerificationError::OodsNotMatching);
    }
    cs.verify_values(sp, proof.0, channel)
}
