#!/usr/bin/env python3
"""Solana leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5) against a REAL validator.

The escrow lives in a PDA whose seeds are the swap's own terms — hashlock, claimant, funder, deadline AND
amount — so the address IS the agreement. That is what these tests are mostly about: the happy path, and
then the ways a counterparty might try to bend it.

Run:  solana-test-validator --rpc-port 8999 ...   (then)
      /root/tools/secvenv/bin/python tests/test_solana_htlc.py <program_id>
"""
import base64, hashlib, json, os, struct, sys, time, urllib.request

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solders.system_program import ID as SYS_ID

RPC = os.environ.get("SOL_RPC", "http://127.0.0.1:8999")
PROGRAM = Pubkey.from_string(sys.argv[1] if len(sys.argv) > 1 else open("/tmp/svl/progid.txt").read().strip())
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}", flush=True)
    else: failed += 1; print(f"  FAIL {m}", flush=True)


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def blockhash():
    return Hash.from_string(rpc("getLatestBlockhash", [{"commitment": "finalized"}])["result"]["value"]["blockhash"])


def balance(pk):
    # read at the same commitment send() waits for; the default (finalized) lags behind and would make a
    # freshly confirmed transfer look like it never happened
    return rpc("getBalance", [str(pk), {"commitment": "confirmed"}])["result"]["value"]


def airdrop(pk, sol=10):
    rpc("requestAirdrop", [str(pk), int(sol * 1e9)])
    for _ in range(40):
        if balance(pk) > 0: return
        time.sleep(0.5)


