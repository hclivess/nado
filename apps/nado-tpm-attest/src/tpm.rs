//! TPM 2.0 commands — the documented path, and deliberately platform-independent.
//!
//! WHY RAW, AFTER ALL THE NCRYPT WORK. `NCryptCreateClaim` mints a FRESH signing key per call: measured on a
//! real chip, the RSASSA pubArea inside the claim is not the AIK we hold, its modulus differs on every call,
//! and qualifiedSigner changes with it. A WebAuthn `tpm` statement requires certInfo to be signed by the key
//! in x5c[0], so a claim-derived statement can never verify against any certificate we issue. That route is
//! closed, and no amount of nonce work reopens it.
//!
//! Raw TPM2_Certify closes it properly: WE choose the signing key, so certInfo is signed by exactly the key
//! whose certificate goes in x5c, and we choose qualifyingData, so the challenge binds where the verifier
//! looks for it. It also drops Microsoft out of the design entirely rather than working around one of their
//! services — the same code path then serves every TPM 2.0 carrying a vendor endorsement certificate.
//!
//! And unlike Microsoft's KAST/KADS container, every byte here is specified: TCG TPM 2.0 Library Part 2
//! (structures) and Part 3 (commands). Command codes below are taken from tpm2-tss's tss2_tpm2_types.h rather
//! than from memory — TPM2_CC_MakeCredential is 0x168, which is exactly the kind of value that is easy to
//! misremember and impossible to debug afterwards.
//!
//! THE COMMAND BYTES ARE THE SAME EVERYWHERE. A TPM speaks TCG Part 3 whether it is reached through Windows'
//! TBS or through /dev/tpmrm0 on Linux, so only the transport differs — that is the `Tpm` trait below, and it
//! is the whole of the platform-specific surface. Keeping the commands here rather than inside the Windows
//! transport is what makes Linux support a new file instead of a second implementation, and it lets the exact
//! command framing be unit-tested on a host with no TPM at all.
#![allow(dead_code)]

/// A way to hand a command to a chip and get its response. Implemented by the TBS transport on Windows and by
/// the character device on Linux; nothing else in this module knows which it is talking to.
pub trait Tpm {
    fn transmit(&self, cmd: &[u8]) -> Result<Vec<u8>, u32>;
}

// TPM2_CC_* — verified against tpm2-tss/include/tss2/tss2_tpm2_types.h
pub const CC_CREATE_PRIMARY: u32 = 0x0000_0131;
pub const CC_ACTIVATE_CREDENTIAL: u32 = 0x0000_0147;
pub const CC_CERTIFY: u32 = 0x0000_0148;
pub const CC_POLICY_SECRET: u32 = 0x0000_0151;
pub const CC_CREATE: u32 = 0x0000_0153;
pub const CC_LOAD: u32 = 0x0000_0157;
pub const CC_FLUSH_CONTEXT: u32 = 0x0000_0165;
pub const CC_MAKE_CREDENTIAL: u32 = 0x0000_0168;
pub const CC_READ_PUBLIC: u32 = 0x0000_0173;
pub const CC_START_AUTH_SESSION: u32 = 0x0000_0176;
pub const CC_GET_CAPABILITY: u32 = 0x0000_017a;

pub const ST_NO_SESSIONS: u16 = 0x8001;
pub const ST_SESSIONS: u16 = 0x8002;

pub const RH_OWNER: u32 = 0x4000_0001;
pub const RH_NULL: u32 = 0x4000_0007;
pub const RH_ENDORSEMENT: u32 = 0x4000_000B;
pub const RS_PW: u32 = 0x4000_0009; // the password "session" used for empty auth

pub const ALG_RSA: u16 = 0x0001;
pub const ALG_SHA1: u16 = 0x0004;
pub const ALG_SHA256: u16 = 0x000B;
pub const ALG_NULL: u16 = 0x0010;
pub const ALG_RSASSA: u16 = 0x0014;

