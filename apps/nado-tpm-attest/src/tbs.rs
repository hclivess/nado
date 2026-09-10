//! Windows transport: the TPM Base Services.
//!
//! Loaded dynamically on purpose — a static import of tbs.dll makes Windows refuse to start the process at all
//! when the DLL is absent, which presents to the user as a crash with no output whatsoever.
#![allow(dead_code)]

use crate::tpm::Tpm;
use std::ffi::c_void;


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


impl Tpm for Tbs {
    fn transmit(&self, cmd: &[u8]) -> Result<Vec<u8>, u32> {
        Tbs::transmit(self, cmd)
    }
}
