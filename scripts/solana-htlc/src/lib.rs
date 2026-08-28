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
    instruction::{AccountMeta, Instruction},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    hash::hashv,
    msg,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::{pubkey, Pubkey},
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
    /// `Pubkey::default()` for a native-SOL lock; otherwise the SPL mint the escrow holds. A token lock's
    /// value sits in the PDA's associated token account, whose only authority is the PDA itself.
    pub mint: Pubkey,
}

pub const LOCK_LEN: usize = 32 + 32 + 32 + 8 + 8 + 32;
/// The SPL Token and Associated Token Account programs, by id: the token instructions are built by hand
/// (Transfer = 3, CloseAccount = 9, ATA CreateIdempotent = 1) so this crate carries no token dependency.
pub const TOKEN_PROGRAM: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
pub const ATA_PROGRAM: Pubkey = pubkey!("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
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
        dst[112..144].copy_from_slice(self.mint.as_ref());
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
            mint: Pubkey::try_from(&src[112..144]).map_err(|_| ProgramError::InvalidAccountData)?,
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
/// A token lock adds the mint as a seventh seed: the same terms in a different token are a different
/// agreement, so they must be a different address.
fn seeds_tok<'a>(
    hashlock: &'a [u8; 32],
    claimant: &'a Pubkey,
    refunder: &'a Pubkey,
    deadline: &'a [u8; 8],
    amount: &'a [u8; 8],
    mint: &'a Pubkey,
) -> [&'a [u8]; 7] {
    [b"htlc", hashlock, claimant.as_ref(), refunder.as_ref(), deadline, amount, mint.as_ref()]
}

/// The associated token account of `owner` for `mint` — derived here, never trusted from the caller.
fn ata_of(owner: &Pubkey, mint: &Pubkey) -> Pubkey {
    Pubkey::find_program_address(&[owner.as_ref(), TOKEN_PROGRAM.as_ref(), mint.as_ref()], &ATA_PROGRAM).0
}
fn ix_ata_create_idempotent(payer: &Pubkey, ata: &Pubkey, owner: &Pubkey, mint: &Pubkey) -> Instruction {
    Instruction {
        program_id: ATA_PROGRAM,
        accounts: vec![
            AccountMeta::new(*payer, true),
            AccountMeta::new(*ata, false),
            AccountMeta::new_readonly(*owner, false),
            AccountMeta::new_readonly(*mint, false),
            AccountMeta::new_readonly(solana_program::system_program::ID, false),
            AccountMeta::new_readonly(TOKEN_PROGRAM, false),
        ],
        data: vec![1],
    }
}
fn ix_token_transfer(src: &Pubkey, dst: &Pubkey, authority: &Pubkey, amount: u64) -> Instruction {
    let mut data = vec![3u8];
    data.extend_from_slice(&amount.to_le_bytes());
    Instruction {
        program_id: TOKEN_PROGRAM,
        accounts: vec![AccountMeta::new(*src, false), AccountMeta::new(*dst, false), AccountMeta::new_readonly(*authority, true)],
        data,
    }
}
fn ix_token_close(acct: &Pubkey, dest: &Pubkey, owner: &Pubkey) -> Instruction {
    Instruction {
        program_id: TOKEN_PROGRAM,
        accounts: vec![AccountMeta::new(*acct, false), AccountMeta::new(*dest, false), AccountMeta::new_readonly(*owner, true)],
        data: vec![9],
    }
}

entrypoint!(process);

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    match tag {
        0 => fund(program_id, accounts, rest),
        1 => claim(program_id, accounts, rest),
        2 => refund(program_id, accounts, rest),
        3 => fund_token(program_id, accounts, rest),
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
    Lock { hashlock, claimant, refunder: *refunder.key, deadline, amount, mint: Pubkey::default() }
        .write(&mut lock_ai.try_borrow_mut_data()?);
    msg!("locked {} lamports until {}", amount, deadline);
    Ok(())
}