/// A command being assembled. The header's size field can only be filled in once the body is complete, so it
/// is patched in `finish()` rather than guessed at.
pub struct Cmd {
    buf: Vec<u8>,
    tag: u16,
}

impl Cmd {
    pub fn new(tag: u16, code: u32) -> Self {
        let mut buf = Vec::with_capacity(64);
        buf.extend_from_slice(&tag.to_be_bytes());
        buf.extend_from_slice(&0u32.to_be_bytes()); // commandSize, patched by finish()
        buf.extend_from_slice(&code.to_be_bytes());
        Cmd { buf, tag }
    }
    pub fn u16(&mut self, v: u16) -> &mut Self { self.buf.extend_from_slice(&v.to_be_bytes()); self }
    pub fn u32(&mut self, v: u32) -> &mut Self { self.buf.extend_from_slice(&v.to_be_bytes()); self }
    pub fn raw(&mut self, b: &[u8]) -> &mut Self { self.buf.extend_from_slice(b); self }
    /// A TPM2B_*: 16-bit size then the bytes.
    pub fn tpm2b(&mut self, b: &[u8]) -> &mut Self {
        self.u16(b.len() as u16);
        self.raw(b)
    }
    /// One password authorization for empty auth: handle, nonce(0), attributes(0), hmac(0).
    pub fn pw_auth(&mut self) -> &mut Self {
        let area = {
            let mut a = Vec::new();
            a.extend_from_slice(&RS_PW.to_be_bytes());
            a.extend_from_slice(&0u16.to_be_bytes()); // nonce
            a.push(0);                                // sessionAttributes
            a.extend_from_slice(&0u16.to_be_bytes()); // hmac
            a
        };
        self.u32(area.len() as u32);
        self.raw(&area)
    }
    pub fn finish(mut self) -> Vec<u8> {
        let n = self.buf.len() as u32;
        self.buf[2..6].copy_from_slice(&n.to_be_bytes());
        let _ = self.tag;
        self.buf
    }
}

/// A response, read positionally. Every accessor is bounds-checked and returns None rather than panicking:
/// this parses bytes from a device, and a truncated or unexpected reply must surface as a clean error.
pub struct Rsp<'a> {
    pub tag: u16,
    pub code: u32,
    body: &'a [u8],
    pos: usize,
}

impl<'a> Rsp<'a> {
    pub fn parse(b: &'a [u8]) -> Option<Rsp<'a>> {
        if b.len() < 10 { return None; }
        let tag = u16::from_be_bytes([b[0], b[1]]);
        let size = u32::from_be_bytes([b[2], b[3], b[4], b[5]]) as usize;
        let code = u32::from_be_bytes([b[6], b[7], b[8], b[9]]);
        if size > b.len() { return None; }
        Some(Rsp { tag, code, body: &b[10..size], pos: 0 })
    }
    pub fn ok(&self) -> bool { self.code == 0 }
    pub fn u16(&mut self) -> Option<u16> {
        let v = u16::from_be_bytes([*self.body.get(self.pos)?, *self.body.get(self.pos + 1)?]);
        self.pos += 2;
        Some(v)
    }
    pub fn u32(&mut self) -> Option<u32> {
        let s = self.body.get(self.pos..self.pos + 4)?;
        self.pos += 4;
        Some(u32::from_be_bytes([s[0], s[1], s[2], s[3]]))
    }
    pub fn tpm2b(&mut self) -> Option<&'a [u8]> {
        let n = self.u16()? as usize;
        let s = self.body.get(self.pos..self.pos + n)?;
        self.pos += n;
        Some(s)
    }
    pub fn rest(&self) -> &'a [u8] { &self.body[self.pos.min(self.body.len())..] }
}

