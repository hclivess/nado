use itertools::{Itertools, chain};
use num_traits::One;
// the BLAKE2s message schedule: csmt_ref's copy (stwo's lives in its prover module, which a stable verifier lacks;
// an honest proof would not verify if the two differed)
use crate::csmt_ref::SIGMA;
use stwo_constraint_framework::{EvalAtRow, RelationEntry};

use super::BlakeElements;
use crate::blake::round::RoundElements;
use crate::blake::{Fu32, N_ROUNDS, STATE_SIZE};

pub fn eval_blake_scheduler_constraints<E: EvalAtRow>(
    eval: &mut E,
    blake_lookup_elements: &BlakeElements,
    round_lookup_elements: &RoundElements,
) {
    let messages: [Fu32<E::F>; STATE_SIZE] = std::array::from_fn(|_| eval_next_u32(eval));
    let states: [[Fu32<E::F>; STATE_SIZE]; N_ROUNDS + 1] =
        std::array::from_fn(|_| std::array::from_fn(|_| eval_next_u32(eval)));
    // NADO (stwo_settle): how many times a consumer (the settlement path component) uses this row's compression. A
    // free multiplicity on a table row is sound — the row IS a proven compression — and lets padding rows publish 0.
    let mult = eval.next_trace_mask();

    // Schedule.
    // pairs (0, 1), (2, 3), ...: array_chunks is nightly-only and this evaluator builds on stable (N_ROUNDS is even)
    for [i, j] in (0..N_ROUNDS).step_by(2).map(|i| [i, i + 1]) {
        // Use triplet in round lookup.
        let [elems_i, elems_j] = [i, j].map(|idx| {
            let input_state = &states[idx];
            let output_state = &states[idx + 1];
            let round_messages = SIGMA[idx].map(|k| messages[k as usize].clone());
            chain![
                input_state.iter().cloned().flat_map(Fu32::into_felts),
                output_state.iter().cloned().flat_map(Fu32::into_felts),
                round_messages.iter().cloned().flat_map(Fu32::into_felts)
            ]
            .collect_vec()
        });
        eval.add_to_relation(RelationEntry::new(round_lookup_elements, E::EF::one(), &elems_i));
        eval.add_to_relation(RelationEntry::new(round_lookup_elements, E::EF::one(), &elems_j));
    }

    let input_state = &states[0];
    let output_state = &states[N_ROUNDS];

    // NADO (stwo_settle): upstream published this entry with multiplicity zero ("TODO: remove"); the settlement path
    // component consumes it, so it carries the row's multiplicity.
    eval.add_to_relation(RelationEntry::new(
        blake_lookup_elements,
        E::EF::from(mult),
        &chain![
            input_state.iter().cloned().flat_map(Fu32::into_felts),
            output_state.iter().cloned().flat_map(Fu32::into_felts),
            messages.iter().cloned().flat_map(Fu32::into_felts)
        ]
        .collect_vec(),
    ));

    eval.finalize_logup_in_pairs();
}

fn eval_next_u32<E: EvalAtRow>(eval: &mut E) -> Fu32<E::F> {
    let l = eval.next_trace_mask();
    let h = eval.next_trace_mask();
    Fu32 { l, h }
}