/// fund_token: [refunder(signer,writable), lock(writable PDA), system_program, refunder_ata(writable),
///              lock_ata(writable), mint, token_program, ata_program]
/// data: hashlock(32) claimant(32) deadline(i64 le) amount(u64 le) mint(32)
/// The record lives in the PDA (rent only); the tokens live in the PDA's associated token account, which
/// this instruction creates. Only the PDA can sign a transfer out of it — i.e. only this program.
fn fund_token(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    if data.len() != 32 + 32 + 8 + 8 + 32 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let it = &mut accounts.iter();
    let refunder = next_account_info(it)?;
    let lock_ai = next_account_info(it)?;
    let system = next_account_info(it)?;
    let src_ata = next_account_info(it)?;
    let lock_ata = next_account_info(it)?;
    let mint_ai = next_account_info(it)?;
    let token_prog = next_account_info(it)?;
    let ata_prog = next_account_info(it)?;
    if !refunder.is_signer {
        return Err(ProgramError::MissingRequiredSignature);
    }
    if *token_prog.key != TOKEN_PROGRAM || *ata_prog.key != ATA_PROGRAM || mint_ai.owner != &TOKEN_PROGRAM {
        msg!("token / ATA program or mint is not what it claims");
        return Err(ProgramError::IncorrectProgramId);
    }
    let mut hashlock = [0u8; 32];
    hashlock.copy_from_slice(&data[0..32]);
    let claimant = Pubkey::try_from(&data[32..64]).map_err(|_| ProgramError::InvalidInstructionData)?;
    let deadline = i64::from_le_bytes(data[64..72].try_into().unwrap());
    let amount = u64::from_le_bytes(data[72..80].try_into().unwrap());
    let mint = Pubkey::try_from(&data[80..112]).map_err(|_| ProgramError::InvalidInstructionData)?;
    if amount == 0 || claimant == Pubkey::default() || mint != *mint_ai.key {
        return Err(ProgramError::InvalidInstructionData);
    }
    let now = Clock::get()?.unix_timestamp;
    if deadline < now + MIN_WINDOW || deadline > now + MAX_WINDOW {
        msg!("deadline outside the allowed window");
        return Err(ProgramError::InvalidInstructionData);
    }
    let d_le = deadline.to_le_bytes();
    let a_le = amount.to_le_bytes();
    let seeds = seeds_tok(&hashlock, &claimant, refunder.key, &d_le, &a_le, &mint);
    let (expect, bump) = Pubkey::find_program_address(&seeds, program_id);
    if expect != *lock_ai.key {
        msg!("lock account is not the PDA for these terms");
        return Err(ProgramError::InvalidArgument);
    }
    if !lock_ai.data_is_empty() {
        msg!("a lock with these exact terms already exists");
        return Err(ProgramError::AccountAlreadyInitialized);
    }
    if *lock_ata.key != ata_of(lock_ai.key, &mint) {
        msg!("lock token account is not the lock's ATA");
        return Err(ProgramError::InvalidArgument);
    }
    // the record: rent only, allocated the same dust-tolerant way as a native lock
    let rent = Rent::get()?.minimum_balance(LOCK_LEN);
    let bump_arr = [bump];
    let signer: [&[u8]; 8] = [seeds[0], seeds[1], seeds[2], seeds[3], seeds[4], seeds[5], seeds[6], &bump_arr];
    let have = lock_ai.lamports();
    if have < rent {
        invoke(&system_instruction::transfer(refunder.key, lock_ai.key, rent - have), &[refunder.clone(), lock_ai.clone(), system.clone()])?;
    }
    invoke_signed(&system_instruction::allocate(lock_ai.key, LOCK_LEN as u64), &[lock_ai.clone(), system.clone()], &[&signer])?;
    invoke_signed(&system_instruction::assign(lock_ai.key, program_id), &[lock_ai.clone(), system.clone()], &[&signer])?;
    // the escrow: the PDA's own token account (idempotent — pre-creating it cannot block the swap either)
    invoke(
        &ix_ata_create_idempotent(refunder.key, lock_ata.key, lock_ai.key, &mint),
        &[refunder.clone(), lock_ata.clone(), lock_ai.clone(), mint_ai.clone(), system.clone(), token_prog.clone(), ata_prog.clone()],
    )?;
    invoke(
        &ix_token_transfer(src_ata.key, lock_ata.key, refunder.key, amount),
        &[src_ata.clone(), lock_ata.clone(), refunder.clone(), token_prog.clone()],
    )?;
    Lock { hashlock, claimant, refunder: *refunder.key, deadline, amount, mint }
        .write(&mut lock_ai.try_borrow_mut_data()?);
    msg!("locked {} tokens of {} until {}", amount, mint, deadline);
    Ok(())
}