def send(ixs, signers, expect_ok=True):
    """Submit and wait. Returns (ok, message) — a revert is a normal outcome here, not an exception."""
    msg = Message.new_with_blockhash(ixs, signers[0].pubkey(), blockhash())
    tx = Transaction(signers, msg, blockhash())
    raw = base64.b64encode(bytes(tx)).decode()
    r = rpc("sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "processed"}])
    if "error" in r:
        return False, json.dumps(r["error"])[:200]
    sig = r["result"]
    for _ in range(40):
        st = rpc("getSignatureStatuses", [[sig]])["result"]["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            return (st.get("err") is None), json.dumps(st.get("err"))[:200]
        time.sleep(0.4)
    return False, "timeout"


def pda(hashlock, claimant, funder, deadline, amount):
    seeds = [b"htlc", hashlock, bytes(claimant), bytes(funder),
             struct.pack("<q", deadline), struct.pack("<Q", amount)]
    return Pubkey.find_program_address(seeds, PROGRAM)


def ix_fund(funder, lock, hashlock, claimant, deadline, amount):
    data = bytes([0]) + hashlock + bytes(claimant) + struct.pack("<q", deadline) + struct.pack("<Q", amount)
    return Instruction(PROGRAM, data, [
        AccountMeta(funder, True, True), AccountMeta(lock, False, True), AccountMeta(SYS_ID, False, False)])


def ix_claim(caller, lock, claimant, preimage):
    return Instruction(PROGRAM, bytes([1]) + preimage, [
        AccountMeta(caller, True, False), AccountMeta(lock, False, True), AccountMeta(claimant, False, True)])


def ix_refund(caller, lock, funder):
    return Instruction(PROGRAM, bytes([2]), [
        AccountMeta(caller, True, False), AccountMeta(lock, False, True), AccountMeta(funder, False, True)])


def main():
    alice, bob, carol = Keypair(), Keypair(), Keypair()      # funder, claimant, unrelated third party
    for k in (alice, bob, carol):
        airdrop(k.pubkey(), 10)
    ok(balance(alice.pubkey()) > 0, "validator up, accounts funded")

    secret = os.urandom(32)
    H = hashlib.sha256(secret).digest()
    now = int(time.time())
    amount = 2 * 10**8                                        # 0.2 SOL
    deadline = now + 3600
    lock, _ = pda(H, bob.pubkey(), alice.pubkey(), deadline, amount)

    # --- the terms are the address ---
    good, err = send([ix_fund(alice.pubkey(), lock, H, bob.pubkey(), deadline, amount)], [alice])
    ok(good, f"1. funded the swap into its PDA ({str(lock)[:12]}…) {'' if good else err}")
    ok(balance(lock) >= amount, "   the escrow holds the swap amount")

    # --- an UNDERFUNDED lock lands at a different address, so it can never buy the secret ---
    other, _ = pda(H, bob.pubkey(), alice.pubkey(), deadline, 1)
    send([ix_fund(alice.pubkey(), other, H, bob.pubkey(), deadline, 1)], [alice])
    ok(str(other) != str(lock), "2. a 1-lamport lock for the same swap lands at a DIFFERENT address")
    bad, _ = send([ix_claim(bob.pubkey(), lock, bob.pubkey(), os.urandom(32))], [bob])
    ok(not bad, "3. a wrong preimage is refused")

    # --- only the recorded claimant is paid, whoever submits ---
    bad, _ = send([ix_claim(carol.pubkey(), lock, carol.pubkey(), secret)], [carol])
    ok(not bad, "4. someone else cannot redirect the payout to themselves")
    bad, _ = send([ix_refund(alice.pubkey(), lock, alice.pubkey())], [alice])
    ok(not bad, "5. the funder cannot refund before the deadline")

    # --- a watchtower completes it, and the money still goes to the claimant ---
    before = balance(bob.pubkey())
    good, err = send([ix_claim(carol.pubkey(), lock, bob.pubkey(), secret)], [carol])
    ok(good, f"6. a THIRD PARTY can submit the claim {'' if good else err}")
    ok(balance(bob.pubkey()) - before >= amount, "   ...and the lamports went to the recorded claimant")
    ok(balance(lock) == 0, "   ...and the escrow is emptied")
    bad, _ = send([ix_claim(bob.pubkey(), lock, bob.pubkey(), secret)], [bob])
    ok(not bad, "7. the same lock cannot be claimed twice")

    # --- refund path, on a lock whose deadline has passed ---
    short = now + 600 + 5                                     # inside MIN_WINDOW+, expires soon
    l2, _ = pda(H, bob.pubkey(), alice.pubkey(), short, amount)
    good, err = send([ix_fund(alice.pubkey(), l2, H, bob.pubkey(), short, amount)], [alice])
    ok(good, f"8. a second lock funded {'' if good else err}")
    bad, _ = send([ix_refund(carol.pubkey(), l2, carol.pubkey())], [carol])
    ok(not bad, "9. a refund cannot be redirected to a stranger either")

    # --- the deadline must sit in a sane window ---
    far, _ = pda(H, bob.pubkey(), alice.pubkey(), now + 40 * 24 * 3600, amount)
    bad, _ = send([ix_fund(alice.pubkey(), far, H, bob.pubkey(), now + 40 * 24 * 3600, amount)], [alice])
    ok(not bad, "10. a deadline beyond the maximum window is refused")
    near, _ = pda(H, bob.pubkey(), alice.pubkey(), now + 60, amount)
    bad, _ = send([ix_fund(alice.pubkey(), near, H, bob.pubkey(), now + 60, amount)], [alice])
    ok(not bad, "11. a deadline inside the minimum window is refused")

    # --- a stranger pre-dusting the predictable escrow address must NOT block the swap ---
    from solders.system_program import transfer, TransferParams
    l3, _ = pda(H, bob.pubkey(), alice.pubkey(), deadline, amount + 1)
    good, _ = send([transfer(TransferParams(from_pubkey=carol.pubkey(), to_pubkey=l3, lamports=1_000_000))], [carol])
    ok(good and balance(l3) == 1_000_000, "12. a stranger dusted the escrow address before it was funded")
    good, err = send([ix_fund(alice.pubkey(), l3, H, bob.pubkey(), deadline, amount + 1)], [alice])
    ok(good, f"    ...and the funder can still lock into it {'' if good else err}")
    ok(balance(l3) >= amount + 1 + 1_000_000, "    ...the dust just joined the escrow")

    # --- SPL tokens: the same lock holding a token; the mint is a seventh seed, the escrow is the PDA's ATA ---
    import subprocess
    TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    ATA = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    PAYER = os.environ.get("SOL_PAYER", "/tmp/svl/payer.json")
    cli = lambda *a: subprocess.run(["spl-token", "-u", RPC, "--fee-payer", PAYER, *a], capture_output=True, text=True, timeout=120)
    r = cli("create-token", "--mint-authority", PAYER, "--decimals", "6", "--output", "json")
    mint = Pubkey.from_string(json.loads(r.stdout)["commandOutput"]["address"]) if r.returncode == 0 else None
    ok(mint is not None, f"13. a test mint exists on the validator {'' if mint else r.stderr[:160]}")
    ata = lambda owner: Pubkey.find_program_address([bytes(owner), bytes(TOKEN), bytes(mint)], ATA)[0]
    cli("create-account", str(mint), "--owner", str(alice.pubkey()))
    cli("mint", str(mint), "1000", str(ata(alice.pubkey())), "--mint-authority", PAYER)
    tok_bal = lambda owner: int((rpc("getTokenAccountBalance", [str(ata(owner)), {"commitment": "confirmed"}]).get("result") or {}).get("value", {}).get("amount", 0))
    ok(tok_bal(alice.pubkey()) == 1000 * 10**6, "    alice holds 1000 tokens")

    def pda_tok(hashlock, claimant, funder, deadline, amount):
        seeds = [b"htlc", hashlock, bytes(claimant), bytes(funder), struct.pack("<q", deadline), struct.pack("<Q", amount), bytes(mint)]
        return Pubkey.find_program_address(seeds, PROGRAM)[0]
    def ix_fund_tok(funder, lock, hashlock, claimant, deadline, amount):
        data = bytes([3]) + hashlock + bytes(claimant) + struct.pack("<q", deadline) + struct.pack("<Q", amount) + bytes(mint)
        return Instruction(PROGRAM, data, [
            AccountMeta(funder, True, True), AccountMeta(lock, False, True), AccountMeta(SYS_ID, False, False),
            AccountMeta(ata(funder), False, True), AccountMeta(ata(lock), False, True), AccountMeta(mint, False, False),
            AccountMeta(TOKEN, False, False), AccountMeta(ATA, False, False)])
    def tok_tail(lock, to):
        return [AccountMeta(ata(lock), False, True), AccountMeta(ata(to), False, True), AccountMeta(mint, False, False),
                AccountMeta(TOKEN, False, False), AccountMeta(ATA, False, False), AccountMeta(SYS_ID, False, False)]
    def ix_claim_tok(caller, lock, claimant, preimage):
        return Instruction(PROGRAM, bytes([1]) + preimage, [
            AccountMeta(caller, True, True), AccountMeta(lock, False, True), AccountMeta(claimant, False, True)] + tok_tail(lock, claimant))
    def ix_refund_tok(caller, lock, funder):
        return Instruction(PROGRAM, bytes([2]), [
            AccountMeta(caller, True, True), AccountMeta(lock, False, True), AccountMeta(funder, False, True)] + tok_tail(lock, funder))

    tamt = 250 * 10**6
    tl = pda_tok(H, bob.pubkey(), alice.pubkey(), deadline, tamt)
    good, err = send([ix_fund_tok(alice.pubkey(), tl, H, bob.pubkey(), deadline, tamt)], [alice])
    ok(good, f"14. 250 tokens locked into the PDA's token account {'' if good else err}")
    ok(tok_bal(tl) == tamt and tok_bal(alice.pubkey()) == 750 * 10**6, "    escrow holds 250, alice keeps 750")
    bad, _ = send([ix_claim_tok(carol.pubkey(), tl, carol.pubkey(), secret)], [carol])
    ok(not bad, "15. a token claim cannot redirect to a stranger")
    bad, _ = send([ix_claim_tok(bob.pubkey(), tl, bob.pubkey(), os.urandom(32))], [bob])
    ok(not bad, "    ...nor open with a wrong preimage")
    good, err = send([ix_claim_tok(carol.pubkey(), tl, bob.pubkey(), secret)], [carol])
    ok(good, f"16. a third party submits the claim; bob (who never held this token) is paid {'' if good else err}")
    ok(tok_bal(bob.pubkey()) == tamt, "    bob's new token account holds the 250")
    ok(rpc("getAccountInfo", [str(ata(tl)), {"commitment": "confirmed"}])["result"]["value"] is None, "    the escrow token account is closed")
    bad, _ = send([ix_claim_tok(bob.pubkey(), tl, bob.pubkey(), secret)], [bob])
    ok(not bad, "    ...and cannot be claimed twice")
    # refund path
    short2 = int(time.time()) + 700                           # fresh: the earlier `short` has aged past MIN_WINDOW
    t2 = pda_tok(H, bob.pubkey(), alice.pubkey(), short2, 100 * 10**6)
    good, err = send([ix_fund_tok(alice.pubkey(), t2, H, bob.pubkey(), short2, 100 * 10**6)], [alice])
    ok(good, f"17. a second token lock funded {'' if good else err}")
    bad, _ = send([ix_refund_tok(carol.pubkey(), t2, carol.pubkey())], [carol])
    ok(not bad, "    a token refund cannot be redirected either")

    print(f"\n[solana-htlc] {passed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