/// TPM2_ReadPublic — the public area, name and qualified name of a loaded object. This is how we learn a key's
/// Name for the credential binding without trusting anything the host tells us.
pub fn read_public(t: &dyn Tpm, handle: u32) -> Result<(Vec<u8>, Vec<u8>), u32> {
    let mut c = Cmd::new(ST_NO_SESSIONS, CC_READ_PUBLIC);
    c.u32(handle);
    let r = t.transmit(&c.finish())?;
    let mut r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    let pub_area = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    let name = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    Ok((pub_area, name))
}

/// TPM2_Certify — the whole point. `qualifying_data` lands in certInfo.extraData, which is where the verifier
/// looks for hash(authData || clientDataHash), and the signature is made by `sign_handle`, which is the key
/// whose certificate we put in x5c. Both facts are ours to choose here, and neither was on the NCrypt path.
pub fn certify(t: &dyn Tpm, object: u32, sign_handle: u32, qualifying_data: &[u8]) -> Result<(Vec<u8>, Vec<u8>), u32> {
    let mut c = Cmd::new(ST_SESSIONS, CC_CERTIFY);
    c.u32(object).u32(sign_handle);
    // two authorizations: one per handle, both empty-password
    let area = {
        let mut a = Vec::new();
        for _ in 0..2 {
            a.extend_from_slice(&RS_PW.to_be_bytes());
            a.extend_from_slice(&0u16.to_be_bytes());
            a.push(0);
            a.extend_from_slice(&0u16.to_be_bytes());
        }
        a
    };
    c.u32(area.len() as u32).raw(&area);
    c.tpm2b(qualifying_data);
    c.u16(ALG_RSASSA).u16(ALG_SHA256);          // inScheme: RSASSA over SHA-256
    let r = t.transmit(&c.finish())?;
    let mut r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    let _param_size = r.u32();
    let cert_info = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    // TPMT_SIGNATURE: sigAlg(2) hashAlg(2) then the TPM2B signature
    let _sig_alg = r.u16().ok_or(0xFFFF_FFFEu32)?;
    let _hash_alg = r.u16().ok_or(0xFFFF_FFFEu32)?;
    let sig = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    Ok((cert_info, sig))
}

// --- object templates ----------------------------------------------------------------------------------
//
// objectAttributes bits (TCG Part 2 §8.3): fixedTPM 0x2, fixedParent 0x10, sensitiveDataOrigin 0x20,
// userWithAuth 0x40, adminWithPolicy 0x80, noDA 0x400, restricted 0x10000, decrypt 0x20000, sign 0x40000.

/// The TCG EK Credential Profile L-1 template (RSA 2048). Its attributes and authPolicy are fixed by that
/// profile, not chosen by us: reproduce them byte for byte or the primary derives to a DIFFERENT key than the
/// one the vendor certified, and the endorsement certificate then belongs to a key we do not hold.
pub const EK_ATTRS: u32 = 0x0003_00B2; // fixedTPM|fixedParent|sensitiveDataOrigin|adminWithPolicy|restricted|decrypt

/// The well-known EK authPolicy: PolicySecret(TPM_RH_ENDORSEMENT) under SHA-256. Because the EK is
/// adminWithPolicy, using it at all requires a policy session that satisfies exactly this.
pub const EK_POLICY_SHA256: [u8; 32] = [
    0x83, 0x71, 0x97, 0x67, 0x44, 0x84, 0xb3, 0xf8, 0x1a, 0x90, 0xcc, 0x8d, 0x46, 0xa5, 0xd7, 0x24,
    0xfd, 0x52, 0xd7, 0x6e, 0x06, 0x52, 0x0b, 0x64, 0xf2, 0xa1, 0xda, 0x1b, 0x33, 0x14, 0x69, 0xaa];

/// A restricted RSA-2048 signing key — an attestation key. Restricted is what makes TPM2_Certify meaningful:
/// such a key will only ever sign TPM-generated structures, so a signature from it cannot be an arbitrary
/// message the host chose. noDA matches what Windows uses for its own AIKs.
pub const AIK_ATTRS: u32 = 0x0005_0472; // fixedTPM|fixedParent|sensitiveDataOrigin|userWithAuth|noDA|restricted|sign

