//! Solana leg of the OTC cross-chain atomic swap (doc/dex-bridge.md §6.5).
//!
//! Same shape as the Bitcoin and Ethereum legs, and locked by the SAME 32-byte SHA-256 image the NADO
//! order carries: `fund` escrows lamports, `claim` releases them to the claimant against the preimage,
//! `refund` returns them to the funder once the deadline has passed. No admin key, no upgrade authority
//! intended, no fee.
//!
//! WHY A PROGRAM AT ALL. Bitcoin can express an HTLC as a script, so its leg needs nothing deployed.
//! Solana has no such script: the conditions have to live in a program, and the escrow in an account that
//! program owns. That account is a PDA derived from the swap's own parameters —
//!     seeds = ["htlc", hashlock, claimant, refunder, deadline_le, amount_le]
//! — so the ADDRESS IS THE AGREEMENT. Two consequences that matter:
//!   * the amount is part of the address, so an underfunded lock lands somewhere else entirely and the
//!     claimant's client simply finds no account — it can never be tricked into revealing the secret for
//!     dust (this is the exact bug an audit proved against the first Ethereum contract);
//!   * nobody can front-run the address: the same parameters always give the same PDA, and only this
//!     program can move lamports out of it.
//!
//! The deadline is a UNIX timestamp read from the Clock sysvar, not a slot: slot times drift, and the
//! §6.3 ordering invariant (the foreign leg must expire before the NADO leg) is stated in wall clock.
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    hash::hashv,
    msg,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

/// A lock's parameters. Stored in the PDA so `claim`/`refund` can check them without trusting the caller.
#[derive(Clone, Copy)]
pub struct Lock {
    pub hashlock: [u8; 32],
    pub claimant: Pubkey,
    pub refunder: Pubkey,
    pub deadline: i64,
    pub amount: u64,
}

pub const LOCK_LEN: usize = 32 + 32 + 32 + 8 + 8;
/// A swap needs long enough to be funded and confirmed on both chains, and must not sit forever.
pub const MIN_WINDOW: i64 = 10 * 60;
pub const MAX_WINDOW: i64 = 30 * 24 * 60 * 60;

impl Lock {
    fn write(&self, dst: &mut [u8]) {
        dst[0..32].copy_from_slice(&self.hashlock);
        dst[32..64].copy_from_slice(self.claimant.as_ref());
        dst[64..96].copy_from_slice(self.refunder.as_ref());
        dst[96..104].copy_from_slice(&self.deadline.to_le_bytes());
        dst[104..112].copy_from_slice(&self.amount.to_le_bytes());
    }
    fn read(src: &[u8]) -> Result<Self, ProgramError> {
        if src.len() < LOCK_LEN {
            return Err(ProgramError::InvalidAccountData);
        }
        let mut hashlock = [0u8; 32];
        hashlock.copy_from_slice(&src[0..32]);
        Ok(Lock {
            hashlock,
            claimant: Pubkey::try_from(&src[32..64]).map_err(|_| ProgramError::InvalidAccountData)?,
            refunder: Pubkey::try_from(&src[64..96]).map_err(|_| ProgramError::InvalidAccountData)?,
            deadline: i64::from_le_bytes(src[96..104].try_into().unwrap()),
            amount: u64::from_le_bytes(src[104..112].try_into().unwrap()),
        })
    }
}

/// The PDA seeds. Every term of the agreement is in here, which is what makes the address binding.
fn seeds_of<'a>(
    hashlock: &'a [u8; 32],
    claimant: &'a Pubkey,
    refunder: &'a Pubkey,
    deadline: &'a [u8; 8],
    amount: &'a [u8; 8],
) -> [&'a [u8]; 6] {
    [b"htlc", hashlock, claimant.as_ref(), refunder.as_ref(), deadline, amount]
}

