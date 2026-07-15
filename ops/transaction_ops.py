import asyncio
import json


from signatures import sign, verify, unhex
from ops.account_ops import get_account, reflect_transaction
from ops.address_ops import proof_sender, make_address
from ops.address_ops import validate_address
from ops.block_ops import get_block_number
from compounder import compound_send_transaction
from config import get_config
from config import get_timestamp_seconds
from config import hostport
from ops.data_ops import sort_list_dict, get_byte_size
from hashing import create_nonce, blake2b_hash, canonical_bytes
from ops.key_ops import load_keys
from ops.log_ops import get_logger
from ops.peer_ops import load_ips
from ops import kv_ops
from protocol import (CHAIN_ID, MIN_TX_FEE, EPOCH_LENGTH, SLASH_BOND_PENALTY, B_MIN, FINALITY_DEPTH,
                      BLOB_MAX_BYTES, MAX_BLOB_BYTES_PER_BLOCK, BRIDGE_ESCROW, DIVIDEND_POOL,
                      POSW_S, POSW_K, POSW_ANCHOR_OFFSET, HTLC_MIN_TIMELOCK, TX_LANDING_WINDOW,
                      HTLC_MAX_TIMELOCK, SHIELD_ESCROW, RESERVED_RECIPIENTS, DEFAULT_NS, valid_namespace)


def _is_hex(s) -> bool:
    """non-empty, even-length (byte-aligned) hex string check"""
    return isinstance(s, str) and len(s) % 2 == 0 and len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)
import aiohttp


async def get_recommneded_fee(target, port, base_fee, logger):
    """Client-side helper: fetch a peer's congestion fee component and add the local size-based
    base_fee to get a fee that should clear the pool. None (logged warning) on failure."""
    try:
        url_construct = f"http://{hostport(target, port)}/get_recommended_fee"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['fee'] + base_fee
    except Exception as e:
        logger.warning(f"Failed to get recommended fee: {e}")


async def get_max_block(target, port, logger):
    """Client-side helper: ask a peer for its latest block and aim the new tx two blocks ahead, so it
    lands inside the acceptance window despite propagation lag. None (logged warning) on failure."""
    try:
        url_construct = f"http://{hostport(target, port)}/get_latest_block"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['block_number'] + 2
    except Exception as e:
        logger.warning(f"Failed to get target block: {e}")


def remove_outdated_transactions(transaction_list, block_number):
    """Mempool hygiene: keep only txs whose max_block is still ahead of the chain tip and within
    the TX_LANDING_WINDOW — anything outside can never be included, so holding it only bloats the pool."""
    cleaned = []
    for transaction in transaction_list:
        if block_number < transaction["max_block"] < block_number + TX_LANDING_WINDOW:
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


def construct_attestation_tx(keydict, target_epoch, target_hash, max_block):
    """Build a SIGNED FFG attestation tx (#6) from a bonded validator's keydict: attests checkpoint
    (target_epoch, target_hash). Fee-exempt, zero-amount; pubkey-once carries public_key (the node
    relays its own attestations so its pubkey is established). max_block must be inside target_epoch."""
    tx = {"sender": keydict["address"], "recipient": "attest", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "target_hash": target_hash},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


# Attestation-equivocation slash heights are namespaced ABOVE any real block height so an FFG double-vote
# slash for epoch E can never collide with a block-authorship slash at block height E.
_ATTEST_SLASH_BASE = 1 << 40


def _validate_attest_fields(data: dict, tb: int, sender: str):
    """FFG attest field rules, shared by the historical `attest` recipient and the `duty` attest
    section — byte-identical semantics (historical replay must never drift)."""
    from ops.block_ops import get_block_hash_by_number
    epoch = data.get("target_epoch")
    target_hash = data.get("target_hash")
    assert isinstance(epoch, int) and not isinstance(epoch, bool), "Attest target_epoch must be an int"
    assert epoch == tb // EPOCH_LENGTH, "Attest target_epoch != max_block's epoch"
    acc = get_account(sender, create_on_error=False)
    assert acc and acc.get("bonded", 0) >= B_MIN, "Attester is not a bonded validator"
    assert not kv_ops.attestation_exists(epoch, sender), "Validator already attested this epoch"
    assert target_hash and get_block_hash_by_number(epoch * EPOCH_LENGTH) == target_hash, \
        "Attest target_hash is not the epoch checkpoint"


def _validate_commit_fields(data: dict, tb: int, sender: str):
    """RANDAO commit field rules (shared historical/duty): lands in the target's E-2, one per (sender, E)."""
    from ops.mining_ops import epoch_of
    E = data.get("target_epoch")
    assert isinstance(E, int) and not isinstance(E, bool) and E >= 2, "target_epoch must be an int >= 2"
    acc = get_account(sender, create_on_error=False)
    assert acc and acc.get("bonded", 0) >= B_MIN, "Commit/reveal sender is not a bonded validator"
    assert epoch_of(tb) == E - 2, "Commit must target a block in epoch E-2"
    assert data.get("commitment"), "Commit missing commitment"
    assert kv_ops.commit_get(sender, E) is None, "Already committed for this epoch"