pub fn ek_template() -> Vec<u8> {
    let mut t = Vec::new();
    t.extend_from_slice(&ALG_RSA.to_be_bytes());
    t.extend_from_slice(&ALG_SHA256.to_be_bytes());
    t.extend_from_slice(&EK_ATTRS.to_be_bytes());
    t.extend_from_slice(&(EK_POLICY_SHA256.len() as u16).to_be_bytes());
    t.extend_from_slice(&EK_POLICY_SHA256);
    // parameters: symmetric AES-128-CFB, scheme NULL, keyBits 2048, exponent default
    t.extend_from_slice(&0x0006u16.to_be_bytes());  // TPM_ALG_AES
    t.extend_from_slice(&128u16.to_be_bytes());
    t.extend_from_slice(&0x0043u16.to_be_bytes());  // TPM_ALG_CFB
    t.extend_from_slice(&ALG_NULL.to_be_bytes());
    t.extend_from_slice(&2048u16.to_be_bytes());
    t.extend_from_slice(&0u32.to_be_bytes());
    // unique: the profile's 256 zero bytes
    t.extend_from_slice(&256u16.to_be_bytes());
    t.extend_from_slice(&[0u8; 256]);
    t
}

pub fn aik_template() -> Vec<u8> {
    let mut t = Vec::new();
    t.extend_from_slice(&ALG_RSA.to_be_bytes());
    t.extend_from_slice(&ALG_SHA256.to_be_bytes());
    t.extend_from_slice(&AIK_ATTRS.to_be_bytes());
    t.extend_from_slice(&0u16.to_be_bytes());       // authPolicy: none
    t.extend_from_slice(&ALG_NULL.to_be_bytes());   // symmetric: none (a signing key)
    t.extend_from_slice(&ALG_RSASSA.to_be_bytes()); // scheme RSASSA...
    t.extend_from_slice(&ALG_SHA256.to_be_bytes()); // ...over SHA-256, so certInfo is COSE -257, not RS1
    t.extend_from_slice(&2048u16.to_be_bytes());
    t.extend_from_slice(&0u32.to_be_bytes());
    t.extend_from_slice(&0u16.to_be_bytes());       // unique: empty
    t
}

/// TPM2_CreatePrimary. Returns (handle, pubArea, name).
pub fn create_primary(t: &dyn Tpm, hierarchy: u32, template: &[u8]) -> Result<(u32, Vec<u8>, Vec<u8>), u32> {
    let mut c = Cmd::new(ST_SESSIONS, CC_CREATE_PRIMARY);
    c.u32(hierarchy);
    c.pw_auth();
    // inSensitive: TPM2B_SENSITIVE_CREATE { userAuth: empty, data: empty }
    c.u16(4).u16(0).u16(0);
    c.tpm2b(template);                              // inPublic
    c.u16(0);                                       // outsideInfo
    c.u32(0);                                       // creationPCR: no selections
    let r = t.transmit(&c.finish())?;
    let mut r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    let handle = r.u32().ok_or(0xFFFF_FFFEu32)?;
    let _param_size = r.u32();
    let pub_area = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    // creationData, creationHash, then the ticket, then the name
    let _creation_data = r.tpm2b().ok_or(0xFFFF_FFFEu32)?;
    let _creation_hash = r.tpm2b().ok_or(0xFFFF_FFFEu32)?;
    let _tk_tag = r.u16().ok_or(0xFFFF_FFFEu32)?;
    let _tk_hierarchy = r.u32().ok_or(0xFFFF_FFFEu32)?;
    let _tk_digest = r.tpm2b().ok_or(0xFFFF_FFFEu32)?;
    let name = r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec();
    Ok((handle, pub_area, name))
}