/// Move a token lock's escrow to `to` and close its token account. Extra accounts, after the three every
/// claim/refund carries: [lock_ata(w), to_ata(w), mint, token_program, ata_program, system_program].
/// The bump is re-derived from the record, so the caller supplies nothing the record does not prove.
fn release_tokens<'a>(
    program_id: &Pubkey,
    lock: &Lock,
    lock_ai: &AccountInfo<'a>,
    caller: &AccountInfo<'a>,
    to: &AccountInfo<'a>,
    it: &mut std::slice::Iter<'_, AccountInfo<'a>>,
) -> ProgramResult {
    let lock_ata = next_account_info(it)?;
    let to_ata = next_account_info(it)?;
    let mint_ai = next_account_info(it)?;
    let token_prog = next_account_info(it)?;
    let ata_prog = next_account_info(it)?;
    let system = next_account_info(it)?;
    if *token_prog.key != TOKEN_PROGRAM || *ata_prog.key != ATA_PROGRAM || *mint_ai.key != lock.mint {
        return Err(ProgramError::IncorrectProgramId);
    }
    if *lock_ata.key != ata_of(lock_ai.key, &lock.mint) || *to_ata.key != ata_of(to.key, &lock.mint) {
        msg!("token accounts are not the expected ATAs");
        return Err(ProgramError::InvalidArgument);
    }
    let d_le = lock.deadline.to_le_bytes();
    let a_le = lock.amount.to_le_bytes();
    let seeds = seeds_tok(&lock.hashlock, &lock.claimant, &lock.refunder, &d_le, &a_le, &lock.mint);
    let (expect, bump) = Pubkey::find_program_address(&seeds, program_id);
    if expect != *lock_ai.key {
        return Err(ProgramError::InvalidArgument);
    }
    let bump_arr = [bump];
    let signer: [&[u8]; 8] = [seeds[0], seeds[1], seeds[2], seeds[3], seeds[4], seeds[5], seeds[6], &bump_arr];
    // the recipient may never have held this token: create their ATA on the submitter's dime (rent is
    // tiny, and a permissionless claim must not fail on a missing account)
    invoke(
        &ix_ata_create_idempotent(caller.key, to_ata.key, to.key, &lock.mint),
        &[caller.clone(), to_ata.clone(), to.clone(), mint_ai.clone(), system.clone(), token_prog.clone(), ata_prog.clone()],
    )?;
    invoke_signed(
        &ix_token_transfer(lock_ata.key, to_ata.key, lock_ai.key, lock.amount),
        &[lock_ata.clone(), to_ata.clone(), lock_ai.clone(), token_prog.clone()],
        &[&signer],
    )?;
    // close the escrow's token account: its rent goes to the recipient along with the record's below
    invoke_signed(
        &ix_token_close(lock_ata.key, to.key, lock_ai.key),
        &[lock_ata.clone(), to.clone(), lock_ai.clone(), token_prog.clone()],
        &[&signer],
    )?;
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
    if lock.mint != Pubkey::default() {
        release_tokens(program_id, &lock, lock_ai, caller, claimant_ai, it)?;
    }
    // Drain the whole account: the swap amount (native) or the rent (token) goes to the claimant, and the
    // record is zeroed so the same terms can never be claimed twice.
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
    if lock.mint != Pubkey::default() {
        release_tokens(program_id, &lock, lock_ai, caller, refunder_ai, it)?;
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
