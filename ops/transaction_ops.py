import asyncio
import json
import os.path
import time

import msgpack

from Curve25519 import sign, verify, unhex
from ops.account_ops import get_account, reflect_transaction
from ops.address_ops import proof_sender, make_address
from ops.address_ops import validate_address
from ops.block_ops import get_block_number
from compounder import compound_send_transaction
from config import get_config
from config import get_timestamp_seconds
from ops.data_ops import sort_list_dict, get_home, get_byte_size
from hashing import create_nonce, blake2b_hash, canonical_bytes
from ops.key_ops import load_keys
from ops.log_ops import get_logger
from ops.peer_ops import load_ips
from ops import kv_ops
from protocol import (CHAIN_ID, MIN_TX_FEE, EPOCH_LENGTH, SLASH_BOND_PENALTY, B_MIN, FINALITY_DEPTH,
                      BLOB_MAX_BYTES, MAX_BLOB_BYTES_PER_BLOCK, BRIDGE_ESCROW, DIVIDEND_POOL,
                      POSW_T, POSW_S, POSW_K, POSW_ANCHOR_OFFSET,
                      HTLC_ESCROW, HTLC_MIN_TIMELOCK, HTLC_MAX_TIMELOCK, SHIELD_ESCROW)


def _is_hex(s) -> bool:
    return isinstance(s, str) and len(s) % 2 == 0 and len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)
import aiohttp


async def get_recommneded_fee(target, port, base_fee, logger):
    try:
        url_construct = f"http://{target}:{port}/get_recommended_fee"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['fee'] + base_fee
    except Exception as e:
        logger.warning(f"Failed to get recommended fee: {e}")


async def get_target_block(target, port, logger):
    try:
        url_construct = f"http://{target}:{port}/get_latest_block"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['block_number'] + 2
    except Exception as e:
        logger.warning(f"Failed to get target block: {e}")


def remove_outdated_transactions(transaction_list, block_number):
    cleaned = []
    for transaction in transaction_list:
        if block_number < transaction["target_block"] < block_number + 360:
            cleaned.append(transaction)

    return cleaned


def get_transaction(txid, logger):
    """return transaction based on txid via a single indexed lookup"""
    try:
        entry = kv_ops.tx_get(txid)
        if not entry:
            return None

        block = get_block_number(number=entry["block_number"])
        if not block:
            return None

        for transaction in block["block_transactions"]:
            if transaction["txid"] == txid:
                return transaction

        return None

    except Exception as e:
        logger.error(f"Failed to get transaction {txid}: {e}")
        return None