/// TPM2_StartAuthSession for a policy session (SHA-256, no salt, no bind). Returns the session handle.
pub fn start_policy_session(t: &dyn Tpm) -> Result<u32, u32> {
    let mut c = Cmd::new(ST_NO_SESSIONS, CC_START_AUTH_SESSION);
    c.u32(RH_NULL).u32(RH_NULL);
    c.tpm2b(&[0u8; 16]);                            // nonceCaller: at least the hash size/2, 16 is safe
    c.u16(0);                                       // encryptedSalt: none
    c.raw(&[0x01]);                                 // sessionType: TPM_SE_POLICY
    c.u16(ALG_NULL);                                // symmetric: none
    c.u16(ALG_SHA256);                              // authHash
    let r = t.transmit(&c.finish())?;
    let mut r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    r.u32().ok_or(0xFFFF_FFFEu32)
}

/// TPM2_PolicySecret against the endorsement hierarchy — what satisfies the EK's authPolicy. With empty
/// endorsement auth this needs no password, but the session is still mandatory: the EK is adminWithPolicy, so
/// a plain password authorization is refused however empty the hierarchy auth happens to be.
pub fn policy_secret_endorsement(t: &dyn Tpm, session: u32) -> Result<(), u32> {
    let mut c = Cmd::new(ST_SESSIONS, CC_POLICY_SECRET);
    c.u32(RH_ENDORSEMENT).u32(session);
    c.pw_auth();
    c.u16(0);                                       // nonceTPM
    c.u16(0);                                       // cpHashA
    c.u16(0);                                       // policyRef
    c.u32(0);                                       // expiration
    let r = t.transmit(&c.finish())?;
    let r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    Ok(())
}

/// TPM2_ActivateCredential — the proof. The chip returns the sealed secret ONLY if `activate` (our AIK) and
/// `key` (the endorsement key) are objects in the SAME TPM, which is precisely the statement the issuer needs
/// signed and the reason the handshake cannot be made non-interactive.
///
/// Two authorizations: the AIK by password (empty), and the EK by the policy session that PolicySecret has
/// already satisfied.
pub fn activate_credential(t: &dyn Tpm, activate: u32, key: u32, session: u32,
                           credential_blob: &[u8], secret: &[u8]) -> Result<Vec<u8>, u32> {
    let mut c = Cmd::new(ST_SESSIONS, CC_ACTIVATE_CREDENTIAL);
    c.u32(activate).u32(key);
    let area = {
        let mut a = Vec::new();
        // activateHandle: empty password
        a.extend_from_slice(&RS_PW.to_be_bytes());
        a.extend_from_slice(&0u16.to_be_bytes());
        a.push(0);
        a.extend_from_slice(&0u16.to_be_bytes());
        // keyHandle: the policy session, continueSession so it survives for a retry
        a.extend_from_slice(&session.to_be_bytes());
        a.extend_from_slice(&0u16.to_be_bytes());
        a.push(0x01);
        a.extend_from_slice(&0u16.to_be_bytes());
        a
    };
    c.u32(area.len() as u32).raw(&area);
    // Both arrive already TPM2B-wrapped from the issuer, so they are written raw rather than re-wrapped.
    c.raw(credential_blob);
    c.raw(secret);
    let r = t.transmit(&c.finish())?;
    let mut r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    let _param_size = r.u32();
    Ok(r.tpm2b().ok_or(0xFFFF_FFFEu32)?.to_vec())
}

/// TPM2_FlushContext — transient handles are a scarce resource; leaking them wedges the chip for other
/// software until reboot.
pub fn flush(t: &dyn Tpm, handle: u32) -> Result<(), u32> {
    let mut c = Cmd::new(ST_NO_SESSIONS, CC_FLUSH_CONTEXT);
    c.u32(handle);
    let r = t.transmit(&c.finish())?;
    let r = Rsp::parse(&r).ok_or(0xFFFF_FFFEu32)?;
    if !r.ok() { return Err(r.code); }
    Ok(())
}
