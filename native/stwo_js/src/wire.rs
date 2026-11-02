//! The proof's byte format, and the decode a node runs on bytes it did not make.
//!
//! FORMAT: bincode 1 (fixed-int, little-endian) of the pair `(claimed: Vec<SecureField>, stark: StarkProof)`, i.e.
//! the prototype's two serialized pieces (`bincode::serialize(&proof.stark)` and the three claimed LogUp sums)
//! concatenated, claimed first. Nothing in either piece changes. A proof at a config with grinds is followed by their
//! 8-byte little-endian nonces in transcript order (nonces_of): NODE_CFG_128 by its OODS nonce; NODE_CFG_128G by its
//! interaction, composition and OODS nonces; a proof at any other config by nothing — so the live 340-bit format is
//! byte-identical to what it always was.
//!
//! DECODE IS STRICTER THAN THE PROTOTYPE, on purpose, because a node decodes attacker bytes:
//!  - trailing bytes are refused, so one proof has one encoding (a txid over the proof bytes is not malleable);
//!  - every u32 in the decoded value must be < P = 2^31 - 1. Stwo's M31 derives Deserialize on its raw u32, so
//!    bincode accepts 0x8000_0005 as a "field element", and M31 addition (`partial_reduce(a + b)`) assumes canonical
//!    inputs: a non-canonical element is a second encoding of a value at best and wrong arithmetic at worst. The only
//!    other u32s in a StarkProof are the PcsConfig fields, all small and checked against the pinned config anyway.
//!  - the input length is capped (MAX_PROOF_BYTES) before anything is allocated.

use serde::ser::{self, Serialize};
use stwo::core::fields::qm31::SecureField;
use stwo::core::poly::line::LinePoly;
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::Blake2sMerkleHasher;

use crate::JsProof;

/// 2^31 - 1, the M31 modulus.
const P: u32 = (1 << 31) - 1;
/// Refuse anything bigger before decoding: an honest proof is ~1.5 MB at 1/80/20 and ~2.9 MB at 2/160/20.
pub const MAX_PROOF_BYTES: usize = 16 << 20;

pub fn encode(proof: &JsProof) -> Vec<u8> {
    let mut b = bincode::serialize(&(&proof.claimed, &proof.stark)).expect("serialize");
    for n in nonces_of(proof.stark.config, proof) {
        b.extend_from_slice(&n.to_le_bytes());
    }
    b
}

/// The grind nonces a proof at `cfg` carries after the pair, in transcript order: interaction, composition (only a
/// config with those grinds, NODE_CFG_128G), then OODS (a config with an OODS grind).
fn nonces_of(cfg: stwo::core::pcs::PcsConfig, p: &JsProof) -> Vec<u64> {
    let mut v = vec![];
    if crate::interaction_pow_bits(cfg) > 0 {
        v.push(p.interaction_nonce);
    }
    if crate::composition_pow_bits(cfg) > 0 {
        v.push(p.composition_nonce);
    }
    if crate::oods_pow_bits(cfg) > 0 {
        v.push(p.oods_nonce);
    }
    v
}

#[derive(Debug)]
pub enum DecodeError {
    TooLarge,
    Malformed(String),
    NonCanonical,
}

