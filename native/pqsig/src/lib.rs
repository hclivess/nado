//! NADO user-selectable post-quantum signature schemes over ONE C ABI (doc/signature-schemes.md).
//!
//! An account picks its scheme; ML-DSA-44 stays the default and keeps its own crate (native/mldsa44, untouched, so the
//! scheme every existing account signs with is never rebuilt by this one). This crate carries the others:
//!
//!   id 1  ML-DSA-65          FIPS 204, KeyGen/Sign/Verify _internal (no ctx) — the convention ML-DSA-44 signs in
//!   id 2  ML-DSA-87          FIPS 204, same
//!   id 3  SLH-DSA-SHA2-128s  FIPS 205, slh_keygen_internal / slh_sign_internal / slh_verify_internal (no ctx)
//!   id 4  FN-DSA-512         pornin's fn-dsa (the FN-DSA DRAFT: DOMAIN_NONE, HASH_ID_RAW). Built and tested, but the
//!                            chain refuses it until FIPS 206 is final (protocol.SIG_FNDSA512_HEIGHT) — its encoding
//!                            may still change, and no user should hold a key in a pre-standard format.
//!
//! THE KEY MODEL IS ONE 32-BYTE SEED FOR EVERY SCHEME (signatures.py), so a recovery phrase restores any account:
//!   ML-DSA      the seed IS FIPS 204's xi.
//!   SLH-DSA     (SK.seed, SK.prf, PK.seed) = SHAKE256("NADO/sig/slh-dsa-sha2-128s/keygen" || seed)[0..48].
//!   FN-DSA      the keygen RNG is SHAKE256("NADO/sig/fn-dsa-512/keygen" || seed).
//! These expansions are CONSENSUS-ADJACENT (an address is a hash of the public key): the browser runs the identical
//! derivation and tests/test_every_signature_scheme_derives_one_key_in_every_stack pins the public keys across stacks.
//!
//! Signing is hedged with the caller's 32-byte `rnd` (SLH-DSA: its first 16 bytes are opt_rand; FN-DSA: it seeds the
//! sampler's SHAKE256 RNG), so signatures are not byte-reproducible — consensus checks verify() == true, never bytes.
//!
//! Every entry returns 0 on success. verify returns 0 iff valid; ANY malformed input is an invalid signature, never a
//! panic across the FFI boundary (pk/sig lengths are passed and checked here, not trusted from Python).

use fn_dsa::{
    signature_size, sign_key_size, vrfy_key_size, CryptoRng, KeyPairGenerator, KeyPairGeneratorStandard, RngCore,
    RngError, SigningKey as _, SigningKeyStandard, VerifyingKey as _, VerifyingKeyStandard, DOMAIN_NONE,
    FN_DSA_LOGN_512, HASH_ID_RAW, SHAKE256,
};
use ml_dsa::{
    EncodedVerifyingKey, ExpandedSigningKey, ExpandedSigningKeyBytes, Keypair, MlDsa65, MlDsa87, MlDsaParams,
    Signature as MlSig, SigningKey as MlSk, VerifyingKey as MlVk, B32,
};
use slh_dsa::signature::Keypair as _;
use slh_dsa::{Sha2_128s, Signature as SlhSig, SigningKey as SlhSk, VerifyingKey as SlhVk};

pub const ALG_MLDSA65: u32 = 1;
pub const ALG_MLDSA87: u32 = 2;
pub const ALG_SLHDSA128S: u32 = 3;
pub const ALG_FNDSA512: u32 = 4;

const SEED: usize = 32;
const RND: usize = 32;
const SLH_N: usize = 16;
const DST_SLH: &[u8] = b"NADO/sig/slh-dsa-sha2-128s/keygen";
const DST_FN: &[u8] = b"NADO/sig/fn-dsa-512/keygen";

/// (public key, secret key, signature) byte lengths of a scheme, or None for an unknown id.
pub fn sizes(alg: u32) -> Option<(usize, usize, usize)> {
    match alg {
        ALG_MLDSA65 => Some((1952, 4032, 3309)),
        ALG_MLDSA87 => Some((2592, 4896, 4627)),
        ALG_SLHDSA128S => Some((32, 64, 7856)),
        ALG_FNDSA512 => Some((
            vrfy_key_size(FN_DSA_LOGN_512),
            sign_key_size(FN_DSA_LOGN_512),
            signature_size(FN_DSA_LOGN_512),
        )),
        _ => None,
    }
}

/// SHAKE256 as a byte stream: the deterministic keygen RNG for FN-DSA and the hedged signing RNG.
struct ShakeRng(SHAKE256);
impl ShakeRng {
    fn new(parts: &[&[u8]]) -> Self {
        let mut sh = SHAKE256::new();
        for p in parts {
            sh.inject(p);
        }
        sh.flip();
        Self(sh)
    }
}
impl CryptoRng for ShakeRng {}
impl RngCore for ShakeRng {
    fn next_u32(&mut self) -> u32 {
        let mut b = [0u8; 4];
        self.0.extract(&mut b);
        u32::from_le_bytes(b)
    }
    fn next_u64(&mut self) -> u64 {
        let mut b = [0u8; 8];
        self.0.extract(&mut b);
        u64::from_le_bytes(b)
    }
    fn fill_bytes(&mut self, dest: &mut [u8]) {
        self.0.extract(dest);
    }
    fn try_fill_bytes(&mut self, dest: &mut [u8]) -> Result<(), RngError> {
        self.0.extract(dest);
        Ok(())
    }
}