def construct_attestation_tx(keydict, target_epoch, target_hash, target_block):
    """Build a SIGNED FFG attestation tx (#6) from a bonded validator's keydict: attests checkpoint
    (target_epoch, target_hash). Fee-exempt, zero-amount; pubkey-once carries public_key (the node
    relays its own attestations so its pubkey is established). target_block must be inside target_epoch."""
    tx = {"sender": keydict["address"], "recipient": "attest", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "target_hash": target_hash},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_commit_tx(keydict, target_epoch, commitment, target_block):
    """Build a SIGNED RANDAO commit tx (#7): a bonded validator publishes a secret's commitment for
    target_epoch's beacon (submitted in epoch E-2). Fee-exempt, zero-amount."""
    tx = {"sender": keydict["address"], "recipient": "commit", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "commitment": commitment},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_reveal_tx(keydict, target_epoch, secret, target_block):
    """Build a SIGNED RANDAO reveal tx (#7): opens the validator's prior commitment, contributing the
    secret to target_epoch's beacon (submitted in epoch E-1's finalized window). Fee-exempt."""
    tx = {"sender": keydict["address"], "recipient": "reveal", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "secret": secret},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bond_tx(keydict, amount, fee, target_block):
    """Build a SIGNED bond tx (used by the node's unattended AUTO-BOND loop): moves `amount` raw from
    the sender's spendable balance into bonded stake. A bond is an ordinary transfer whose recipient is
    the reserved name "bond" (account_ops.reflect_transaction handles the balance->bonded move), so the
    normal fee applies. Pubkey-once carries public_key (always safe; the node's pubkey is established)."""
    tx = {"sender": keydict["address"], "recipient": "bond", "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def blob_payload_size(payload) -> int:
    """True canonical byte length of a blob payload (for the DA size cap) — deterministic across nodes."""
    return len(canonical_bytes(payload))


def block_blob_bytes(transactions) -> int:
    """Total opaque blob bytes carried by a block's transactions (data-availability weight)."""
    return sum(blob_payload_size(t.get("data")) for t in transactions if t.get("recipient") == "blob")


def assert_block_blob_cap(transactions):
    """CONSENSUS check (doc/execution-layer.md §3.3): a single block may not carry more than
    MAX_BLOB_BYTES_PER_BLOCK of blob data, so DA growth stays within what phones download/relay."""
    total = block_blob_bytes(transactions)
    assert total <= MAX_BLOB_BYTES_PER_BLOCK, \
        f"Block blob bytes {total} exceed per-block cap {MAX_BLOB_BYTES_PER_BLOCK}"
    return True


def cap_block_blobs(transactions, logger=None):
    """Assembly helper: keep every non-blob tx, but admit blob txs (deterministically, in txid order)
    only while their cumulative payload stays within MAX_BLOB_BYTES_PER_BLOCK — so an assembled block
    always passes assert_block_blob_cap. Every honest producer drops the SAME excess blobs (txid order),
    so the built block is identical across nodes. A dropped blob must be resubmitted at a later target."""
    out, used = [], 0
    for t in sorted(transactions, key=lambda x: x.get("txid", "")):
        if t.get("recipient") == "blob":
            sz = blob_payload_size(t.get("data"))
            if used + sz > MAX_BLOB_BYTES_PER_BLOCK:
                if logger:
                    logger.warning(f"DA cap: dropping blob {t.get('txid', '')[:12]}… ({sz}B) from block")
                continue
            used += sz
        out.append(t)
    return out


def construct_blob_tx(keydict, payload, target_block, fee):
    """Build a SIGNED data-availability blob tx: recipient is the reserved name "blob"; the OPAQUE
    execution-layer payload rides in `data`. L1 orders + stores it and burns the fee, never decoding it."""
    tx = {"sender": keydict["address"], "recipient": "blob", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": payload,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_settle_tx(keydict, exec_cursor, state_root, target_block):
    """Build a SIGNED execution-layer settlement attestation: recipient 'settle', data
    {exec_cursor, state_root}, fee-exempt (fee 0). Posted by a bonded validator running an exec node."""
    tx = {"sender": keydict["address"], "recipient": "settle", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"exec_cursor": int(exec_cursor), "state_root": state_root},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def _treasury_spend_body(recipient, amount, memo, nonce, expiry):
    from hashing import treasury_proposal_id
    memo = memo or ""
    return {"pid": treasury_proposal_id(recipient, amount, memo, nonce, expiry),
            "spend": {"recipient": recipient, "amount": int(amount), "memo": memo, "nonce": nonce, "expiry": int(expiry)}}


def construct_treasury_vote_tx(keydict, recipient, amount, memo, nonce, target_block, expiry, choice="yes", fee=None):
    """Build a SIGNED treasury vote (doc/treasury.md §3.3): recipient 'treasury_vote', cast by a bonded validator.
    Carries a small anti-spam FEE + the full spend + its id, so the vote binds to EXACTLY that payout (recipient,
    amount, AND expiry block). `choice` is 'yes' (approve) or 'no' (oppose/withdraw); re-voting overwrites."""
    body = _treasury_spend_body(recipient, amount, memo, nonce, expiry); body["choice"] = choice
    tx = {"sender": keydict["address"], "recipient": "treasury_vote", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": body,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": int(MIN_TX_FEE if fee is None else fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_treasury_execute_tx(keydict, recipient, amount, memo, nonce, target_block, expiry, fee=None):
    """Build a SIGNED treasury PAYOUT trigger (doc/treasury.md §3.3): recipient 'treasury_execute'. Carries a small
    anti-spam FEE. Pays the proposal out once the bonded quorum has approved it (and only at/before its expiry)."""
    tx = {"sender": keydict["address"], "recipient": "treasury_execute", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": _treasury_spend_body(recipient, amount, memo, nonce, expiry),
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": int(MIN_TX_FEE if fee is None else fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bridge_deposit_tx(keydict, amount, target_block, fee):
    """Build a SIGNED bridge DEPOSIT: recipient 'bridge', amount locked into escrow; exec node credits it."""
    tx = {"sender": keydict["address"], "recipient": "bridge", "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "", "nonce": create_nonce(),
          "public_key": keydict["public_key"], "target_block": int(target_block),
          "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bridge_withdraw_tx(keydict, addr, amount, nonce, proof, target_block):
    """Build a SIGNED bridge EXIT: recipient 'bridge_withdraw', fee-exempt, data carries the Merkle proof
    that {addr, amount, nonce} is in the settled execution-layer root."""
    tx = {"sender": keydict["address"], "recipient": "bridge_withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"addr": addr, "amount": int(amount), "nonce": nonce, "proof": proof},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_dividend_withdraw_tx(keydict, addr, amount, nonce, proof, target_block):
    """Build a SIGNED presence-dividend COLLECTION claim: recipient 'dividend_withdraw', fee-exempt, data
    carries the Merkle proof that {addr, amount, nonce} is in the settled execution-layer root."""
    tx = {"sender": keydict["address"], "recipient": "dividend_withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"addr": addr, "amount": int(amount), "nonce": nonce, "proof": proof},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_alias_tx(keydict, op, name, target_block, fee, to=None):
    """Build a SIGNED alias op tx (op in {"register","transfer","unregister"}); recipient is the reserved
    name "alias" and the operation rides in `data`. `to` is the new owner for a transfer. amount is 0."""
    data = {"op": op, "name": name}
    if op == "transfer":
        data["to"] = to
    tx = {"sender": keydict["address"], "recipient": "alias", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": data,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "target_block": int(target_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def reserved_uniqueness_key(tx):
    """AUDIT FIX (in-block uniqueness): the key under which a reserved-recipient tx may appear AT MOST
    ONCE in a block — None for ordinary transfers (deduped by spending/txid). Used by BOTH block
    assembly (drop duplicates) and verify_block (reject duplicates), keeping them consistent. Without
    it, duplicate reserved txs in one block all validate against parent state and all apply, enabling:
    K `withdraw`s draining one unbond (slash-escape / chain-halt), duplicate `slash` over-burn/halt,
    and heartbeat/reveal DUPSORT desync forks. Returns a hashable tuple."""
    r = tx.get("recipient")
    try:
        if r in ("withdraw", "unbond", "register"):
            return (r, tx["sender"])                                  # one per sender per block
        if r in ("attest", "commit"):
            return (r, tx["sender"], (tx.get("data") or {}).get("target_epoch"))
        if r == "reveal":
            return ("reveal", (tx.get("data") or {}).get("secret"))   # dedup by secret (cross-validator too)
        if r == "slash":
            d = tx.get("data") or {}
            return ("slash", make_address(d["public_key"]), d["block_number"])
        if r == "alias":
            return ("alias", (tx.get("data") or {}).get("name"))     # one op per name per block
        if r == "settle":
            return ("settle", tx["sender"], (tx.get("data") or {}).get("exec_cursor"))  # one per (validator, cursor)
        if r == "bridge_withdraw":
            d = tx.get("data") or {}
            return ("bridge_withdraw", d.get("addr"), d.get("nonce"))                    # one claim per (addr, nonce)
        if r == "dividend_withdraw":
            d = tx.get("data") or {}
            return ("dividend_withdraw", d.get("addr"), d.get("nonce"))                  # one dividend claim per (addr, nonce)
        if r in ("htlc_claim", "htlc_refund"):
            return ("htlc_settle", (tx.get("data") or {}).get("htlc_id"))               # one claim OR refund per HTLC per block
        if r == "unshield":
            d = tx.get("data") or {}
            return ("unshield", d.get("addr"), d.get("nonce"))                          # one unshield exit per (addr, nonce)
        if r == "treasury_vote":
            return ("treasury_vote", tx["sender"], (tx.get("data") or {}).get("pid"))    # one vote per (validator, pid) per block
        if r == "treasury_execute":
            return ("treasury_execute", (tx.get("data") or {}).get("pid"))               # one payout per pid per block
    except Exception:
        return ("malformed", tx.get("txid"))   # unique-ish; the tx is rejected by validate_transaction
    return None


def dedupe_reserved(transactions):
    """Drop duplicate reserved txs (same reserved_uniqueness_key), keeping the first. Used by block
    assembly so an honest producer never builds a block verify_block would reject for duplicates."""
    seen, out = set(), []
    for t in transactions:
        k = reserved_uniqueness_key(t)
        if k is not None:
            if k in seen:
                continue
            seen.add(k)
        out.append(t)
    return out


def assert_unique_reserved(transactions):
    """Raise if a block contains two reserved txs with the same reserved_uniqueness_key (verify side)."""
    seen = set()
    for t in transactions:
        k = reserved_uniqueness_key(t)
        if k is not None:
            if k in seen:
                raise ValueError(f"Duplicate reserved transaction in block: {k}")
            seen.add(k)


def create_txid(transaction):
    # canonical encoding (sorted keys) commits the whole body — incl. chain_id — so the signature
    # (over the txid) binds every field and cannot be replayed cross-chain. PUBKEY-ONCE (#19): the
    # `public_key` is EXCLUDED from the preimage — it is a recoverable authentication witness (bound
    # to the sender address by proof_sender, stored on-chain on first use), not part of the tx
    # identity — so a later tx may OMIT the 1312-byte ML-DSA key and still produce the same txid.
    # The browser light-miner computes the identical txid (canonical_bytes, public_key excluded).
    body = {k: v for k, v in transaction.items() if k != "public_key"}
    return blake2b_hash(body)


def validate_transaction(transaction, logger, block_height):
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert transaction.get("chain_id") == CHAIN_ID, "Wrong or missing chain id"
    assert validate_origin(transaction), "Invalid origin"
    # SENDER must be a real keyed address — never a reserved protocol pseudo-recipient.
    assert validate_address(transaction["sender"], allow_reserved=False), f"Invalid sender {transaction['sender']}"
    # RECIPIENT (the target) must be a checksum-valid address OR a reserved protocol recipient
    # (bond/unbond/register/heartbeat/alias/…) OR a REGISTERED ALIAS name (send-to-alias). A malformed/
    # typo target with a bad checksum, or an unregistered alias, is rejected.
    _recip = transaction["recipient"]
    if not validate_address(_recip):
        from ops import alias_ops
        assert alias_ops.resolve_alias(_recip) is not None, f"Invalid recipient {_recip}"
    assert isinstance(transaction["fee"], int) and not isinstance(transaction["fee"], bool), "Transaction fee is not an integer"
    # amount must be a non-negative integer (not a bool, not a float): a float would
    # satisfy the old check_balance comparison and corrupt the integer-satoshi ledger
    assert isinstance(transaction["amount"], int) and not isinstance(transaction["amount"], bool), "Transaction amount is not an integer"
    assert transaction["amount"] >= 0, "Transaction amount lower than zero"
    assert len(transaction["txid"]) >= 64

    recipient = transaction["recipient"]
    if recipient == "slash":
        # SLASHING (#15 step 5C): a FEE-EXEMPT tx whose `data` carries an equivocation proof — the
        # same identity validly signed two blocks at one slot. Anyone may report it (the proof is
        # the anti-spam: it can't be forged, and one-per-(offender,height) blocks replay). The
        # offender must currently hold >= SLASH_BOND_PENALTY so apply_slash never floors (revert-safe).
        from ops.block_ops import verify_equivocation_proof
        assert transaction["amount"] == 0, "Slash tx must have zero amount"
        assert transaction["fee"] == 0, "Slash tx is fee-exempt (fee must be 0)"
        result = verify_equivocation_proof(transaction.get("data"))
        assert result, "Invalid or missing equivocation proof"
        offender, height = result
        assert not kv_ops.slash_exists(offender, height), "This offence is already slashed (replay)"
        offender_acc = get_account(offender, create_on_error=False)
        assert offender_acc and offender_acc.get("bonded", 0) >= SLASH_BOND_PENALTY, \
            "Offender holds insufficient bonded stake to slash"
    elif recipient == "attest":
        # FFG attestation (#6): a BONDED validator attests the CURRENT epoch's checkpoint (the first
        # block of the epoch its target_block falls in). Fee-exempt validator duty; one per validator
        # per epoch (the attestation index rejects a second -> no on-chain double-vote). data carries
        # {target_epoch, target_hash}; target_hash must equal the real checkpoint block hash.
        from ops.block_ops import get_block_hash_by_number
        from ops.mining_ops import epoch_of
        assert transaction["amount"] == 0, "Attest tx must have zero amount"
        assert transaction["fee"] == 0, "Attest tx is fee-exempt (fee must be 0)"
        data = transaction.get("data") or {}
        epoch = data.get("target_epoch")
        target_hash = data.get("target_hash")
        assert isinstance(epoch, int) and not isinstance(epoch, bool), "Attest target_epoch must be an int"
        assert epoch == transaction["target_block"] // EPOCH_LENGTH, "Attest target_epoch != target_block's epoch"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Attester is not a bonded validator"
        assert not kv_ops.attestation_exists(epoch, transaction["sender"]), "Validator already attested this epoch"
        assert target_hash and get_block_hash_by_number(epoch * EPOCH_LENGTH) == target_hash, \
            "Attest target_hash is not the epoch checkpoint"
    elif recipient in ("commit", "reveal"):
        # COMMIT-REVEAL RANDAO (#7): bonded validators COMMIT a secret's hash in epoch E-2 and REVEAL
        # the secret in epoch E-1's FINALIZED window; the secrets seed epoch E's beacon. Fee-exempt
        # bonded duty. Committing BEFORE the seeded beacon is revealed kills just-in-time grinding.
        from ops.mining_ops import epoch_of, beacon_commitment
        assert transaction["amount"] == 0, "Commit/reveal tx must have zero amount"
        assert transaction["fee"] == 0, "Commit/reveal tx is fee-exempt (fee must be 0)"
        data = transaction.get("data") or {}
        E = data.get("target_epoch")
        assert isinstance(E, int) and not isinstance(E, bool) and E >= 2, "target_epoch must be an int >= 2"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Commit/reveal sender is not a bonded validator"
        tb = transaction["target_block"]
        if recipient == "commit":
            # commit must land in epoch E-2 (before E-1's reveal window), one per (sender, E)
            assert epoch_of(tb) == E - 2, "Commit must target a block in epoch E-2"
            assert data.get("commitment"), "Commit missing commitment"
            assert kv_ops.commit_get(transaction["sender"], E) is None, "Already committed for this epoch"
        else:  # reveal
            # reveal must land in epoch E-1's FINALIZED window (so the seed is immutable when E begins),
            # and must open the sender's own prior commitment.
            lo = (E - 1) * EPOCH_LENGTH
            hi = E * EPOCH_LENGTH - FINALITY_DEPTH - 1
            assert lo <= tb <= hi, "Reveal must land in epoch E-1's finalized window"
            secret = data.get("secret")
            commitment = kv_ops.commit_get(transaction["sender"], E)
            assert commitment, "No matching commit for this reveal"
            assert secret and beacon_commitment(secret) == commitment, "Reveal does not open the commitment"
            # AUDIT FIX: each secret may seed the beacon at most once — the DUPSORT row dedups identical
            # secrets but does not reject the second tx, so a reorg can over-delete the shared row and
            # desync epoch_beacon (whole-epoch producer fork). Rejecting an already-present secret also
            # blocks cross-validator commitment-copying.
            assert secret not in kv_ops.reveals_for_epoch(E), "This secret is already revealed for the epoch"
    elif recipient in ("unbond", "withdraw"):
        # UNBOND DELAY: fee-exempt actions on the sender's OWN stake. `unbond` requests a release (coins
        # stay bonded + slashable); `withdraw` claims it only at/after the matured release_block. Bound
        # to target_block (the deterministic landing block) so the mempool gate and block validation agree.
        assert transaction["fee"] == 0, "unbond/withdraw is fee-exempt (fee must be 0)"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc, "unbond/withdraw from an account with no stake"
        pending = kv_ops.unbond_get(transaction["sender"])
        if recipient == "unbond":
            assert transaction["amount"] > 0, "unbond amount must be positive"
            assert acc.get("bonded", 0) >= transaction["amount"], "unbond amount exceeds bonded stake"
            assert pending is None, "an unbond is already pending (one withdrawal at a time)"
        else:  # withdraw
            assert pending, "no pending unbond to withdraw"
            assert transaction["target_block"] >= pending["release_block"], \
                "unbond has not matured yet (BOND_UNLOCK_DELAY)"
            data = transaction.get("data") or {}
            assert data.get("amount") == pending["amount"] and data.get("release_block") == pending["release_block"], \
                "withdraw data does not match the pending unbond"
            assert acc.get("bonded", 0) >= pending["amount"], "bonded stake is below the pending unbond"
    elif recipient == "register":
        # OPEN-lane entry/renewal: FEE-EXEMPT (a zero-balance newcomer can't pay) and moves no coins.
        assert transaction["amount"] == 0, "register tx must have zero amount"
        assert transaction["fee"] == 0, "register tx is fee-exempt (fee must be 0)"
        # SEQUENTIAL Proof-of-Work (doc/ip-spoofing-and-sybil.md, Appendix A): a non-parallelizable hash-chain
        # PoSW so a GPU can't mint identities in bulk. The challenge binds sender ‖ hash of block
        # (target_block − POSW_ANCHOR_OFFSET) — a finalized, stable block — so the proof is un-precomputable
        # far ahead and non-reusable. `register` is a RENEWABLE presence LEASE and the SINGLE presence signal
        # (no separate heartbeat): a fresh recert keeps you eligible for POSW_LEASE_EPOCHS (doc/presence-dividend.md §2.4).
        from ops import posw
        from ops.block_ops import get_block_hash_by_number
        anchor = get_block_hash_by_number(max(0, transaction["target_block"] - POSW_ANCHOR_OFFSET))
        assert anchor, "PoSW anchor block not found"
        proof = transaction.get("posw")
        assert proof, "Missing registration PoSW"
        # CONSENSUS registration-rate difficulty: the required sequential-work count scales with recent
        # registration volume, keyed off the FINALIZED anchor epoch so every node computes the SAME requirement
        # and rejects an under-worked proof (a modified node can't register cheaply). See ops/reg_difficulty.py.
        from ops.reg_difficulty import required_posw_t
        from ops.mining_ops import epoch_of
        req_t = required_posw_t(epoch_of(max(0, transaction["target_block"] - POSW_ANCHOR_OFFSET)))
        assert posw.verify(posw.challenge_bytes(transaction["sender"], anchor), proof,
                           req_t, POSW_S, POSW_K), "Invalid registration PoSW (or below the required difficulty)"
    elif recipient == "alias":
        # ALIAS op (register / transfer / unregister): validate the op, name, ownership + fee floor.
        from ops import alias_ops
        alias_ops.validate_alias_op(transaction)
    elif recipient == "blob":
        # DATA-AVAILABILITY blob (execution-layer Phase 1): envelope-only checks. L1 orders + stores the
        # opaque payload and never decodes it. Zero amount, a non-empty payload within the size cap, and
        # a paid DA fee (>= MIN_TX_FEE, burned). The sender must afford the fee (enforced at reflect).
        assert transaction["amount"] == 0, "Blob tx must have zero amount"
        assert transaction["fee"] >= MIN_TX_FEE, f"Blob DA fee below minimum {MIN_TX_FEE}"
        payload = transaction.get("data")
        assert payload not in (None, "", {}, []), "Blob tx must carry a data payload"
        assert blob_payload_size(payload) <= BLOB_MAX_BYTES, f"Blob payload exceeds {BLOB_MAX_BYTES} bytes"
    elif recipient == "settle":
        # EXECUTION-LAYER SETTLEMENT (Phase 2): a BONDED validator attests an exec-layer checkpoint
        # {exec_cursor, state_root}. Fee-exempt validator duty; one attestation per (validator, cursor).
        assert transaction["amount"] == 0, "Settle tx must have zero amount"
        assert transaction["fee"] == 0, "Settle tx is fee-exempt (fee must be 0)"
        data = transaction.get("data") or {}
        cursor = data.get("exec_cursor")
        root = data.get("state_root")
        assert isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0, "Settle exec_cursor must be a non-negative int"
        assert isinstance(root, str) and len(root) == 64 and all(c in "0123456789abcdef" for c in root), "Settle state_root must be 64-hex"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Settle sender is not a bonded validator"
        assert not kv_ops.settlement_exists(cursor, transaction["sender"]), "Validator already settled this exec_cursor"
    elif recipient == "bridge":
        # BRIDGE DEPOSIT (Phase 2): lock L1 coins into escrow; an exec node credits the sender exec-side.
        assert transaction["amount"] > 0, "Bridge deposit amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"Bridge deposit fee below minimum {MIN_TX_FEE}"
    elif recipient == "bridge_withdraw":
        # BRIDGE EXIT (Phase 2): prove the withdrawal {addr, amount, nonce} is in the bonded-quorum SETTLED
        # execution-layer root; L1 verifies that ONE Merkle proof, checks the nullifier + escrow, releases.
        from ops.settlement_ops import latest_settled
        from hashing import verify_merkle_proof, withdrawal_leaf
        assert transaction["amount"] == 0, "bridge_withdraw carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "bridge_withdraw is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        assert addr == transaction["sender"], "bridge_withdraw must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad withdraw amount"
        assert isinstance(nonce, str) and isinstance(proof, list), "bad withdraw nonce/proof"
        _cur, settled_root = latest_settled()
        assert settled_root, "no settled execution-layer root yet"
        assert verify_merkle_proof(withdrawal_leaf(addr, amount, nonce), proof, settled_root), \
            "withdrawal is not proven against the settled execution-layer root"
        assert not kv_ops.bridge_nullifier_exists(addr, nonce), "this withdrawal was already claimed"
        escrow = get_account(BRIDGE_ESCROW, create_on_error=False)
        assert escrow and escrow.get("balance", 0) >= amount, "bridge escrow underfunded"
    elif recipient == "dividend_withdraw":
        # DIVIDEND COLLECTION (doc/presence-dividend.md): prove {addr, amount, nonce} is in the bonded-quorum
        # SETTLED execution-layer root; L1 verifies that ONE Merkle proof, checks the nullifier + pool funding,
        # then releases `amount` from the DIVIDEND_POOL to the claimant. Fee-exempt, self-claimed.
        from ops.settlement_ops import latest_settled
        from hashing import verify_merkle_proof, dividend_leaf
        assert transaction["amount"] == 0, "dividend_withdraw carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "dividend_withdraw is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        assert addr == transaction["sender"], "dividend_withdraw must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad dividend amount"
        assert isinstance(nonce, str) and isinstance(proof, list), "bad dividend nonce/proof"
        _cur, settled_root = latest_settled()
        assert settled_root, "no settled execution-layer root yet"
        assert verify_merkle_proof(dividend_leaf(addr, amount, nonce), proof, settled_root), \
            "dividend collection is not proven against the settled execution-layer root"
        assert not kv_ops.dividend_nullifier_exists(addr, nonce), "this dividend was already collected"
        pool = get_account(DIVIDEND_POOL, create_on_error=False)
        assert pool and pool.get("balance", 0) >= amount, "dividend pool underfunded"
    elif recipient == "treasury_vote":
        # TREASURY GOVERNANCE (doc/treasury.md §3.3): a BONDED validator votes to APPROVE a treasury_spend
        # proposal. Fee-exempt duty (like `settle`); one vote per (validator, pid). ELIGIBILITY = real bonded
        # stake (bonded >= B_MIN) — the open, capital-free lane never votes on money (that would reopen the
        # Sybil faucet). The vote carries the full spend so its id is verifiable + displayable; the id binds
        # the approval to EXACTLY that payout, so a passing vote can never be redirected.
        from hashing import treasury_proposal_id
        from protocol import RESERVED_RECIPIENTS, TREASURY_PROPOSAL_MAX_TTL
        assert transaction["amount"] == 0, "treasury_vote must have zero amount"
        assert transaction["fee"] >= MIN_TX_FEE, f"treasury_vote fee below minimum {MIN_TX_FEE}"   # not free -> no spam faucet
        data = transaction.get("data") or {}
        spend, pid = data.get("spend") or {}, data.get("pid")
        sr, sa, memo, snonce, sexpiry = spend.get("recipient"), spend.get("amount"), spend.get("memo", ""), spend.get("nonce"), spend.get("expiry")
        assert isinstance(sr, str) and sr.startswith("ndo") and len(sr) == 49, "treasury spend recipient must be a normal address"
        assert sr not in RESERVED_RECIPIENTS, "treasury spend recipient cannot be a reserved recipient"
        assert isinstance(sa, int) and not isinstance(sa, bool) and sa > 0, "treasury spend amount must be a positive int"
        assert isinstance(snonce, str) and 0 < len(snonce) <= 64, "treasury spend nonce must be 1..64 chars"
        assert isinstance(memo, str) and len(memo) <= 256, "treasury spend memo must be a string (<= 256 chars)"
        assert isinstance(sexpiry, int) and not isinstance(sexpiry, bool) and sexpiry > 0, "treasury spend needs a positive int expiry block"
        assert pid == treasury_proposal_id(sr, sa, memo, snonce, sexpiry), "pid does not match the spend content"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "treasury_vote sender is not a bonded validator"
        assert acc.get("balance", 0) >= transaction["fee"], "treasury_vote sender cannot afford the fee"
        # the proposal's expiry must be in the future (you can't vote on an already-expired proposal) and no more
        # than TREASURY_PROPOSAL_MAX_TTL out — bounds stale execution + the size of the live proposal set.
        assert transaction["target_block"] <= sexpiry <= transaction["target_block"] + TREASURY_PROPOSAL_MAX_TTL, \
            "proposal expiry must be >= this block and <= this block + TREASURY_PROPOSAL_MAX_TTL"
        # CHANGE/WITHDRAW: re-voting is allowed and OVERWRITES the prior vote (revert-symmetric in reflect).
        # "yes" approves at the snapshot weight; "no" withdraws/opposes (counts as 0). Choice is outside the pid
        # (it's per-vote, not per-proposal), so it never affects which payout the id authorizes.
        choice = data.get("choice", "yes")
        assert choice in ("yes", "no"), "treasury_vote choice must be 'yes' or 'no'"
    elif recipient == "treasury_execute":
        # TREASURY PAYOUT (doc/treasury.md §3.3): pay out a proposal the bonded quorum APPROVED. Anyone may
        # trigger it. Carries a FEE (so an execute-flood — each forces an O(accounts) registry scan — isn't free).
        # Gated on: the 2/3 bonded quorum, a per-proposal cap vs the CURRENT treasury balance, funding, and a
        # one-shot nullifier. CHEAP checks run FIRST; the registry-scanning quorum check runs LAST.
        from hashing import treasury_proposal_id
        from ops.settlement_ops import treasury_justified
        from ops.account_ops import get_bonded_registry
        from ops.mining_ops import epoch_of
        from protocol import TREASURY_ADDRESS, TREASURY_MAX_SPEND_BPS, BPS_DENOM, RESERVED_RECIPIENTS
        assert transaction["amount"] == 0, "treasury_execute carries no L1 amount (amount is in data)"
        assert transaction["fee"] >= MIN_TX_FEE, f"treasury_execute fee below minimum {MIN_TX_FEE}"
        data = transaction.get("data") or {}
        spend, pid = data.get("spend") or {}, data.get("pid")
        sr, sa, memo, snonce, sexpiry = spend.get("recipient"), spend.get("amount"), spend.get("memo", ""), spend.get("nonce"), spend.get("expiry")
        assert isinstance(sr, str) and sr.startswith("ndo") and len(sr) == 49, "bad treasury spend recipient"
        assert sr not in RESERVED_RECIPIENTS, "treasury spend recipient cannot be a reserved recipient"
        assert isinstance(sa, int) and not isinstance(sa, bool) and sa > 0, "bad treasury spend amount"
        assert isinstance(snonce, str) and 0 < len(snonce) <= 64 and isinstance(memo, str) and len(memo) <= 256, "bad treasury spend nonce/memo"
        assert isinstance(sexpiry, int) and not isinstance(sexpiry, bool) and sexpiry > 0, "treasury spend needs a positive int expiry block"
        assert pid == treasury_proposal_id(sr, sa, memo, snonce, sexpiry), "pid does not match the spend content"
        assert not kv_ops.treasury_executed_exists(pid), "this proposal was already executed"
        assert transaction["target_block"] <= sexpiry, "this proposal has expired (past its bound expiry block)"
        sender_acc = get_account(transaction["sender"], create_on_error=False)
        assert sender_acc and sender_acc.get("balance", 0) >= transaction["fee"], "treasury_execute sender cannot afford the fee"
        assert kv_ops.treasury_voters(pid), "no votes recorded for this proposal"          # cheap gate BEFORE the O(N) scan
        treasury = get_account(TREASURY_ADDRESS, create_on_error=False)
        bal = treasury.get("balance", 0) if treasury else 0
        assert bal >= sa, "treasury underfunded for this payout"
        assert sa * BPS_DENOM <= bal * TREASURY_MAX_SPEND_BPS, "treasury spend exceeds the per-proposal cap (% of balance)"
        assert treasury_justified(pid, get_bonded_registry(), epoch_of(transaction["target_block"])), \
            "treasury proposal has not reached the bonded quorum"
    elif recipient == "htlc_lock":
        # HTLC LOCK (cross-chain atomic swap): escrow `amount` under a SHA-256 hashlock + block-height timelock.
        data = transaction.get("data") or {}
        h = transaction["target_block"]                          # deterministic landing height (mempool == build)
        assert transaction["amount"] > 0, "HTLC lock amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"HTLC lock fee below minimum {MIN_TX_FEE}"
        claimant, hashlock, expiry = data.get("claimant"), data.get("hashlock"), data.get("expiry")
        assert isinstance(claimant, str) and claimant.startswith("ndo") and len(claimant) == 49, "bad HTLC claimant address"
        assert claimant != transaction["sender"], "HTLC claimant must differ from the sender"
        assert isinstance(hashlock, str) and len(hashlock) == 64 and _is_hex(hashlock), "HTLC hashlock must be 32-byte SHA-256 hex"
        assert isinstance(expiry, int) and not isinstance(expiry, bool), "HTLC expiry must be an int block height"
        assert h + HTLC_MIN_TIMELOCK <= expiry <= h + HTLC_MAX_TIMELOCK, "HTLC expiry outside the allowed timelock window"
    elif recipient == "htlc_claim":
        # HTLC CLAIM: reveal the preimage before expiry. Fee-EXEMPT so a zero-balance claimant can still claim.
        import hashlib
        data = transaction.get("data") or {}
        h = transaction["target_block"]
        assert transaction["amount"] == 0, "htlc_claim carries no amount"
        assert transaction["fee"] == 0, "htlc_claim is fee-exempt"
        hid, preimage = data.get("htlc_id"), data.get("preimage")
        assert isinstance(hid, str) and hid, "bad HTLC id"
        assert _is_hex(preimage) and len(preimage) <= 128, "HTLC preimage must be hex (<= 64 bytes)"
        doc = kv_ops.htlc_get(hid)
        assert doc and doc.get("status") == "open", "no OPEN HTLC with that id"
        assert transaction["sender"] == doc["claimant"], "only the claimant may claim this HTLC"
        assert h < int(doc["expiry"]), "HTLC has expired — the claim window is closed"
        assert hashlib.sha256(bytes.fromhex(preimage)).hexdigest() == doc["hashlock"], "preimage does not match the hashlock"
    elif recipient == "htlc_refund":
        # HTLC REFUND: the original sender reclaims an unclaimed lock after expiry. Fee-EXEMPT.
        data = transaction.get("data") or {}
        h = transaction["target_block"]
        assert transaction["amount"] == 0, "htlc_refund carries no amount"
        assert transaction["fee"] == 0, "htlc_refund is fee-exempt"
        hid = data.get("htlc_id")
        assert isinstance(hid, str) and hid, "bad HTLC id"
        doc = kv_ops.htlc_get(hid)
        assert doc and doc.get("status") == "open", "no OPEN HTLC with that id"
        assert transaction["sender"] == doc["sender"], "only the original sender may refund this HTLC"
        assert h >= int(doc["expiry"]), "HTLC has not expired yet — refund is not available"
    elif recipient == "shield":
        # SHIELD DEPOSIT into the shielded pool: lock coins in escrow; the exec node adds the note commitment(s).
        assert transaction["amount"] > 0, "shield amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"shield fee below minimum {MIN_TX_FEE}"
        data = transaction.get("data") or {}
        if data.get("field"):                                        # Phase-2 field-native note (single commitment)
            # C-2: the exec node BINDS the note value to this escrowed amount by recomputing
            # commit(amount, owner, rho) itself, so the deposit must carry (owner, rho), not a free-choice cm.
            assert data.get("owner") is not None and data.get("rho") is not None, "field shield needs owner + rho"
        else:                                                        # transparent-phase note openings
            assert isinstance(data.get("out_commitments"), list) and data.get("out_commitments"), "shield needs output note commitments"
    elif recipient == "unshield":
        # UNSHIELD EXIT: prove {addr, amount, nonce} is in the bonded-quorum SETTLED exec root; release escrow.
        from ops.settlement_ops import latest_settled
        from hashing import verify_merkle_proof, unshield_leaf
        assert transaction["amount"] == 0, "unshield carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "unshield is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        assert addr == transaction["sender"], "unshield must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad unshield amount"
        assert isinstance(nonce, str) and isinstance(proof, list), "bad unshield nonce/proof"
        _cur, settled_root = latest_settled()
        assert settled_root, "no settled execution-layer root yet"
        assert verify_merkle_proof(unshield_leaf(addr, amount, nonce), proof, settled_root), \
            "unshield is not proven against the settled execution-layer root"
        assert not kv_ops.shield_nullifier_exists(addr, nonce), "this unshield was already claimed"
        escrow = get_account(SHIELD_ESCROW, create_on_error=False)
        assert escrow and escrow.get("balance", 0) >= amount, "shield escrow underfunded"
    else:
        # ordinary transfer / bond / send-to-alias: deterministic minimum-fee floor (anti-spam), block 1
        assert transaction["fee"] >= MIN_TX_FEE, f"Transaction fee below minimum {MIN_TX_FEE}"

    # bind the signature to the FULL body: the signature only covers the txid, so without
    # recomputing the txid from the body an attacker could keep a valid (sender, public_key,
    # txid, signature) and swap recipient/amount. The block path previously skipped this.
    assert validate_txid(transaction, logger=logger), "Transaction id does not match its contents"
    return True


def min_from_transaction_pool(transactions: list, key="fee") -> dict:
    """returns dictionary from a list of dictionaries with minimum value"""
    return min(sort_list_dict(transactions), key=lambda transaction: transaction[key])


def max_from_transaction_pool(transactions: list, key="fee") -> dict:
    """returns dictionary from a list of dictionaries with maximum value"""
    return max(sort_list_dict(transactions), key=lambda transaction: transaction[key])


def sort_transaction_pool(transactions: list, key="txid") -> list:
    """sorts list of dictionaries based on a dictionary value"""
    return sorted(
        sort_list_dict(transactions), key=lambda transaction: transaction[key]
    )


def get_transactions_of_account(account, min_block: int, logger, limit: int = 1000):
    """history for an account, from the consolidated KV index.

    A UNION of the two DUPSORT secondary indexes (tx_by_sender, tx_by_recipient) — each ordered by
    block — replaces the old OR-over-an-unusable-index full scan, deduped and ordered by block, then
    txids are grouped by block so each block file is read at most once instead of once per tx."""
    fetched = kv_ops.tx_of_account(account, min_block, limit)  # [(block_number, txid)], block-ordered

    txids_by_block = {}
    block_order = []
    for block_number, txid in fetched:
        if block_number not in txids_by_block:
            txids_by_block[block_number] = set()
            block_order.append(block_number)
        txids_by_block[block_number].add(txid)

    all_txs = []
    for block_number in block_order:
        block = get_block_number(number=block_number)
        if not block:
            continue
        wanted = txids_by_block[block_number]
        for transaction in block["block_transactions"]:
            if transaction["txid"] in wanted:
                all_txs.append(transaction)

    return {"transactions": all_txs}


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 10000000000):.10f}"


def to_raw_amount(amount: [int, float]) -> int:
    return int(float(amount) * 10000000000)


def check_balance(account, amount, fee):
    """for single transaction, check if the fee and the amount spend are allowable"""
    balance = get_account(account)["balance"]
    assert (
            balance - amount - fee > 0 <= amount
    ), f"{account} spending more than owned in a single transaction"
    return True


def get_senders(transaction_pool: list) -> list:
    sender_pool = []
    for transaction in transaction_pool:
        if transaction["sender"] not in sender_pool:
            sender_pool.append(transaction["sender"])
    return sender_pool


def _spend_costs(tx):
    """(spendable-balance cost, bonded-stake cost) of a tx for overspend checks.
    An `unbond` draws its `amount` from bonded stake (only the fee leaves balance); every
    other tx — including `bond` — consumes amount+fee from spendable balance."""
    if tx["recipient"] == "unbond":
        return tx["fee"], tx["amount"]
    return tx["amount"] + tx["fee"], 0


def validate_single_spending(transaction_pool: list, transaction):
    """validate spending of a single spender against his transactions in a transaction pool"""
    pool = transaction_pool + [transaction]  # future state (no mutation of the caller's list)
    sender = transaction["sender"]
    acc = get_account(sender)
    balance, bonded = acc["balance"], acc["bonded"]

    balance_spent = 0
    bonded_spent = 0
    for pool_tx in pool:
        if pool_tx["sender"] == sender:
            b_cost, bond_cost = _spend_costs(pool_tx)
            balance_spent += b_cost
            bonded_spent += bond_cost
            assert balance_spent <= balance, "Overspending balance"
            assert bonded_spent <= bonded, "Overspending bonded stake"
    return True


def validate_all_spending(transaction_pool: list):
    """validate spending of all spenders in a transaction pool against their balance AND
    their bonded stake (unbond draws from bonded, not from spendable balance)."""
    for sender in get_senders(transaction_pool):
        acc = get_account(sender)
        balance, bonded = acc["balance"], acc["bonded"]

        balance_spent = 0
        bonded_spent = 0
        for pool_tx in transaction_pool:
            if pool_tx["sender"] == sender:
                b_cost, bond_cost = _spend_costs(pool_tx)
                balance_spent += b_cost
                bonded_spent += bond_cost
                assert balance_spent <= balance, "Overspending balance"
                assert bonded_spent <= bonded, "Overspending bonded stake"
    return True


def validate_origin(transaction: dict):
    """signature is verified over the txid (which canonically commits the whole body,
    including chain_id); it is not itself part of the signed message."""

    transaction = transaction.copy()
    signature = transaction["signature"]
    del transaction["signature"]

    # PUBKEY-ONCE (#19): the tx MAY omit public_key. If omitted, recover the sender's pubkey
    # established on-chain by an earlier tx (every address's pubkey is fixed, bound by proof_sender).
    # The very FIRST tx from an address MUST carry it (nothing to recover yet).
    public_key = transaction.get("public_key")
    if not public_key:
        account = get_account(transaction["sender"], create_on_error=False)
        public_key = account.get("public_key") if account else None
        assert public_key, "Missing public_key and no on-chain pubkey for sender (first tx must carry it)"

    assert proof_sender(
        sender=transaction["sender"],
        public_key=public_key
    ), "Invalid sender"

    assert verify(
        signed=signature,
        message=unhex(transaction["txid"]),
        public_key=public_key,
    ), "Invalid signature"

    return True


def get_base_fee(transaction):
    try:
        tx_copy = transaction.copy()
        base_fee = get_byte_size(tx_copy)
        return base_fee

    except Exception as e:
        logger.info(f'Failed to calculate base fee: {e}')
        return False


def validate_base_fee(transaction, logger):
    try:
        tx_copy = transaction.copy()
        fee = tx_copy["fee"]
        tx_copy.pop("fee")
        tx_copy.pop("signature")
        tx_copy.pop("txid")

        if fee >= get_base_fee(tx_copy):
            return True
        else:
            return False

    except Exception as e:
        logger.info(f'Failed to validate base fee: {e}')
        return False


def validate_txid(transaction, logger):
    try:
        tx_copy = transaction.copy()
        txid_to_check = tx_copy["txid"]
        tx_copy.pop("txid")
        tx_copy.pop("signature")
        txid_genuine = create_txid(tx_copy)
        if txid_genuine == txid_to_check:
            return True
        else:
            return False
    except Exception as e:
        logger.info(f'Failed to match transaction to its id: {e}')
        return False


def create_transaction(draft, private_key, fee):
    """construct transaction, then add txid, then add signature as last"""
    transaction_message = draft.copy()
    transaction_message.update(fee=fee)

    txid = create_txid(transaction_message)
    transaction_message.update(txid=txid)

    signature = sign(private_key=private_key, message=unhex(txid))
    transaction_message.update(signature=signature)

    # from ops.log_ops import get_logger
    # print(validate_txid(transaction=transaction_message, logger=get_logger()))
    # time.sleep(10000)

    return transaction_message


def draft_transaction(sender, recipient, amount, public_key, timestamp, data, target_block):
    """construct to be able to calculate base fee, signature and txid are not present here"""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": amount,
        "timestamp": timestamp,
        "data": data,
        "nonce": create_nonce(),
        "public_key": public_key,
        "target_block": target_block,
        "chain_id": CHAIN_ID,
    }

    return transaction_message


def draft_open_lane_transaction(sender, recipient, public_key, timestamp, target_block,
                                pow_nonce=None, epoch=None):
    """Draft a FEE-EXEMPT open-lane mining tx (recipient 'register' or 'heartbeat'): amount 0, and
    create_transaction will set fee 0. Carries pow_nonce (register) or epoch (heartbeat) in the
    SIGNED body so both are committed by the txid. The browser light-miner builds the identical
    structure (canonical_bytes reproducibility)."""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": 0,
        "timestamp": timestamp,
        "data": "",
        "nonce": create_nonce(),
        "public_key": public_key,
        "target_block": target_block,
        "chain_id": CHAIN_ID,
    }
    if pow_nonce is not None:
        transaction_message["pow_nonce"] = pow_nonce
    if epoch is not None:
        transaction_message["epoch"] = epoch
    return transaction_message


def unindex_transactions(block, logger, block_height):
    """Revert a block's txs: undo the balance/state changes AND delete the exact primary + DUPSORT
    secondary index entries written on apply (the block||txid dup encoding makes each delete
    unambiguous). Runs inside the rollback write txn (kv_ops uses the active txn), so it is atomic
    with the rest of the rollback — no per-statement retry loop is needed or possible under LMDB."""
    for transaction in block["block_transactions"]:
        reflect_transaction(transaction=transaction,
                            revert=True,
                            logger=logger,
                            block_height=block_height)
        from ops import alias_ops
        _recip = alias_ops.resolve_alias(transaction["recipient"]) or transaction["recipient"]
        kv_ops.tx_index_del(txid=transaction["txid"],
                            block_number=block_height,
                            sender=transaction["sender"],
                            recipient=_recip)
        # PUBKEY-ONCE revert: after this tx's index entry is removed, if the sender has NO remaining
        # indexed tx, this block held its first-ever tx -> clear the established pubkey so the account
        # doc returns byte-identical to before (revert-symmetric). A sender with earlier-block txs
        # keeps its pubkey (established earlier).
        if not kv_ops.tx_of_account(transaction["sender"], min_block=0, limit=1):
            kv_ops.account_del_field(transaction["sender"], "public_key")


def index_transactions(block, sorted_transactions, logger):
    block_height = block["block_number"]

    # Apply balance/state changes AND write the tx index (primary + DUPSORT secondaries) for every
    # tx. Runs inside the incorporate write txn (kv_ops uses the active txn), so the balances and the
    # index commit atomically with the rest of the block.
    for transaction in sorted_transactions:
        reflect_transaction(transaction=transaction,
                            logger=logger,
                            block_height=block_height)
        # Index under the RESOLVED recipient (an alias -> its owner address), matching where
        # reflect_transaction actually credited the coins — otherwise a send-to-alias is filed under the
        # alias STRING and never appears in the recipient's own transaction history.
        from ops import alias_ops
        _recip = alias_ops.resolve_alias(transaction["recipient"]) or transaction["recipient"]
        kv_ops.tx_index_put(txid=transaction["txid"],
                            block_number=block_height,
                            sender=transaction["sender"],
                            recipient=_recip)
        # PUBKEY-ONCE (#19): record the sender's pubkey on its FIRST indexed tx (the one carrying it),
        # so later txs from this sender (e.g. every-epoch heartbeats) may omit the 1312-byte key.
        # Idempotent (skip if already stored); revert is handled symmetrically in unindex_transactions.
        pk = transaction.get("public_key")
        if pk:
            sender_acc = get_account(transaction["sender"], create_on_error=False)
            if sender_acc is not None and not sender_acc.get("public_key"):
                kv_ops.account_set_field(transaction["sender"], "public_key", pk)


if __name__ == "__main__":
    logger = get_logger(file="transactions.log", logger_name="transactions_logger")
    # print(get_account("noob23"))
    LOCAL = False

    key_dict = load_keys()
    address = key_dict["address"]
    recipient = "ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29"
    private_key = key_dict["private_key"]
    public_key = key_dict["public_key"]
    amount = to_raw_amount(0)
    data = {"data_id": "seek_id", "data_content": "some_actual_content"}

    config = get_config()
    ip = config["ip"]

    port = config["port"]

    if LOCAL:
        ips = ["127.0.0.1"]
    else:
        ips = asyncio.run(load_ips(logger=logger,
                                   fail_storage=[],
                                   unreachable={},
                                   port=port))

    for x in range(0, 50000):
        try:
            draft = draft_transaction(sender=address,
                                      recipient=recipient,
                                      amount=to_raw_amount(amount),
                                      data=data,
                                      public_key=public_key,
                                      timestamp=get_timestamp_seconds(),
                                      target_block=asyncio.run(get_target_block(target=ips[0],
                                                                                port=port,
                                                                                logger=logger)))
            fee = asyncio.run(get_recommneded_fee(
                target=ips[0],
                port=port,
                base_fee=get_base_fee(transaction=draft),
                logger=logger))

            if fee > 500:
                fee = 500

            transaction = create_transaction(draft=draft,
                                             private_key=private_key,
                                             fee=fee
                                             )

            print(transaction)
            print(validate_transaction(transaction, logger=logger, block_height=111112))

            fails = []
            results = asyncio.run(compound_send_transaction(ips=ips,
                                                            port=port,
                                                            fail_storage=fails,
                                                            logger=logger,
                                                            transaction=transaction,
                                                            semaphore=asyncio.Semaphore(50)))

            print(f"Submitted to {len(results)} nodes successfully")

            # time.sleep(5)
        except Exception as e:
            print(e)
            raise

    # tx_pool = json.loads(requests.get(f"http://{ip}:{port}/transaction_pool").text, timeout=5)
