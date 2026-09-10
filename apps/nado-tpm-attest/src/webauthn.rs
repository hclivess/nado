//! Assembling a WebAuthn `tpm` attestation statement out of what the chip gives us.
//!
//! The verifier is native/attest (doc/device-attestation.md): it wants an attestationObject of
//!   {fmt: "tpm", attStmt: {ver, alg, x5c, sig, certInfo, pubArea}, authData}
//! where certInfo is a TPM_ST_ATTEST_CERTIFY whose extraData == hash(authData || sha256(clientDataJSON)) and
//! whose attested name == name(pubArea), and pubArea's key IS the credential key in authData. Every one of
//! those fields comes out of the claim blob (see doc/windows-tpm-attester.md for its measured layout); the
//! only piece the chip cannot supply is x5c, the AIK certificate, which only exists where Microsoft certifies.

/// Minimal CBOR writer — only the shapes an attestationObject needs.
pub struct Cbor(pub Vec<u8>);
impl Cbor {
    pub fn new() -> Self { Cbor(Vec::new()) }
    fn head(&mut self, major: u8, n: u64) {
        let m = major << 5;
        match n {
            0..=23 => self.0.push(m | n as u8),
            24..=255 => { self.0.push(m | 24); self.0.push(n as u8); }
            256..=65535 => { self.0.push(m | 25); self.0.extend_from_slice(&(n as u16).to_be_bytes()); }
            _ => { self.0.push(m | 26); self.0.extend_from_slice(&(n as u32).to_be_bytes()); }
        }
    }
    pub fn uint(&mut self, v: u64) { self.head(0, v); }
    pub fn nint(&mut self, v: i64) { self.head(1, (-1 - v) as u64); }   // negative integer
    pub fn bytes(&mut self, b: &[u8]) { self.head(2, b.len() as u64); self.0.extend_from_slice(b); }
    pub fn text(&mut self, s: &str) { self.head(3, s.len() as u64); self.0.extend_from_slice(s.as_bytes()); }
    pub fn array(&mut self, n: u64) { self.head(4, n); }
    pub fn map(&mut self, n: u64) { self.head(5, n); }
    pub fn int(&mut self, v: i64) { if v < 0 { self.nint(v) } else { self.uint(v as u64) } }
}

pub fn b64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for c in data.chunks(3) {
        let b = [c[0], *c.get(1).unwrap_or(&0), *c.get(2).unwrap_or(&0)];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

pub fn b64url_nopad(data: &[u8]) -> String {
    b64(data).replace('+', "-").replace('/', "_").trim_end_matches('=').to_string()
}

/// (modulus, exponent) of an RSA TPMT_PUBLIC. Accepts a bare TPMT_PUBLIC or a TPM2B_PUBLIC (size-prefixed),
/// which is how the PCP blob stores it.
/// TPMT_PUBLIC: type(2) nameAlg(2) objectAttributes(4) authPolicy(2+n) [symmetric(2) scheme(2) keyBits(2)
/// exponent(4)] unique(2+n).
pub fn rsa_from_pub_area(pa: &[u8]) -> Option<(Vec<u8>, u32, &[u8])> {
    // strip a TPM2B size prefix if present
    let body: &[u8] = if pa.len() > 2 && u16::from_be_bytes([pa[0], pa[1]]) as usize == pa.len() - 2 {
        &pa[2..]
    } else { pa };
    let be16 = |o: usize| -> Option<u16> { Some(u16::from_be_bytes([*body.get(o)?, *body.get(o + 1)?])) };
    if be16(0)? != 0x0001 { return None; }                 // TPM_ALG_RSA
    // authPolicy's 16-bit size lives at offset 8, after type(2) nameAlg(2) objectAttributes(4).
    let policy = be16(8)? as usize;
    let mut o = 10 + policy;
    // TPMT_SYM_DEF_OBJECT and TPMT_RSA_SCHEME each carry details ONLY when they are not TPM_ALG_NULL. An EK
    // is AES-128-CFB and so does carry them; a credential key is NULL and does not. Walk, do not assume.
    let sym = be16(o)?;
    o += 2;
    if sym != 0x0010 { o += 4; }                            // keyBits + mode
    let scheme = be16(o)?;
    o += 2;
    if scheme != 0x0010 { o += 2; }                         // hashAlg
    o += 2;                                                 // keyBits
    let exp = u32::from_be_bytes([*body.get(o)?, *body.get(o + 1)?, *body.get(o + 2)?, *body.get(o + 3)?]);
    o += 4;
    let n = be16(o)? as usize;
    let modulus = body.get(o + 2..o + 2 + n)?.to_vec();
    Some((modulus, if exp == 0 { 65537 } else { exp }, body))
}

/// COSE_Key for an RSA credential key: kty(1)=3, alg(3)=-257, n(-1), e(-2). native/attest compares n and e
/// against pubArea, so these must be the pubArea's own bytes.
pub fn cose_rsa(modulus: &[u8], exponent: u32) -> Vec<u8> {
    let e = {
        let b = exponent.to_be_bytes();
        let first = b.iter().position(|&x| x != 0).unwrap_or(3);
        b[first..].to_vec()
    };
    let mut c = Cbor::new();
    c.map(4);
    c.int(1); c.int(3);          // kty: RSA
    c.int(3); c.int(-257);       // alg: RS256
    c.int(-1); c.bytes(modulus); // n
    c.int(-2); c.bytes(&e);      // e
    c.0
}

/// authData = rpIdHash(32) | flags(1) | signCount(4) | aaguid(16) | credIdLen(2) | credId | credPubKey
pub fn auth_data(rp_id_hash: &[u8; 32], cred_id: &[u8], cose: &[u8]) -> Vec<u8> {
    let mut a = Vec::new();
    a.extend_from_slice(rp_id_hash);
    a.push(0x45);                                   // UP | UV | AT — the same flags real Windows Hello sends
    a.extend_from_slice(&0u32.to_be_bytes());       // signCount
    a.extend_from_slice(&[0u8; 16]);                // aaguid: not a FIDO authenticator, so all zero
    a.extend_from_slice(&(cred_id.len() as u16).to_be_bytes());
    a.extend_from_slice(cred_id);
    a.extend_from_slice(cose);
    a
}

/// The attestationObject the chain verifies.
pub fn attestation_object(alg: i64, x5c: &[Vec<u8>], sig: &[u8], cert_info: &[u8], pub_area: &[u8],
                          auth_data: &[u8]) -> Vec<u8> {
    let mut c = Cbor::new();
    c.map(3);
    c.text("fmt"); c.text("tpm");
    c.text("attStmt");
    c.map(6);
    c.text("ver"); c.text("2.0");
    c.text("alg"); c.int(alg);
    c.text("x5c"); c.array(x5c.len() as u64);
    for cert in x5c { c.bytes(cert); }
    c.text("sig"); c.bytes(sig);
    c.text("certInfo"); c.bytes(cert_info);
    c.text("pubArea"); c.bytes(pub_area);
    c.text("authData"); c.bytes(auth_data);
    c.0
}
