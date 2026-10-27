//! NADO gen-29 settlement prototype (Goldilocks retirement G4, doc/stwo/g4-settlement-statement.md).
//!
//! `blake` is upstream Stwo's BLAKE2s example AIR (crates/examples/src/blake at the pinned revision, Apache-2.0, see
//! LICENSE-stwo-apache-2.0), vendored so the settlement circuit proves its compressions with the components G1 measured.
//! NOTE: upstream example code, not StarkWare's audited core; it gets the same forgery tests as everything we add.
#![feature(portable_simd, iter_array_chunks)]
#![allow(clippy::too_many_arguments)]

pub mod blake;
pub mod csmt_ref;
pub mod vm;
pub mod wire;