def _validate_reveal_fields(data: dict, tb: int, sender: str):
    """RANDAO reveal field rules (shared historical/duty): lands in the target's E-1 FINALIZED window,
    opens the sender's own commitment, and each secret seeds the beacon at most once (audit fix)."""
    from ops.mining_ops import beacon_commitment
    E = data.get("target_epoch")
    assert isinstance(E, int) and not isinstance(E, bool) and E >= 2, "target_epoch must be an int >= 2"
    acc = get_account(sender, create_on_error=False)
    assert acc and acc.get("bonded", 0) >= B_MIN, "Commit/reveal sender is not a bonded validator"
    lo = (E - 1) * EPOCH_LENGTH
    hi = E * EPOCH_LENGTH - FINALITY_DEPTH - 1
    assert lo <= tb <= hi, "Reveal must land in epoch E-1's finalized window"
    secret = data.get("secret")
    commitment = kv_ops.commit_get(sender, E)
    assert commitment, "No matching commit for this reveal"
    assert secret and beacon_commitment(secret) == commitment, "Reveal does not open the commitment"
    assert secret not in kv_ops.reveals_for_epoch(E), "This secret is already revealed for the epoch"


def construct_duty_tx(keydict, max_block, attest=None, commit=None, reveal=None):
    """Build the SIGNED merged per-epoch DUTY tx (doc/consensus-aggregation.md): the validator's FFG
    attest (landing epoch X), RANDAO commit (X+2) and reveal (X+1) sections — whichever are due —
    under ONE ML-DSA signature instead of three full txs. Fee-exempt committee duty; lands exactly
    at max_block like every timing-critical reserved tx."""
    data = {}
    if attest is not None:
        data["attest"] = attest
    if commit is not None:
        data["commit"] = commit
    if reveal is not None:
        data["reveal"] = reveal
    assert data, "duty tx needs at least one section"
    tx = {"sender": keydict["address"], "recipient": "duty", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": data, "nonce": create_nonce(),
          "max_block": max_block, "chain_id": CHAIN_ID, "fee": 0,
          "public_key": keydict["public_key"]}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def verify_attestation_equivocation_proof(proof):
    """Verify an FFG ATTESTATION double-vote: the SAME bonded validator SIGNED two attestations for the SAME
    target_epoch but DIFFERENT target_hash. proof = {"attest_a": <signed attest tx>, "attest_b": <signed
    attest tx>}. Returns (offender_address, target_epoch) when valid, else None. Unforgeable: only the
    key-holder can sign either attestation, and there is NO honest reason to attest two checkpoints for one
    epoch — so a valid proof is irrefutable evidence of a finality double-vote."""
    try:
        def _open(tx):
            if not isinstance(tx, dict) or tx.get("recipient") not in ("attest", "duty"):
                return None
            pk, sig, txid, sender = tx.get("public_key"), tx.get("signature"), tx.get("txid"), tx.get("sender")
            if not (pk and sig and txid and sender) or not isinstance(sig, str):
                return None
            if not proof_sender(public_key=pk, sender=sender):        # pubkey must hash to the claimed sender
                return None
            body = {k: v for k, v in tx.items() if k not in ("txid", "signature")}
            if create_txid(body) != txid:                              # txid binds the full attestation body
                return None
            if not verify(signed=sig, public_key=pk, message=unhex(txid)):
                return None
            d = tx.get("data") or {}
            if tx.get("recipient") == "duty":                          # attest section inside a merged duty tx
                d = d.get("attest") or {}
            return sender, d.get("target_epoch"), d.get("target_hash")
        ra = _open((proof or {}).get("attest_a")); rb = _open((proof or {}).get("attest_b"))
        if not ra or not rb:
            return None
        (sa, ea, ha), (sb, eb, hb) = ra, rb
        if sa != sb or ea != eb or not isinstance(ea, int) or isinstance(ea, bool) or ea < 0:
            return None
        if not ha or not hb or ha == hb:                               # must be two DIFFERENT checkpoints
            return None
        return sa, int(ea)
    except Exception:
        return None


def resolve_slash(data):
    """Resolve a slash proof — block-authorship OR FFG-attestation equivocation — to (offender, dedup_height).
    Attestation slashes are namespaced at _ATTEST_SLASH_BASE+epoch so they never collide with a block-height
    slash. Returns None if neither proof verifies. Shared by validate_transaction + reflect_transaction."""
    if isinstance(data, dict) and ("attest_a" in data or "attest_b" in data):
        r = verify_attestation_equivocation_proof(data)
        return (r[0], _ATTEST_SLASH_BASE + r[1]) if r else None
    from ops.block_ops import verify_equivocation_proof
    r = verify_equivocation_proof(data)
    return (r[0], r[1]) if r else None