fn slh_seeds(seed: &[u8]) -> [u8; 3 * SLH_N] {
    let mut out = [0u8; 3 * SLH_N];
    ShakeRng::new(&[DST_SLH, seed]).fill_bytes(&mut out);
    out
}

fn ml_keygen<P: MlDsaParams>(seed: &[u8]) -> Option<(Vec<u8>, Vec<u8>)> {
    let xi = B32::try_from(seed).ok()?;
    let sk = MlSk::<P>::from_seed(&xi);
    let pk = sk.verifying_key().encode().to_vec();
    #[allow(deprecated)]
    let skb = sk.expanded_key().to_expanded().to_vec();
    Some((pk, skb))
}

fn ml_sign<P: MlDsaParams>(sk: &[u8], msg: &[u8], rnd: &[u8]) -> Option<Vec<u8>> {
    let skb = ExpandedSigningKeyBytes::<P>::try_from(sk).ok()?;
    #[allow(deprecated)]
    let esk = ExpandedSigningKey::<P>::from_expanded(&skb);
    let rnd = B32::try_from(rnd).ok()?;
    Some(esk.sign_internal(&[msg], &rnd).encode().to_vec())
}

fn ml_verify<P: MlDsaParams>(pk: &[u8], msg: &[u8], sig: &[u8]) -> bool {
    let Ok(pkb) = EncodedVerifyingKey::<P>::try_from(pk) else { return false };
    let vk = MlVk::<P>::decode(&pkb);
    let Ok(s) = MlSig::<P>::try_from(sig) else { return false };
    vk.verify_internal(msg, &s)
}

/// Deterministic keypair of scheme `alg` from a 32-byte seed. None for an unknown id or a wrong-length seed.
pub fn keygen(alg: u32, seed: &[u8]) -> Option<(Vec<u8>, Vec<u8>)> {
    if seed.len() != SEED {
        return None;
    }
    match alg {
        ALG_MLDSA65 => ml_keygen::<MlDsa65>(seed),
        ALG_MLDSA87 => ml_keygen::<MlDsa87>(seed),
        ALG_SLHDSA128S => {
            let s = slh_seeds(seed);
            let sk = SlhSk::<Sha2_128s>::slh_keygen_internal(&s[..SLH_N], &s[SLH_N..2 * SLH_N], &s[2 * SLH_N..]);
            Some((sk.verifying_key().to_vec(), sk.to_vec()))
        }
        ALG_FNDSA512 => {
            let (pkl, skl, _) = sizes(alg)?;
            let mut sk = vec![0u8; skl];
            let mut pk = vec![0u8; pkl];
            let mut rng = ShakeRng::new(&[DST_FN, seed]);
            KeyPairGeneratorStandard::default().keygen(FN_DSA_LOGN_512, &mut rng, &mut sk, &mut pk);
            Some((pk, sk))
        }
        _ => None,
    }
}

/// Hedged signature of `msg` under the encoded secret key `sk` of scheme `alg`. None on any malformed input.
pub fn sign(alg: u32, sk: &[u8], msg: &[u8], rnd: &[u8]) -> Option<Vec<u8>> {
    let (_, skl, _) = sizes(alg)?;
    if sk.len() != skl || rnd.len() != RND {
        return None;
    }
    match alg {
        ALG_MLDSA65 => ml_sign::<MlDsa65>(sk, msg, rnd),
        ALG_MLDSA87 => ml_sign::<MlDsa87>(sk, msg, rnd),
        ALG_SLHDSA128S => {
            let k = SlhSk::<Sha2_128s>::try_from(sk).ok()?;
            Some(k.slh_sign_internal(msg, Some(&rnd[..SLH_N])).to_vec())
        }
        ALG_FNDSA512 => {
            let mut k = SigningKeyStandard::decode(sk)?;
            let mut sig = vec![0u8; signature_size(k.get_logn())];
            k.sign(&mut ShakeRng::new(&[rnd]), &DOMAIN_NONE, &HASH_ID_RAW, msg, &mut sig);
            Some(sig)
        }
        _ => None,
    }
}

/// True iff `sig` is a valid signature of `msg` by the encoded public key `pk` under scheme `alg`. Never panics on
/// attacker-chosen bytes: a wrong length or an undecodable key or signature is simply invalid.
pub fn verify(alg: u32, pk: &[u8], msg: &[u8], sig: &[u8]) -> bool {
    let Some((pkl, _, sigl)) = sizes(alg) else { return false };
    if pk.len() != pkl || sig.len() != sigl {
        return false;
    }
    match alg {
        ALG_MLDSA65 => ml_verify::<MlDsa65>(pk, msg, sig),
        ALG_MLDSA87 => ml_verify::<MlDsa87>(pk, msg, sig),
        ALG_SLHDSA128S => {
            let (Ok(vk), Ok(s)) = (SlhVk::<Sha2_128s>::try_from(pk), SlhSig::<Sha2_128s>::try_from(sig)) else {
                return false;
            };
            vk.slh_verify_internal(msg, &s).is_ok()
        }
        ALG_FNDSA512 => match VerifyingKeyStandard::decode(pk) {
            Some(vk) => vk.verify(sig, &DOMAIN_NONE, &HASH_ID_RAW, msg),
            None => false,
        },
        _ => false,
    }
}

