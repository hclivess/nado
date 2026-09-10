//! Raw TPM 2.0 over Windows TBS — the documented path.
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
#![allow(dead_code)]

use std::ffi::c_void;

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

// --- TBS transport -------------------------------------------------------------------------------------
// Loaded dynamically: a static import of tbs.dll makes Windows refuse to start the process at all when the
// DLL is absent, which presents as a crash with no output whatsoever.

pub type TbsiContextCreate = unsafe extern "system" fn(*const u32, *mut *mut c_void) -> u32;
pub type TbsipSubmitCommand = unsafe extern "system" fn(*mut c_void, u32, u32, *const u8, u32, *mut u8, *mut u32) -> u32;
pub type TbsipContextClose = unsafe extern "system" fn(*mut c_void) -> u32;

pub const TBS_COMMAND_LOCALITY_ZERO: u32 = 0;
pub const TBS_COMMAND_PRIORITY_NORMAL: u32 = 200;

pub struct Tbs {
    ctx: *mut c_void,
    submit: TbsipSubmitCommand,
    close: TbsipContextClose,
}

impl Tbs {
    /// Open a raw TPM 2.0 context. `flags` is a bitfield — bit 2 is includeTpm20; passing 1 (requestRaw
    /// alone, no version) is answered with TPM_NOT_FOUND on a perfectly healthy chip.
    pub unsafe fn open(load: impl Fn(&[u8]) -> *mut c_void) -> Result<Tbs, u32> {
        let lib = load(b"tbs.dll\0");
        if lib.is_null() { return Err(0xFFFF_FFFF); }
        Err(0) // wired by the caller, which owns GetProcAddress
    }

    pub unsafe fn from_parts(ctx: *mut c_void, submit: TbsipSubmitCommand, close: TbsipContextClose) -> Tbs {
        Tbs { ctx, submit, close }
    }

    pub fn transmit(&self, cmd: &[u8]) -> Result<Vec<u8>, u32> {
        let mut out = vec![0u8; 4096];
        let mut n = out.len() as u32;
        let rc = unsafe {
            (self.submit)(self.ctx, TBS_COMMAND_LOCALITY_ZERO, TBS_COMMAND_PRIORITY_NORMAL,
                          cmd.as_ptr(), cmd.len() as u32, out.as_mut_ptr(), &mut n)
        };
        if rc != 0 { return Err(rc); }
        out.truncate(n as usize);
        Ok(out)
    }
}

impl Drop for Tbs {
    fn drop(&mut self) {
        unsafe { (self.close)(self.ctx) };
    }
}

/// TPM2_ReadPublic — the public area, name and qualified name of a loaded object. This is how we learn a key's
/// Name for the credential binding without trusting anything the host tells us.
pub fn read_public(t: &Tbs, handle: u32) -> Result<(Vec<u8>, Vec<u8>), u32> {
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
pub fn certify(t: &Tbs, object: u32, sign_handle: u32, qualifying_data: &[u8]) -> Result<(Vec<u8>, Vec<u8>), u32> {
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
