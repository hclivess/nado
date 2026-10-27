//! The settlement VM proof's byte format (G4), and the decode a verifier runs on bytes it did not make. The same rules as
//! native/stwo_js/src/wire.rs, whose checking serializer is copied below unchanged:
//!
//! FORMAT: bincode 1 (fixed-int, little-endian) of `(blake_log: u32, sums: Vec<SecureField>, stark: StarkProof)`.
//!
//! DECODE IS STRICT because the bytes are a stranger's:
//!  - the input length is capped (MAX_PROOF_BYTES) before anything is allocated;
//!  - trailing bytes are refused, so one proof has one encoding;
//!  - every u32 in the decoded value must be < P = 2^31 - 1: Stwo's M31 derives Deserialize on its raw u32, and M31
//!    arithmetic assumes canonical inputs, so a non-canonical element is a second encoding at best and wrong
//!    arithmetic at worst. blake_log and the PcsConfig fields are u32s too, all small and checked by verify_vm.

use serde::ser::{self, Serialize};
use stwo::core::fields::qm31::SecureField;
use stwo::core::proof::StarkProof;
use stwo::core::vcs_lifted::blake2_merkle::Blake2sMerkleHasher;

use crate::blake::vm_air::VmProof;

/// 2^31 - 1, the M31 modulus.
const P: u32 = (1 << 31) - 1;
/// Refuse anything bigger before decoding: an honest proof is ~1.1 MB at the node config.
pub const MAX_PROOF_BYTES: usize = 16 << 20;

pub fn encode(proof: &VmProof) -> Vec<u8> {
    bincode::serialize(&(&proof.blake_log, &proof.sums, &proof.stark)).expect("serialize")
}

#[derive(Debug)]
pub enum DecodeError {
    TooLarge,
    Malformed(String),
    NonCanonical,
}

pub fn decode(bytes: &[u8]) -> Result<VmProof, DecodeError> {
    use bincode::Options;
    if bytes.len() > MAX_PROOF_BYTES {
        return Err(DecodeError::TooLarge);
    }
    let (blake_log, sums, stark): (u32, Vec<SecureField>, StarkProof<Blake2sMerkleHasher>) = bincode::DefaultOptions::new()
        .with_fixint_encoding()
        .with_little_endian()
        .with_limit(bytes.len() as u64)
        .reject_trailing_bytes()
        .deserialize(bytes)
        .map_err(|e| DecodeError::Malformed(format!("{e}")))?;
    let mut chk = Canon { ok: true };
    (&sums, &stark).serialize(&mut chk).map_err(|e| DecodeError::Malformed(e.0))?;
    if !chk.ok {
        return Err(DecodeError::NonCanonical);
    }
    // THE FRI LAST LAYER'S SIZE FIELD must equal log2 of its coefficient count: Stwo deserializes it unchecked and the
    // transcript does not cover it (native/stwo_js/src/wire.rs last_layer_size). This format has no history, so anything
    // but the canonical field is refused: one encoding per proof.
    let poly = &stark.0.fri_proof.last_layer_poly;
    let n = { let s: &[SecureField] = poly; s.len() };
    let enc = bincode::serialize(poly).map_err(|e| DecodeError::Malformed(format!("{e}")))?;
    let field = u32::from_le_bytes(enc[enc.len() - 4..].try_into().unwrap());
    if !n.is_power_of_two() || field != n.ilog2() {
        return Err(DecodeError::NonCanonical);
    }
    Ok(VmProof { blake_log, sums, stark })
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