entrypoint!(process);

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    match tag {
        0 => fund(program_id, accounts, rest),
        1 => claim(program_id, accounts, rest),
        2 => refund(program_id, accounts, rest),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

/// fund: [refunder(signer,writable), lock(writable PDA), system_program]
/// data: hashlock(32) claimant(32) deadline(i64 le) amount(u64 le)
fn fund(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    if data.len() != 32 + 32 + 8 + 8 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let it = &mut accounts.iter();
    let refunder = next_account_info(it)?;
    let lock_ai = next_account_info(it)?;
    let system = next_account_info(it)?;
    if !refunder.is_signer {
        return Err(ProgramError::MissingRequiredSignature);
    }

    let mut hashlock = [0u8; 32];
    hashlock.copy_from_slice(&data[0..32]);
    let claimant = Pubkey::try_from(&data[32..64]).map_err(|_| ProgramError::InvalidInstructionData)?;
    let deadline = i64::from_le_bytes(data[64..72].try_into().unwrap());
    let amount = u64::from_le_bytes(data[72..80].try_into().unwrap());

    if amount == 0 || claimant == Pubkey::default() {
        return Err(ProgramError::InvalidInstructionData);
    }
    let now = Clock::get()?.unix_timestamp;
    // An unbounded deadline makes the refund unreachable forever; too short a one cannot be funded and
    // confirmed on the other chain in time.
    if deadline < now + MIN_WINDOW || deadline > now + MAX_WINDOW {
        msg!("deadline outside the allowed window");
        return Err(ProgramError::InvalidInstructionData);
    }

    let d_le = deadline.to_le_bytes();
    let a_le = amount.to_le_bytes();
    let seeds = seeds_of(&hashlock, &claimant, refunder.key, &d_le, &a_le);
    let (expect, bump) = Pubkey::find_program_address(&seeds, program_id);
    if expect != *lock_ai.key {
        msg!("lock account is not the PDA for these terms");
        return Err(ProgramError::InvalidArgument);
    }
    if !lock_ai.data_is_empty() {
        msg!("a lock with these exact terms already exists");
        return Err(ProgramError::AccountAlreadyInitialized);
    }

    // The escrow is the account's own lamports: rent for the record, plus the swap amount on top.
    //
    // NOT `create_account`: that refuses an address that already holds lamports, and this address is
    // predictable from the order's public terms. A stranger could send it the rent minimum (~0.001 SOL)
    // and block the swap forever. So: top the balance up to what is needed, then allocate and assign —
    // the same three steps, each of which tolerates lamports being there already. Whatever a stranger
    // dropped in simply becomes part of the escrow and goes to whoever the lock pays out to.
    let rent = Rent::get()?.minimum_balance(LOCK_LEN);
    let lamports = rent.checked_add(amount).ok_or(ProgramError::ArithmeticOverflow)?;
    let bump_arr = [bump];
    let signer: [&[u8]; 7] = [seeds[0], seeds[1], seeds[2], seeds[3], seeds[4], seeds[5], &bump_arr];
    let have = lock_ai.lamports();
    if have < lamports {
        invoke(
            &system_instruction::transfer(refunder.key, lock_ai.key, lamports - have),
            &[refunder.clone(), lock_ai.clone(), system.clone()],
        )?;
    }
    invoke_signed(
        &system_instruction::allocate(lock_ai.key, LOCK_LEN as u64),
        &[lock_ai.clone(), system.clone()],
        &[&signer],
    )?;
    invoke_signed(
        &system_instruction::assign(lock_ai.key, program_id),
        &[lock_ai.clone(), system.clone()],
        &[&signer],
    )?;
    Lock { hashlock, claimant, refunder: *refunder.key, deadline, amount }
        .write(&mut lock_ai.try_borrow_mut_data()?);
    msg!("locked {} lamports until {}", amount, deadline);
    Ok(())
}

/// claim: [caller(signer), lock(writable PDA), claimant(writable)]   data: preimage(32)
/// Anyone may submit — a watchtower, the counterparty — but the lamports only ever go to the recorded
/// claimant, so submitting on someone's behalf is a favour, never a theft.
fn claim(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    if data.len() != 32 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let it = &mut accounts.iter();
    let caller = next_account_info(it)?;
    let lock_ai = next_account_info(it)?;
    let claimant_ai = next_account_info(it)?;
    if !caller.is_signer {
        return Err(ProgramError::MissingRequiredSignature);
    }
    if lock_ai.owner != program_id {
        return Err(ProgramError::IllegalOwner);
    }
    let lock = Lock::read(&lock_ai.try_borrow_data()?)?;
    if *claimant_ai.key != lock.claimant {
        msg!("that is not this lock's claimant");
        return Err(ProgramError::InvalidArgument);
    }
    // SHA-256 of the preimage, exactly what Bitcoin's OP_SHA256 and the EVM leg check.
    if hashv(&[data]).to_bytes() != lock.hashlock {
        msg!("bad preimage");
        return Err(ProgramError::InvalidArgument);
    }
    if Clock::get()?.unix_timestamp >= lock.deadline {
        msg!("expired — the claim window is closed");
        return Err(ProgramError::InvalidArgument);
    }
    // Drain the whole account: the swap amount AND the rent deposit go to the claimant, and the record
    // is zeroed so the same terms can never be claimed twice.
    let all = lock_ai.lamports();
    **lock_ai.try_borrow_mut_lamports()? = 0;
    **claimant_ai.try_borrow_mut_lamports()? = claimant_ai
        .lamports()
        .checked_add(all)
        .ok_or(ProgramError::ArithmeticOverflow)?;
    lock_ai.try_borrow_mut_data()?.fill(0);
    msg!("claimed {} lamports", all);
    Ok(())
}

/// refund: [caller(signer), lock(writable PDA), refunder(writable)]
/// Also permissionless: at or after the deadline the lamports can only go back to whoever funded them.
fn refund(program_id: &Pubkey, accounts: &[AccountInfo], _data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let caller = next_account_info(it)?;
    let lock_ai = next_account_info(it)?;
    let refunder_ai = next_account_info(it)?;
    if !caller.is_signer {
        return Err(ProgramError::MissingRequiredSignature);
    }
    if lock_ai.owner != program_id {
        return Err(ProgramError::IllegalOwner);
    }
    let lock = Lock::read(&lock_ai.try_borrow_data()?)?;
    if *refunder_ai.key != lock.refunder {
        msg!("that is not this lock's funder");
        return Err(ProgramError::InvalidArgument);
    }
    if Clock::get()?.unix_timestamp < lock.deadline {
        msg!("not yet — the claim window is still open");
        return Err(ProgramError::InvalidArgument);
    }
    let all = lock_ai.lamports();
    **lock_ai.try_borrow_mut_lamports()? = 0;
    **refunder_ai.try_borrow_mut_lamports()? = refunder_ai
        .lamports()
        .checked_add(all)
        .ok_or(ProgramError::ArithmeticOverflow)?;
    lock_ai.try_borrow_mut_data()?.fill(0);
    msg!("refunded {} lamports", all);
    Ok(())
}
