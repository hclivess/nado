//! The Windows surface we need, declared by hand so the crate builds offline with no dependencies.
//! Every name and flag below is from Microsoft's own TPM key-attestation sample
//! (github.com/microsoft/Attestation-Client-Samples: utils.cpp, EnrollAik.ps1) or from ncrypt.h /
//! wincrypt.h — nothing here is guessed. See doc/windows-tpm-attester.md.
#![allow(non_camel_case_types, non_snake_case)]

use std::ffi::c_void;

pub type SECURITY_STATUS = i32;
pub type NCRYPT_HANDLE = usize;

// ncrypt.h
pub const NCRYPT_MACHINE_KEY_FLAG: u32 = 0x0000_0020;
pub const NCRYPT_SILENT_FLAG: u32 = 0x0000_0040;
pub const NCRYPT_OVERWRITE_KEY_FLAG: u32 = 0x0000_0080;   // ncrypt.h — 0x1000 was wrong and read as NTE_BAD_FLAGS
/// NCryptCreateClaim: bind the SUBJECT key to the AUTHORITY (the AIK) — this is TPM key attestation,
/// i.e. a TPM2_Certify of the subject's public area signed by the AIK.
pub const NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT: u32 = 0x0000_0002;
pub const NCRYPT_CLAIM_PLATFORM: u32 = 0x0001_0000;

pub const MS_PLATFORM_KEY_STORAGE_PROVIDER: &str = "Microsoft Platform Crypto Provider";
pub const BCRYPT_RSA_ALGORITHM: &str = "RSA";
pub const BCRYPT_ECDSA_P256_ALGORITHM: &str = "ECDSA_P256";
pub const NCRYPT_LENGTH_PROPERTY: &str = "Length";
/// The TPM 2.0 public area (TPMT_PUBLIC) of a Platform-Crypto-Provider key — exactly the `pubArea`
/// a WebAuthn `tpm` attestation statement carries.
pub const NCRYPT_PCP_TPM12_IDBINDING_PROPERTY: &str = "PCP_TPM12_IDBINDING";
pub const NCRYPT_PCP_PLATFORMHANDLE_PROPERTY: &str = "PCP_PLATFORMHANDLE";
pub const NCRYPT_PCP_KEYUSAGEPOLICY_PROPERTY: &str = "PCP_KEYUSAGEPOLICY";
pub const NCRYPT_ALGORITHM_PROPERTY: &str = "Algorithm Name";
pub const BCRYPT_RSAPUBLIC_BLOB: &str = "RSAPUBLICBLOB";
pub const BCRYPT_ECCPUBLIC_BLOB: &str = "ECCPUBLICBLOB";