pub fn decode(bytes: &[u8]) -> Result<JsProof, DecodeError> {
    use bincode::Options;
    if bytes.len() > MAX_PROOF_BYTES {
        return Err(DecodeError::TooLarge);
    }
    // The pair, then EXACTLY the bytes its config calls for: none, or the 8-byte OODS nonce. Anything else is refused,
    // so one proof still has one encoding.
    let mut rest: &[u8] = bytes;
    let (claimed, stark): (Vec<SecureField>, StarkProof<Blake2sMerkleHasher>) = bincode::DefaultOptions::new()
        .with_fixint_encoding()
        .with_little_endian()
        .with_limit(bytes.len() as u64)
        .allow_trailing_bytes()
        .deserialize_from(&mut rest)
        .map_err(|e| DecodeError::Malformed(format!("{e}")))?;
    // exactly the nonces the config calls for, 8 bytes each (nonces_of): anything else is refused
    let cfg = stark.config;
    let (ib, kb, ob) = (crate::interaction_pow_bits(cfg) > 0, crate::composition_pow_bits(cfg) > 0, crate::oods_pow_bits(cfg) > 0);
    let want = 8 * (ib as usize + kb as usize + ob as usize);
    if rest.len() != want {
        return Err(DecodeError::Malformed(format!("expected {want} bytes of grind nonces, got {} trailing bytes", rest.len())));
    }
    let mut it = rest.chunks_exact(8).map(|c| u64::from_le_bytes(c.try_into().unwrap()));
    let interaction_nonce = if ib { it.next().unwrap() } else { 0 };
    let composition_nonce = if kb { it.next().unwrap() } else { 0 };
    let oods_nonce = if ob { it.next().unwrap() } else { 0 };
    let mut chk = Canon { ok: true };
    (&claimed, &stark).serialize(&mut chk).map_err(|e| DecodeError::Malformed(e.0))?;
    if !chk.ok {
        return Err(DecodeError::NonCanonical);
    }
    let mut stark = stark;
    // a config new with NODE_CFG_128G has no history of the lenient field: there it is canonical or refused (one encoding)
    last_layer_size(&mut stark, !ib)?;
    Ok(JsProof { claimed, stark, oods_nonce, interaction_nonce, composition_nonce, dbg: None })
}

/// THE FRI LAST LAYER'S SIZE FIELD (2026-10-27): ONE ENCODING PER PROOF. Stwo's LinePoly stores `log_size` beside its
/// coefficients and derives Deserialize, so the field arrives unchecked, and the transcript mixes only the coefficients.
/// The verifier reads the field as `1 << log_size` (a shift masked to 6 bits on a 64-bit node) for the degree bound and
/// as the number of doublings before its fold. So:
///  * coefficient count a power of two n, field congruent to log2(n) mod 64: the verifier already treats it exactly as the
///    canonical proof (same masked degree, the fold uses the same first log2(n) doublings). With `rewrite` the field is
///    set to log2(n): the same verdict, and the work is the canonical proof's;
///  * anything else was refused in every case (the degree bound, an earlier FRI check, or the fold's length assertion, a
///    panic nado_stwo_js_verify turns into a refusal), and is refused here.
/// INVARIANT: this must never refuse what the verifier would accept, or nodes that update and nodes that have not disagree
/// on a pool spend, a fork of the exec root. The two bullets are the whole case split; tests/test_stwo_js_honest_proof_
/// verifies_and_forged_public_inputs_are_refused.py drives both against the verifier.
pub fn last_layer_size(stark: &mut StarkProof<Blake2sMerkleHasher>, rewrite: bool) -> Result<(), DecodeError> {
    let poly = &stark.0.fri_proof.last_layer_poly;
    let n = poly.len_coeffs();
    let enc = bincode::serialize(poly).map_err(|e| DecodeError::Malformed(format!("{e}")))?;
    let field = u32::from_le_bytes(enc[enc.len() - 4..].try_into().unwrap());
    if !n.is_power_of_two() {
        return Err(DecodeError::NonCanonical);
    }
    let lg = n.ilog2();
    if field == lg {
        return Ok(());
    }
    if rewrite && field % 64 == lg {
        stark.0.fri_proof.last_layer_poly = LinePoly::new(poly.to_vec());
        return Ok(());
    }
    Err(DecodeError::NonCanonical)
}

/// the coefficient count of a LinePoly (its slice; `len()` reads the size field this module distrusts)
trait CoeffCount {
    fn len_coeffs(&self) -> usize;
}
impl CoeffCount for LinePoly {
    fn len_coeffs(&self) -> usize {
        let s: &[SecureField] = self;
        s.len()
    }
}