// ---- C ABI (bound by nado_pqsig.py via ctypes) -----------------------------------------------------------------------

unsafe fn slice<'a>(p: *const u8, n: usize) -> &'a [u8] {
    if n == 0 || p.is_null() { &[] } else { std::slice::from_raw_parts(p, n) }
}

/// Writes the scheme's (pk, sk, sig) lengths. Returns 0, or 1 for an unknown id.
#[no_mangle]
pub extern "C" fn nado_pqs_sizes(alg: u32, pk: *mut usize, sk: *mut usize, sig: *mut usize) -> i32 {
    match (sizes(alg), pk.is_null() || sk.is_null() || sig.is_null()) {
        (Some((a, b, c)), false) => unsafe {
            *pk = a;
            *sk = b;
            *sig = c;
            0
        },
        _ => 1,
    }
}

/// Keygen from a 32-byte seed into caller buffers of exactly the sizes nado_pqs_sizes reports.
#[no_mangle]
pub extern "C" fn nado_pqs_keygen(alg: u32, seed: *const u8, seedlen: usize, pk_out: *mut u8, pklen: usize,
                                  sk_out: *mut u8, sklen: usize) -> i32 {
    if pk_out.is_null() || sk_out.is_null() {
        return 1;
    }
    let Some((pk, sk)) = keygen(alg, unsafe { slice(seed, seedlen) }) else { return 2 };
    if pk.len() != pklen || sk.len() != sklen {
        return 3;
    }
    unsafe {
        std::ptr::copy_nonoverlapping(pk.as_ptr(), pk_out, pklen);
        std::ptr::copy_nonoverlapping(sk.as_ptr(), sk_out, sklen);
    }
    0
}

/// Hedged sign into a caller buffer of exactly the scheme's signature size.
#[no_mangle]
pub extern "C" fn nado_pqs_sign(alg: u32, sk: *const u8, sklen: usize, m: *const u8, mlen: usize,
                                rnd: *const u8, rndlen: usize, sig_out: *mut u8, siglen: usize) -> i32 {
    if sig_out.is_null() {
        return 1;
    }
    let Some(sig) = (unsafe { sign(alg, slice(sk, sklen), slice(m, mlen), slice(rnd, rndlen)) }) else { return 2 };
    if sig.len() != siglen {
        return 3;
    }
    unsafe { std::ptr::copy_nonoverlapping(sig.as_ptr(), sig_out, siglen) };
    0
}

/// 0 iff valid; non-zero for an invalid or malformed signature, key or scheme id.
#[no_mangle]
pub extern "C" fn nado_pqs_verify(alg: u32, pk: *const u8, pklen: usize, m: *const u8, mlen: usize,
                                  sig: *const u8, siglen: usize) -> i32 {
    if unsafe { verify(alg, slice(pk, pklen), slice(m, mlen), slice(sig, siglen)) } { 0 } else { 1 }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_scheme_round_trips_and_refuses_forgeries() {
        for alg in [ALG_MLDSA65, ALG_MLDSA87, ALG_SLHDSA128S, ALG_FNDSA512] {
            let (pk, sk) = keygen(alg, &[0x42; 32]).unwrap();
            let (pk2, sk2) = keygen(alg, &[0x42; 32]).unwrap();
            assert!(pk == pk2 && sk == sk2, "alg {alg}: keygen is a function of the seed");
            let sig = sign(alg, &sk, b"msg", &[7; 32]).unwrap();
            assert!(verify(alg, &pk, b"msg", &sig), "alg {alg}: honest signature");
            assert!(!verify(alg, &pk, b"other", &sig), "alg {alg}: wrong message");
            let mut f = sig.clone();
            f[sig.len() / 2] ^= 1;
            assert!(!verify(alg, &pk, b"msg", &f), "alg {alg}: flipped byte");
            assert!(!verify(alg, &pk, b"msg", &sig[..sig.len() - 1]), "alg {alg}: truncated");
            let (pko, _) = keygen(alg, &[0x99; 32]).unwrap();
            assert!(!verify(alg, &pko, b"msg", &sig), "alg {alg}: another key");
            for other in [ALG_MLDSA65, ALG_MLDSA87, ALG_SLHDSA128S, ALG_FNDSA512] {
                if other != alg {
                    assert!(!verify(other, &pk, b"msg", &sig), "alg {alg}: verified as {other}");
                }
            }
        }
        assert!(keygen(9, &[0; 32]).is_none() && keygen(ALG_MLDSA65, &[0; 31]).is_none());
    }
}