#[link(name = "ncrypt")]
extern "system" {
    pub fn NCryptOpenStorageProvider(phProvider: *mut NCRYPT_HANDLE, pszProviderName: *const u16, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptOpenKey(hProvider: NCRYPT_HANDLE, phKey: *mut NCRYPT_HANDLE, pszKeyName: *const u16, dwLegacyKeySpec: u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptCreatePersistedKey(hProvider: NCRYPT_HANDLE, phKey: *mut NCRYPT_HANDLE, pszAlgId: *const u16, pszKeyName: *const u16, dwLegacyKeySpec: u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptSetProperty(hObject: NCRYPT_HANDLE, pszProperty: *const u16, pbInput: *const u8, cbInput: u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptGetProperty(hObject: NCRYPT_HANDLE, pszProperty: *const u16, pbOutput: *mut u8, cbOutput: u32, pcbResult: *mut u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptFinalizeKey(hKey: NCRYPT_HANDLE, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptExportKey(hKey: NCRYPT_HANDLE, hExportKey: NCRYPT_HANDLE, pszBlobType: *const u16, pParameterList: *const c_void, pbOutput: *mut u8, cbOutput: u32, pcbResult: *mut u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptCreateClaim(hSubjectKey: NCRYPT_HANDLE, hAuthorityKey: NCRYPT_HANDLE, dwClaimType: u32, pParameterList: *const c_void, pbClaimBlob: *mut u8, cbClaimBlob: u32, pcbResult: *mut u32, dwFlags: u32) -> SECURITY_STATUS;
    pub fn NCryptFreeObject(hObject: NCRYPT_HANDLE) -> SECURITY_STATUS;
    pub fn NCryptDeleteKey(hKey: NCRYPT_HANDLE, dwFlags: u32) -> SECURITY_STATUS;
}

// TPM Base Services. LOADED DYNAMICALLY ON PURPOSE (2026-09-10): a static import of tbs.dll means Windows
// refuses to start the process at all when the DLL is missing — the loader fails before main(), so the user
// sees a crash with no output whatsoever. That is exactly the failure reported on first run. Nothing else we
// call is optional, but the TPM probe is, so it must never be able to prevent the program from running.
pub type TbsiContextCreate = unsafe extern "system" fn(*const u32, *mut *mut c_void) -> u32;
pub type TbsipContextClose = unsafe extern "system" fn(*mut c_void) -> u32;

// crypt32 — locating the AIK certificate that certreq installed.
pub const CERT_SYSTEM_STORE_LOCAL_MACHINE: u32 = 2 << 16;
pub const X509_ASN_ENCODING: u32 = 0x0000_0001;
pub const PKCS_7_ASN_ENCODING: u32 = 0x0001_0000;

#[repr(C)]
pub struct CERT_CONTEXT {
    pub dwCertEncodingType: u32,
    pub pbCertEncoded: *mut u8,
    pub cbCertEncoded: u32,
    pub pCertInfo: *mut c_void,
    pub hCertStore: *mut c_void,
}

#[link(name = "crypt32")]
extern "system" {
    pub fn CertOpenStore(lpszStoreProvider: usize, dwEncodingType: u32, hCryptProv: usize, dwFlags: u32, pvPara: *const c_void) -> *mut c_void;
    pub fn CertEnumCertificatesInStore(hCertStore: *mut c_void, pPrevCertContext: *const CERT_CONTEXT) -> *const CERT_CONTEXT;
    pub fn CertCloseStore(hCertStore: *mut c_void, dwFlags: u32) -> i32;
    pub fn CertGetNameStringW(pCertContext: *const CERT_CONTEXT, dwType: u32, dwFlags: u32, pvTypePara: *const c_void, pszNameString: *mut u16, cchNameString: u32) -> u32;
}
pub const CERT_STORE_PROV_SYSTEM_W: usize = 10;
pub const CERT_NAME_SIMPLE_DISPLAY_TYPE: u32 = 4;
pub const CERT_NAME_ISSUER_FLAG: u32 = 0x1;

/// A NUL-terminated UTF-16 string, kept alive by the caller.
pub fn w(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

// --- console + elevation, so the tool is usable by someone who is not a systems engineer ---------------

pub const STD_OUTPUT_HANDLE: u32 = -11i32 as u32;
pub const ENABLE_VIRTUAL_TERMINAL_PROCESSING: u32 = 0x0004;
pub const TOKEN_QUERY: u32 = 0x0008;

#[link(name = "kernel32")]
extern "system" {
    pub fn LoadLibraryA(lpLibFileName: *const u8) -> *mut c_void;
    pub fn GetProcAddress(hModule: *mut c_void, lpProcName: *const u8) -> *mut c_void;
    pub fn GetStdHandle(nStdHandle: u32) -> *mut c_void;
    pub fn GetConsoleMode(hConsoleHandle: *mut c_void, lpMode: *mut u32) -> i32;
    pub fn SetConsoleMode(hConsoleHandle: *mut c_void, dwMode: u32) -> i32;
    pub fn GetCurrentProcess() -> *mut c_void;
}

#[link(name = "advapi32")]
extern "system" {
    pub fn OpenProcessToken(ProcessHandle: *mut c_void, DesiredAccess: u32, TokenHandle: *mut *mut c_void) -> i32;
    pub fn GetTokenInformation(TokenHandle: *mut c_void, TokenInformationClass: u32, TokenInformation: *mut c_void,
                               TokenInformationLength: u32, ReturnLength: *mut u32) -> i32;
}

/// Turn on ANSI colour support (Windows 10+). Harmless if it fails — the text just prints uncoloured.
pub fn enable_colour() -> bool {
    unsafe {
        let h = GetStdHandle(STD_OUTPUT_HANDLE);
        let mut mode = 0u32;
        if GetConsoleMode(h, &mut mode) == 0 { return false; }
        SetConsoleMode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0
    }
}

/// True when this process is running elevated ("Run as administrator").
pub fn is_elevated() -> bool {
    unsafe {
        let mut tok: *mut c_void = std::ptr::null_mut();
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut tok) == 0 { return false; }
        let mut elevated = 0u32;
        let mut len = 0u32;
        // TokenElevation = 20
        let ok = GetTokenInformation(tok, 20, &mut elevated as *mut u32 as *mut c_void, 4, &mut len) != 0;
        ok && elevated != 0
    }
}

/// True when a TPM answers through TBS. Never panics, never prevents startup: tbs.dll is resolved at run time
/// and a missing DLL or missing export simply reads as "no TPM".
pub fn tbs_tpm_present() -> bool {
    unsafe {
        let h = LoadLibraryA(b"tbs.dll\0".as_ptr());
        if h.is_null() { return false; }
        let create = GetProcAddress(h, b"Tbsi_Context_Create\0".as_ptr());
        let close = GetProcAddress(h, b"Tbsip_Context_Close\0".as_ptr());
        if create.is_null() || close.is_null() { return false; }
        let create: TbsiContextCreate = std::mem::transmute(create);
        let close: TbsipContextClose = std::mem::transmute(close);
        let params = [2u32, 1u32 << 2];   // version 2, includeTpm20 — NOT 1 (that is requestRaw alone)
        let mut ctx: *mut c_void = std::ptr::null_mut();
        if create(params.as_ptr(), &mut ctx) != 0 { return false; }
        close(ctx);
        true
    }
}