/// A serializer that writes nothing and records whether every u32 it is shown is a canonical M31 (< P).
struct Canon {
    ok: bool,
}
#[derive(Debug)]
struct CanonErr(String);
impl std::fmt::Display for CanonErr {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for CanonErr {}
impl ser::Error for CanonErr {
    fn custom<T: std::fmt::Display>(msg: T) -> Self {
        CanonErr(msg.to_string())
    }
}

type R = Result<(), CanonErr>;

macro_rules! ignore {
    ($($f:ident: $t:ty),*) => { $(fn $f(self, _v: $t) -> R { Ok(()) })* };
}

impl<'a> ser::Serializer for &'a mut Canon {
    type Ok = ();
    type Error = CanonErr;
    type SerializeSeq = Self;
    type SerializeTuple = Self;
    type SerializeTupleStruct = Self;
    type SerializeTupleVariant = Self;
    type SerializeMap = Self;
    type SerializeStruct = Self;
    type SerializeStructVariant = Self;

    fn serialize_u32(self, v: u32) -> R {
        if v >= P {
            self.ok = false;
        }
        Ok(())
    }
    ignore!(serialize_bool: bool, serialize_i8: i8, serialize_i16: i16, serialize_i32: i32, serialize_i64: i64,
            serialize_u8: u8, serialize_u16: u16, serialize_u64: u64, serialize_f32: f32, serialize_f64: f64,
            serialize_char: char, serialize_str: &str, serialize_bytes: &[u8]);
    fn serialize_none(self) -> R {
        Ok(())
    }
    fn serialize_some<T: ?Sized + Serialize>(self, v: &T) -> R {
        v.serialize(self)
    }
    fn serialize_unit(self) -> R {
        Ok(())
    }
    fn serialize_unit_struct(self, _: &'static str) -> R {
        Ok(())
    }
    fn serialize_unit_variant(self, _: &'static str, _: u32, _: &'static str) -> R {
        Ok(())
    }
    fn serialize_newtype_struct<T: ?Sized + Serialize>(self, _: &'static str, v: &T) -> R {
        v.serialize(self)
    }
    fn serialize_newtype_variant<T: ?Sized + Serialize>(self, _: &'static str, _: u32, _: &'static str, v: &T) -> R {
        v.serialize(self)
    }
    fn serialize_seq(self, _: Option<usize>) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_tuple(self, _: usize) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_tuple_struct(self, _: &'static str, _: usize) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_tuple_variant(self, _: &'static str, _: u32, _: &'static str, _: usize) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_map(self, _: Option<usize>) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_struct(self, _: &'static str, _: usize) -> Result<Self, CanonErr> {
        Ok(self)
    }
    fn serialize_struct_variant(self, _: &'static str, _: u32, _: &'static str, _: usize) -> Result<Self, CanonErr> {
        Ok(self)
    }
}

macro_rules! compound {
    ($tr:ident, $f:ident) => {
        impl<'a> ser::$tr for &'a mut Canon {
            type Ok = ();
            type Error = CanonErr;
            fn $f<T: ?Sized + Serialize>(&mut self, v: &T) -> R {
                v.serialize(&mut **self)
            }
            fn end(self) -> R {
                Ok(())
            }
        }
    };
}
compound!(SerializeSeq, serialize_element);
compound!(SerializeTuple, serialize_element);
compound!(SerializeTupleStruct, serialize_field);
compound!(SerializeTupleVariant, serialize_field);

impl<'a> ser::SerializeMap for &'a mut Canon {
    type Ok = ();
    type Error = CanonErr;
    fn serialize_key<T: ?Sized + Serialize>(&mut self, k: &T) -> R {
        k.serialize(&mut **self)
    }
    fn serialize_value<T: ?Sized + Serialize>(&mut self, v: &T) -> R {
        v.serialize(&mut **self)
    }
    fn end(self) -> R {
        Ok(())
    }
}
impl<'a> ser::SerializeStruct for &'a mut Canon {
    type Ok = ();
    type Error = CanonErr;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, _: &'static str, v: &T) -> R {
        v.serialize(&mut **self)
    }
    fn end(self) -> R {
        Ok(())
    }
}
impl<'a> ser::SerializeStructVariant for &'a mut Canon {
    type Ok = ();
    type Error = CanonErr;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, _: &'static str, v: &T) -> R {
        v.serialize(&mut **self)
    }
    fn end(self) -> R {
        Ok(())
    }
}
