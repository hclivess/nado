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
pub const NCRYPT_OVERWRITE_KEY_FLAG: u32 = 0x0000_1000;
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

// TPM Base Services — used only to prove a TPM is reachable at all.
#[link(name = "tbs")]
extern "system" {
    pub fn Tbsi_Context_Create(pContextParams: *const u32, phContext: *mut *mut c_void) -> u32;
    pub fn Tbsip_Context_Close(hContext: *mut c_void) -> u32;
}

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