def construct_commit_tx(keydict, target_epoch, commitment, max_block):
    """Build a SIGNED RANDAO commit tx (#7): a bonded validator publishes a secret's commitment for
    target_epoch's beacon (submitted in epoch E-2). Fee-exempt, zero-amount."""
    tx = {"sender": keydict["address"], "recipient": "commit", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "commitment": commitment},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_reveal_tx(keydict, target_epoch, secret, max_block):
    """Build a SIGNED RANDAO reveal tx (#7): opens the validator's prior commitment, contributing the
    secret to target_epoch's beacon (submitted in epoch E-1's finalized window). Fee-exempt."""
    tx = {"sender": keydict["address"], "recipient": "reveal", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"target_epoch": int(target_epoch), "secret": secret},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bond_tx(keydict, amount, fee, max_block):
    """Build a SIGNED bond tx (used by the node's unattended AUTO-BOND loop): moves `amount` raw from
    the sender's spendable balance into bonded stake. A bond is an ordinary transfer whose recipient is
    the reserved name "bond" (account_ops.reflect_transaction handles the balance->bonded move), so the
    normal fee applies. Pubkey-once carries public_key (always safe; the node's pubkey is established)."""
    tx = {"sender": keydict["address"], "recipient": "bond", "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_unbond_tx(keydict, amount, max_block):
    """Build a SIGNED unbond tx: moves `amount` raw from bonded stake back to spendable (after the unlock
    delay). FEE-EXEMPT — the node rejects a non-zero fee on an unbond, so a fully-bonded wallet can always
    exit. Mirror of construct_bond_tx; shared by the wallet, the CLI, and the headless agent."""
    tx = {"sender": keydict["address"], "recipient": "unbond", "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_register_tx(keydict, max_block, posw_proof):
    """Build a SIGNED open-lane registration/renewal tx. FEE-EXEMPT + zero-amount; carries the sequential
    PoSW proof (ops.posw.prove of posw.challenge_bytes(sender, anchor-block-hash)) that gates open-lane entry.
    posw rides in the signed body (create_txid commits it — only public_key is excluded), exactly like the
    browser's buildRegisterTx, so the node validates a CLI/agent registration identically to a wallet one."""
    tx = {"sender": keydict["address"], "recipient": "register", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0, "posw": posw_proof}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_msgkey_tx(keydict, kem_pub, max_block):
    """Build a SIGNED on-chain messaging-key tx. FEE-EXEMPT + zero-amount identity tx (recipient 'msgkey')
    that BINDS the sender's ML-KEM-768 encryption pubkey (`kem_pub`, 2368 hex chars) to their on-chain
    account, so anyone can DM them by address/alias with no off-chain prekey publish. kem_pub rides top-level
    in the SIGNED body (create_txid commits it — only public_key is excluded), exactly like register's `posw`,
    so the browser's buildMsgkeyTx and the node agree byte-for-byte. Key rotation is allowed (a later msgkey
    overwrites; apply_msgkey is revert-symmetric)."""
    tx = {"sender": keydict["address"], "recipient": "msgkey", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0, "kem_pub": kem_pub}
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


def construct_blob_tx(keydict, payload, max_block, fee, min_block=0):
    """Build a SIGNED data-availability blob tx: recipient is the reserved name "blob"; the OPAQUE
    execution-layer payload rides in `data`. L1 orders + stores it and burns the fee, never decoding it.
    min_block (submit_tip + TX_INCLUSION_DELAY) is the earliest height a producer may include it — see
    protocol.TX_INCLUSION_DELAY; 0 = immediate."""
    tx = {"sender": keydict["address"], "recipient": "blob", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": payload,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    if int(min_block) > 0:
        tx["min_block"] = int(min_block)
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_dividend_withdraw_tx(keydict, amount, nonce, proof, max_block):
    """Build a SIGNED presence-dividend claim: recipient 'dividend_withdraw', fee-exempt, self-claimed
    (data.addr == sender). Releases a COLLECTED {addr, amount, nonce} from the DIVIDEND_POOL once its
    Merkle proof verifies against the settled execution-layer root (validate_transaction checks that)."""
    tx = {"sender": keydict["address"], "recipient": "dividend_withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"addr": keydict["address"], "amount": int(amount), "nonce": str(nonce), "proof": proof},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_settle_tx(keydict, exec_cursor, state_root, max_block, ns=DEFAULT_NS):
    """Build a SIGNED execution-layer settlement attestation: recipient 'settle', data
    {exec_cursor, state_root[, ns]}, fee-exempt (fee 0). Posted by a bonded validator running an exec node.
    `ns` names the rollup namespace; the default namespace is omitted from `data` so default-layer settle txs
    stay byte-identical to the pre-namespace format."""
    d = {"exec_cursor": int(exec_cursor), "state_root": state_root}
    if ns != DEFAULT_NS:
        d["ns"] = ns
    tx = {"sender": keydict["address"], "recipient": "settle", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": d,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def _treasury_spend_body(recipient, amount, memo, nonce, expiry):
    """Canonical {pid, spend} payload shared by treasury vote AND execute txs, so both derive the
    proposal id from the SAME normalized fields (memo None -> "") and a vote can only ever authorize
    exactly the payout that gets executed."""
    from hashing import treasury_proposal_id
    memo = memo or ""
    return {"pid": treasury_proposal_id(recipient, amount, memo, nonce, expiry),
            "spend": {"recipient": recipient, "amount": int(amount), "memo": memo, "nonce": nonce, "expiry": int(expiry)}}


def construct_treasury_vote_tx(keydict, recipient, amount, memo, nonce, max_block, expiry, choice="yes", fee=None):
    """Build a SIGNED treasury vote (doc/treasury.md §3.3): recipient 'treasury_vote', cast by a bonded validator.
    Carries a small anti-spam FEE + the full spend + its id, so the vote binds to EXACTLY that payout (recipient,
    amount, AND expiry block). `choice` is 'yes' (approve) or 'no' (oppose/withdraw); re-voting overwrites."""
    body = _treasury_spend_body(recipient, amount, memo, nonce, expiry); body["choice"] = choice
    tx = {"sender": keydict["address"], "recipient": "treasury_vote", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": body,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(MIN_TX_FEE if fee is None else fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_treasury_execute_tx(keydict, recipient, amount, memo, nonce, max_block, expiry, fee=None):
    """Build a SIGNED treasury PAYOUT trigger (doc/treasury.md §3.3): recipient 'treasury_execute'. Carries a small
    anti-spam FEE. Pays the proposal out once the bonded quorum has approved it (and only at/before its expiry)."""
    tx = {"sender": keydict["address"], "recipient": "treasury_execute", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": _treasury_spend_body(recipient, amount, memo, nonce, expiry),
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(MIN_TX_FEE if fee is None else fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bridge_deposit_tx(keydict, amount, max_block, fee):
    """Build a SIGNED bridge DEPOSIT: recipient 'bridge', amount locked into escrow; exec node credits it."""
    tx = {"sender": keydict["address"], "recipient": "bridge", "amount": int(amount),
          "timestamp": get_timestamp_seconds(), "data": "", "nonce": create_nonce(),
          "public_key": keydict["public_key"], "max_block": int(max_block),
          "chain_id": CHAIN_ID, "fee": int(fee)}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_bridge_withdraw_tx(keydict, addr, amount, nonce, proof, max_block, ns=DEFAULT_NS):
    """Build a SIGNED bridge EXIT: recipient 'bridge_withdraw', fee-exempt, data carries the Merkle proof
    that {addr, amount, nonce} is in namespace `ns`'s settled execution-layer root (default ns omitted)."""
    d = {"addr": addr, "amount": int(amount), "nonce": nonce, "proof": proof}
    if ns != DEFAULT_NS:
        d["ns"] = ns
    tx = {"sender": keydict["address"], "recipient": "bridge_withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": d,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_xmsg_tx(keydict, from_ns, to_ns, message, proof, max_block):
    """Build a SIGNED cross-rollup message DELIVERY: recipient 'xmsg', fee-exempt, data carries the outbox
    `message` {seq, from, to_ns, data} + the Merkle `proof` that it is committed in from_ns's SETTLED root.
    L1 verifies that ONE proof against latest_settled(from_ns) and burns the (from_ns, seq) nullifier; the
    receiver rollup's exec node then delivers it to its inbox. Relayer-submittable — anyone can carry a
    genuinely-settled message, and the proof makes forgery impossible."""
    d = {"from_ns": from_ns, "to_ns": to_ns, "message": message, "proof": proof}
    tx = {"sender": keydict["address"], "recipient": "xmsg", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": d, "nonce": create_nonce(),
          "public_key": keydict["public_key"], "max_block": int(max_block),
          "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_alias_tx(keydict, op, name, max_block, fee, to=None):
    """Build a SIGNED alias op tx (op in {"register","transfer","unregister"}); recipient is the reserved
    name "alias" and the operation rides in `data`. `to` is the new owner for a transfer. amount is 0."""
    data = {"op": op, "name": name}
    if op == "transfer":
        data["to"] = to
    tx = {"sender": keydict["address"], "recipient": "alias", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": data,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(fee)}
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
        if r == "duty":
            # handled by reserved_uniqueness_keys (a duty tx emits one key PER SECTION, matching the
            # historical single-duty keys, plus one per (sender, epoch)); return a sentinel here so
            # single-key callers still dedupe whole-duty duplicates.
            return ("duty", tx["sender"], tx["max_block"] // EPOCH_LENGTH)
        if r == "slash":
            d = tx.get("data") or {}
            return ("slash", make_address(d["public_key"]), d["block_number"])
        if r == "alias":
            return ("alias", (tx.get("data") or {}).get("name"))     # one op per name per block
        if r == "settle":
            _d = tx.get("data") or {}
            return ("settle", _d.get("ns", DEFAULT_NS), tx["sender"], _d.get("exec_cursor"))  # one per (ns, validator, cursor)
        if r == "bridge_withdraw":
            d = tx.get("data") or {}
            return ("bridge_withdraw", d.get("addr"), d.get("nonce"))                    # one claim per (addr, nonce)
        if r == "xmsg":
            d = tx.get("data") or {}
            return ("xmsg", d.get("from_ns", DEFAULT_NS), (d.get("message") or {}).get("seq"))  # one delivery per (from_ns, seq)
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


def reserved_uniqueness_keys(tx) -> list:
    """ALL uniqueness keys a reserved tx occupies in a block. Single-duty txs emit their one
    historical key (byte-identical to before — historical block validity must never drift); a
    merged `duty` tx emits its own key PLUS one key per section, MATCHING the historical
    single-duty keys — so a duty-carried attest and a bare `attest` for the same (sender, epoch)
    (or two reveals of one secret) can never share a block, in either combination."""
    base = reserved_uniqueness_key(tx)
    if base is None:
        return []
    keys = [base]
    if tx.get("recipient") == "duty":
        d = tx.get("data") or {}
        if isinstance(d.get("attest"), dict):
            keys.append(("attest", tx.get("sender"), d["attest"].get("target_epoch")))
        if isinstance(d.get("commit"), dict):
            keys.append(("commit", tx.get("sender"), d["commit"].get("target_epoch")))
        if isinstance(d.get("reveal"), dict):
            keys.append(("reveal", d["reveal"].get("secret")))
    return keys


def dedupe_reserved(transactions):
    """Drop duplicate reserved txs (any shared uniqueness key), keeping the first. Used by block
    assembly so an honest producer never builds a block verify_block would reject for duplicates."""
    seen, out = set(), []
    for t in transactions:
        keys = reserved_uniqueness_keys(t)
        if keys:
            if any(k in seen for k in keys):
                continue
            seen.update(keys)
        out.append(t)
    return out


def assert_unique_reserved(transactions):
    """Raise if a block contains two reserved txs sharing ANY uniqueness key (verify side)."""
    seen = set()
    for t in transactions:
        for k in reserved_uniqueness_keys(t):
            if k in seen:
                raise ValueError(f"Duplicate reserved transaction in block: {k}")
            seen.add(k)


def create_txid(transaction):
    """The tx identity: blake2b over the CANONICAL (sorted-keys) encoding of the whole body, with
    `public_key` EXCLUDED (PUBKEY-ONCE #19 — the key is a recoverable authentication witness, not
    identity, so a later tx may omit it and hash the same). MUST be byte-exact and deterministic:
    the signature covers this hash, and every implementation (incl. the browser light-miner)
    recomputes it — any encoding divergence forks txids across nodes."""
    # canonical encoding (sorted keys) commits the whole body — incl. chain_id — so the signature
    # (over the txid) binds every field and cannot be replayed cross-chain. PUBKEY-ONCE (#19): the
    # `public_key` is EXCLUDED from the preimage — it is a recoverable authentication witness (bound
    # to the sender address by proof_sender, stored on-chain on first use), not part of the tx
    # identity — so a later tx may OMIT the 1312-byte ML-DSA key and still produce the same txid.
    # The browser light-miner computes the identical txid (canonical_bytes, public_key excluded).
    body = {k: v for k, v in transaction.items() if k != "public_key"}
    return blake2b_hash(body)


def validate_transaction(transaction, logger, block_height):
    """CONSENSUS admission gate for one tx — raises AssertionError on the first violation. Checks:
    chain_id (no cross-chain replay), signature over the txid (validate_origin, PUBKEY-ONCE aware),
    sender is a real KEYED address (a keyless reserved name can never originate a tx), recipient is a
    checksum-valid address / reserved protocol recipient / registered alias, amount+fee are real
    non-negative ints (a float or bool would corrupt the integer ledger), then the per-reserved-
    recipient rules (slash proof, attest/commit/reveal duties, unbond maturity, PoSW register, Merkle
    +nullifier exits, treasury quorum, HTLC windows, fee floors, ...), and finally validate_txid so
    the signature binds the FULL body. Runs in both the mempool and block verification and reads only
    committed state, so it MUST be deterministic — nodes that disagree here fork on block validity.
    Rejection is what stands between the ledger and forged, replayed, underpaid or double-claimed txs."""
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert transaction.get("chain_id") == CHAIN_ID, "Wrong or missing chain id"
    if transaction.get("multisig") is not None:
        # OPT-IN MULTISIG (ops/multisig_ops.py). Cheap consensus gates BEFORE the M signature
        # verifications in validate_origin:
        #  * PAYMENT accounts only — a multisig sender can never bond/register/vote/lock (reserved
        #    recipients all assume one-key-one-identity validator semantics);
        #  * per-signature fee floor — each ~2.4KB ML-DSA entry is stripped from the byte-size base
        #    fee (like the single signature), so charge MIN_TX_FEE per entry to price the block bytes
        #    + verification work an entry adds.
        assert transaction["recipient"] not in RESERVED_RECIPIENTS, \
            "a multisig account can only make plain transfers"
        assert isinstance(transaction.get("signature"), list), "multisig tx needs a signature list"
        assert transaction.get("fee", 0) >= MIN_TX_FEE * len(transaction["signature"]), \
            "multisig fee below the per-signature floor"
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
    # min_block (optional, flexibly-landing inclusion delay) must be a sane int. Without this gate a
    # crafted non-int min_block passed admission and then raised inside match_transactions_target on
    # EVERY node's candidate assembly -> match returns False -> production halts network-wide, and the
    # poison tx can never age out because blocks stop advancing (max_block never passes). Deterministic
    # (pure shape check); no historical block can carry a malformed min_block — check_target_match
    # would have failed that block at verification.
    _mb = transaction.get("min_block", 0)
    assert isinstance(_mb, int) and not isinstance(_mb, bool) and 0 <= _mb <= transaction["max_block"], \
        "Invalid min_block"
    assert len(transaction["txid"]) >= 64

    recipient = transaction["recipient"]
    if recipient == "slash":
        # SLASHING (#15 step 5C): a FEE-EXEMPT tx whose `data` carries an equivocation proof — the
        # same identity validly signed two blocks at one slot. Anyone may report it (the proof is
        # the anti-spam: it can't be forged, and one-per-(offender,height) blocks replay). The
        # offender must currently hold >= SLASH_BOND_PENALTY so apply_slash never floors (revert-safe).
        assert transaction["amount"] == 0, "Slash tx must have zero amount"
        assert transaction["fee"] == 0, "Slash tx is fee-exempt (fee must be 0)"
        result = resolve_slash(transaction.get("data"))   # block-authorship OR FFG-attestation equivocation
        assert result, "Invalid or missing equivocation proof"
        offender, height = result
        assert not kv_ops.slash_exists(offender, height), "This offence is already slashed (replay)"
        offender_acc = get_account(offender, create_on_error=False)
        assert offender_acc and offender_acc.get("bonded", 0) >= SLASH_BOND_PENALTY, \
            "Offender holds insufficient bonded stake to slash"
    elif recipient == "attest":
        # FFG attestation (#6) — HISTORICAL single-duty form: kept consensus-valid forever (genesis
        # sync replays the pre-`duty` blocks that carry these), but the mempool refuses NEW ones —
        # honest emission is the merged `duty` tx (doc/consensus-aggregation.md).
        assert transaction["amount"] == 0, "Attest tx must have zero amount"
        assert transaction["fee"] == 0, "Attest tx is fee-exempt (fee must be 0)"
        _validate_attest_fields(transaction.get("data") or {}, transaction["max_block"], transaction["sender"])
    elif recipient in ("commit", "reveal"):
        # COMMIT-REVEAL RANDAO (#7) — HISTORICAL single-duty forms (see the `attest` note): valid for
        # replay, refused at the mempool; honest emission is the merged `duty` tx.
        assert transaction["amount"] == 0, "Commit/reveal tx must have zero amount"
        assert transaction["fee"] == 0, "Commit/reveal tx is fee-exempt (fee must be 0)"
        if recipient == "commit":
            _validate_commit_fields(transaction.get("data") or {}, transaction["max_block"], transaction["sender"])
        else:
            _validate_reveal_fields(transaction.get("data") or {}, transaction["max_block"], transaction["sender"])
    elif recipient == "duty":
        # MERGED EPOCH DUTY (doc/consensus-aggregation.md): a bonded validator's whole per-epoch
        # consensus participation in ONE fee-exempt tx — sections `attest` (epoch X = the landing
        # epoch), `commit` (X+2) and `reveal` (X+1), each optional, each validated by EXACTLY the
        # same field rules as the historical single-duty forms (shared helpers). The sender must
        # hold a seat in epoch X's DUTY COMMITTEE (beacon-sampled, stake-weighted — the O(seats)
        # consensus-load bound); a reveal needs no committee check beyond its own commitment, which
        # already proves committee membership at commit time.
        from ops.block_ops import duty_committee_for_epoch
        from ops.mining_ops import epoch_of
        assert transaction["amount"] == 0, "Duty tx must have zero amount"
        assert transaction["fee"] == 0, "Duty tx is fee-exempt (fee must be 0)"
        data = transaction.get("data") or {}
        sections = {k: data.get(k) for k in ("attest", "commit", "reveal") if data.get(k) is not None}
        assert sections, "Duty tx carries no sections"
        assert set(data.keys()) <= {"attest", "commit", "reveal"}, "Duty tx carries unknown sections"
        tb = transaction["max_block"]
        X = epoch_of(tb)
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Duty sender is not a bonded validator"
        committee = duty_committee_for_epoch(X)
        assert transaction["sender"] in committee, "Duty sender holds no seat in this epoch's committee"
        if "attest" in sections:
            a = sections["attest"]
            assert isinstance(a, dict) and a.get("target_epoch") == X, "Duty attest must target the landing epoch"
            _validate_attest_fields(a, tb, transaction["sender"])
        if "commit" in sections:
            c = sections["commit"]
            assert isinstance(c, dict) and c.get("target_epoch") == X + 2, "Duty commit must target epoch X+2"
            _validate_commit_fields(c, tb, transaction["sender"])
        if "reveal" in sections:
            r = sections["reveal"]
            assert isinstance(r, dict) and r.get("target_epoch") == X + 1, "Duty reveal must target epoch X+1"
            _validate_reveal_fields(r, tb, transaction["sender"])
    elif recipient in ("unbond", "withdraw"):
        # UNBOND DELAY: fee-exempt actions on the sender's OWN stake. `unbond` requests a release (coins
        # stay bonded + slashable); `withdraw` claims it only at/after the matured release_block. Bound
        # to max_block (the deterministic landing block) so the mempool gate and block validation agree.
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
            assert transaction["max_block"] >= pending["release_block"], \
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
        # (max_block − POSW_ANCHOR_OFFSET) — a finalized, stable block — so the proof is un-precomputable
        # far ahead and non-reusable. `register` is a RENEWABLE presence LEASE and the SINGLE presence signal
        # (no separate heartbeat): a fresh recert keeps you eligible for POSW_LEASE_EPOCHS (doc/presence-dividend.md §2.4).
        from ops import posw
        from ops.block_ops import get_block_hash_by_number
        anchor = get_block_hash_by_number(max(0, transaction["max_block"] - POSW_ANCHOR_OFFSET))
        assert anchor, "PoSW anchor block not found"
        proof = transaction.get("posw")
        assert proof, "Missing registration PoSW"
        # CONSENSUS registration-rate difficulty: the required sequential-work count scales with recent
        # registration volume, keyed off the FINALIZED anchor epoch so every node computes the SAME requirement
        # and rejects an under-worked proof (a modified node can't register cheaply). See ops/reg_difficulty.py.
        from ops.reg_difficulty import required_posw_t
        from ops.mining_ops import epoch_of
        req_t = required_posw_t(epoch_of(max(0, transaction["max_block"] - POSW_ANCHOR_OFFSET)))
        assert posw.verify(posw.challenge_bytes(transaction["sender"], anchor), proof,
                           req_t, POSW_S, POSW_K), "Invalid registration PoSW (or below the required difficulty)"
    elif recipient == "msgkey":
        # ON-CHAIN MESSAGING KEY: FEE-EXEMPT, zero-amount identity tx binding the sender's ML-KEM-768
        # encryption pubkey to their account so senders can DM by address with no off-chain prekey. It is
        # sender-scoped (writes only the sender's own kem_pub) and anti-spam-gated by the empty-account rule
        # (msgkey is NOT in the onboarding bypass, so the sender must already have an on-chain account), so
        # envelope-shape checks suffice here. Re-publish / key rotation is allowed.
        assert transaction["amount"] == 0, "msgkey tx must have zero amount"
        assert transaction["fee"] == 0, "msgkey tx is fee-exempt (fee must be 0)"
        kp = transaction.get("kem_pub")
        # ML-KEM-768 public key = 1184 bytes = 2368 lowercase-hex chars (fixed length).
        assert isinstance(kp, str) and len(kp) == 2368 and all(c in "0123456789abcdef" for c in kp), \
            "msgkey kem_pub must be a 2368-hex-char ML-KEM-768 public key"
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
        ns = data.get("ns", DEFAULT_NS)
        assert valid_namespace(ns), "Settle ns must be a valid namespace id ([a-z0-9._-], <=32)"
        assert ns != DEFAULT_NS or "ns" not in data, "default namespace must be omitted from settle data (canonical form)"
        assert isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0, "Settle exec_cursor must be a non-negative int"
        assert isinstance(root, str) and len(root) == 64 and all(c in "0123456789abcdef" for c in root), "Settle state_root must be 64-hex"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Settle sender is not a bonded validator"
        assert not kv_ops.settlement_exists(ns, cursor, transaction["sender"]), "Validator already settled this (ns, exec_cursor)"
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
        ns = data.get("ns", DEFAULT_NS)
        assert valid_namespace(ns), "bridge_withdraw ns must be a valid namespace id"
        assert addr == transaction["sender"], "bridge_withdraw must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad withdraw amount"
        assert isinstance(nonce, str) and isinstance(proof, list), "bad withdraw nonce/proof"
        _cur, settled_root = latest_settled(ns)
        assert settled_root, "no settled execution-layer root yet for this namespace"
        assert verify_merkle_proof(withdrawal_leaf(addr, amount, nonce), proof, settled_root), \
            "withdrawal is not proven against the settled execution-layer root"
        assert not kv_ops.bridge_nullifier_exists(ns, addr, nonce), "this withdrawal was already claimed"
        escrow = get_account(BRIDGE_ESCROW, create_on_error=False)
        assert escrow and escrow.get("balance", 0) >= amount, "bridge escrow underfunded"
    elif recipient == "xmsg":
        # CROSS-ROLLUP MESSAGE DELIVERY: verify the outbox message is committed in from_ns's SETTLED root,
        # then let the receiver rollup's exec node deliver it. L1 is the verifier (it holds the settled roots),
        # exactly like bridge_withdraw — so delivery is deterministic for every receiver node. Fee-exempt; one
        # delivery per (from_ns, seq) via the nullifier.
        from ops.settlement_ops import latest_settled
        from hashing import verify_merkle_proof, outbox_leaf
        assert transaction["amount"] == 0, "xmsg carries no L1 amount"
        assert transaction["fee"] == 0, "xmsg is fee-exempt"
        data = transaction.get("data") or {}
        from_ns, to_ns = data.get("from_ns", DEFAULT_NS), data.get("to_ns")
        msg, proof = data.get("message"), data.get("proof")
        assert valid_namespace(from_ns) and valid_namespace(to_ns), "xmsg from_ns/to_ns must be valid namespaces"
        assert isinstance(msg, dict) and isinstance(proof, list), "bad xmsg message/proof"
        seq = msg.get("seq")
        assert isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0, "xmsg message seq must be a non-negative int"
        assert msg.get("to_ns") == to_ns, "xmsg message.to_ns must match the delivery to_ns"
        _cur, settled_root = latest_settled(from_ns)
        assert settled_root, "sending namespace has no settled root yet"
        leaf = outbox_leaf(seq, msg.get("from"), msg.get("to_ns"), msg.get("data"))
        assert verify_merkle_proof(leaf, proof, settled_root), "message is not proven against from_ns's settled root"
        assert not kv_ops.xmsg_nullifier_exists(from_ns, seq), "this cross-domain message was already delivered"
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
        from protocol import TREASURY_PROPOSAL_MAX_TTL
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
        assert transaction["max_block"] <= sexpiry <= transaction["max_block"] + TREASURY_PROPOSAL_MAX_TTL, \
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
        from protocol import TREASURY_ADDRESS, TREASURY_MAX_SPEND_BPS, BPS_DENOM
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
        assert transaction["max_block"] <= sexpiry, "this proposal has expired (past its bound expiry block)"
        sender_acc = get_account(transaction["sender"], create_on_error=False)
        assert sender_acc and sender_acc.get("balance", 0) >= transaction["fee"], "treasury_execute sender cannot afford the fee"
        assert kv_ops.treasury_voters(pid), "no votes recorded for this proposal"          # cheap gate BEFORE the O(N) scan
        treasury = get_account(TREASURY_ADDRESS, create_on_error=False)
        bal = treasury.get("balance", 0) if treasury else 0
        assert bal >= sa, "treasury underfunded for this payout"
        assert sa * BPS_DENOM <= bal * TREASURY_MAX_SPEND_BPS, "treasury spend exceeds the per-proposal cap (% of balance)"
        assert treasury_justified(pid, get_bonded_registry(), epoch_of(transaction["max_block"])), \
            "treasury proposal has not reached the bonded quorum"
    elif recipient == "htlc_lock":
        # HTLC LOCK (cross-chain atomic swap): escrow `amount` under a SHA-256 hashlock + block-height timelock.
        data = transaction.get("data") or {}
        h = transaction["max_block"]                          # deterministic landing height (mempool == build)
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
        h = transaction["max_block"]
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
        h = transaction["max_block"]
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




def sort_transaction_pool(transactions: list, key="txid") -> list:
    """sorts list of dictionaries based on a dictionary value"""
    return sorted(
        sort_list_dict(transactions), key=lambda transaction: transaction[key]
    )


def get_transactions_of_account(account, min_block: int, limit: int = 1000):
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
    """integer raw units -> fixed 10-decimal display string (1 coin = 10^10 raw); display only,
    the ledger itself never leaves integers"""
    return f"{(raw_amount / 10000000000):.10f}"


def to_raw_amount(amount: [int, float]) -> int:
    """readable coin amount -> INTEGER raw units (1 coin = 10^10 raw); the float only exists at this
    UI/tooling boundary — everything on-chain stays integer"""
    return int(float(amount) * 10000000000)


def check_balance(account, amount, fee):
    """for single transaction, check if the fee and the amount spend are allowable"""
    balance = get_account(account)["balance"]
    assert (
            balance - amount - fee > 0 <= amount
    ), f"{account} spending more than owned in a single transaction"
    return True


def get_senders(transaction_pool: list) -> list:
    """unique senders in a transaction pool, first-seen order preserved (deterministic iteration)"""
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

    # MULTISIG spend (ops/multisig_ops.py): the sender is a descriptor-derived account, "signature"
    # is a LIST of member signatures over the txid, and there is no top-level public_key. The whole
    # origin question (descriptor -> sender binding, M distinct valid member sigs) lives there.
    if transaction.get("multisig") is not None:
        from ops.multisig_ops import verify_multisig_origin
        return verify_multisig_origin(transaction)

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
    """Minimum fee for a tx = its serialized byte size, so a tx pays for the block/storage space it
    consumes. False (not raise) on failure so callers treat an unmeasurable tx as unpayable."""
    try:
        tx_copy = transaction.copy()
        base_fee = get_byte_size(tx_copy)
        return base_fee

    except Exception as e:
        logger.info(f'Failed to calculate base fee: {e}')
        return False


def validate_base_fee(transaction, logger):
    """Size-proportional anti-spam floor: the declared fee must cover get_base_fee of the tx WITHOUT
    its fee/signature/txid fields (those aren't part of what the sender drafted against, and the fee
    must not price its own bytes). Returns False (never raises) on shortfall or malformed input."""
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
    """CONSENSUS: recompute the canonical txid from the body (txid + signature stripped) and require
    an EXACT match. The signature covers only the txid, so this is what binds it to the full body —
    without it an attacker could keep a valid (txid, signature) pair and swap recipient/amount.
    Returns False (never raises) on mismatch or malformed input."""
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


def draft_transaction(sender, recipient, amount, public_key, timestamp, data, max_block):
    """construct to be able to calculate base fee, signature and txid are not present here"""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": amount,
        "timestamp": timestamp,
        "data": data,
        "nonce": create_nonce(),
        "public_key": public_key,
        "max_block": max_block,
        "chain_id": CHAIN_ID,
    }

    return transaction_message


def draft_open_lane_transaction(sender, recipient, public_key, timestamp, max_block,
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
        "max_block": max_block,
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
        # PUBKEY-ONCE revert: clear the established pubkey ONLY when reverting a tx that actually CARRIED it
        # (so could have established it) AND the sender has no earlier indexed tx. The `public_key` guard is
        # REQUIRED and is the fix for a rolling/pruned node: there tx_of_account reads the PRUNED history and
        # returns empty even for a long-established sender, so a reorg reverting a LATER pubkey-less tx (e.g. a
        # `bond`) would otherwise WRONGLY cull the sender's pubkey — permanently bricking its validation with
        # "first tx must carry it". A pubkey-less tx never established the key, so it must never delete it.
        # (Full/archive nodes are unaffected: there tx_of_account already returned the establishing tx for a
        # non-carrying revert, so it never deleted — this only stops the false deletion on pruned nodes.)
        if transaction.get("public_key") and not kv_ops.tx_of_account(transaction["sender"], min_block=0, limit=1):
            kv_ops.account_del_field(transaction["sender"], "public_key")


def index_transactions(block, sorted_transactions, logger):
    """Apply every tx's balance/state effect AND write its index rows (primary + DUPSORT
    sender/recipient secondaries) inside the incorporate write txn, so ledger state and index commit
    ATOMICALLY with the block. Files each tx under the RESOLVED recipient (alias -> owner) and
    establishes the sender's pubkey on its first carrying tx (PUBKEY-ONCE #19). MUST stay exactly
    symmetric with unindex_transactions or a reorg leaves state and index diverged."""
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
                                      max_block=asyncio.run(get_max_block(target=ips[0],
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
