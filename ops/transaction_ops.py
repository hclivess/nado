import time as _time
import json


from signatures import sign, verify, unhex
from ops.account_ops import get_account, reflect_transaction
from ops.address_ops import proof_sender, make_address, is_address
from ops.address_ops import validate_address
from ops.block_ops import get_block_number
from config import get_timestamp_seconds
from hashing import create_nonce, blake2b_hash, canonical_bytes
from ops import kv_ops
import protocol as _P
from protocol import (CHAIN_ID, MIN_TX_FEE, EPOCH_LENGTH, SLASH_BOND_PENALTY, B_MIN, FINALITY_DEPTH,

                      BLOB_MAX_BYTES, MAX_BLOB_BYTES_PER_BLOCK, BRIDGE_ESCROW, DIVIDEND_POOL,
                      POSW_ANCHOR_OFFSET, HTLC_MIN_TIMELOCK, TX_LANDING_WINDOW,
                      HTLC_MAX_TIMELOCK, SHIELD_ESCROW, RESERVED_RECIPIENTS, DEFAULT_NS, valid_namespace)


def _is_hex(s) -> bool:
    """non-empty, even-length (byte-aligned) hex string check"""
    return isinstance(s, str) and len(s) % 2 == 0 and len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)


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
    # MUST be a str: commit_put does commitment.encode() at apply-time — a non-string (int/list/dict) passes
    # this truthiness gate but raises AttributeError inside incorporate_block on every node = network halt
    # (same poison class as the min_block/settle fixes).
    assert isinstance(data.get("commitment"), str) and data.get("commitment"), "Commit commitment must be a non-empty string"
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
    # MUST be a str: reveal_put does secret.encode() at apply-time (halt-class poison if non-string), and
    # beacon_commitment hashes a list so it tolerates non-strings — so the type check has to be explicit here.
    assert isinstance(secret, str) and secret, "Reveal secret must be a non-empty string"
    commitment = kv_ops.commit_get(sender, E)
    assert commitment, "No matching commit for this reveal"
    assert beacon_commitment(secret) == commitment, "Reveal does not open the commitment"
    assert secret not in kv_ops.reveals_for_epoch(E), "This secret is already revealed for the epoch"


def construct_duty_tx(keydict, max_block, attest=None, commit=None, reveal=None, min_block=0):
    """Build the SIGNED merged per-epoch DUTY tx (doc/consensus-aggregation.md): the validator's FFG
    attest (landing epoch X), RANDAO commit (X+2) and reveal (X+1) sections — whichever are due —
    under ONE ML-DSA signature instead of three full txs. Fee-exempt committee duty.

    min_block > 0 (DUTY_WINDOW_ACTIVATION): the tx lands FLEXIBLY in [min_block, max_block] — the
    signed min_block is the propagation guard (no producer can front-run it), max_block carries every
    timing deadline (epoch / RANDAO-reveal clamps). min_block=0 builds the LEGACY exact-landing form."""
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
    if min_block and int(min_block) > 0:
        tx["min_block"] = int(min_block)   # inside the signed body: create_txid below binds it
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_tpm_tx(keydict, recipient, data, max_block, min_block=0):
    """Build a SIGNED enrolment message (doc/tpm-attestation-without-a-ca.md): `tpm_enrol`,
    `tpm_challenge`, `tpm_commit` or `tpm_reveal`. Fee-exempt, zero-amount, `data` carried in the signed
    body like every other proof-bearing tx.

    THE WINDOW MATTERS MORE HERE THAN ANYWHERE ELSE. Every message must land STRICTLY after the one it
    answers, and a flexible window is what makes that reachable: an exact landing height is one block that
    the tx must reach every producer in time for, and missing it kills an enrolment that then has to start
    over with a new attestation key. min_block gives the message a full inclusion delay to propagate;
    max_block is the deadline.
    """
    assert recipient in ("tpm_enrol", "tpm_challenge", "tpm_commit", "tpm_reveal", "tpm_ready"), recipient
    tx = {"sender": keydict["address"], "recipient": recipient, "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": data, "nonce": create_nonce(),
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0,
          "public_key": keydict["public_key"]}
    if min_block and int(min_block) > 0:
        tx["min_block"] = int(min_block)
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_slash_tx(keydict, proof, max_block):
    """Build the SIGNED fee-exempt slash tx from an equivocation proof (block-authorship or FFG
    attestation double-vote). Anyone may report — the unforgeable proof is the anti-spam — and the
    WATCHTOWER (memserver.maybe_watchtower_slash) is the automatic reporter: punishment must land
    because the protocol saw the offence, not because a human happened to."""
    tx = {"sender": keydict["address"], "recipient": "slash", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": proof, "nonce": create_nonce(),
          "max_block": max_block, "chain_id": CHAIN_ID, "fee": 0,
          "public_key": keydict["public_key"]}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def verify_attestation_equivocation_proof(proof, judge_height=None):
    """Verify an FFG ATTESTATION double-vote: the SAME bonded validator SIGNED two attestations for the SAME
    target_epoch but DIFFERENT target_hash. proof = {"attest_a": <signed attest tx>, "attest_b": <signed
    attest tx>}. Returns (offender_address, target_epoch) when valid, else None. Unforgeable: only the
    key-holder can sign either attestation, and there is NO honest reason to attest two checkpoints for one
    epoch — so a valid proof is irrefutable evidence of a finality double-vote."""
    try:
        def _open(tx):
            if not isinstance(tx, dict) or tx.get("recipient") not in ("attest", "duty"):
                return None
            # CHAIN BINDING (critical): the attested content is {target_epoch, target_hash} — both
            # chain-INDEPENDENT (epoch numbering restarts at 0 at every genesis). Without this check an
            # attacker could pair a validator's attestation from a PREVIOUS chain generation with its
            # attestation for the same epoch number on THIS chain: both signatures verify, both bind to the
            # sender, the epochs match, and the target_hashes differ (different lineage) — a valid-looking
            # equivocation proof that burns an honest validator's bond, repeatable once per overlapping
            # epoch until the stake is gone. Old-generation bodies survive rerolls on disk and in backups,
            # so this is reachable in practice (it went live the moment betanet-8 was rerolled to
            # betanet-9). The block-authorship proof is implicitly chain-bound via parent_hash; this one
            # is not, so bind it explicitly. chain_id is inside the signed txid preimage, so it cannot be
            # forged onto a foreign-chain attestation.
            if tx.get("chain_id") != CHAIN_ID:
                return None
            pk, sig, txid, sender = tx.get("public_key"), tx.get("signature"), tx.get("txid"), tx.get("sender")
            if not (pk and sig and txid and sender) or not isinstance(sig, str):
                return None
            _d0 = tx.get("data") or {}
            if tx.get("recipient") == "duty":
                _d0 = _d0.get("attest") or {}
            from ops.auth_ops import key_valid_at
            _h = int(_d0.get("target_epoch", 0)) * EPOCH_LENGTH if isinstance(_d0.get("target_epoch"), int) else 0
            if not key_valid_at(pk, sender, _h, judge_height):         # the key must have authorized the sender THEN
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


def resolve_slash(data, judge_height=None):
    """Resolve a slash proof — block-authorship OR FFG-attestation equivocation — to (offender, dedup_height).
    Attestation slashes are namespaced at _ATTEST_SLASH_BASE+epoch so they never collide with a block-height
    slash. Returns None if neither proof verifies. Shared by validate_transaction + reflect_transaction."""
    if isinstance(data, dict) and ("attest_a" in data or "attest_b" in data):
        r = verify_attestation_equivocation_proof(data, judge_height)
        return (r[0], _ATTEST_SLASH_BASE + r[1]) if r else None
    from ops.block_ops import verify_equivocation_proof
    r = verify_equivocation_proof(data, judge_height)
    return (r[0], r[1]) if r else None


def sign_entries(body, signer_keydicts):
    """Finalize a drafted tx body for a CONFIGURED account: set the txid and a LIST of signature entries
    (one per keydict) over it. The body must not carry a top-level public_key (each entry carries its own)."""
    tx = {k: v for k, v in body.items() if k not in ("txid", "signature", "public_key")}
    tx["txid"] = create_txid(tx)
    msg = unhex(tx["txid"])
    tx["signature"] = [{"public_key": kd["public_key"], "signature": sign(private_key=kd["private_key"], message=msg)}
                       for kd in signer_keydicts]
    return tx


def auth_pop(sender, cfg, keydict):
    """A new authenticator's proof of possession for `cfg` on `sender` (ops/auth_ops.pop_message)."""
    from ops.auth_ops import pop_message
    return sign(private_key=keydict["private_key"], message=pop_message(sender, cfg))


def construct_auth_tx(sender, signer_keydicts, data, fee, max_block, min_block=0):
    """Build a SIGNED `auth` tx (doc/key-rotation.md): data = {"op": "set", "cfg", "pop"} | {"op": "cancel"},
    authenticated by a LIST of signature entries — one per signer keydict, each an ML-DSA signature over the
    txid — the multisig wire shape. Fee-paying (never exempt), zero amount. The `sender` is the account being
    reconfigured; the signers are whichever of its authenticators are acting."""
    tx = {"sender": sender, "recipient": "auth", "amount": 0, "timestamp": get_timestamp_seconds(),
          "data": data, "nonce": create_nonce(), "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(fee)}
    if min_block:
        tx["min_block"] = int(min_block)
    tx["txid"] = create_txid(tx)
    msg = unhex(tx["txid"])
    tx["signature"] = [{"public_key": kd["public_key"], "signature": sign(private_key=kd["private_key"], message=msg)}
                       for kd in signer_keydicts]
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


def construct_withdraw_tx(keydict, amount, release_block, max_block):
    """Build a SIGNED withdraw tx — the SECOND half of leaving savings, which actually moves the coins.

    `unbond` only RECORDS a request: the amount stays bonded (still slashable, still selection-weighted)
    until a matured `withdraw` claims it. Consensus has always validated this recipient, but nothing in
    the tree could BUILD one — no wallet path, no CLI command, not even a constructor — so a user who
    unbonded watched their coins sit in limbo with no way to complete the exit. That is what this is.

    The data is SELF-DESCRIBING ({amount, release_block}) because apply/revert both read it: validation
    requires it to match the pending record exactly, and `max_block` must be >= release_block, since
    max_block IS the deterministic landing block the maturity check is made against. Fee-exempt, like
    unbond — a fully-bonded wallet with no spendable balance must always be able to get out.
    """
    tx = {"sender": keydict["address"], "recipient": "withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"amount": int(amount), "release_block": int(release_block)},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def _is_hex_str(s) -> bool:
    return isinstance(s, str) and len(s) % 2 == 0 and all(c in "0123456789abcdef" for c in s)


def _hex_bytes(v, cap: int, what: str) -> bytes:
    """A hex field from a transaction, size-capped. Lowercase-only and even-length so ONE encoding of a value
    exists: the txid commits `data` verbatim, so accepting "AB" and "ab" would make two distinct transactions
    carry the identical proof."""
    assert _is_hex_str(v) and 0 < len(v) <= cap * 2, f"{what} must be at most {cap} bytes of lowercase hex"
    return bytes.fromhex(v)


def _hex_list(v, max_items: int, cap: int, what: str) -> list:
    assert isinstance(v, list) and 0 < len(v) <= max_items, f"{what} must be 1..{max_items} entries"
    return [_hex_bytes(x, cap, what) for x in v]


def _anchor_time(transaction: dict, block_height: int) -> int:
    """The clock a certificate's validity is judged against at `block_height` — the ONE function every consensus
    certificate check reads (tpm_enrol validation, its apply in account_ops, verify_register_device).

    Never wall time: that makes validity node-local, and a certificate expiring mid-block would be valid on one node
    and expired on the next. Nor the anchor block's block_timestamp, the clock betanet-8 used below block 29000, which
    turned out to be node-local too — it is outside the block hash and every node stamps its own copy (protocol.py
    "CERTIFICATE VALIDITY READS AGREED TIME" carries the measurement). It is agreed_time(anchor height): the median of
    the bonded validators' own duty-transaction clocks in committed blocks, so a pruned node, an archive node and a
    node fed a re-stamped block by a lying peer reach the same verdict.
    INVARIANT: nothing here may read block_timestamp, time.time() or any stored block field other than committed
    transaction bodies; a certificate verdict must be a function of agreed data alone."""
    from protocol import POSW_ANCHOR_OFFSET
    return agreed_time(max(0, int(block_height) - POSW_ANCHOR_OFFSET))


_agreed_time_cache = {}                # {(lo, hi, hash of block hi-1): seconds}; bounded below


def agreed_time_window(height: int) -> tuple:
    """[lo, hi) of committed blocks agreed_time(height) reads: the CERT_CLOCK_WINDOW blocks before the start of
    `height`'s epoch — every one an ancestor of `height`, quantised so the answer is cached per epoch."""
    from protocol import CERT_CLOCK_WINDOW, EPOCH_LENGTH
    hi = (max(0, int(height)) // EPOCH_LENGTH) * EPOCH_LENGTH
    return max(1, hi - CERT_CLOCK_WINDOW), hi


def agreed_time(height: int) -> int:
    """AGREED TIME at `height` (protocol.py "CERTIFICATE VALIDITY READS AGREED TIME"): the median, over distinct senders, of the timestamps the
    bonded committee signed into its own duty transactions in agreed_time_window(height).

    WHY THIS AND NOT THE OTHERS. block_timestamp is outside the block hash and differs node to node for one block
    (measured 12 s apart) and a syncing peer can serve any value. chain_clock(height) is agreed but only assumes a
    cadence: on betanet-8 it ran 11.8 h behind after 2.3 days, which would refuse every freshly issued certificate.
    A duty tx's `timestamp` is inside its txid (so inside the block), written by the validator's own clock when it
    signs, and every node reads the same committed bodies — agreed data that tracks real time. One sample per sender
    (its latest in the window) and the MEDIAN: a minority of the committee cannot move it outside the honest range,
    the same trust the committee's FFG votes already carry. Lags real time by roughly the window plus the anchor
    offset (~30 min at 8 s blocks); CERT_NOT_BEFORE_GRACE absorbs that for freshly issued certificates.
    Fewer than CERT_CLOCK_MIN_SAMPLES senders (a newborn chain) falls back to chain_clock(hi), agreed as well.
    A block of the window this node does not hold DEFERS (WindowUnavailable), never guesses — the challenger draw's
    rule (2026-09-13: guessing from a partial window forked two nodes)."""
    from protocol import CERT_CLOCK_MIN_SAMPLES, chain_clock
    lo, hi = agreed_time_window(height)
    # keyed on the window's LAST block hash too: a reorg reaching into the window must never be answered from memory
    from ops.block_ops import get_block_hash_by_number
    key = (lo, hi, get_block_hash_by_number(hi - 1) if hi > lo else None)
    if key in _agreed_time_cache:
        return _agreed_time_cache[key]
    latest = {}
    for h in range(lo, hi):
        block = get_block_number(h)
        if not block:
            raise WindowUnavailable(
                f"the certificate clock needs block {h} of the window [{lo},{hi}) and this node does not have it "
                f"— cannot judge certificate validity without it (sync the gap, do not guess)", lo, hi)
        for t in (block.get("block_transactions") or []):
            if t.get("recipient") not in _DUTY_RECIPIENTS:
                continue
            ts, who = t.get("timestamp"), t.get("sender")
            # an unvalidated field: only a sane integer counts (no bool, no float, no pre-2020 or far-future value)
            if who and isinstance(ts, int) and not isinstance(ts, bool) and 1_577_836_800 <= ts < (1 << 40):
                if ts > latest.get(who, 0):
                    latest[who] = ts
    samples = sorted(latest.values())
    t = samples[(len(samples) - 1) // 2] if len(samples) >= CERT_CLOCK_MIN_SAMPLES else chain_clock(hi)
    if len(_agreed_time_cache) >= 64:
        _agreed_time_cache.clear()
    _agreed_time_cache[key] = t
    return t


def cert_verdict(verify_at, now: int) -> dict:
    """Run a certificate-chain check `verify_at(seconds) -> verdict` at the agreed clock, with the notBefore grace.

    The kernel checks notBefore <= now <= notAfter for every certificate at ONE instant. Agreed time lags real time
    (agreed_time), so a certificate issued minutes ago looks not-yet-valid. So a chain that fails
    at `now` is checked once more at now + CERT_NOT_BEFORE_GRACE and accepted if that passes: acceptance then means
    every notBefore <= now + grace and every notAfter >= now, so an EXPIRED certificate is never accepted by the
    grace (expiry is still judged at `now`). The one chain this can refuse that the ideal rule accepts is one whose
    certificates are valid together only strictly inside (now, now + grace) — a fresh certificate beside one expiring
    within the grace. Deterministic: both instants are agreed. (Betanet-8 ran one check at `now` below block 29000;
    every certificate check on betanet-9 runs at a height >= 1, where the grace always applied — protocol.py, the
    CERT_CLOCK_HEIGHT deletion note.)"""
    from protocol import CERT_NOT_BEFORE_GRACE
    v = verify_at(int(now))
    if v.get("ok"):
        return v
    v2 = verify_at(int(now) + CERT_NOT_BEFORE_GRACE)
    return v2 if v2.get("ok") else v


# Recent-producer weights, memoised on the window they cover. The window only moves when the tip does, and
# an enrolment message is validated by every node, so recomputing a 120-block scan per validation would be
# paid over and over for an answer that cannot have changed.
def _window_key(lo: int, hi: int) -> tuple:
    """Cache key for a scan over blocks [lo, hi): the bounds AND the hash of block hi-1. Block hashes chain, so that hash
    names every block of the window — a reorg reaching into the window (up to FINALITY_DEPTH blocks, inside one epoch)
    gives a new key instead of an answer computed from the replaced blocks. "" when the block is not held (the scan
    itself then defers).
    INVARIANT: every window cache whose answer can reach the state root keys on this, as _agreed_time does."""
    from ops.block_ops import get_block_hash_by_number
    return (int(lo), int(hi), (get_block_hash_by_number(hi - 1) or "") if hi > lo else "")


_tpm_producer_cache = [None]


# The duty transactions that prove a node runs the core loop. `duty` is the merged modern form; the
# three legacy singles are still accepted by consensus, so a node emitting either kind counts.
_DUTY_RECIPIENTS = ("duty", "attest", "commit", "reveal")


def _recent_producers(block_height: int) -> dict:
    """{address: duty transactions landed} over the window ending just before `block_height`.

    THE SIGNAL HAS TO MEAN "THIS NODE RUNS THE LOOP THAT ANSWERS CHALLENGES", and two earlier answers did
    not. Bonded stake measures capital: 22% of it sat behind a running node. Block production measures
    winning a draw: an open-lane miner produces from a browser wallet and runs no duty loop, so of 53
    producers measured over 240 blocks only 7 ran the software and the chance all three drawn challengers
    could answer was 0.2%.

    An FFG duty transaction — attest, commit or reveal — requires being a bonded validator running the
    core loop, and the challenger duty lives in that same loop. So this is not a proxy for the property
    we need; it is the property. A browser wallet cannot produce one.

    Reads committed blocks and nothing else, so a node replaying this in a year derives the same set.
    """
    from protocol import DEVICE_ATTEST_EK_PRODUCER_WINDOW as _W
    hi = int(block_height)
    lo = max(1, hi - _W)
    wkey = _window_key(lo, hi)
    entry = _tpm_producer_cache[0]
    if entry is not None and entry[0] == wkey:
        return dict(entry[1])
    weights = {}
    for h in range(lo, hi):
        block = get_block_number(h)
        if not block:
            continue
        for t in (block.get("block_transactions") or []):
            if t.get("recipient") in _DUTY_RECIPIENTS:
                who = t.get("sender")
                if who:
                    weights[who] = weights.get(who, 0) + 1
    _tpm_producer_cache[0] = (wkey, dict(weights))
    return weights


_tpm_proven_cache = [None]              # [{(lo, hi, hash of block hi-1): {address: weight}}], or [None] when cleared
_TPM_PROVEN_CACHE_WINDOWS = 8          # a delayed draw reads a window at most ~5 epochs behind the tip's


def proven_window(block_height: int) -> tuple:
    """[lo, hi) of blocks the challenger draw for `block_height` reads — quantised to the epoch.

    ONE DEFINITION. The production gate (core_loop._rules_evaluable_at_tip) has to name the same window
    the draw scans, so it can fill exactly the blocks the draw will need; two hand-mirrored copies of this
    arithmetic would be a fork waiting for someone to edit one of them."""
    from protocol import DEVICE_ATTEST_EK_PROVEN_WINDOW as _W, EPOCH_LENGTH
    hi = (int(block_height) // EPOCH_LENGTH) * EPOCH_LENGTH
    return max(1, hi - _W), hi


def _proven_challengers(block_height: int) -> dict:
    """{address: duty transactions landed} restricted to addresses that have ACTED as a challenger.

    A tpm_challenge, tpm_commit or tpm_reveal on chain is the only thing that distinguishes a node
    running the challenger loop from a WALLET that mines. A mining wallet bonds, registers, attests with
    its own TPM and lands the same FFG duties — on chain it is indistinguishable from a node — but it
    runs no daemon, so drawing it wastes a slot that can never be filled. Measured on this chain: the
    owner's own mining wallet drawn for a stranger's enrolment, one of three slots dead on arrival.

    QUANTISED TO THE EPOCH so the scan is cached rather than repeated per block: the window ends at the
    start of `block_height`'s epoch, which every node computes identically from committed blocks, and a
    node replaying this in a year derives the same set."""
    from protocol import DEVICE_ATTEST_EK_READY_WINDOW as _R
    lo, hi = proven_window(block_height)
    # SEVERAL WINDOWS AT ONCE (COMMIT, THEN DRAW, ops/tpm_enrol): a delayed enrolment is drawn
    # from the pool as of its ENROL block, read up to a few epochs after the tip's own window moved on, so a single
    # slot would thrash — two pending enrolments from different epochs meant two 6000-block rescans per block in the
    # challenger loop alone. INVARIANT: keep more than one window cached; `[0] = None` still clears it (tests do).
    wkey = _window_key(lo, hi)
    entry = _tpm_proven_cache[0] or {}
    if wkey in entry:
        return dict(entry[wkey])
    acted, duties = set(), {}
    # ONLY A CHALLENGER'S OWN ACTS (protocol.TPM_POOL_CHALLENGER_ACTS_HEIGHT): tpm_commit is the ENROLLEE's message, so
    # counting it let anyone buy a free seat by opening an enrolment and committing garbage. Keyed on `hi` (the draw's
    # window), never on the scanned block, so one window has one rule. INVARIANT: never count an enrollee's tx here.
    from protocol import TPM_POOL_CHALLENGER_ACTS_HEIGHT
    _acts_only = hi >= TPM_POOL_CHALLENGER_ACTS_HEIGHT
    for h in range(lo, hi):
        block = get_block_number(h)
        if not block:
            # A BLOCK WE CANNOT READ IS NOT AN EMPTY BLOCK (2026-09-13). This skipped it and carried on,
            # so the answer depended on which blocks happened to be on THIS node's disk — and the answer
            # picks the challengers, which enter the state root. Two nodes with gaps in this window
            # computed a smaller pool, drew different challengers, wrote a different state root, and
            # forked the chain away from nine nodes with complete history; the gap-ridden pair then raced
            # ahead unopposed while the correct majority sat frozen.
            #
            # THE THIRD OUTCOME, not a rejection. ProofUnavailable is this exact category and says so in
            # its own docstring: "rejecting it would fork the fleet along the axis of who happened to have
            # the data." A plain error would be worse than the bug — on OWN assembly the caller DROPS the
            # offending transaction and keeps building, so a gap-ridden node would quietly omit the
            # enrolment and diverge a second way. Deferring makes the node stall and backfill, which every
            # node applies identically, so a gap costs liveness on that node and never safety on the chain.
            raise WindowUnavailable(
                f"challenger draw needs block {h} of the window [{lo},{hi}) and this node does not have "
                f"it — cannot evaluate the enrolment rule without it (sync the gap, do not guess)", lo, hi)
        for t in (block.get("block_transactions") or []):
            r, who = t.get("recipient"), t.get("sender")
            if not who:
                continue
            if r in ("tpm_challenge", "tpm_reveal") or (r == "tpm_commit" and not _acts_only):
                # ACTED. Having answered a challenge proves the loop was running, and it counts for the
                # full window because a challenger only acts when it is drawn — a node willing for hours
                # may simply not have been picked.
                acted.add(who)
            elif r == "tpm_ready" and h >= hi - _R:
                # SAID IT WILL. An announcement is a claim about RIGHT NOW, so it expires faster than
                # evidence of having acted: a node that stopped running must drop out of the pool
                # without anyone having to notice. Without it, a node that has never been drawn could
                # never become eligible at all.
                acted.add(who)
            elif r in _DUTY_RECIPIENTS:
                duties[who] = duties.get(who, 0) + 1
    out = {a: max(1, duties.get(a, 0)) for a in acted}
    kept = dict(_tpm_proven_cache[0] or {})
    kept[wkey] = dict(out)
    _tpm_proven_cache[0] = dict(sorted(kept.items())[-_TPM_PROVEN_CACHE_WINDOWS:])   # the newest windows
    return out


def _tpm_pool(block_height: int) -> dict:
    """{address: weight} the challenger draw for an enrolment opened at `block_height` samples from: identities that
    landed an FFG DUTY transaction in the recent window, weighted by how many (see _recent_producers for why duty and
    not stake or production) — restricted to the PROVEN challengers when at least k exist.

    PROVEN CHALLENGERS FIRST, duty senders only as a fallback. Eligibility earned by acting, where acting requires
    being drawn, would exclude everyone on a fresh chain and after any long quiet period — so when fewer than k have
    proven themselves the wider pool still runs the draw. Worse, but live, and it self-heals the moment k nodes have
    answered once.

    ONE DEFINITION, shared by the enrol-time check (pool_can_seat) and the materialisation of the draw, so the pool an
    enrolment was admitted against is exactly the pool it is later drawn from."""
    from protocol import DEVICE_ATTEST_EK_CHALLENGERS
    weights = _recent_producers(block_height)
    proven = _proven_challengers(block_height)
    if len(proven) >= DEVICE_ATTEST_EK_CHALLENGERS:
        weights = proven
    return weights


_tpm_presence_cache = [None]           # [{(lo, hi, hash of block hi-1): {address: distinct epochs}}], or [None] when cleared


def _duty_presence(block_height: int) -> dict:
    """{address: DISTINCT EPOCHS with a landed FFG duty tx} over proven_window(block_height) — the presence half of
    the v2 challenger pool (protocol.TPM_POOL_V2_HEIGHT).

    EPOCHS, NOT TRANSACTIONS. A count of duty txs rewards whoever lands the most of them; a distinct-epoch count asks
    the only question the pool needs — was this validator's loop running, epoch after epoch — and a burst cannot buy
    what steady presence earns. The epoch of a duty is the epoch of the block it landed in.

    THE SAME WINDOW AS _proven_challengers (proven_window: quantised to the epoch, ending at the start of the enrol
    block's epoch), so the production gate that fills that window (core_loop._rules_evaluable_at_tip) covers this
    scan too. A block of the window this node does not hold DEFERS (WindowUnavailable), never guesses: the pool
    enters the record, so a guess is a state-root split (the 2026-09-13 lesson). Cached per window, several at once,
    for the reason _proven_challengers gives."""
    from protocol import EPOCH_LENGTH
    lo, hi = proven_window(block_height)
    wkey = _window_key(lo, hi)
    entry = _tpm_presence_cache[0] or {}
    if wkey in entry:
        return dict(entry[wkey])
    seen = {}
    for h in range(lo, hi):
        block = get_block_number(h)
        if not block:
            # INVARIANT: a block we cannot read is not an empty block — see _proven_challengers
            raise WindowUnavailable(
                f"challenger pool needs block {h} of the window [{lo},{hi}) and this node does not have "
                f"it — cannot evaluate the enrolment rule without it (sync the gap, do not guess)", lo, hi)
        for t in (block.get("block_transactions") or []):
            if t.get("recipient") in _DUTY_RECIPIENTS:
                who = t.get("sender")
                if who:
                    seen.setdefault(who, set()).add(h // EPOCH_LENGTH)
    out = {a: len(e) for a, e in seen.items()}
    kept = dict(_tpm_presence_cache[0] or {})
    kept[wkey] = dict(out)
    _tpm_presence_cache[0] = dict(sorted(kept.items())[-_TPM_PROVEN_CACHE_WINDOWS:])
    return out


def tpm_record_faults(rec: dict) -> list:
    """The challengers at fault for v2 record `rec` once expired (ops/tpm_enrol.faults), its drawn set read from the
    record — the stored set, or the pure draw from its OWN snapshot when no challenge ever materialised it."""
    from ops import tpm_enrol as _te
    if not _te.is_v2(rec) or rec.get("state") == _te.STATE_PROVEN:
        return []
    drawn = None
    if rec.get("state") == _te.STATE_OPEN:
        try:
            drawn = tpm_drawn_challengers(rec, _te.expiry(rec))
        except ValueError as e:
            # epoch_beacon raises ValueError when its anchor block is missing locally: DEFER like a window gap, never
            # treat it as "nobody was drawn" (that would let a missing block decide who is excluded)
            a = (_te.draw_epoch(rec["h"]) - 1) * _P.EPOCH_LENGTH
            raise WindowUnavailable(f"challenger exclusion needs the beacon anchor block {a}: {e}", a, a + 1)
    return _te.faults(rec, drawn)


def _tpm_excluded(block_height: int) -> set:
    """Addresses left out of a v2 pool built at `block_height`: every challenger at fault (tpm_record_faults) for a v2
    record whose expiry lies in (block_height - TPM_MISS_EXCLUDE_BLOCKS, block_height], plus the misses a record carried
    over from the expired record it superseded ("missed", same window).

    THE CARRY IS WHAT MAKES THIS HOLD. A chip retries with the same attestation key, so its retry derives the same
    enrolment id and SUPERSEDES the expired record in place — the record that names the miss is overwritten exactly
    when the miss matters. apply_tpm_enrol_tx therefore copies the faults into the new record (tpm_carry_misses), and
    the scan reads them there. It also keeps validation (parent state) and apply (mid-block) in agreement when a
    supersede lands earlier in the same block. Reads state only; an expired record never changes again except by
    that supersede, so the answer is a pure function of the chain."""
    from protocol import TPM_MISS_EXCLUDE_BLOCKS
    from ops import tpm_enrol as _te
    h = int(block_height)
    out = set()
    for _eid, rec in kv_ops.tpm_enrols_all():
        if not _te.is_v2(rec):
            continue                                  # legacy records fault nobody (rule 6: old records unchanged)
        for e, a in (rec.get("missed") or []):
            if h - TPM_MISS_EXCLUDE_BLOCKS < int(e) <= h:
                out.add(str(a))
        exp = _te.expiry(rec)
        if h - TPM_MISS_EXCLUDE_BLOCKS < exp <= h:
            out.update(tpm_record_faults(rec))
    return out


def tpm_carry_misses(prev, block_height: int) -> list:
    """The [expiry, address] misses a v2 record superseding `prev` at `block_height` must carry: prev's own faults
    and the misses prev itself carried, kept only while they can still exclude someone (expiry > block_height -
    TPM_MISS_EXCLUDE_BLOCKS), so the list is bounded by one exclusion period of retries."""
    from protocol import TPM_MISS_EXCLUDE_BLOCKS
    from ops import tpm_enrol as _te
    if not prev or not _te.is_v2(prev):
        return []
    floor = int(block_height) - TPM_MISS_EXCLUDE_BLOCKS
    out = {(int(e), str(a)) for e, a in (prev.get("missed") or []) if int(e) > floor}
    exp = _te.expiry(prev)
    if exp > floor:
        out.update((exp, a) for a in tpm_record_faults(prev))
    return [[e, a] for e, a in sorted(out)]


_epoch_duty_cache = [None]              # [(window key, frozenset of duty senders)]


def _duty_senders_in_epoch(e: int) -> frozenset:
    """Addresses that landed any FFG duty tx in a block of epoch `e`. A block of the epoch this node does not hold DEFERS
    (WindowUnavailable), never guesses — the answer reaches the state root through the pool. Cached on _window_key."""
    lo, hi = int(e) * EPOCH_LENGTH, (int(e) + 1) * EPOCH_LENGTH
    wkey = _window_key(lo, hi)
    entry = _epoch_duty_cache[0]
    if entry is not None and entry[0] == wkey:
        return entry[1]
    who = set()
    for h in range(lo, hi):
        block = get_block_number(h)
        if not block:
            raise WindowUnavailable(
                f"the reveal-miss rule needs block {h} of epoch {e} [{lo},{hi}) and this node does not have it "
                f"— cannot evaluate the challenger pool without it (sync the gap, do not guess)", lo, hi)
        for t in (block.get("block_transactions") or []):
            if t.get("recipient") in _DUTY_RECIPIENTS and t.get("sender"):
                who.add(t["sender"])
    out = frozenset(who)
    _epoch_duty_cache[0] = (wkey, out)
    return out


def _randao_unrevealed(block_height: int, candidates) -> set:
    """The `candidates` that committed a RANDAO secret for the epoch of `block_height` and were ABSENT from the reveal
    epoch — no duty tx of theirs landed in epoch E-1 — so the secret went unrevealed (protocol.RANDAO_MISS_POOL_HEIGHT;
    empty below it). A validator present in E-1 whose reveal still missed is NOT excluded: the reveal window
    (E-1)*L .. E*L-FINALITY_DEPTH-1 is 14 blocks and TX_INCLUSION_DELAY leaves ~6 to start a duty that carries it,
    so a present validator's miss is a timing casualty, not absence (measured 2026-10-10: 122 of 173 misses).
    The window cannot widen: commits for E land in E-2, so a reveal before E-1 would let a late committer see secrets,
    and L1's epoch_beacon(E) reads E's reveals at block E*L, so they must be final by then.
    INVARIANT: a pure function of committed rows and blocks of epochs E-2..E-1, identical at every block of epoch E."""
    from protocol import RANDAO_MISS_POOL_HEIGHT
    from ops.mining_ops import beacon_commitment
    if int(block_height) < RANDAO_MISS_POOL_HEIGHT:
        return set()
    E = int(block_height) // EPOCH_LENGTH
    if E < 2:
        return set()
    revealed = {beacon_commitment(sec) for sec in kv_ops.reveals_for_epoch(E)}
    missed = []
    for a in sorted(candidates):                      # point reads: commits is keyed sender|epoch
        c = kv_ops.commit_get(a, E)
        if c is not None and c not in revealed:
            missed.append(a)
    if not missed:
        return set()
    present = _duty_senders_in_epoch(E - 1)
    return {a for a in missed if a not in present}


def tpm_pool_v2(block_height: int) -> dict:
    """{address: weight} a v2 enrolment opened at `block_height` is drawn from (protocol.TPM_POOL_V2_HEIGHT): ONLINE
    STAKE — bonded >= B_MIN now, an FFG duty landed in >= TPM_POOL_PRESENCE_MIN distinct epochs of the proven window,
    not excluded for a recent miss — weighted bonded // B_MIN.

    STAKE PRICES THE SEAT. Weighting by duty count let thin accounts earn seats cheaply; weighting by bonded stake
    makes a seat cost the capital it represents, and the presence floor keeps that stake to validators whose loop is
    actually running. Computed ONCE per enrolment, at its enrol block, and STORED in the record (ops/tpm_enrol
    new_record): the draw reads that snapshot, never this function at another height.
    INVARIANT: validation (pool_can_seat) and apply (the stored snapshot) call this one function."""
    from protocol import TPM_POOL_PRESENCE_MIN
    presence = _duty_presence(block_height)
    excluded = _tpm_excluded(block_height) | _randao_unrevealed(block_height, presence)
    out = {}
    for a in sorted(presence):
        if presence[a] < TPM_POOL_PRESENCE_MIN or a in excluded:
            continue
        acc = get_account(a, create_on_error=False)
        bonded = int((acc or {}).get("bonded", 0) or 0)
        if bonded >= B_MIN:
            out[a] = bonded // B_MIN
    return out


def tpm_drawn_challengers(rec: dict, block_height: int):
    """The challenger set of enrolment `rec` as a block at `block_height` sees it, or None when it is not drawn yet.

    A record whose first challenge landed answers with the stored set. A record with an empty set is drawn here — COMMIT, THEN DRAW (ops/tpm_enrol):
    keyed on the endorsement identity only, weighted by the pool as of the ENROL block, with the beacon of the draw
    epoch, and only from that epoch's first block on. A pure function of committed chain data, so the challenger
    loop, the relay's /tpm_enrolment and consensus all name the same set without it having been written yet.

    INVARIANT: the three inputs stay (rec["ek"], _tpm_pool(rec["h"]), epoch_beacon(draw_epoch(rec["h"]))). Keying on
    anything the client writes, or reading the pool or the beacon at `block_height`, re-opens the grind: the pool
    could be joined after the dice are known, and a beacon the client knew at the enrol is the original hole."""
    from protocol import DEVICE_ATTEST_EK_CHALLENGERS
    from ops.block_ops import epoch_beacon
    from ops import tpm_enrol as _te
    stored = list(rec.get("challengers") or [])
    if stored:
        return stored
    if int(block_height) < _te.draw_opens(rec["h"]):
        return None
    if _te.is_v2(rec):
        # TPM POOL v2: the pool and k are the record's own SNAPSHOT, taken at the enrol block before the dice existed.
        # INVARIANT: never recompute the pool here — a recomputation at any other height is a pool that can be joined
        # (or bonded into) after the beacon is known.
        return _te.challenger_set_exact(_te.draw_key(rec["ek"]), _te.pool_weights(rec),
                                        epoch_beacon(_te.draw_epoch(rec["h"])), _te.record_k(rec))
    return _te.challenger_set_exact(_te.draw_key(rec["ek"]), _tpm_pool(int(rec["h"])),
                                    epoch_beacon(_te.draw_epoch(rec["h"])), DEVICE_ATTEST_EK_CHALLENGERS)


def tpm_retry_view(rec: dict, tip: int) -> dict:
    """The retry fields /tpm_enrolment serves (protocol.TPM_ENROL_V3_HEIGHT): {"client_failed", "retry_ready_at"} — the
    first block a new enrolment of this chip validates at, by the SAME rule validate_transaction enforces (the record's
    expiry, plus the spacing when its client failed it, from the gate on).
    INVARIANT: a client told retry_ready_at = N is accepted at N and refused at N - 1."""
    from protocol import TPM_ENROL_V3_HEIGHT
    from ops import tpm_enrol as _te
    failed = bool(_te.client_failed(rec))
    if int(tip) + 1 < TPM_ENROL_V3_HEIGHT:
        return {"client_failed": failed, "retry_ready_at": int(_te.expiry(rec))}
    return {"client_failed": failed, "retry_ready_at": int(_te.retry_ready_at(rec, kv_ops.tpm_retry_get(str(rec.get("ek") or ""))))}


def tpm_challengers_view(rec: dict, tip: int) -> dict:
    """The challenger fields /tpm_enrolment serves for `rec` at `tip`: {} for a record whose set is written, else
    {"challengers": the pure draw once its epoch has come, or k placeholders before, "draw_at", "draw_pending"}.

    NEVER AN EMPTY SET FOR AN OPEN RECORD. The shipped helper (apps/nado-tpm-attest enrol.rs) reads only
    len(challengers) and compares it with len(blobs): an empty list reads as "every drawn challenger answered", so
    it would activate nothing, commit to nothing, be refused, and exit — a client that cannot be rebuilt by us
    breaking on the delayed draw. k placeholders keep it printing "0/3 answered" and waiting, exactly as a slow draw does."""
    from ops import tpm_enrol as _te
    if rec.get("state") != "open" or rec.get("challengers"):
        return {}
    at = _te.draw_opens(int(rec.get("h") or 0))
    try:
        drawn = tpm_drawn_challengers(rec, tip)
    except Exception:
        drawn = None                         # this node cannot evaluate the draw yet; the placeholders still say "wait"
    k = _te.record_k(rec)                    # 5 for a v2 record: the helper then waits for "0/5 answered"
    full = bool(drawn) and len(drawn) == k
    return {"challengers": sorted(drawn) if full else [f"(drawn at block {at})"] * k,
            "draw_at": at, "draw_pending": not full}


def tpm_materialise_draw(rec: dict, block_height: int) -> dict:
    """`rec` with its challenger set filled in, for the tpm_challenge that is about to land at `block_height`.
    Validation and apply both call this before apply_challenge, so the dry run and the real transition see the same
    set; apply then STORES it, and every later message (commit, reveal, register) reads a written set exactly as it
    read the enrol-time draw's records on betanet-8. The record it was materialised from is what the rollback journal holds, so a revert puts
    the empty set back byte for byte. Raises AssertionError before the draw epoch or on a short set."""
    from ops import tpm_enrol as _te
    if rec.get("challengers"):
        return rec
    drawn = tpm_drawn_challengers(rec, block_height)
    assert drawn is not None, \
        f"this enrolment's challengers are drawn at block {_te.draw_opens(rec['h'])} — a challenge cannot land before"
    # Cannot be short for a record the enrol check admitted (same pool, exact sampling), but a short set is a weaker
    # proof, so it is never written: the record then simply expires and the chip re-enrols.
    assert len(drawn) == _te.record_k(rec), \
        "not enough independent challengers were in the pool this enrolment was opened against"
    out = dict(rec)
    out["challengers"] = sorted(str(a) for a in drawn)
    return out


def tpm_duty_bounds(rec: dict, tip: int) -> tuple:
    """(min_block, max_block) for a challenger's next message on `rec` sent at `tip` — ONE DEFINITION for the node's
    own challenger loop (core_loop.maybe_tpm_challenge) and the wallets' /tpm_duty, so a wallet is told exactly the
    window a node would use. THE DEADLINE IS THE ENROLMENT'S, THE WINDOW IS THE MEMPOOL'S: the last block the record
    accepts a message (expiry - 1), clamped to what the mempool admits with a margin to wait for inclusion. When
    min_block > max_block nothing sent now could land: the caller skips the duty."""
    from protocol import TX_INCLUSION_DELAY, TX_LANDING_WINDOW, RESERVED_TX_MARGIN
    from ops import tpm_enrol as _te
    tip = int(tip)
    return tip + TX_INCLUSION_DELAY, min(_te.expiry(rec) - 1, tip + TX_LANDING_WINDOW - RESERVED_TX_MARGIN)


def tpm_pending_duties(tip: int, live) -> dict:
    """{address: [duty, ...]} for every LIVE enrolment (`live`: kv_ops.tpm_enrols_live(tip=tip)) whose drawn
    challenger still owes a message — the index /tpm_duty serves, so a challenger that is a WALLET rather than a node
    learns it was drawn (v2 draws from online stake, and a wallet can hold that stake).

      "challenge"  the record is open and the address is drawn and has published no challenge;
      "reveal"     the record is in commit and the address has a challenge on chain and no reveal.
    Each duty is {"id", "action", "ekpub", "name", "min_block", "max_block", "expires_at"} (+ "blob", the address's own
    published challenge, on a reveal), the bounds from tpm_duty_bounds; a duty
    whose window cannot fit is omitted, as the node's loop skips it. Membership is asked of the draw at the tip
    (tpm_drawn_challengers), exactly as the loop asks it — a record whose draw epoch has not come names nobody yet.
    Read-only; a record this node cannot evaluate yet is skipped, never guessed."""
    from ops import tpm_enrol as _te
    out = {}
    for eid, rec in live:
        state = rec.get("state")
        if state not in (_te.STATE_OPEN, _te.STATE_COMMITTED):
            continue
        try:
            drawn = tpm_drawn_challengers(rec, tip) or []
        except Exception:
            continue                                 # a window or beacon this node does not hold yet
        lo, hi = tpm_duty_bounds(rec, tip)
        if lo > hi:
            continue
        blob_of = {b[0]: b[1] for b in (rec.get("blobs") or [])}
        reveals = {r[0] for r in (rec.get("reveals") or [])}
        if state == _te.STATE_OPEN:
            owed = [(a, "challenge") for a in drawn if a not in blob_of]
        else:
            owed = [(a, "reveal") for a in drawn if a in blob_of and a not in reveals]
        expires_at = int(rec["h"]) + _te.enrol_window(int(rec["h"]))
        for a, action in owed:
            duty = {"id": str(eid), "action": action, "ekpub": rec["ekpub"], "name": rec["name"],
                    "min_block": int(lo), "max_block": int(hi), "expires_at": expires_at}
            if action == "reveal":
                # THE CHALLENGE THIS ADDRESS PUBLISHED, so a wallet open on two devices reveals only from the device whose
                # secret reproduces it (the other device's challenge was refused as a duplicate and its secret is wrong).
                duty["blob"] = blob_of[a]
            out.setdefault(str(a), []).append(duty)
    for duties in out.values():
        duties.sort(key=lambda d: d["id"])
    return out


def register_device_challenge(sender: str, anchor_hash: str, max_block: int) -> bytes:
    """The 32-byte challenge a device must attest over: bound to the chain, the identity, the anchor block
    (fresh, unpredictable) and the landing block — an attestation can never be replayed for another identity
    or another lease. The wallet computes the same bytes (blake2bHash of the same list)."""
    from hashing import blake2b_hash
    return bytes.fromhex(blake2b_hash([CHAIN_ID, sender, anchor_hash, int(max_block)]))


def is_assert_device(dev) -> bool:
    """True when a register's `device` is a SIGNATURE RENEWAL (protocol.LEASE_ASSERT_CLASSES): a WebAuthn assertion
    {ad, cdj, sig, rp} by the credential a statement already bound — no attestation object, no enrolment id."""
    return (isinstance(dev, dict) and isinstance(dev.get("sig"), str) and isinstance(dev.get("ad"), str)
            and "att" not in dev and "id" not in dev)


def verify_register_assertion(transaction, anchor_hash):
    """SIGNATURE RENEWAL (gen 25's LEASE_V2_EPOCH, LEASE_ASSERT_CLASSES; doc/device-attestation.md §"Leases per class").
    The sender's account carries `devkey` (the device its statement bound) and `devcred` (that statement's WebAuthn
    credential, COSE); the devbind row must still point at the sender; the class must be one whose device key does not
    rotate; and the kernel verifies the assertion over THIS block's own challenge. Renews the lease exactly like a
    statement renewal and binds nothing. Raises AssertionError with the reason."""
    import base64 as _b64
    from protocol import DEVICE_ATTEST_RP_IDS, POSW_ANCHOR_OFFSET, LEASE_ASSERT_CLASSES
    from ops import attest_native
    dev = transaction["device"]
    height = int(transaction.get("max_block") or 0)                 # `register` lands EXACTLY at max_block
    # (the LEASE_V2_EPOCH "not enabled yet" assert is gone: that gate was epoch 0 from gen 26, true for every epoch)
    acc = get_account(transaction["sender"], create_on_error=False) or {}
    dk, dc = acc.get("devkey"), acc.get("devcred")
    assert isinstance(dk, str) and dk and isinstance(dc, str) and dc, \
        "signature renewal: this identity has no credential on chain — renew with a statement first"
    cls = dk.split(":", 1)[0]
    assert cls in LEASE_ASSERT_CLASSES, f"signature renewal is not available for a {cls} binding — renew with a statement"
    bound = kv_ops.devbind_get(dk)
    assert bound and bound[0] == transaction["sender"], \
        "signature renewal: the device that vouched for this identity now vouches for another — attest again"
    try:
        ad = _b64.b64decode(str(dev.get("ad", "")), validate=True)
        cdj = _b64.b64decode(str(dev.get("cdj", "")), validate=True)
        sig = _b64.b64decode(str(dev.get("sig", "")), validate=True)
        cose = bytes.fromhex(dc)
    except Exception:
        raise AssertionError("signature renewal is not valid base64")
    assert 37 <= len(ad) <= 4_000 and 0 < len(cdj) <= 4_000 and 0 < len(sig) <= 1_024, "signature renewal size out of bounds"
    rp = str(dev.get("rp", "") or "")
    assert 0 < len(rp) <= 253 and all(c.isalnum() or c in ".-" for c in rp), "device rp id malformed"
    anchor_block = get_block_number(max(0, height - POSW_ANCHOR_OFFSET))
    assert anchor_block and anchor_block.get("block_hash") == anchor_hash, "attestation anchor block unavailable"
    challenge = register_device_challenge(transaction["sender"], anchor_hash, height)
    verdict = attest_native.verify_assertion(cose, ad, cdj, sig, challenge, rp_ids=list(DEVICE_ATTEST_RP_IDS) + [rp])
    assert verdict.get("ok"), f"signature renewal rejected: {verdict.get('reason')}"
    return verdict


def is_ek_device(dev) -> bool:
    """True when a register's `device` is a VENDOR-ENDORSED TPM proof rather than a WebAuthn statement.
    Keyed on the presence of an enrolment id, which no WebAuthn statement carries — the two shapes share no
    field, so a statement can never be read as the other kind by accident."""
    return isinstance(dev, dict) and isinstance(dev.get("id"), str) and "att" not in dev


def verify_register_device_ek(transaction: dict, anchor_hash: str) -> dict:
    """Consensus check of a VENDOR-ENDORSED TPM register (doc/tpm-attestation-without-a-ca.md).

        device = {"ek": <64-hex endorsement identity>, "id": <32-hex enrolment id>,
                  "certinfo": <hex TPMS_ATTEST>, "sig": <hex signature>}

    WHAT MAKES THIS A REGISTRATION AND NOT A REPLAY. The enrolment proved, once, that an attestation key
    lives inside a chip a silicon vendor certified. It says nothing about WHEN, and a proof from last year is
    not evidence the machine still exists. So the register carries a FRESH TPM2_Certify under that key whose
    extraData is this block's own challenge — bound to this sender, this anchor and this landing height, so
    it can be replayed for no other identity and no other lease.

    THE SENDER NEED NOT BE THE ACCOUNT THAT OPENED THE ENROLMENT, and that is deliberate rather than an
    oversight. Whoever can make the chip sign this block's challenge holds the chip; an enrolment is public
    data and grants its opener nothing. What stops one chip becoming many identities is that the binding key
    below is the ENDORSEMENT identity, which is one per chip by manufacture — so a machine that enrols ten
    attestation keys, or whose owner changes, still holds exactly one identity at a time.
    """
    from ops import tpm_aik
    from ops.tpm_enrol import record_k
    dev = transaction.get("device") or {}
    height = int(transaction.get("max_block") or 0)      # `register` lands EXACTLY at max_block
    # DEVICE_ATTEST_EK_HEIGHT was 1 from gen 26 (deleted): only a max_block of 0 — block 0 is genesis, which carries
    # no transactions — still falls below it. Kept so the verdict for such a tx is unchanged.
    assert height >= 1, "vendor-endorsed TPM attestation is not enabled yet"
    eid = dev.get("id")
    assert isinstance(eid, str) and len(eid) == 32 and _is_hex_str(eid), "malformed enrolment id"
    rec = kv_ops.tpm_enrol_get(eid)
    assert rec, "no such enrolment"
    assert rec.get("state") == "proven", "this enrolment has not completed its challenges"
    # The endorsement identity rides in the tx so the BINDING KEY is a pure function of the transaction's own
    # bytes, exactly like every other device class: apply and revert then derive the same key with no DB read,
    # and a record that changed underneath could never move a binding.
    assert dev.get("ek") == rec["ek"], "the declared endorsement identity is not this enrolment's"
    # the record's OWN k: 3 for a legacy record (unchanged), 5 for a v2 one (protocol.TPM_POOL_V2_HEIGHT)
    assert len(rec["challengers"]) == record_k(rec), \
        "this enrolment was proved against the wrong number of challengers"
    cert_info = _hex_bytes(dev.get("certinfo"), 2048, "certInfo")
    sig = _hex_bytes(dev.get("sig"), 1024, "certify signature")
    challenge = register_device_challenge(transaction["sender"], anchor_hash, height)
    try:
        detail = tpm_aik.verify_certify(bytes.fromhex(rec["pub"]), cert_info, sig, challenge)
    except ValueError as e:
        raise AssertionError(f"vendor-endorsed attestation rejected: {e}")
    return {"ok": True, "fmt": "ek", "ek": rec["ek"], "enrol": eid, "detail": detail,
            "root_sha256": "", "aaguid": ""}


def verify_register_device(transaction: dict, anchor_hash: str) -> dict:
    """Consensus check of transaction["device"] = {"att": b64, "cdj": b64, "rp": str}. Deterministic: the
    certificate validity clock is the ANCHOR block's timestamp (never wall time), the roots are the pinned
    set, the accepted rp ids are protocol.DEVICE_ATTEST_RP_IDS plus the tx's own declared rp (the rp id is a
    phishing control, not the Sybil control — the secure-element chain is). Raises AssertionError on any
    failure; returns the kernel's verdict dict on success."""
    import base64 as _b64
    from protocol import DEVICE_ATTEST_FORMATS, DEVICE_ATTEST_RP_IDS, POSW_ANCHOR_OFFSET
    from ops import attest_native
    dev = transaction.get("device")
    assert isinstance(dev, dict), "Missing device attestation (a registered identity must be a real phone)"
    if is_ek_device(dev):                       # vendor-endorsed TPM: a certify, not a WebAuthn statement
        return verify_register_device_ek(transaction, anchor_hash)
    try:
        att = _b64.b64decode(str(dev.get("att", "")), validate=True)
        cdj = _b64.b64decode(str(dev.get("cdj", "")), validate=True)
    except Exception:
        raise AssertionError("device attestation is not valid base64")
    assert 0 < len(att) <= 64_000 and 0 < len(cdj) <= 4_000, "device attestation size out of bounds"
    rp = str(dev.get("rp", "") or "")
    assert 0 < len(rp) <= 253 and all(c.isalnum() or c in ".-" for c in rp), "device rp id malformed"
    anchor_block = get_block_number(max(0, int(transaction["max_block"]) - POSW_ANCHOR_OFFSET))
    assert anchor_block and anchor_block.get("block_hash") == anchor_hash, "attestation anchor block unavailable"
    # THE CERTIFICATE CLOCK IS _anchor_time, never this block's own block_timestamp read inline: that field is outside
    # the block hash and differs node to node for the same block (protocol.py "CERTIFICATE VALIDITY READS AGREED
    # TIME"). `register` lands exactly at max_block, so max_block is the height the clock is read at. The anchor block
    # is still read above — the challenge binds its HASH, which is committed — but its timestamp must never decide
    # validity. INVARIANT: never pass the anchor block's timestamp (or the block) into the clock.
    now = _anchor_time(transaction, int(transaction["max_block"]))
    challenge = register_device_challenge(transaction["sender"], anchor_hash, int(transaction["max_block"]))
    # the notBefore grace (cert_verdict): agreed time lags, a phone's certificate may be minutes old
    verdict = cert_verdict(lambda t: attest_native.verify(att, cdj, challenge, t, rp_ids=list(DEVICE_ATTEST_RP_IDS) + [rp]),
                           now)
    assert verdict.get("ok"), f"device attestation rejected: {verdict.get('reason')}"
    fmt = verdict.get("fmt")
    assert fmt in DEVICE_ATTEST_FORMATS, f"device attestation format not accepted: {fmt}"
    # PER-DEVICE-CLASS CONSTRAINTS (doc/device-attestation.md — none of these may be spoofable):
    #   apple / android-key: the vendor root reached is the whole proof (chain verified by the kernel).
    #   tpm: the chain must end at Microsoft's TPM root and the AIK certificate's TPM manufacturer must be a physical
    #        maker (Microsoft's own id is a virtual TPM). On gen 25 below 41200 it ALSO had to carry the Windows Hello
    #        hardware AAGUID — see the regression note below.
    #   packed: the AAGUID must be a FIDO2 authenticator with full attestation in the pinned metadata snapshot AND
    #        the chain must end at one of THAT authenticator's own roots.
    from protocol import (DEVICE_ATTEST_TPM_AAGUIDS, DEVICE_ATTEST_TPM_MANUFACTURERS, DEVICE_ATTEST_FIDO_AAGUID_ROOTS,
                          DEVICE_ATTEST_ROOT_FINGERPRINTS)
    aaguid, root = str(verdict.get("aaguid") or ""), str(verdict.get("root_sha256") or "")
    if fmt == "tpm":
        # NEVER JUDGE A TPM STATEMENT BY ITS AAGUID AGAIN (2026-09-10). The AAGUID names the Windows Hello FLAVOUR
        # (hardware / "VBS" / "software"), not where the key lives: a real Intel-PTT PC produced four statements under
        # the "VBS" AAGUID 9ddd1817 that the kernel verified end to end — Microsoft TPM root, manufacturer INTC, a
        # TPM_ST_ATTEST_CERTIFY over the credential's own pubArea — and this line threw every one of them away, while
        # the wallet told the owner to disable Credential Guard. A key that is genuinely NOT in a TPM cannot produce a
        # certify at all: Windows returns fmt "none" and the format assert above already refuses it. The three asserts
        # that remain ARE the proof (pinned Microsoft root + physical manufacturer + the kernel's certify check), and
        # the binding is the AIK certificate either way (one per physical TPM per Windows account), so widening this
        # cannot buy an attacker an extra identity. Height-gated because it is a consensus rule: `register` lands
        # EXACTLY at max_block (block_ops._lands_flexibly), so max_block IS this tx's landing height. The gate
        # (DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT) was 1 from gen 26 and is deleted; only a max_block below 1 — a tx that
        # can never land, block 0 being genesis — still met the old rule, and keeps it so its verdict is unchanged.
        if int(transaction.get("max_block") or 0) < 1:
            assert aaguid in DEVICE_ATTEST_TPM_AAGUIDS, "tpm attestation: not the Windows Hello hardware authenticator"
        assert root in DEVICE_ATTEST_ROOT_FINGERPRINTS, "tpm attestation: chain does not end at the pinned Microsoft TPM root"
        assert str(verdict.get("tpm_manufacturer") or "").upper() in DEVICE_ATTEST_TPM_MANUFACTURERS, \
            f"tpm attestation: TPM manufacturer {verdict.get('tpm_manufacturer')} is not a physical TPM maker"
    elif fmt == "packed":
        roots_for = DEVICE_ATTEST_FIDO_AAGUID_ROOTS.get(aaguid)
        assert roots_for, "packed attestation: AAGUID is not a FIDO2 authenticator with full attestation"
        assert root in roots_for, "packed attestation: chain does not end at this authenticator's own root"
    elif fmt == "trezor":
        # the kernel reports the model (T2B1/T3B1/T3T1/T3W1) from the device certificate's CN and the sha256 of the
        # bare root KEY that signed the CA certificate; that key must be one of THAT model's pinned roots
        from protocol import DEVICE_ATTEST_TREZOR_ROOTS
        import hashlib as _h
        keys = DEVICE_ATTEST_TREZOR_ROOTS.get(aaguid)
        assert keys, f"trezor attestation: model {aaguid} is not accepted"
        assert root in {_h.sha256(bytes.fromhex(k)).hexdigest() for k in keys}, \
            "trezor attestation: CA certificate is not signed by this model's pinned Trezor root"
        # THE REAL DEVICE CERTIFICATE HAS NO serialNumber (2026-09-14). The kernel used to refuse on that alone; the
        # first real Trezor Safe statement to reach the fleet (the operator's tap for the LA node) failed exactly there
        # with every cryptographic check passed. trezorlib tolerates its absence and nothing consumes it (binding key
        # = sha256 of the certificate, model = CN), so the serial is not required. `register` lands exactly at max_block;
        # the gate (DEVICE_ATTEST_TREZOR_SERIAL_OPTIONAL_HEIGHT) was 1 from gen 26 and is deleted — only a max_block
        # below 1 (a tx that can never land) still met the historical refusal, and keeps it so its verdict is unchanged.
        if int(transaction.get("max_block") or 0) < 1:
            from ops.device_attest import cbor_decode, cert_subject_has_serial
            _x5c = ((cbor_decode(att) or {}).get("attStmt") or {}).get("x5c") or []
            assert _x5c and cert_subject_has_serial(_x5c[0]), \
                "device attestation rejected: trezor: device certificate has no serialNumber"
    elif fmt == "ledger":
        from protocol import DEVICE_ATTEST_LEDGER_ISSUER_KEYS
        import hashlib as _h
        assert root in {_h.sha256(bytes.fromhex(k)).hexdigest() for k in DEVICE_ATTEST_LEDGER_ISSUER_KEYS}, \
            "ledger attestation: device certificate is not signed by the pinned Ledger issuer key"
    else:
        assert root in DEVICE_ATTEST_ROOT_FINGERPRINTS, "attestation chain does not end at a pinned vendor root"
    return verdict


def construct_register_tx(keydict, max_block, posw_proof=None, device=None):
    """Build a SIGNED open-lane registration/renewal tx. FEE-EXEMPT + zero-amount; carries the sequential
    PoSW proof (ops.posw.prove of posw.challenge_bytes(sender, anchor-block-hash)) that gates open-lane entry.
    posw rides in the signed body (create_txid commits it — only public_key is excluded), exactly like the
    browser's buildRegisterTx, so the node validates a CLI/agent registration identically to a wallet one."""
    tx = {"sender": keydict["address"], "recipient": "register", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    if posw_proof is not None:
        tx["posw"] = posw_proof          # retired at gen 25: ignored by validation, kept for old callers
    if device is not None:
        tx["device"] = device            # {"att", "cdj", "rp"} — committed by the txid like posw
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_msgkey_tx(keydict, kem_pub, max_block, fee=0):
    """Build a SIGNED on-chain messaging-key tx. FEE-EXEMPT + zero-amount identity tx (recipient 'msgkey')
    that BINDS the sender's ML-KEM-768 encryption pubkey (`kem_pub`, 2368 hex chars) to their on-chain
    account, so anyone can DM them by address/alias with no off-chain prekey publish. kem_pub rides top-level
    in the SIGNED body (create_txid commits it — only public_key is excluded), exactly like register's `posw`,
    so the browser's buildMsgkeyTx and the node agree byte-for-byte. Key rotation is allowed (a later msgkey
    overwrites; apply_msgkey is revert-symmetric)."""
    tx = {"sender": keydict["address"], "recipient": "msgkey", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": "",
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": int(fee), "kem_pub": kem_pub}   # fee: a ROTATION pays MIN_TX_FEE
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


def construct_dividend_withdraw_tx(keydict, amount, nonce, proof, max_block, min_block=0):
    """Build a SIGNED presence-dividend claim: recipient 'dividend_withdraw', fee-exempt, self-claimed
    (data.addr == sender). Releases a COLLECTED {addr, amount, nonce} from the DIVIDEND_POOL once its
    Merkle proof verifies against the settled execution-layer root (validate_transaction checks that)."""
    tx = {"sender": keydict["address"], "recipient": "dividend_withdraw", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": {"addr": keydict["address"], "amount": int(amount), "nonce": str(nonce), "proof": proof},
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": 0}
    if int(min_block) > 0:
        # dividend_withdraw lands FLEXIBLY, so min_block is its propagation guard — without it the
        # claiming node includes its own claim the second it exists, before gossip delivers it anywhere,
        # and forks the chain (fork seed h66894). Same rule every flexibly-landing tx already follows.
        tx["min_block"] = int(min_block)
    tx["txid"] = create_txid(tx)
    tx["signature"] = sign(private_key=keydict["private_key"], message=unhex(tx["txid"]))
    return tx


def construct_settle_tx(keydict, exec_cursor, state_root, max_block, ns=DEFAULT_NS, proof=None,
                        proof_da=None):
    """Build a SIGNED execution-layer settlement attestation: recipient 'settle', data
    {exec_cursor, state_root[, ns][, proof]}, fee-exempt (fee 0) in the default namespace and MIN_TX_FEE in any other
    (from max_block 1). Posted by a bonded validator running an
    exec node. `ns` names the rollup namespace; the default namespace is omitted from `data` so default-layer
    settle txs stay byte-identical to the pre-namespace format.

    `proof` (optional) is the succinct SPARSE settlement proof (doc/zk-recursion.md §5c):
    {cursor, kv_pre, kv_post, rec, segments} — segments chain bound epochs over the KV half of the settled
    root (execnode/exec_root.py); `rec` is the (unchanged) records half. When present, EVERY node verifies it
    deterministically at block-validation and, on success, the root is settled TRUSTLESSLY (no bonded quorum
    needed) — see validate_transaction's `settle` branch: rnode(kv_pre, rec) must equal the committed settled
    tip (EXEC_GENESIS_ROOT for the first settlement) and rnode(kv_post, rec) must equal state_root."""
    d = {"exec_cursor": int(exec_cursor), "state_root": state_root}
    if ns != DEFAULT_NS:
        d["ns"] = ns
    if proof is not None:
        d["proof"] = proof
    if proof_da is not None:
        # DA-CARRIED PROOF. The inline `proof` above is ~97 MiB at protocol strength against a ~256 KiB
        # block and an 8 MiB submit cap, so it can never ride on chain — measured, doc/settle-proof-
        # transport.md §1. `proof_da` is the DA commitment for exactly those proof bytes, so the proof is
        # PUBLISHED and reconstructible by any node (da_fetch collects k-of-n verified shards and checks
        # the commitment round-trip) instead of existing only on the prover's disk.
        #
        # It does NOT yet settle the root trustlessly: that needs L1 to fetch and verify during block
        # validation inside the depth gate, which is a consensus change (§4 option 0/1). Until then the
        # root still rides the bonded quorum and this field makes the proof AVAILABLE and independently
        # checkable, which is the difference between a claim and evidence.
        d["proof_da"] = proof_da
    # A NAMESPACE SETTLE PAYS (protocol.py "NO FREE REPEATABLE TRANSACTIONS"): outside the default namespace validation requires
    # fee >= MIN_TX_FEE, and this builder signed fee 0 for every namespace — so every settle an exec node posted for a
    # NADO_EXEC_NAMESPACES namespace was refused (found 2026-09-28 by the gen-28 rehearsal). The default namespace stays
    # fee 0, byte-identical. INVARIANT: this must charge exactly what the settle branch of validate_transaction demands
    # (`>= 1` there, gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value; a max_block of 0 can never land anyway).
    from protocol import MIN_TX_FEE
    fee = MIN_TX_FEE if (ns != DEFAULT_NS and int(max_block) >= 1) else 0
    tx = {"sender": keydict["address"], "recipient": "settle", "amount": 0,
          "timestamp": get_timestamp_seconds(),
          "data": d,
          "nonce": create_nonce(), "public_key": keydict["public_key"],
          "max_block": int(max_block), "chain_id": CHAIN_ID, "fee": fee}
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
    """Build a SIGNED cross-rollup message DELIVERY: recipient 'xmsg' (MIN_TX_FEE from max_block 1), data carries the outbox
    `message` {seq, from, to_ns, data} + the Merkle `proof` that it is committed in from_ns's SETTLED root.
    L1 verifies that ONE proof against latest_settled(from_ns) and burns the (from_ns, seq) nullifier; the
    receiver rollup's exec node then delivers it to its inbox. Relayer-submittable — anyone can carry a
    genuinely-settled message, and the proof makes forgery impossible."""
    d = {"from_ns": from_ns, "to_ns": to_ns, "message": message, "proof": proof}
    # PAID, exactly as validation demands (fee >= MIN_TX_FEE from height 1, == 0 at height 0 — gen 27's
    # SPAM_HARDEN_HEIGHT at its gen-28 value, deleted). This builder signed fee 0 at every height, so each delivery it
    # built was refused (gen-28 rehearsal, tests/test_namespace_settle_pays.py — the settle builder had the same defect).
    from protocol import MIN_TX_FEE
    tx = {"sender": keydict["address"], "recipient": "xmsg", "amount": 0,
          "timestamp": get_timestamp_seconds(), "data": d, "nonce": create_nonce(),
          "public_key": keydict["public_key"], "max_block": int(max_block),
          "chain_id": CHAIN_ID, "fee": MIN_TX_FEE if int(max_block) >= 1 else 0}
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
        if r in ("withdraw", "unbond", "register", "msgkey", "auth", "pool", "delegate", "undelegate"):
            return (r, tx["sender"])                                  # one per sender per block
            # pool / delegate / undelegate are always refused by validate_transaction (pools never ran from gen 26);
            # their keys stay so assembly drops and verify_block rejects exactly what they did before the cleanup.
            # `msgkey` is fee-exempt and (unlike register) not epoch-gated, so without a per-block
            # uniqueness key an account could flood unlimited distinct-txid ~2.4 KB msgkey txs for free.
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
            # ONE SLASH PER OFFENCE (the SLASH_DEDUP_HEIGHT gate, 1 from gen 26, deleted): key by the RESOLVED
            # offence for both proof shapes. `>= 1` is that gate's value, kept because a tx's max_block is its own
            # field and 0 (never landable) must keep its per-proof key exactly as before.
            if int(tx.get("max_block") or 0) >= 1:
                res = resolve_slash(d)
                if res is not None:
                    return ("slash", res[0], res[1])
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
        if r in ("invite_claim", "invite_refund"):
            return ("invite_settle", (tx.get("data") or {}).get("id"))                  # one claim OR refund per invite per block
        if r == "invite_lock":
            # two locks under ONE key in one block would both pass validation against the parent state (no row yet) and
            # the second would overwrite the first's escrow record — one lock per key per block
            return ("invite_lock", (tx.get("data") or {}).get("key"))
        if r == "unshield":
            d = tx.get("data") or {}
            return ("unshield", d.get("addr"), d.get("nonce"))                          # one unshield exit per (addr, nonce)
        if r == "treasury_vote":
            return ("treasury_vote", tx["sender"], (tx.get("data") or {}).get("pid"))    # one vote per (validator, pid) per block
        if r == "treasury_execute":
            return ("treasury_execute", (tx.get("data") or {}).get("pid"))               # one payout per pid per block
        # ONE ENROLMENT MESSAGE PER (sender, enrolment) PER BLOCK. Each validates against the parent record, so a
        # challenger loop's retry could put two in one candidate; the second always raised at apply ("already
        # challenged" / "not awaiting a commitment" / "already revealed") and the node built a block it could not
        # apply. The key refuses NO block that apply did not already refuse, so it needs no height gate — only the
        # builder changes (dedupe_reserved drops the copy). tpm_enrol was deliberately absent: a second enrolment of
        # the same chip applied (it overwrote the row), so keying it changes which blocks are valid — it is keyed below,
        # behind `max_block >= 1`.
        if r in ("tpm_challenge", "tpm_commit", "tpm_reveal"):
            return (r, tx["sender"], str((tx.get("data") or {}).get("id")))
        # NO FREE REPEATS (protocol.py "NO FREE REPEATABLE TRANSACTIONS", audit 2026-09-27; betanet-8 from block 24000),
        # keyed on the tx's own max_block like `slash`. `>= 1` is gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value (the
        # constant is deleted), kept because max_block is the tx's own field: a zero or missing one keeps yielding no key.
        #  * tpm_ready — one per sender per block. It had no key at all and lands flexibly, so copies with fresh nonces
        #    all landed together (five blocks on betanet-8 carried two from one sender before the rule).
        #  * tpm_enrol — one per CHIP per block. The one-open-enrolment-per-chip rule reads the parent record, so several
        #    enrolments of one chip (distinct attestation keys) all passed inside a single block; the key is the chip's
        #    endorsement identity, sha256 of its SubjectPublicKeyInfo, the same handle the kernel's verdict names.
        if r == "legacy_claim":
            return ("legacy_claim", str((tx.get("data") or {}).get("legacy")))     # one claim per old address per block
        if r in ("tpm_ready", "tpm_enrol") and int(tx.get("max_block") or 0) >= 1:
            if r == "tpm_ready":
                return ("tpm_ready", tx["sender"])
            return ("tpm_enrol", ek_identity_of(tx))
    except Exception:
        return ("malformed", tx.get("txid"))   # unique-ish; the tx is rejected by validate_transaction
    return None


def ek_identity_of(tx) -> str:
    """The endorsement identity a tpm_enrol names: sha256 of the leaf certificate's SubjectPublicKeyInfo, lifted by the
    kernel's lenient parser — the handle attest_native.verify_ek reports as `identity`. A leaf that does not parse gets a
    per-tx key (no dedupe), and validation refuses the tx anyway."""
    import hashlib
    from ops import attest_native
    try:
        leaf = bytes.fromhex(str(((tx.get("data") or {}).get("ek") or [""])[0]))
        return hashlib.sha256(attest_native.ek_public_der(leaf)).hexdigest()
    except Exception:
        return "unparsed:" + str(tx.get("txid"))


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
    # ONE DEVICE PER BLOCK (the strict binding rule, gen 25's DEVICE_BIND_STRICT_HEIGHT): the devbind rule reads PARENT
    # state, so without this key N senders could bind one device inside a single block. `register` lands exactly at
    # max_block, so max_block is the block height. `>= 1` is the deleted gate's gen-26+ value, kept because max_block is
    # the tx's own field (a malformed or zero one must keep yielding no key). A malformed statement yields no key here;
    # validation rejects it anyway.
    if tx.get("recipient") == "register":
        from protocol import DEVICE_BIND_MAX_CERT_SECS
        try:
            # a statement-free renewal (the permanent binding mode) binds nothing, so it occupies no device key
            if (int(tx.get("max_block", 0)) >= 1
                    and isinstance(tx.get("device"), dict) and not is_assert_device(tx.get("device"))):   # an assertion binds nothing
                from ops.device_attest import device_binding_key
                # the SAME key validation and apply use (canonical: the signed part of the certificate — gen 27's
                # DEVICE_BIND_CANONICAL_HEIGHT, 1 from gen 28 and deleted; the `>= 1` above already covers it), so two
                # statements of one device with different trailing junk collide here too
                keys.append(("devbind", device_binding_key(
                    tx.get("device") or {}, DEVICE_BIND_MAX_CERT_SECS, strict=True, canonical=True)))
        except Exception:
            pass
    if tx.get("recipient") == "duty":
        d = tx.get("data") or {}
        if isinstance(d.get("attest"), dict):
            keys.append(("attest", tx.get("sender"), d["attest"].get("target_epoch")))
        if isinstance(d.get("commit"), dict):
            keys.append(("commit", tx.get("sender"), d["commit"].get("target_epoch")))
        if isinstance(d.get("reveal"), dict):
            keys.append(("reveal", d["reveal"].get("secret")))
    return keys


def _has_float(o):
    """True if a float appears anywhere in `o` (recursively). bool is an int subclass, not a float, so
    True/False pass. Used to keep floats out of tx `data` — see the validate_transaction data gate."""
    if isinstance(o, float):
        return True
    if isinstance(o, dict):
        return any(_has_float(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return any(_has_float(v) for v in o)
    return False


def dedupe_reserved(transactions):
    """Drop duplicate reserved txs (any shared uniqueness key), keeping the CANONICAL survivor — the
    lowest txid — NOT the first by mempool arrival. Two DISTINCT txids can share one reserved uniqueness
    key: a validator restart re-mints a duty/register tx with a fresh timestamp+nonce (new txid, same
    (sender, epoch) key), so both circulate. Resolving the collision by arrival order made two honest nodes
    build DIFFERENT blocks at the same height — recoverable (lowest-hash fork-choice converges, and the
    tx-index is out of the state root so H+1 roots still match) but a needless reorg that also desynced the
    upcoming_block_hash agreement signal. Iterating in txid order makes the survivor arrival-independent;
    the block's final order is re-sorted by txid downstream (cap_block_blobs + construct_block CO-8), so
    this ONLY pins WHICH of a colliding pair is kept. Used by block assembly so an honest producer never
    builds a block verify_block would reject for duplicates.

    WIDEST FORM FIRST, then lowest txid. Ordering by txid ALONE is deterministic but semantically wrong
    when the colliding pair are different FORMS of the same duty: a merged `duty` tx occupies its own key
    plus one per carried section, while a historical bare `attest` occupies exactly one. Whichever is
    processed first claims its keys and evicts the other, so a bare attest that happened to sort lower
    would evict the duty tx — silently dropping that validator's commit AND reveal for the epoch, not
    just the redundant attest. Sorting by descending key count keeps the form that carries strictly more
    duty, and txid still breaks every remaining tie, so the result stays arrival-independent."""
    seen, out = set(), []
    for t in sorted(transactions, key=lambda x: (-len(reserved_uniqueness_keys(x)), x.get("txid") or "")):
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
    # INVARIANT (audit 2026-09-25 "sig/pubkey hex re-encoding"): whatever this hash leaves out (public_key here, the
    # signature via validate_txid) still enters the block hash, so it must have exactly ONE valid spelling —
    # excluded_witness_check pins it. Excluding a new field without adding it there reopens tx re-encoding.
    body = {k: v for k, v in transaction.items() if k != "public_key"}
    return blake2b_hash(body)


# Port every DA node serves on. A module constant so tests can point the trustless fetch at a stand-in
# server instead of the real exec node (which owns 9273 on a live box).
DA_PORT = 9273

def _fetch_da_proof(commitment, timeout=8):
    """Reconstruct a DA-published settle proof by commitment, or None if this node cannot get it yet.

    Asks the LOCAL exec node first (it owns the DA store and can pull missing shards from peers itself),
    then falls back to REMOTE DA nodes over the trustless shard path. The fallback is the point: most of
    this fleet runs L1 only, with no :9273 listener anywhere except the publisher, so a DA-carried settle
    was unresolvable by every peer — and a block carrying one therefore lost every reorg.

    Returning None means "not yet", NEVER "invalid" — the caller defers the block rather than judging it.
    That distinction is the whole design: unavailability must cost liveness, never safety, or nodes fork
    along the axis of who happened to hold the data.

    Deliberately NOT cached and deliberately bounded by one overall deadline: a slow, missing or hostile
    source must degrade to a defer, not hang block validation. The bound is why this cannot become a
    liveness weapon — the worst a withholder achieves is that we wait, and the depth gate ends the wait.
    """
    import time as _t
    import urllib.request as _rq
    from urllib.parse import quote as _q
    _c = _q(str(commitment), safe="")
    _deadline = _t.time() + timeout
    # 1) THE LOCAL EXEC NODE, which owns the DA store and can itself pull missing shards from peers. Cheap
    #    when it has the blob; on a node that runs no exec layer this fails immediately (connection refused)
    #    and costs nothing.
    try:
        with _rq.urlopen(f"http://127.0.0.1:{DA_PORT}/da/get?c={_c}", timeout=timeout) as r:  # nosec B310 # literal http:// to a peer/loopback host; redirects guarded process-wide (ops/outbound_guard.py)
            if r.status == 200:
                return r.read()
    except Exception:
        pass
    # 2) REMOTE DA NODES, TRUSTLESSLY. Most of this fleet runs L1 ONLY — no :9273 listener anywhere but the
    #    publisher — so step 1 can never succeed there and a DA-carried settle was unresolvable by every
    #    peer, which is why such a block loses every reorg (observed live: block 23471 was built locally
    #    with a proof settle and reorged out; canonical 23471 carries zero settle txs on all four nodes).
    #
    #    NOT via /da/get: those bytes arrive unauthenticated, and bytes that merely fail to PARSE hit the
    #    reject branch ("retrievable but not a proof: that IS a judgement we can make"), so a hostile DA
    #    server could make us reject an HONEST block. The shard path is bound: every shard is checked
    #    against the on-chain commitment, and since the manifest is bound into each leaf that same check
    #    authenticates k/n/stripes/length, which STEER the decode.
    #
    #    ANY failure here means UNRESOLVED, never invalid — the caller defers the block.
    try:
        from ops import peer_ops as _po
        from ops.da_store import reconstruct_from as _rf
        _srcs, _seen = [], set()
        for _ip in list(_po.seed_peers()) + list(_po.known_peer_ips()):
            if _ip and _ip not in _seen:
                _seen.add(_ip); _srcs.append(_ip)
    except Exception:
        return None
    for _ip in _srcs:
        if _t.time() >= _deadline:
            break
        _left = max(0.5, _deadline - _t.time())
        try:
            with _rq.urlopen(f"http://{_ip}:{DA_PORT}/da/meta?c={_c}", timeout=min(3.0, _left)) as r:  # nosec B310 # literal http:// to a peer/loopback host; redirects guarded process-wide (ops/outbound_guard.py)
                if r.status != 200:
                    continue
                _meta = json.loads(r.read().decode())
            _k, _n = int(_meta["k"]), int(_meta["n"])
            # Bound k/n before iterating so a lied manifest cannot drive an unbounded fetch loop; the
            # binding check below is what actually decides whether the manifest is honest.
            if not (1 <= _k <= _n <= 64):
                continue
            _meta = dict(_meta, commitment=str(commitment))
            _pairs = []
            for _i in range(_n):                     # 0..k-1 first: the SYSTEMATIC shards, whose
                if len(_pairs) >= _k:                # reconstruction is pure byte movement
                    break
                if _t.time() >= _deadline:
                    break
                _left = max(0.5, _deadline - _t.time())
                try:
                    with _rq.urlopen(f"http://{_ip}:{DA_PORT}/da/shard?c={_c}&i={_i}", timeout=_left) as r:  # nosec B310 # literal http:// to a peer/loopback host; redirects guarded process-wide (ops/outbound_guard.py)
                        if r.status != 200:
                            continue
                        _j = json.loads(r.read().decode())
                    _pairs.append((_i, bytes.fromhex(_j["shard"]), _j["proof"]))
                except Exception:
                    continue
            if len(_pairs) < _k:
                continue
            return _rf(_meta, _pairs)                # verifies every shard AND the manifest, then decodes
        except Exception:
            continue
    return None


# Cryptographic verdicts for settle proofs, keyed by the proof's own identity. See the settle branch: a
# pooled tx is re-validated on every block-candidate build, and re-running a ~28 s (previously 94 s) proof
# verification each time is what stalled block production. The verdict is a pure function of the proof, so
# caching it changes no consensus decision — every context check around it still runs each time.
_SETTLE_VERIFY_MEMO = {}
_SETTLE_VERIFY_MEMO_MAX = 64
# SINGLE FLIGHT + ONE AT A TIME (2026-09-02). The memo only helps the SECOND arrival of a proof; the same
# settle tx pushed by nine peers inside one second reached nine to_thread workers before any of them had
# finished, and the sparse verification is pure-Python alghash2 under the GIL — fourteen concurrent
# verifications (25 s each alone) turned into a many-minute jam that starved every other API handler on
# the public relay, timed out the exec node's L1 calls and the peers syncing from this box, and the fleet
# forked five ways while nobody could fetch blocks here. One lock per verify key makes the followers wait
# for the leader's memo entry; one process-wide gate makes distinct proofs verify sequentially, which under
# the GIL is faster in total and leaves the worker pool free for everything else.
import threading as _threading
_SETTLE_VERIFY_LOCKS = {}
_SETTLE_VERIFY_LOCKS_GUARD = _threading.Lock()
_SETTLE_VERIFY_GATE = _threading.BoundedSemaphore(1)


def _settle_verify_lock(key):
    with _SETTLE_VERIFY_LOCKS_GUARD:
        if len(_SETTLE_VERIFY_LOCKS) > 256:
            _SETTLE_VERIFY_LOCKS.clear()
        return _SETTLE_VERIFY_LOCKS.setdefault(key, _threading.Lock())


def settle_verify_key(proof, pda, from_da, rules=None):
    """Cache key for a settle proof's cryptographic verdict — it MUST bind the proof's BYTES, and the RULES.

    This was once keyed on (cursor, kv_pre, kv_post, rec, rec_post): the proof's CLAIMS, not the FRI
    openings that actually get verified. Two proofs asserting the same thing shared an entry, so verifying
    an honest settle cached ok=True under a key a CORRUPTED settle also matched, and the tampered proof was
    accepted without ever being verified (tests/test_settle_depth_gate, tests/test_settle_verify_memo_key).

    DA proofs key on the COMMITMENT — a hash-based Merkle root over the exact shard set, which different
    bytes cannot present, and which the local DA store checks on the round trip before returning them.
    Inline proofs are digested directly: one pass over the proof against the ~22 s verification it guards.

    THE RULES ARE PART OF THE KEY (2026-09-23). The verdict is a function of the bytes AND of the verification
    rules in force at the block being judged (stark.rules_at: the FRI domain pin and the statement binding
    from PROOF_BIND_HEIGHT). An old-format proof verified ok=True one block below the gate must NOT answer
    ok=True for the block at the gate, where the same bytes are refused — the same "answers for input it
    never saw" bypass as the claims-only key, on the rules axis instead of the bytes axis.
    """
    from execnode.stark import stark as _stk
    r = tuple(_stk.current_rules() if rules is None else rules)
    return ("da", str(pda), r) if from_da else ("inline", blake2b_hash(proof), r)


class ProofUnavailable(Exception):
    """The block carries a DA-published settle proof we do not hold yet.

    NOT "invalid" — the third outcome. A node that cannot fetch the proof has learned NOTHING about whether
    the block is good, so rejecting it would fork the fleet along the axis of who happened to have the data.
    Deferring cannot: every node applies the same rule, so all converge on the same chain and a DA outage
    costs LIVENESS, never safety. This is the 4844/Celestia blob rule, and the exec layer already implements
    it one level down (_apply_block returns False and "the block STALLS in L1 order" when a field_transfer
    proof is unavailable).

    The stall is BOUNDED by the depth gate: once the block ages past FINALITY_DEPTH below the known tip,
    deep=True and the proof is no longer required, so a permanently unavailable proof degrades to the
    accumulated-weight path instead of halting the node forever.
    """


class WindowUnavailable(ProofUnavailable):
    """The challenger draw needs a block in [lo, hi) that this node does not hold.

    A ProofUnavailable — defer, never reject — that also NAMES the window, so the node can start filling it
    the moment validation trips over the hole instead of waiting to reach the production gate. A node stuck
    in recovery never reaches that gate (185.238.249.208 sat in an adoption loop for an hour with its hole
    untouched), and the block it cannot evaluate is exactly the one telling it what to fetch."""

    def __init__(self, msg, lo, hi):
        super().__init__(msg)
        self.lo, self.hi = int(lo), int(hi)



def settle_proof_io_check(proof, records_bound, block_height):
    """What a settle proof's io log may carry, judged at `block_height`. Raises AssertionError on refusal.

    NO PAYOUTS IN A RECORDS-FROZEN PROOF: a PAY moves bridge balances (RECORDS) at the runtime boundary, invisible to
    block_records_inert, while the proof pins one records root across the span. A records-BOUND proof derives the
    payout instead (records_bind.pay_effects_from_proof).

    ASSET IO IS ADMITTED BECAUSE IT IS BOUND. Review 2026-09-24 refused asset io in every settle proof: AMINT/ABURN/
    ASEL/ARENOUNCE move the exec asset ledger exactly as PAY moves records, and an ABAL read came from the io log with
    nothing tying it to the settled ledger (the BHASH/BEACON hole chain_reads closes). The zk audit 2026-09-26
    (gen 27's ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted) bound it instead: records_bind.PinnedAssets re-derives every
    asset move from the proven io against the pinned pre-state (issuer, supply cap, holdings, and each ABAL read
    against the running balance), and the settle branch folds those moves into the records binding — or, for a
    records-frozen proof, requires them to net to nothing (records_bind.proof_asset_ids). The refusal ran only at
    heights 1 <= h < that gate, an empty window on gen 28, so it is gone at every height (height 0 never refused).
    `block_height` stays in the signature for the callers and tests that pass it."""
    from execnode import zkvm as _zkvm
    segs = proof.get("segments") or []
    if not records_bound:
        for _seg in segs:
            for _e in (_seg.get("io") or []):
                assert int(_e[0]) != _zkvm.IO_PAY, \
                    "settle-with-proof io contains a PAY (moves RECORDS, which the proof freezes)"


def exit_amount_check(amount, block_height):
    """An exit claim's amount must be a real coin amount, not a field residue (review 2026-09-24). exec_root.verify_record
    folds `amount % P`, so a claim of amount + k*P verified against a record of `amount`; escrow balances and the per-block
    release cap happened to stop it, but the proof check itself must not depend on that. An exit is below 2^61 —
    MAX_EXIT_VALUE, the bound every exec record is created under — at every height from 1 (gen 25's
    PROOF_QUERY_FULL_HEIGHT, 1 from gen 26 and deleted; height 0 keeps its old verdict). Raises AssertionError like the
    branches that call it."""
    if int(block_height) >= 1:
        assert int(amount) < (1 << 61), "exit amount exceeds MAX_EXIT_VALUE"


def field_shield_check(data, block_height):
    """Admission rules for a field-native `shield` deposit, judged at `block_height` (the block being validated).
    A pure function so tests can drive it directly — the inline form read an unbound `h` for a day and nothing
    caught it (tests/test_privacy_pause.py). Raises AssertionError on refusal, like the branch it came from."""
    # C-2: the exec node BINDS the note value to this escrowed amount by recomputing
    # commit(amount, owner, rho) itself, so the deposit must carry (owner, rho), not a free-choice cm.
    assert data.get("owner") is not None and data.get("rho") is not None, "field shield needs owner + rho"
    # THE HEIGHT IS `block_height`, the block being judged. This branch read `h`, which only the HTLC
    # branches above ever assign, so from a8a720f1 (2026-09-23) every field-shield deposit raised
    # UnboundLocalError and was refused — the wide pool's own deposits included, i.e. on the reroll chain
    # nobody could have entered it. Found 2026-09-24 while adding the privacy pause.
    _sh = int(block_height)
    # THE LEGACY FIELD POOL TAKES NO DEPOSITS: gen 25 closed it between REVIEW_R2_HEIGHT and SHIELD_WIDE_HEIGHT, and
    # from gen 26 both gates were 1, so that window is empty and every deposit from block 1 is a WIDE one. Height 0
    # (mempool admission on a genesis tip) was below both gates and keeps its old verdict: no shape check.
    if _sh >= 1:
        # THE WIDE POOL (Z3): the owner is a 64-hex alghash2 digest and rho a decimal field element,
        # EXACTLY what state._apply_wide_shield computes the note from. Admitting any other shape
        # escrows the coins behind a note the exec layer then refuses to create — coins gone.
        from execnode.stark import znote as _Z, field as _ZF
        _ow = data.get("owner")
        assert isinstance(_ow, str) and len(_ow) == 64 and _ow == _ow.lower(), "wide shield owner must be a 64-hex digest"
        _Z.from_hex(_ow)                                                 # raises on an out-of-field lane
        _rh = data.get("rho")
        assert isinstance(_rh, (str, int)) and not isinstance(_rh, bool) and str(_rh).isdigit() \
            and 0 <= int(_rh) < _ZF.P, "wide shield rho must be a decimal field element"

def tx_shape_check(transaction, block_height):
    """Only the known top-level keys, and a body no bigger than its kind needs (protocol.py "NO FREE REPEATABLE
    TRANSACTIONS"). Pure shape — no state — so it is identical in the mempool and in block verification. Every size below
    is canonical bytes (the txid's own encoding), measured on the tx as signed. INVARIANT: a new top-level field on any
    client needs its name here (protocol.TX_TOP_KEYS / TX_TOP_KEYS_BY_RECIPIENT) before that client ships, or the node
    refuses its transactions.
    Height None or 0: no rule. `>= 1` is gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value (the constant is deleted), kept
    because validate_transaction also runs at mempool admission with the tip's height, which is 0 on a genesis tip."""
    from protocol import (TX_TOP_KEYS, TX_TOP_KEYS_BY_RECIPIENT, TX_MAX_BYTES,
                          TX_MAX_BYTES_PER_EXTRA_SIG, TPM_ENROL_MAX_BYTES, BLOB_MAX_BYTES)
    if block_height is None or int(block_height) < 1:
        return
    recipient = transaction.get("recipient")
    allowed = TX_TOP_KEYS | TX_TOP_KEYS_BY_RECIPIENT.get(recipient, frozenset())
    extra = sorted(k for k in transaction if k not in allowed)
    assert not extra, f"unknown transaction field(s): {', '.join(str(k)[:32] for k in extra[:4])}"
    body = transaction
    if recipient == "settle":
        # the settle proof is verified (inline, or fetched from DA by its commitment) and priced by its own rules; what
        # is capped here is everything else, where nothing checks the bytes
        data = transaction.get("data")
        if isinstance(data, dict) and "proof" in data:
            body = dict(transaction, data={k: v for k, v in data.items() if k != "proof"})
    sigs = transaction.get("signature")
    cap = TX_MAX_BYTES + TX_MAX_BYTES_PER_EXTRA_SIG * max(0, len(sigs) - 1 if isinstance(sigs, list) else 0)
    if recipient == "tpm_enrol":
        cap = max(cap, TPM_ENROL_MAX_BYTES)
    elif recipient in ("blob", "xmsg"):
        cap = max(cap, BLOB_MAX_BYTES + TX_MAX_BYTES)
    size = len(canonical_bytes(body))
    assert size <= cap, f"transaction is {size} bytes, over the {cap}-byte limit for a {recipient if recipient in RESERVED_RECIPIENTS else 'transfer'}"


_LOWER_HEX = frozenset("0123456789abcdef")


def _canonical_hex(s, n: int) -> bool:
    """Exactly `n` lowercase hex characters — the ONE spelling of a byte string. bytes.fromhex also takes uppercase,
    mixed case and whitespace, which is precisely the freedom excluded_witness_check removes."""
    return isinstance(s, str) and len(s) == n and all(c in _LOWER_HEX for c in s)


def excluded_witness_check(transaction, block_height):
    """Every witness the txid does NOT hash has exactly one byte-string spelling (protocol.py "ONE TRANSACTION, ONE BYTE
    STRING"; betanet-9 from block 1, never live on betanet-8).

    create_txid excludes `public_key` and validate_txid strips `signature` (a string, or the auth/multisig entry list
    with each entry's own key), but the block hash and the upcoming-block hash commit the full body. Without this a
    relayer could re-encode those fields (case, whitespace, an entry's extra keys or a null key) into a different body
    with the SAME txid that still validated — two nodes then held "the same" tx and built different blocks from one
    mempool, and a mixed-case key on an account's first tx became its stored PUBKEY-ONCE key, locking the owner's own
    transactions out (audit 2026-09-25, MED "sig/pubkey hex re-encoding"; tests/test_excluded_hex_fields_are_canonical.py).

    INVARIANT: a new txid-excluded field on a transaction, or a new key inside a signature entry, must be added HERE with
    its exact canonical form, or it reopens the re-encoding hole. Pure shape — no state read — so the mempool and
    verify_block agree. Height None or 0: no rule. `>= 1` is gen 27's TX_HEX_CANONICAL_HEIGHT at its gen-28 value (the
    constant is deleted), kept because validate_transaction also runs at mempool admission with the tip's height, which
    is 0 on a genesis tip."""
    if block_height is None or int(block_height) < 1:
        return
    pk_n, sig_n = _P.MLDSA44_PUBKEY_HEX, _P.MLDSA44_SIG_HEX
    # PRESENT means canonical: an honest client that relies on the key it already published OMITS the field, it never
    # sends null or "" (validate_origin reads both as "omitted", so either was a free re-encoding of an absent key)
    if "public_key" in transaction:
        assert _canonical_hex(transaction["public_key"], pk_n), \
            f"public_key must be exactly {pk_n} lowercase hex characters"
    sig = transaction.get("signature")
    if isinstance(sig, list):
        # NO TOP-LEVEL KEY BESIDE AN ENTRY LIST (found while fixing the above, reproduced): with a list, every key rides
        # in its entry and verification never reads the top-level public_key — yet index_transactions stored it as the
        # sender's PUBKEY-ONCE key when none was stored, and the implicit config then authorizes exactly that key. So a
        # relayer adding ITS key to an account's list-signed FIRST tx (same txid, still valid) took the account over.
        # sign_entries, the wallet's auth/multisig builders and draft_multisig_spend never send one.
        assert "public_key" not in transaction, "a transaction signed with an entry list carries no top-level public_key"
        for entry in sig:
            assert isinstance(entry, dict) and set(entry) in ({"signature"}, {"signature", "public_key"}), \
                "a signature entry carries exactly signature and, optionally, public_key"
            assert _canonical_hex(entry["signature"], sig_n), \
                f"a signature entry's signature must be exactly {sig_n} lowercase hex characters"
            if "public_key" in entry:
                assert _canonical_hex(entry["public_key"], pk_n), \
                    f"a signature entry's public_key must be exactly {pk_n} lowercase hex characters"
    else:
        assert _canonical_hex(sig, sig_n), f"signature must be exactly {sig_n} lowercase hex characters"


def validate_transaction(transaction, logger, block_height, deep=False):
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
    # NO UNBOUNDED BODIES (protocol.py "NO FREE REPEATABLE TRANSACTIONS"): any tx used to be able to carry unlimited extra
    # top-level keys, because the txid hashes every key and nothing listed the allowed ones — a fee-exempt message was free AND
    # unbounded in size. Checked first, before any signature or state read, so an oversized body costs one encode.
    tx_shape_check(transaction, block_height)
    # ONE TX, ONE BYTE STRING (protocol.py, audit 2026-09-25 "sig/pubkey hex re-encoding"): the
    # witnesses the txid does not hash must have exactly one spelling, BEFORE validate_origin decodes them leniently.
    # INVARIANT: never move this after validate_origin or behind a branch — every tx kind, multisig and auth included.
    excluded_witness_check(transaction, block_height)
    # HALT-CLASS (codec safety, audit 2026-07): `data` must survive the STORAGE codec, which
    # incorporate_block -> save_block packs with ensure_ascii=False. A lone UTF-16 surrogate ("\ud800")
    # passes the txid/signature (canonical_bytes is ensure_ascii=True) yet makes that pack raise
    # UnicodeEncodeError inside a path that must never raise — ~30s of blocked production and a lost slot per
    # MIN_TX_FEE tx, network-wide. Reject it here (this gate runs at mempool admission AND in verify_block)
    # so it can never reach block storage on any node. Cheap: the encode is work save_block does anyway.
    if "data" in transaction:
        from ops import codec as _codec
        try:
            _codec.pack(transaction["data"])
        except Exception:
            raise AssertionError("transaction data is not storage-encodable")
        # BROWSER-REPRODUCIBILITY + determinism: reject any float anywhere in `data`. `data` rides into the
        # txid AND the block-hash preimage (canonical_bytes), and arbitrary-key `data` is stored verbatim by
        # some handlers. Python json renders 1.0 as "1.0" but JS JSON.stringify renders it "1", so a float
        # makes a browser light-miner's txid disagree with the node's — and it breaks the integer-only
        # consensus invariant. amount/fee/min_block are int-gated separately; this closes the free-form hole.
        assert not _has_float(transaction["data"]), "transaction data must be integer/string-shaped (no floats)"
        # SIZE CAP for ORDINARY transfers. A non-reserved recipient is a plain value send and never carries
        # a proof, so its `data` must not become free unbounded storage: without this an ordinary transfer
        # could carry ~MAX_INLINE_TX_BYTES (192 MiB) of `data` for a flat MIN_TX_FEE, bypassing the DA-blob
        # pricing (BLOB_MAX_BYTES + a burned fee) the blob path exists to enforce. Reserved recipients keep
        # their own per-branch validation (settle/unshield/bridge_withdraw/xmsg legitimately carry large
        # proofs; blob is capped at BLOB_MAX_BYTES below). Deterministic (canonical-bytes), runs in verify.
        from protocol import RESERVED_RECIPIENTS as _RESERVED
        if transaction.get("recipient") not in _RESERVED:
            assert blob_payload_size(transaction["data"]) <= BLOB_MAX_BYTES, \
                f"transaction data exceeds {BLOB_MAX_BYTES} bytes (use a DA blob for large payloads)"
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
    if isinstance(transaction.get("signature"), list) and transaction.get("multisig") is None:
        # a configured account pays the fee floor for every signature entry BEYOND the first (bounded by
        # AUTH_MAX_KEYS in verify_entries) — the first is what a single-key tx already carries, so a
        # fee-exempt duty signed by one authenticator stays exempt
        assert transaction.get("fee", 0) >= MIN_TX_FEE * (len(transaction["signature"]) - 1), \
            "fee below the per-signature floor"
    assert validate_origin(transaction, block_height), "Invalid origin"
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
    # fee >= 0 as a TOP-LEVEL backstop (not only per-recipient): reflect_transaction debits balance-amount-fee,
    # so a negative fee MINTS coins to the sender. Non-negativity was enforced only by the scattered per-branch
    # `fee == 0 or fee >= MIN_TX_FEE` asserts; a future recipient branch that forgets one would be an inflation
    # bug. Pin it here beside the amount>=0 check, exactly as this function's own docstring already promises.
    assert transaction["fee"] >= 0, "Transaction fee lower than zero"
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
        result = resolve_slash(transaction.get("data"), block_height)   # judged at THIS block (ADDRESS_KEY_BIND)
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
        # REVEAL_SEATLESS_HEIGHT: a reveal-only duty opens a commitment the sender made while seated, so it needs no
        # seat of its own. INVARIANT: every other section still requires the landing epoch's seat.
        from protocol import REVEAL_SEATLESS_HEIGHT
        if not (set(sections) == {"reveal"} and tb >= REVEAL_SEATLESS_HEIGHT):
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
        assert transaction["amount"] == 0, "register tx must have zero amount"
        assert transaction["fee"] == 0, "register tx is fee-exempt (fee must be 0)"
        validate_register_referrer(transaction, block_height)
        from ops.block_ops import get_block_hash_by_number
        anchor = get_block_hash_by_number(max(0, transaction["max_block"] - POSW_ANCHOR_OFFSET))
        assert anchor, "registration anchor block not found"
        assert kv_ops.recert_latest(transaction["sender"]) < (block_height // EPOCH_LENGTH), \
            "sender already recerted this epoch (one register per epoch)"
        # REAL DEVICE (gen 25, doc/device-attestation.md): every register tx — entry or renewal — carries a hardware
        # attestation over the anchor-bound challenge, verified by the native kernel against the PINNED vendor
        # roots. This replaced the sequential-work proof (PoSW) and its difficulty machinery at the betanet-7
        # reroll: a VM, a desktop without hardware, an emulator, a virtual TPM or a rooted phone cannot attest;
        # a genuine device needs a human tap per identity per lease.
        from protocol import DEVICE_BIND_MAX_CERT_SECS, permanent_classes_at
        epoch_now = block_height // EPOCH_LENGTH
        # THE DEVICE GATES ARE GONE (gen 25's DEVICE_BIND_HEIGHT, DEVICE_BIND_STRICT_HEIGHT, DEVICE_BIND_PERMANENT_HEIGHT and
        # DEVICE_REBIND_INSTANT_HEIGHT were all 1 from gen 26). `block_height >= 1` below is that value, kept only because
        # this function also runs at mempool admission on a genesis tip (block_height 0), where every one of them was off.
        # BINDING MODES (doc/device-attestation.md §"Binding modes"): a register WITHOUT a statement is the statement-free
        # presence renewal of an identity permanently bound to a hardware wallet — valid only while the sender's `devkey`
        # row still points back at the sender in "perm" mode (a rebind elsewhere ends it from the next block). For anyone
        # else it is the historical "Missing device attestation".
        stmt_free = bool(block_height >= 1 and not isinstance(transaction.get("device"), dict))
        if is_assert_device(transaction.get("device")):
            # SIGNATURE RENEWAL (LEASE_V2_EPOCH): the credential a statement bound signs this block's challenge; nothing is
            # bound and no device key is derived (the shape has no certificate). Validated in full here.
            verify_register_assertion(transaction, anchor)
        elif stmt_free:
            acc_r = get_account(transaction["sender"], create_on_error=False) or {}
            dk = acc_r.get("devkey")
            bound = kv_ops.devbind_get(dk) if isinstance(dk, str) and dk else None
            assert bound and bound[0] == transaction["sender"] and bound[2] == "perm", \
                "Missing device attestation (a registered identity must be a real device; only an identity bound for life " \
                "to a hardware wallet renews without one)"
        else:
            verify_register_device(transaction, anchor)
            # ONE DEVICE, ONE IDENTITY (doc/device-attestation.md §"One device, one identity"):
            # the device certificate behind this statement may vouch for ONE sender per lease. A class with no per-device
            # certificate (FIDO2 batch key, Apple, batch-attested Android) cannot be bound and is refused outright —
            # "using one device to attest 100,000 wallets must be impossible". Reads the same consensus table
            # apply_register writes, at the block's own height.
            if block_height >= 1:
                from ops.device_attest import device_binding_key
                try:
                    # strict: duplicate CBOR keys are refused, so the chain the kernel verified IS the certificate that
                    # gets bound (IndexError/ValueError alike = malformed = invalid)
                    # canonical: keyed on the certificate's SIGNED part, trailing bytes refused — the raw-bytes key let
                    # one device back unlimited identities (protocol.py "ONE DEVICE, ONE IDENTITY — FOR REAL"; gen 27's
                    # DEVICE_BIND_CANONICAL_HEIGHT, 1 from gen 28 and deleted — this block already requires height >= 1)
                    dkey = device_binding_key(transaction.get("device") or {}, DEVICE_BIND_MAX_CERT_SECS, strict=True,
                                              canonical=True)
                except (ValueError, IndexError) as e:
                    raise AssertionError(f"register: {e}")
                # NO COOLDOWN (gen 25's DEVICE_REBIND_INSTANT_HEIGHT, 1 from gen 26, deleted with the pre-gate cooldown it
                # replaced): a device may move to another sender in any block, because apply EVICTS the identity it leaves
                # (its lease is voided at once), so one device backs one identity at every instant.
                # ...BUT NOT TO A NEW SENDER EVERY BLOCK (protocol.py "NO FREE REPEATABLE TRANSACTIONS", audit 2026-09-27).
                # A register needs no funds and creates its sender's account, so one device hopping to a fresh address
                # each block was a free ~13 KB tx and a new account row per block, forever. A device moves to a DIFFERENT
                # sender at most once per epoch (60 blocks): the first move — a lost key, a sold device, a wallet
                # migration — is still instant, and renewals by the bound sender are unaffected.
                # INVARIANT: keep the first move instant; bound the rest.
                _cur = kv_ops.devbind_get(dkey)
                assert not (_cur and _cur[0] != transaction["sender"] and int(_cur[1]) == epoch_now), \
                    "register: this device already moved to another account this epoch — try again next epoch"
                if dkey.split(":", 1)[0] in permanent_classes_at(block_height):
                    # ONE HARDWARE WALLET PER IDENTITY: an identity whose live permanent device is a DIFFERENT one is refused a
                    # second (a replaced or lost hardware wallet means a new account, or that device rebinding here later).
                    acc_r = get_account(transaction["sender"], create_on_error=False) or {}
                    dk_prev = acc_r.get("devkey")
                    if isinstance(dk_prev, str) and dk_prev and dk_prev != dkey:
                        pb = kv_ops.devbind_get(dk_prev)
                        assert not (pb and pb[0] == transaction["sender"] and pb[2] == "perm"), \
                            "register: this identity is already bound for life to another hardware wallet — use that device, " \
                            "or bind this one to a new account"
    elif recipient == "legacy_claim":
        # LEGACY CLAIM (gen 28; operator: "sign with your old key and get the coins"). An account whose key no chain
        # ever saw was carried at its OLD 46-character format-1 address, which format 2 refuses as a sender; its owner's
        # key K claims it from K's format-2 address (validate_origin has bound the sender to K). The claim names the
        # old address and its EXACT balance, so apply moves a stated amount and a rollback moves exactly that back, and
        # a second claim fails because the balance is then zero. ACCEPTED RISK (operator's decision, 332 accounts /
        # 142 NADO measured 2026-09-28): a key sharing the old address's 21 bytes can claim first — the exposure those
        # accounts already carried on gen 27. INVARIANT: only ever the whole balance, only an address with no key.
        # `>= 1` IS THE DELETED GATE'S OWN VALUE (LEGACY_CLAIM_HEIGHT was 1 from gen 28, deleted after the betanet-9
        # reroll): mempool admission validates at the tip's height, which is 0 on a genesis tip, and a claim was
        # refused there. Keep it; it changes no verdict on a chain with a block.
        from protocol import ADDRESS_BODY, ADDRESS_PREFIX
        from ops.address_ops import legacy_address
        assert block_height is not None and int(block_height) >= 1, "legacy claims are not enabled on this chain"
        assert transaction["amount"] == 0 and transaction["fee"] == 0, "legacy_claim carries no amount and no fee"
        data = transaction.get("data")
        assert isinstance(data, dict) and set(data) == {"legacy", "amount"}, "legacy_claim data is {legacy, amount}"
        legacy, amt = data["legacy"], data["amount"]
        assert isinstance(legacy, str) and len(legacy) == len(ADDRESS_PREFIX) + ADDRESS_BODY + 4, "not an old-format address"
        assert legacy != transaction["sender"], "a legacy claim cannot name its own sender"
        pk = transaction.get("public_key") or (get_account(transaction["sender"], create_on_error=False) or {}).get("public_key")
        assert isinstance(pk, str) and pk, "legacy_claim needs the claimant's public key"
        assert legacy_address(pk) == legacy, "this key's old address is not the one claimed"
        old = get_account(legacy, create_on_error=False)
        assert old and not old.get("public_key"), "only an old address whose key no chain ever saw can be claimed"
        assert int(old.get("bonded", 0) or 0) == 0, "a bonded old address cannot be claimed"
        assert isinstance(amt, int) and not isinstance(amt, bool) and amt > 0 and amt == int(old.get("balance", 0) or 0), \
            "legacy_claim amount must be the old address's whole balance"
    elif recipient == "tpm_ready":
        # VOLUNTEERING TO BE DRAWN. Carries nothing and proves nothing: it is an operator declaring that
        # this node runs the challenger loop, so the draw can prefer addresses that have said so over
        # addresses that merely look like validators on chain. Zero amount, no data, and the signature
        # (checked for every transaction) is the whole of what makes it the sender's own statement.
        # gen 25's DEVICE_ATTEST_EK_READY_HEIGHT was 1 from gen 26 (deleted); only block_height 0 (mempool admission on
        # a genesis tip) fell below it, and keeps its verdict.
        assert block_height >= 1, "challenger announcements are not enabled yet"
        assert int(transaction.get("amount") or 0) == 0, "tpm_ready carries no amount"
        assert not transaction.get("data"), "tpm_ready carries no data"
        # A VOLUNTEER HAS STAKE (protocol.py "NO FREE REPEATABLE TRANSACTIONS", audit 2026-09-27). This used to be the
        # cheapest message on the chain: any fee, no uniqueness key, sendable from a never-funded address (it skips the
        # empty-account check), and it wrote the sender's account row — free, unlimited, every block — and every sender
        # joined the challenger pool at weight 1, so a thousand free addresses outweighed the fleet in the TPM challenger
        # draw. It is fee-free only from a bonded sender, once per sender per block (reserved_uniqueness_key), and writes
        # nothing. Unconditional: the `>= 1` assert above already holds (gen 27's SPAM_HARDEN_HEIGHT, deleted).
        # INVARIANT: an announcement must cost the announcer stake; never let it through from an unbonded account.
        assert transaction["fee"] == 0, "tpm_ready is fee-exempt (fee must be 0)"
        _acc = get_account(transaction["sender"], create_on_error=False)
        assert _acc and _acc.get("bonded", 0) >= B_MIN, "only a bonded validator can volunteer as a challenger"

    elif recipient in ("tpm_enrol", "tpm_challenge", "tpm_commit", "tpm_reveal"):
        # VENDOR-ENDORSED TPM ENROLMENT (doc/tpm-attestation-without-a-ca.md).
        # Four fee-exempt, zero-amount messages that prove an attestation key lives inside a chip whose
        # ENDORSEMENT key a silicon vendor certified — the path for the 26.8 % of attempts Windows Hello
        # refuses, and the only path a headless Linux node has ever had.
        #
        # NOTHING HERE CONFERS STANDING. A completed enrolment records that one attestation key is inside one
        # certified chip. It is `register` that consumes it, with a FRESH TPM2_Certify over that block's own
        # challenge, and the identity binds to the ENDORSEMENT key — so enrolling ten attestation keys in one
        # chip yields one identity, not ten. Anyone may spend blocks on enrolments that buy them nothing.
        from protocol import DEVICE_ATTEST_EK_CHALLENGERS
        from ops import tpm_enrol as _te
        # gen 25's DEVICE_ATTEST_EK_HEIGHT was 1 from gen 26 (deleted); only block_height 0 (mempool admission on a
        # genesis tip) fell below it, and keeps its verdict.
        assert block_height >= 1, "vendor-endorsed TPM enrolment is not enabled yet"
        assert transaction["amount"] == 0 and transaction["fee"] == 0, \
            f"{recipient} tx is fee-exempt and carries no amount"
        data = transaction.get("data") or {}
        assert isinstance(data, dict), f"{recipient} data must be an object"
        sender = transaction["sender"]
        if recipient == "tpm_enrol":
            # STEP 1. The chip's endorsement chain and the public area of the key it will vouch for. The
            # chain is verified by the native kernel against the PINNED vendor roots — real vendor
            # certificates are not strictly DER and no Python parser in the node's runtime reads them.
            from ops import attest_native
            chain = _hex_list(data.get("ek"), 8, 8192, "ek chain")
            pub = _hex_bytes(data.get("pub"), 2048, "attestation public area")
            # the clock is _anchor_time, and apply_tpm_enrol_tx re-runs this same call through it — validation and
            # apply must judge the chain at the SAME agreed time or a record validated here fails to apply there
            _now = _anchor_time(transaction, block_height)
            ek = cert_verdict(lambda t: attest_native.verify_ek(chain, t, height=block_height), _now)
            assert ek.get("ok"), f"endorsement certificate rejected: {ek.get('reason')}"
            from protocol import ek_roots_at
            # the set the kernel just verified against (ek_roots_at), not the base set: the base set refused Intel
            # V2-root chips the kernel had accepted (betanet-8 below block 1400; protocol.py "ENROLMENT TRUSTS THE
            # ROOTS IN FORCE"). INVARIANT: the kernel's set and this one are the same call at the same height.
            assert ek.get("root_sha256") in ek_roots_at(block_height), \
                "endorsement certificate does not chain to a pinned silicon-vendor root"
            _te.validate_publication(str(ek["identity"]), pub)
            eid = _te.enrol_id(CHAIN_ID, str(ek["identity"]), _te.aik_name_hex(pub))
            # AN EXPIRED ATTEMPT MUST BE RETRYABLE, and making it so is not optional: the enrolment id is
            # DERIVED from (chain id, endorsement identity, attestation key name) with no nonce, so the
            # same chip with the same key template derives the same id forever. That is what makes a
            # proven enrolment stable and resumable, and it is also what made a FAILED one permanent —
            # refusing every duplicate meant a chip whose first attempt stalled could never open another,
            # because every future attempt derived the same id and hit the same dead record. Observed on
            # real hardware: an enrolment drew three challengers under an older rule, one answered, it
            # expired, and the chip could not try again under the corrected rule because no new draw could
            # ever happen. An expired, unproven record is therefore SUPERSEDED — apply overwrites it with
            # a fresh draw, and journals the old one so a rollback restores it exactly.
            _existing = kv_ops.tpm_enrol_get(eid)
            if _existing:
                assert _existing.get("state") != "proven", \
                    "this chip has already proved this attestation key — use the existing enrolment"
                assert block_height >= int(_existing["h"]) + _te.enrol_window(_existing["h"]), \
                    "this attestation key already has an enrolment in progress"
            # ONE OPEN ENROLMENT PER CHIP. An endorsement certificate is PUBLIC — anyone who has seen a
            # machine's certificate can copy it — so without this bound a single stolen certificate could
            # open unlimited enrolments by varying the attestation key, and tpm_enrol is in the
            # empty-account bypass. With it, an attacker's ceiling is the number of genuine vendor-signed
            # certificates they hold, once per expiry window. Copying a certificate still proves nothing:
            # the challengers seal to its public key and only the real chip can open them.
            _open = kv_ops.tpm_enrol_open_for_ek(str(ek["identity"]))
            if _open:
                _prev = kv_ops.tpm_enrol_get(str(_open))
                assert not (_prev and _prev.get("state") != "proven"
                            and block_height < int(_prev["h"]) + _te.enrol_window(_prev["h"])), \
                    "this chip already has an enrolment in progress — finish it or wait for it to expire"
                from protocol import TPM_ENROL_V3_HEIGHT
                if _prev and block_height >= TPM_ENROL_V3_HEIGHT:
                    _ready = _te.retry_ready_at(_prev, kv_ops.tpm_retry_get(str(ek["identity"])))
                    assert block_height >= _ready, \
                        f"this chip's last enrolment was not completed by its client — it can enrol again from block {_ready}"
            # A SHORT CHALLENGER SET IS A WEAKER PROOF, so it is not a proof. An attacker who can shrink the
            # bonded registry must not thereby cut the number of parties it takes to collude.
            # COMMIT, THEN DRAW (ops/tpm_enrol; audit 2026-09-27). The set does not exist yet — its dice are two epochs
            # away — so what is checked here is that the pool it WILL be drawn from, frozen at this block, can seat k
            # (exact sampling always does when it has k weighted members).
            # INVARIANT: never draw here from anything the client chose (eid hashes its public area) or from a beacon
            # it already knows (this epoch's) — that is the grind the delayed draw closes.
            from protocol import TPM_POOL_V2_HEIGHT, DEVICE_ATTEST_EK_CHALLENGERS_V2
            if block_height >= TPM_POOL_V2_HEIGHT:
                # TPM POOL v2: the pool this enrolment will be drawn from is the snapshot apply stores (tpm_pool_v2,
                # the same function), and it must seat k = 5. INVARIANT: the same call here and in apply.
                assert _te.pool_can_seat(tpm_pool_v2(block_height), DEVICE_ATTEST_EK_CHALLENGERS_V2), \
                    "not enough independent challengers are bonded and online to open an enrolment"
            else:
                assert _te.pool_can_seat(_tpm_pool(block_height), DEVICE_ATTEST_EK_CHALLENGERS), \
                    "not enough independent challengers are bonded to open an enrolment"
        else:
            eid = data.get("id")
            assert isinstance(eid, str) and len(eid) == 32 and _is_hex_str(eid), "malformed enrolment id"
            rec = kv_ops.tpm_enrol_get(eid)
            assert rec, "no such enrolment"
            assert block_height < int(rec["h"]) + _te.enrol_window(rec["h"]), \
                "this enrolment has expired — open a new one"
            # Each branch below is a DRY RUN of the exact state transition apply will perform, on the record
            # as it stands at this block. The state machine raises AssertionError on every rule it enforces,
            # which is what validation wants, and apply re-runs it rather than trusting this.
            if recipient == "tpm_challenge":
                # a delayed draw's set is materialised by its first challenge; apply does the same (account_ops)
                # INVARIANT: validation and apply must both materialise, or they judge against different sets
                _te.apply_challenge(tpm_materialise_draw(rec, block_height), sender,
                                    _hex_bytes(data.get("blob"), 1024, "credential blob"),
                                    _hex_bytes(data.get("enc"), 1024, "wrapped seed"), block_height)
            elif recipient == "tpm_commit":
                _te.apply_commit(rec, sender, str(data.get("commit") or ""), block_height)
            else:
                from protocol import TPM_ENROL_V3_HEIGHT
                _te.apply_reveal(rec, sender, _hex_bytes(data.get("secret"), 64, "secret"),
                                 _hex_bytes(data.get("seed"), 64, "seed"), block_height,
                                 fail_on_mismatch=int(block_height) >= TPM_ENROL_V3_HEIGHT)
    elif recipient in ("pool", "delegate", "undelegate"):
        # STAKING POOLS NEVER RAN FROM GENERATION 26 ON (protocol.py "THE SAVINGS LANE IS PLAIN STAKE"): the gen-25 branch
        # opened with `assert POOL_HEIGHT and block_height >= POOL_HEIGHT, "staking pools are not enabled yet"` and
        # POOL_HEIGHT was 0, so every pool / delegate / undelegate tx was refused here, first, with this message. The
        # rest of the branch and the apply path were deleted with the gate. INVARIANT: these three recipients stay in
        # RESERVED_RECIPIENTS and stay REFUSED — letting one fall through to the generic path would turn a refused tx
        # into an accepted one and fork every node still running the refusal.
        raise AssertionError("staking pools are not enabled yet")
    elif recipient == "msgkey":
        # ON-CHAIN MESSAGING KEY: FEE-EXEMPT, zero-amount identity tx binding the sender's ML-KEM-768
        # encryption pubkey to their account so senders can DM by address with no off-chain prekey. It is
        # sender-scoped (writes only the sender's own kem_pub) and anti-spam-gated by the empty-account rule
        # (msgkey is NOT in the onboarding bypass, so the sender must already have an on-chain account).
        # THAT WAS NOT A BOUND (audit 2026-09-27): the empty-account check is mempool policy that consensus never runs,
        # an emptied account still "exists", and accounts were free to create (tpm_ready wrote one) — so msgkey was a
        # free ~10 KB message every block, forever, from any number of accounts. So only the FIRST bind is free (bounded
        # by the paid transfer that created the account); a rotation pays MIN_TX_FEE, re-binding the key already bound is
        # refused, and the tx carries no data. INVARIANT: never make a repeatable msgkey free.
        # `>= 1` below is gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value (deleted), kept because this also runs at
        # mempool admission with the tip's height, 0 on a genesis tip, where the old fee-exempt rule held.
        assert transaction["amount"] == 0, "msgkey tx must have zero amount"
        kp = transaction.get("kem_pub")
        # ML-KEM-768 public key = 1184 bytes = 2368 lowercase-hex chars (fixed length).
        assert isinstance(kp, str) and len(kp) == 2368 and all(c in "0123456789abcdef" for c in kp), \
            "msgkey kem_pub must be a 2368-hex-char ML-KEM-768 public key"
        if block_height is not None and int(block_height) >= 1:
            assert not transaction.get("data"), "msgkey carries no data"
            _acc = get_account(transaction["sender"], create_on_error=False)
            assert _acc, "msgkey needs an account on chain"
            if _acc.get("kem_pub"):
                assert _acc["kem_pub"] != kp, "this messaging key is already bound to the account"
                assert transaction["fee"] >= MIN_TX_FEE, f"rotating a messaging key pays the minimum fee {MIN_TX_FEE}"
                assert _acc.get("balance", 0) >= transaction["fee"], "msgkey sender cannot afford the fee"
            else:
                assert transaction["fee"] == 0, "the first messaging key is fee-exempt (fee must be 0)"
        else:
            assert transaction["fee"] == 0, "msgkey tx is fee-exempt (fee must be 0)"
    elif recipient == "auth":
        # ACCOUNT AUTHENTICATION (doc/key-rotation.md): install / rotate / cancel the sender's auth config.
        # validate_origin verified every signature entry; here the SIGNER SET decides the effect (full
        # reconfig policy -> immediate; signing policy alone -> pending; a reconfig-only key -> cancel).
        from ops import auth_ops
        _acc = get_account(transaction["sender"], create_on_error=False)
        _cfg = auth_ops.effective_config(transaction["sender"], _acc, block_height)
        auth_ops.validate_auth_tx(transaction, block_height, auth_ops.verify_entries(transaction, transaction["sender"], _cfg))
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
        # HALT-CLASS field typing (audit 2026-07): the exec node replays these payloads and uses some fields
        # as DICT KEYS or coerces them. A wrong TYPE there raises INSIDE the exec tail loop, which has no
        # per-tx guard, so the cursor never advances — one MIN_TX_FEE blob permanently wedges every exec node
        # (every game + every asset frozen; assets have no L1 exit). L1 orders the blob and never decodes it,
        # but it must still REFUSE a payload that would halt the layer downstream — the same discipline the
        # `settle` op below already applies to exec_cursor. Only dict payloads carry ops.
        if isinstance(payload, dict):
            _op = payload.get("op")
            assert _op is None or isinstance(_op, str), "Blob op must be a string"
            # F2 (2026-09-23): `method` is looked up in the contract's code dict; a list raised TypeError past the
            # exec layer's escrow. The exec layer refuses it before debiting and L1 refuses to order it at all.
            # `>= 1` is gen 25's EXEC_RULES_V2_HEIGHT from gen 26 (deleted): height 0 / None keep their old verdict.
            if "method" in payload and block_height is not None \
                    and int(block_height) >= 1:
                assert isinstance(payload["method"], str), "Blob method must be a string"
            # ns/to_ns/from_ns index the per-namespace state map: a list/dict there is unhashable -> TypeError.
            assert valid_namespace(payload.get("ns", DEFAULT_NS)), "Blob ns must be a valid namespace id"
            for _k in ("to_ns", "from_ns"):
                if _k in payload:
                    assert valid_namespace(payload[_k]), f"Blob {_k} must be a valid namespace id"
            if "value" in payload:                         # int()'d in the exec summary AND the ledger
                _v = payload["value"]
                assert isinstance(_v, int) and not isinstance(_v, bool) and _v >= 0, \
                    "Blob value must be a non-negative int"
            if "asset" in payload:                         # a str/int id; anything else breaks ledger keys
                _a = payload["asset"]
                assert (isinstance(_a, int) and not isinstance(_a, bool)) or isinstance(_a, str), \
                    "Blob asset must be an int or string id"
            if "proof_da" in payload:                      # a DA commitment; path chars reach DaStore._dir
                _pda = payload["proof_da"]
                assert isinstance(_pda, str) and _pda and "/" not in _pda and "\\" not in _pda \
                    and _pda not in (".", ".."), "Blob proof_da must be a safe commitment string"
    elif recipient == "settle":
        # EXECUTION-LAYER SETTLEMENT (Phase 2): a BONDED validator attests an exec-layer checkpoint
        # {exec_cursor, state_root}. Fee-exempt validator duty; one attestation per (validator, cursor).
        from protocol import SETTLE_MAX_LAG
        assert transaction["amount"] == 0, "Settle tx must have zero amount"
        data = transaction.get("data") or {}
        cursor = data.get("exec_cursor")
        root = data.get("state_root")
        ns = data.get("ns", DEFAULT_NS)
        # FREE ONLY WHERE IT IS A DUTY (protocol.py "NO FREE REPEATABLE TRANSACTIONS", audit 2026-09-27). One 10-NADO bond
        # used to be able to land a
        # permanent settle row for every (namespace, cursor) pair — any namespace name, any past cursor — for free. The
        # duty is the default namespace near the tip (honest settles trailed their block by 12..380 blocks); another
        # namespace pays MIN_TX_FEE, and a cursor more than SETTLE_MAX_LAG behind is refused.
        # INVARIANT: never make a settle free that the settle loop does not need — and construct_settle_tx must charge
        # exactly this (it signed fee 0 for every namespace until 2026-09-28: tests/test_namespace_settle_pays.py).
        # `>= 1` is gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value (deleted), kept because this also runs at mempool
        # admission with the tip's height, 0 on a genesis tip, where the old free-settle rule held.
        _spam = block_height is not None and int(block_height) >= 1
        if _spam and ns != DEFAULT_NS:
            assert transaction["fee"] >= MIN_TX_FEE, f"a settle outside the default namespace pays the minimum fee {MIN_TX_FEE}"
            _sa = get_account(transaction["sender"], create_on_error=False)
            assert _sa and _sa.get("balance", 0) >= transaction["fee"], "settle sender cannot afford the fee"
        else:
            assert transaction["fee"] == 0, "Settle tx is fee-exempt (fee must be 0)"
        if _spam and isinstance(cursor, int) and not isinstance(cursor, bool):     # (the type is refused just below)
            assert int(block_height) - cursor <= SETTLE_MAX_LAG, \
                f"Settle exec_cursor is more than {SETTLE_MAX_LAG} blocks behind this block"
        assert valid_namespace(ns), "Settle ns must be a valid namespace id ([a-z0-9._-], <=32)"
        assert ns != DEFAULT_NS or "ns" not in data, "default namespace must be omitted from settle data (canonical form)"
        # Upper bound is CONSENSUS-CRITICAL, not cosmetic: exec_cursor is packed be8 (struct '>Q') into the
        # LMDB settlement key at apply-time (kv_ops._settle_key), which raises struct.error for cursor >= 2**64
        # INSIDE incorporate_block — a path that must never raise, or one cheap tx halts production+verify on
        # every node (same class as the old min_block poison). The 2**64-1 ceiling also keeps a real cursor from
        # ever equaling the b'\xff'*8 end-of-namespace sentinel that settlement_max_cursor range-seeks past.
        # NOTE: exec_cursor is an EXEC-LAYER position, NOT the L1 block height (it is not bounded by
        # block_height — see the settlement tests). The upper bound below is purely the be8-pack safety bound.
        assert isinstance(cursor, int) and not isinstance(cursor, bool) and 0 <= cursor < (1 << 64) - 1, "Settle exec_cursor must be an int in [0, 2**64-1)"
        # SETTLEMENT-ORACLE CAPTURE (critical). active_settler_shares anchors the quorum DENOMINATOR on
        # settlement_max_cursor(ns) and leaks out anyone who has not attested within SETTLE_ACTIVITY_CURSORS
        # of it. With the cursor unbounded, ONE fee-exempt settle at cursor ~2**64 pushes that activity floor
        # above every honest settler's real cursor, so they all leak from the denominator and the poster
        # becomes the SOLE quorum member — permanently, since no honest exec node will ever reach that
        # cursor to re-enter. latest_settled() then returns the attacker's fabricated root, and
        # bridge_withdraw / unshield / dividend_withdraw prove against it to drain BRIDGE_ESCROW,
        # SHIELD_ESCROW and DIVIDEND_POOL. Total cost: B_MIN bonded (10 NADO) and no fee. The per-namespace
        # escrow cap does not help — all bridge deposits and every unshield/dividend exit use DEFAULT_NS.
        # The exec cursor IS an L1 block height in practice (execnode sets state.cursor = h while applying
        # FINALIZED blocks), so it can never legitimately exceed the height of the block carrying the settle.
        # Bounding it here is deterministic (block_height is consensus input) and cannot reject an honest
        # settle, which is always well behind the tip.
        assert block_height is None or cursor <= int(block_height), (
            f"Settle exec_cursor {cursor} exceeds the current block height {block_height} — the exec layer "
            f"applies FINALIZED blocks and can never be ahead of L1 (settlement-oracle capture guard)")
        assert isinstance(root, str) and len(root) == 64 and all(c in "0123456789abcdef" for c in root), "Settle state_root must be 64-hex"
        acc = get_account(transaction["sender"], create_on_error=False)
        assert acc and acc.get("bonded", 0) >= B_MIN, "Settle sender is not a bonded validator"
        assert not kv_ops.settlement_exists(ns, cursor, transaction["sender"]), "Validator already settled this (ns, exec_cursor)"
        # DA-CARRIED PROOF COMMITMENT. Same hardening as the blob branch: the string reaches
        # DaStore._dir, so path characters must never get through. Validated for SHAPE only — this field
        # does not (yet) justify the root, so an unfetchable or bogus commitment cannot change what
        # settles; it degrades to the ordinary bonded-quorum path exactly as a bare attestation does.
        # Making it justify the root requires L1 to fetch+verify during validation inside the depth gate,
        # which is the consensus step in doc/settle-proof-transport.md §4 and is NOT done here.
        _pda = data.get("proof_da")
        if _pda is not None:
            assert isinstance(_pda, str) and _pda and len(_pda) <= 128 and "/" not in _pda \
                and "\\" not in _pda and _pda not in (".", ".."), \
                "Settle proof_da must be a safe commitment string"
        proof = data.get("proof")
        _from_da = False          # set once the proof came back from DA, so the verdict memo can key on the
                                  # commitment (which cryptographically binds those exact bytes)
        if proof is None and _pda is not None and not deep:
            # DA-CARRIED PROOF, RESOLVED AT VALIDATION. A settle proof is ~118 MiB at protocol strength
            # against an 8 MiB submit cap and a ~256 KiB block, so it cannot ride in the tx. It is published
            # k-of-n and the tx carries the commitment; here we pull it back and verify it as if it had been
            # inline, so the root settles TRUSTLESSLY on a validity proof rather than on a bonded quorum.
            #
            # THE BYTES ARE BINDING, so fetching does not introduce trust: da reconstruction checks the
            # commitment round-trip, and a blob that does not hash to `proof_da` is not returned. Whoever
            # serves it cannot substitute a different proof.
            #
            # NOT HOLDING IT IS NOT A REJECTION. Raising ProofUnavailable defers the whole block: every node
            # applies the same rule, so unavailability costs liveness, never safety. Rejecting instead would
            # fork the fleet along the axis of who happened to have the data.
            #
            # `deep` bounds the stall. Past FINALITY_DEPTH below the known tip the proof is not consulted at
            # all (SETTLE_PROOF_DEPTH_GATED), so a permanently unavailable proof degrades to the
            # accumulated-weight path rather than halting the node — the same weak subjectivity already
            # accepted for snapshot bootstrap.
            _blob = _fetch_da_proof(_pda)
            if _blob is None:
                raise ProofUnavailable(
                    f"settle proof {_pda[:16]}… for (ns={ns}, cursor={cursor}) is not available via DA yet — "
                    f"deferring this block rather than judging it")
            try:
                proof = json.loads(_blob.decode())
                _from_da = True
            except Exception as e:
                # Retrievable but not a proof: that IS a judgement we can make, so reject rather than defer.
                raise AssertionError(f"Settle proof_da resolved to non-proof bytes: {type(e).__name__}")
        if proof is not None:
            # PHASE-2b VALIDITY SETTLEMENT — a universal, deterministic consensus rule (NO activation gate, no
            # block-height special-casing): the carried SPARSE settlement proof must PROVE exactly this
            # checkpoint's EXECUTION half and STRICTLY EXTEND the namespace's settled chain, verified
            # identically on every node. On success this tx settles the root TRUSTLESSLY at apply-time
            # (kv_ops.settlement_proof_put), no bonded quorum needed.
            #
            # The settled root is rnode(KV half, RECORDS half) (execnode/exec_root.py). The proof covers the
            # KV half (contract execution — bound epochs over the sparse tree); the RECORDS half must be
            # UNCHANGED across the proven span (pinned equal in the pre and post compositions below). That is
            # an EXPLICIT, enforced restriction, not an assumption: epochs that also moved records (bridge
            # credits, dividends, exits) ride the bonded quorum until record transitions are proven in-circuit
            # — a forward-compatible extension on the SAME tree, never a scheme change.
            import protocol as _protocol
            from ops.settlement_ops import latest_settled
            from execnode.stark import settlement_sparse as SS
            from execnode import exec_root as ER
            from execnode.stark import storage_tree as SST
            assert isinstance(proof, dict), "Settle proof must be an object"
            rec_hex = proof.get("rec")
            kv_pre_claim, kv_post_claim = proof.get("kv_pre"), proof.get("kv_post")
            assert int(proof.get("cursor", -1)) == cursor, "Settle proof cursor must equal exec_cursor"
            # CHAIN: the (kv, records) decomposition composed with rnode must equal the namespace's committed
            # settled tip (EXEC_GENESIS_ROOT before the first settlement) — rnode is collision-resistant, so
            # only the REAL decomposition of the tip can satisfy this; a proof can never start from a
            # fabricated pre-state, and only one settlement extends the tip per block.
            _tip_cursor, tip_root = latest_settled(ns)
            # FIRST SETTLEMENT MUST BE BY QUORUM — asserted HERE, before any verification work, so a
            # genesis-spanning proof is rejected outright rather than fully verified and then thrown away.
            # This is also what bounds the exec-summary window the DA binding needs: a proof only ever
            # extends a real committed tip, so its span is recent and small, never "from block 0" (which
            # was guaranteed pruned and is what broke the previous attempt).
            assert tip_root is not None, "first settlement in a namespace must be by bonded quorum, not by proof"
            expected_pre = tip_root
            # Verify every bound epoch at the PROTOCOL query strength (None ⇒ the protocol constant — never
            # the bundle's own word) and at the PROTOCOL tree depth, deterministically on every node.
            # RECORDS HALF. Frozen by default: the SAME rec_hex composes both roots, so a proven span must
            # not have moved records (enforced per block in verify_calls_bound_to_summaries).
            # With SETTLE_PROOF_RECORDS the proof may instead carry `rec_post` and a `records` transition,
            # and the records half is allowed to MOVE — provided that transition proves EXACTLY the effects
            # this node committed for the span's blocks. `_records_bound` is the switch the DA gate reads.
            rec_post_hex = rec_hex
            _records_bound = False
            if _protocol.SETTLE_PROOF_RECORDS and proof.get("records") is not None:
                rec_post_hex = proof.get("rec_post") or rec_hex
                _records_bound = True
            # S3 (2026-09-23): THE CHEAP CHECKS RUN FIRST, ON THE PROOF'S CLAIMS. The full STARK verify and an
            # O(state) sparse_root over a PROVER-CHOSEN pre_contracts used to run before the tip-extension, root,
            # chain-read and calldata checks (fee-exempt, 192 MiB bodies) — a settle that could never land still
            # cost minutes of consensus CPU. Every check below is a pure function of committed state and the
            # proof's claimed halves; the verification that follows then pins those claims to what was proven,
            # so nothing accepted here is accepted on the prover's word.
            assert isinstance(kv_pre_claim, str) and isinstance(kv_post_claim, str) and isinstance(rec_hex, str), \
                "Settle proof halves must be hex strings"
            pre_full = ER.full_root_hex(SST.digest_from_hex(kv_pre_claim), SST.digest_from_hex(rec_hex))
            post_full = ER.full_root_hex(SST.digest_from_hex(kv_post_claim), SST.digest_from_hex(rec_post_hex))
            assert pre_full == expected_pre, "Settle proof pre_root must extend the settled tip"
            assert post_full == root, "Settle proof post_root must equal state_root"
            # CHAIN-RANDOMNESS SOUNDNESS: the STARK only proves the computation is CONSISTENT with the
            # BHASH/BEACON values in the bundle's io log — a malicious prover may put ANY value there. Bind
            # every chain read to THIS node's authoritative finalized chain (block hash at height / exec
            # beacon of epoch — both pure functions of the finalized chain, so every node agrees), exactly as
            # the interactive verifier does (execnode /exec/verify_state). Without this a bonded validator
            # could settle-with-proof a state built on attacker-chosen dice/wheel/beacon outcomes.
            from execnode.stark import field as _F
            from execnode import zkvm as _zkvm
            from execnode.state import ExecState as _ExecState
            from ops.block_ops import get_block_hash_by_number as _bhash
            from protocol import EPOCH_LENGTH as _EL, FINALITY_DEPTH as _FD
            _fin = int(block_height) - _FD - 1                    # highest position that is finalized & immutable now
            for _kind, _key, _val in SS.chain_reads(proof):
                assert 0 <= _val < _F.P, "Settle proof chain read value out of field"
                if _kind == _zkvm.IO_BHASH:
                    assert 0 <= _key <= _fin, "Settle proof BHASH height is not finalized"
                    _bh = _bhash(_key)
                    assert _bh, "Settle proof BHASH height unavailable on chain"
                    assert int(_bh, 16) % _F.P == _val, "Settle proof BHASH does not match the finalized chain"
                elif _kind == _zkvm.IO_BEACON:
                    assert 0 <= _key and _key * _EL <= _fin, "Settle proof BEACON epoch is not finalized"
                    # INVARIANT: the same function the exec node computes BEACON with (ExecState.exec_beacon_at,
                    # protocol.BEACON_EXTEND_HEIGHT), read at this block's finalized position
                    _bv = _ExecState.exec_beacon_at(_key, kv_ops.reveals_for_epoch, _fin // _EL)
                    assert _bv is not None, "Settle proof BEACON epoch is not finalized"
                    assert _bv % _F.P == _val, "Settle proof BEACON does not match the finalized chain"
                else:
                    raise AssertionError("unknown chain-read kind in settle proof")
            # DA BINDING — PRUNE-SAFE. The old check read every block BODY in the span via get_block_number,
            # which returns False on a pruned node and the body on an archive node, so the same tx validated
            # differently across the fleet -> consensus FORK (and because these are bare asserts, the pruned
            # node rejected the WHOLE BLOCK its peers accepted). No depth fence can fix that: a snapshot
            # re-anchor (snapshot_ops.adopt_new_identity -> segment_store.reset) wipes ALL bodies, blob-bearing
            # included, and backfills only a best-effort ~265-block tail. So the binding now reads the per-block
            # EXEC SUMMARIES persisted at incorporate time (kv_ops.exec_summary_get) — committed state, which
            # pruning never touches — instead of bodies.
            #
            # FIRST SETTLEMENT MUST BE BY QUORUM. This is what makes the summary window bounded and therefore
            # obtainable: a proof may only EXTEND an already-settled tip, so the span is always
            # (settled_cursor, cursor] — recent and small — never "from block 0", which was guaranteed pruned
            # and was the concrete case that broke the previous attempt.
            # NO EPOCH BOUNDARY. The presence dividend accrues with NO transaction at all, in the exec node's
            # tail loop, once per EPOCH_LENGTH blocks (execnode.tail_loop -> accrue_dividend_epoch), and it
            # writes st.dividend — a RECORDS position. It is therefore invisible to any per-block body scan.
            # A span that crosses an epoch boundary may carry that accrual, so a records-frozen proof must not
            # settle it. Cursor arithmetic only — no body, no exec state.
            # ...UNLESS THE PROOF BINDS THE RECORDS HALF. The accrual is now DERIVED at incorporate time
            # (records_bind.epoch_accrual_due + dividend_accrual_effects, committed into the boundary
            # block's exec summary), so a records-bound proof carries it like any other effect and the
            # binding below checks it against THIS node's own committed derivation. The blanket refusal was
            # the single largest reason a span was rejected — 55 of 146 over one day — and it existed only
            # because the accrual was invisible, not because it was unprovable.
            # A records-FROZEN proof keeps the old rule exactly: it pins one records root across the span,
            # so an accrual inside it would make the proof assert something false.
            if not _records_bound:
                assert (int(_tip_cursor) // _protocol.EPOCH_LENGTH) == (int(cursor) // _protocol.EPOCH_LENGTH), \
                    "settle-with-proof span crosses an epoch boundary (possible presence-dividend accrual)"
            # NO PAYOUTS IN-PROOF. A PAY opcode moves bridge balances at the runtime boundary (state.py), i.e.
            # RECORDS, while the proof pins records frozen. block_records_inert cannot see this — PAY is
            # emitted by execution, not visible in the calldata — so it is caught here, on the proof's own io.
            # A RECORDS-FROZEN proof still refuses a PAY, and must: it pins one records root across the
            # span, so a payout inside it would make the proof assert something false. A records-BOUND
            # proof is the opposite case — records are allowed to MOVE and every effect is checked — so
            # there the payout is DERIVED below (records_bind.pay_effects_from_proof) instead of refused.
            settle_proof_io_check(proof, _records_bound, block_height)   # PAY + asset io (see the function)
            from execnode.stark import calls_commit as _CC
            # `records_out` is passed ONLY for a records-bound proof. Passing None keeps the old, stricter
            # rule (any non-inert block refuses the span), so a frozen-records proof is validated exactly as
            # before and the two forms cannot be confused for one another.
            _rec_effects = [] if _records_bound else None
            _ok, _why = _CC.verify_calls_bound_to_summaries(
                proof, ns, _tip_cursor, cursor, kv_ops.exec_summary_get, _protocol.SETTLE_PROOF_MAX_SPAN,
                records_out=_rec_effects)
            assert _ok, f"Settle proof not bound to the on-chain calldata: {_why}"
            # DEPTH-GATED VERIFICATION. Cryptographic verification of the proof runs while the block is
            # near the tip; a block already buried under FINALITY_DEPTH is accepted on accumulated weight
            # instead, exactly as the chain already treats deep history for snapshot bootstrap.
            #
            # WHY: the proof cannot live in the block (~97 MiB vs a ~256 KiB block, see
            # doc/settle-proof-transport.md), so it has to be fetched. Re-fetching and re-verifying one per
            # settle for the whole of history would make joining the network cost hundreds of GiB.
            #
            # WHAT IT COSTS, stated plainly: a from-genesis sync no longer independently verifies
            # historical settlements — it INHERITS them from the nodes that were online when the block was
            # at the tip. That is a real reduction in what a full sync proves, and it is a deliberate
            # choice (option 1 of doc/settle-proof-transport.md §4), not a side effect.
            #
            # WHY IT CANNOT FORK THE FLEET: the gate only ever RELAXES. Two nodes disagreeing about depth
            # disagree as "strict rejects / relaxed accepts", so they diverge only on a proof that is
            # actually INVALID — and an invalid proof cannot reach a deep block in the first place, because
            # the nodes that saw it at the tip were in the strict regime and rejected it there.
            #
            # Everything else in this branch still runs at any depth: cursor match, tip extension, root
            # composition, chain-read binding, the epoch/PAY guards and the DA binding. Only the expensive
            # cryptographic check is skipped, so a fabricated settle is still refused on structure.
            # THE PROOF IDENTITY IS NEEDED ON BOTH PATHS: the records-half memo below keys on it (`_rvk`). It used to
            # be computed only in the strict branch, so a records-bound settle validated DEEP (a node more than
            # FINALITY_DEPTH behind, catching up) raised UnboundLocalError on `_vk`. The first records-bound settle on
            # betanet-8 landed at block 10212; nodes that saw it at the tip moved on, and a node that had to SYNC
            # across it (behind, restarting, or new) rejected the block forever — the relay sat frozen at 10211 for
            # 80 minutes (2026-09-26). Computing it here costs one hash and changes no verdict.
            from execnode.stark import stark as _stk
            _rules = _stk.rules_for_height(block_height)
            _vk = settle_verify_key(proof, _pda, _from_da, _rules)
            if deep and _protocol.SETTLE_PROOF_DEPTH_GATED:
                kv_pre, kv_post = kv_pre_claim, kv_post_claim
            else:
                # MEMOISE THE CRYPTOGRAPHIC VERDICT. A settle proof verifies or it does not — that is a
                # property of the proof's own bytes and NOTHING else, so re-deriving it is pure repetition.
                # And it is repeated: a tx sitting in the mempool is re-validated on EVERY block-candidate
                # build, so a single pooled settle turned the block-producing core loop into a 91 s loop and
                # took this node OUT OF CONSENSUS — blocks frozen 221 s, 219 unhealthy episodes, while peers
                # advanced normally (observed 2026-08-04). The node poisoned its own block production with
                # its own transaction.
                #
                # THE KEY MUST BIND THE PROOF'S BYTES, NOT ITS CLAIMS. This was keyed on
                # (cursor, kv_pre, kv_post, rec, rec_post) — all of which are what the proof ASSERTS, none of
                # which is the FRI/openings body that actually gets verified. Two proofs making identical
                # claims therefore shared an entry, so verifying an HONEST settle cached ok=True under a key
                # a CORRUPTED one also matched: the tampered proof was then accepted without ever being
                # verified. Caught by tests/test_settle_depth_gate ("corrupted proof is REJECTED near the
                # tip"), which truncates seg["proof"]["openings"] while leaving every claim identical.
                # A cache that answers for input it never saw is not a cache.
                #
                # See settle_verify_key for the binding argument.
                # THE RULES FOR THIS BLOCK, not for "now" (PROOF_BIND_HEIGHT; stark.rules_at). Set here, once,
                # for every prove/verify beneath — the segment STARKs, the K->1 fold, the transition binding —
                # and carried explicitly into the child interpreter, which has no context of its own.
                _hit = _SETTLE_VERIFY_MEMO.get(_vk)
                if _hit is None:
                    with _settle_verify_lock(_vk), _stk.rules_at(block_height):   # single flight per proof
                        _hit = _SETTLE_VERIFY_MEMO.get(_vk)
                        if _hit is None:
                            # TIME THE KV HALF. Two records-bearing submits died at ~1200s while the
                            # measured verify cost of their records half is only ~472s, so ~730s is
                            # somewhere else; these timers split the budget between the two verifications.
                            with _SETTLE_VERIFY_GATE:         # one sparse verification at a time, process-wide
                                _t_kv = _time.time()
                                # OUT OF PROCESS (2026-09-07): the verdict is computed by a child interpreter so
                                # the 70-780 s of hashing never holds THIS process's GIL (ops/proof_child.py);
                                # NADO_PROOF_VERIFY_INPROC=1 keeps the old inline path. A child failure is not
                                # a verdict: fall back inline, exactly as before.
                                import os as _os
                                _hit = None
                                if not _os.environ.get("NADO_PROOF_VERIFY_INPROC"):
                                    from ops.proof_child import verify_sparse_out_of_process
                                    _hit = verify_sparse_out_of_process(proof, _protocol.EXEC_TREE_DEPTH,
                                                                        rules=_rules)
                                    _where = "child"
                                if _hit is None:
                                    # A MISSING OR STALE NATIVE KERNEL IS NOT A VERDICT (native_guard.NODE_LOCAL_ERRORS):
                                    # it says nothing about the proof, so it defers the block like an unavailable DA
                                    # blob instead of rejecting what every peer accepts. Never memoised (raised here).
                                    # ALL of NODE_LOCAL_ERRORS, not just NativeMissing: an out-of-memory here is this node's
                                    # limit, not the proof's fault, and rejecting on it split a low-memory node from the fleet
                                    # (zk audit 2026-09-26, SETTLE-2).
                                    from execnode.stark.native_guard import NODE_LOCAL_ERRORS as _NM
                                    try:
                                        _hit = SS.verify_settlement_sparse(proof, depth=_protocol.EXEC_TREE_DEPTH)
                                    except _NM as _nm:
                                        raise ProofUnavailable(f"this node cannot verify settle proofs yet: {_nm}") from _nm
                                    _where = "inproc"
                                print(f"[settle-verify] KV half {_time.time() - _t_kv:.1f}s ok={_hit[0]} ({_where})", flush=True)
                            if len(_SETTLE_VERIFY_MEMO) >= _SETTLE_VERIFY_MEMO_MAX:
                                _SETTLE_VERIFY_MEMO.clear()   # bounded: a proof is ~118 MiB, entries are tiny
                            _SETTLE_VERIFY_MEMO[_vk] = _hit
                ok, why, kv_pre, kv_post = _hit
                assert ok, f"Settle proof invalid: {why}"
            assert kv_pre == kv_pre_claim and kv_post == kv_post_claim, "Settle proof kv halves mismatch"
            # PAYOUTS, DERIVED FROM THE PROVEN io LOG. This runs only AFTER the segments have been bound to
            # this node's committed calls above — that binding is what makes the io log's provenance mean
            # anything, because the payee registry is rebuilt from those same calls. Appending here (rather
            # than inside verify_calls_bound_to_summaries) keeps the calldata binding a pure function of
            # committed state, with the execution-derived half added on top and clearly separable.
            # ASSET IO, BOUND (zk audit 2026-09-26; settle_proof_io_check admits it). The asset ledger is part
            # of the records half, so what an asset call did is judged against the PINNED pre-state: records_pre
            # must hash to the tip's records root, and PinnedAssets walks the proven io through the live staging
            # rules — issuer-only mint/renounce, the supply cap, holdings, and every ABAL read against the running
            # authenticated balance. A records-bound proof folds those moves into its binding like a payout; a
            # records-FROZEN one (say, a span that only reads balances) must move nothing at all.
            # No height guard (the gen-27 ZK_HARDEN_HEIGHT, 1 from gen 28): block_height >= 1 is proven here — the DA
            # binding above passed, which needs a non-empty span (tip_cursor, cursor] with tip_cursor >= 0 (a real
            # settlement) and cursor <= block_height.
            _asset_view = _asset_pin = None
            from execnode.stark import records_bind as _RBA
            if _RBA.proof_asset_ids(proof)[0]:
                try:
                    _asset_pin = _RBA.pinned_pre_get(proof.get("records_pre") or {}, SST.digest_from_hex(rec_hex),
                                                     depth=_protocol.EXEC_TREE_DEPTH)
                except (_RBA.Unbindable, TypeError, ValueError, AttributeError) as _e:
                    raise AssertionError(f"settle-with-proof asset io without a pinned pre-state: {_e}")
                _asset_view = _RBA.PinnedAssets(_asset_pin, proof.get("asset_meta_pre") or {})
                if not _records_bound:
                    # An asset-VALUED call's escrow is not in this net (PinnedAssets.escrow emits nothing; the summary
                    # carries it), which is safe only because block_records_inert marks every value call non-inert and
                    # verify_calls_bound_to_summaries refuses a frozen proof over a non-inert block. Keep them together.
                    try:
                        _anet = _RBA.net_records_updates(_asset_pin, _RBA.pay_effects_from_proof(proof, _asset_view),
                                                         _protocol.EXEC_TREE_DEPTH, nonneg=True)
                    except _RBA.Unbindable as _e:
                        raise AssertionError(f"settle-with-proof carries an unsettleable asset effect: {_e}")
                    assert not _anet, "records-frozen settle proof moves the asset ledger"
            if _records_bound:
                from execnode.stark import records_bind as _RBP
                try:
                    _pay_fx = _RBP.pay_effects_from_proof(proof, _asset_view)
                except _RBP.Unbindable as _e:
                    raise AssertionError(f"settle-with-proof carries an unsettleable payout: {_e}")
                if _pay_fx:
                    _rec_effects.extend(_pay_fx)

            if _records_bound:
                # THE RECORDS BINDING. The effects come from THIS node's committed summaries — never from
                # the proof — so a prover cannot choose what it is proving. The transition must advance the
                # records half from the tip's rec_hex to the claimed rec_post over exactly that set.
                from execnode.stark import records_bind as _RB
                _pre_rec = SST.digest_from_hex(rec_hex)
                _post_rec = SST.digest_from_hex(rec_post_hex)
                _eff = [(int(t), tuple(str(p) for p in parts), int(dv)) for (t, parts, dv) in _rec_effects]
                # An empty effect set must not be able to MOVE the half: with nothing to prove, rec_post is
                # required to equal rec_hex, which collapses to the frozen case rather than trusting the
                # prover's word for a root nothing authorises.
                if not _eff:
                    assert rec_post_hex == rec_hex, \
                        "Settle proof moves the records half but the span committed no records effects"
                else:
                    # PIN THE PRE-STATE the binding reads, exactly as the KV half pins pre_contracts
                    # against sparse_pre_root: the projection must hash to the TIP's committed records
                    # root, so every value the arithmetic touches is authenticated rather than asserted.
                    # (already pinned above when the proof carries asset io: same projection, same root)
                    _pre_get = _asset_pin or _RB.pinned_pre_get(proof.get("records_pre") or {}, _pre_rec,
                                                                depth=_protocol.EXEC_TREE_DEPTH)
                    # MEMOIZE THE RECORDS VERDICT TOO — this is what wedged the node, twice.
                    #
                    # The KV half has been memoized since settle_verify_key existed; the records half was
                    # not, so EVERY revalidation of a mempool transaction re-ran it. Measured on one live
                    # settle (span 7800->7866, 29 effects):
                    #     08:58:55  RECORDS half 1057.2s ok=True    <- the submit
                    #     09:13:50  RECORDS half  878.9s ok=True    <- again, 15 minutes later
                    # while the KV half was verified once (15.7 s) and never repeated. ~900-1050 s of CPU
                    # per revalidation is enough to stop this node keeping up: it stalled at block 7364 and
                    # again at 8203 while the rest of the fleet ran on, both times with a records settle
                    # sitting in the mempool. An exact-landing tx waits ~280 blocks for its slot, so it gets
                    # revalidated repeatedly by construction — the cost was guaranteed to recur.
                    #
                    # KEYED ON THE SAME PROOF IDENTITY AS THE KV HALF, which binds the proof's BYTES
                    # (blake2b over the inline proof, or the DA commitment) — see settle_verify_key, which
                    # documents why keying on CLAIMS once let a tampered proof through unverified. The
                    # records inputs are added on top: the pre/post roots being asserted and a digest of the
                    # effect set THIS node derived. Same bytes + same roots + same effects = same verdict;
                    # anything else misses and is verified in full.
                    _rvk = (_vk, rec_hex, rec_post_hex, blake2b_hash(_eff))
                    _rhit = _SETTLE_VERIFY_MEMO.get(_rvk)
                    if _rhit is not None:
                        _rok, _rwhy = _rhit
                    else:
                        _t_rec = _time.time()
                        from execnode.stark.native_guard import NODE_LOCAL_ERRORS as _NM2   # OOM included (SETTLE-2)
                        try:
                            _rok, _rwhy = _RB.bind_and_verify_records(
                                proof["records"], _pre_rec, _post_rec, _pre_get, _eff,
                                depth=_protocol.EXEC_TREE_DEPTH,
                                # S2: refuse a running balance below zero (from height 1: gen 25's
                                # EXEC_RULES_V2_HEIGHT, 1 from gen 26 and deleted)
                                nonneg=(int(block_height) >= 1))
                        except _NM2 as _nm2:              # node-local, not a verdict: defer (see the KV half above)
                            raise ProofUnavailable(f"this node cannot verify settle proofs yet: {_nm2}") from _nm2
                        print(f"[settle-verify] RECORDS half {_time.time() - _t_rec:.1f}s "
                              f"({len(_eff)} effects) ok={_rok}", flush=True)
                        if len(_SETTLE_VERIFY_MEMO) >= _SETTLE_VERIFY_MEMO_MAX:
                            _SETTLE_VERIFY_MEMO.clear()
                        _SETTLE_VERIFY_MEMO[_rvk] = (_rok, _rwhy)
                    assert _rok, f"Settle proof records half invalid: {_rwhy}"
    elif recipient == "bridge":
        # BRIDGE DEPOSIT (Phase 2): lock L1 coins into escrow; an exec node credits the sender exec-side.
        assert transaction["amount"] > 0, "Bridge deposit amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"Bridge deposit fee below minimum {MIN_TX_FEE}"
        # Deposits credit the DEFAULT-namespace escrow ledger (where the exec node credits the depositor);
        # only that rollup's settled root can release them (per-namespace cap in bridge_withdraw), which is
        # what closes the lone-quorum drain via any fresh/attacker namespace.
    elif recipient == "faucet":
        # FAUCET DONATION (doc/faucet.md): lock L1 coins into the faucet escrow; the exec layer credits
        # the faucet contract's balance. Same shape as a bridge deposit — anyone can fund it from any wallet.
        assert transaction["amount"] > 0, "Faucet donation amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"Faucet donation fee below minimum {MIN_TX_FEE}"
    elif recipient == "bridge_withdraw":
        # BRIDGE EXIT (Phase 2): prove the withdrawal {addr, amount, nonce} is a record of the bonded-quorum
        # SETTLED execution-layer root (the frozen sparse scheme, execnode/exec_root.py): L1 recomputes the
        # record's 256-bit position from the tx's public fields, folds ONE packed sparse path, composes with
        # the claimed kv half and compares to the settled root — then checks the nullifier + escrow, releases.
        from ops.settlement_ops import latest_settled
        from execnode import exec_root as ER
        assert transaction["amount"] == 0, "bridge_withdraw carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "bridge_withdraw is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        ns = data.get("ns", DEFAULT_NS)
        assert valid_namespace(ns), "bridge_withdraw ns must be a valid namespace id"
        assert addr == transaction["sender"], "bridge_withdraw must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad withdraw amount"
        exit_amount_check(amount, block_height)       # no amount + k*P aliasing (review 2026-09-24)
        assert isinstance(nonce, str) and isinstance(proof, dict), "bad withdraw nonce/proof"
        # WINDOWED like dividend_withdraw (same bug class): an exit proven against the newest root died
        # at the next settle; the (ns, addr, nonce) nullifier still guarantees at-most-once release.
        # LONE-SETTLER DRAIN (audit 2026-09-25 HIGH): the window is only as strong as settlement_justified, whose stake
        # floor (protocol.SETTLE_FLOOR_NUM/DEN of all bonded) is what stops one fresh 10-NADO bond settling a made-up root and
        # proving this exit against it. INVARIANT: read the settled roots through recent_settled_roots only.
        from ops.settlement_ops import recent_settled_roots
        _window = recent_settled_roots(ns, k=3)
        assert _window, "no settled execution-layer root yet for this namespace"
        assert any(ER.verify_withdrawal(_root, addr, amount, nonce, proof) for _c, _root in _window), \
            "withdrawal is not proven against the settled execution-layer root window"
        assert not kv_ops.bridge_nullifier_exists(ns, addr, nonce), "this withdrawal was already claimed"
        escrow = get_account(BRIDGE_ESCROW, create_on_error=False)
        assert escrow and escrow.get("balance", 0) >= amount, "bridge escrow underfunded"
        # PER-NAMESPACE ESCROW CAP (SECURITY): a namespace can only ever release what was DEPOSITED targeting
        # it. This is the L1 conservation boundary that closes the lone-quorum drain — a lone bonded validator
        # can self-settle a fabricated root in a fresh namespace, but that namespace holds 0 escrow, so the
        # exit releases nothing. Even a captured namespace can only reclaim its own deposits. Independent of
        # the (attacker-influenced) settled root, so it holds regardless of quorum capture. It does NOT cover the
        # DEFAULT namespace, which holds every deposit (and which dividend_withdraw / unshield always read): there
        # the stake floor in settlement_justified (SETTLE_FLOOR_NUM/DEN, lone-settler drain) is the guard.
        assert kv_ops.bridge_escrow_ns(ns) >= amount, "namespace bridge escrow underfunded"
    elif recipient == "xmsg":
        # CROSS-ROLLUP MESSAGE DELIVERY: verify the outbox message is committed in from_ns's SETTLED root,
        # then let the receiver rollup's exec node deliver it. L1 is the verifier (it holds the settled roots),
        # exactly like bridge_withdraw — so delivery is deterministic for every receiver node. Fee-exempt; one
        # delivery per (from_ns, seq) via the nullifier.
        from ops.settlement_ops import latest_settled
        from execnode import exec_root as ER
        assert transaction["amount"] == 0, "xmsg carries no L1 amount"
        # PAID (protocol.py "NO FREE REPEATABLE TRANSACTIONS", audit 2026-09-27): a lone bonded settler is quorum in a
        # namespace nobody else settles, so it could settle a made-up root there and deliver unlimited free xmsgs against
        # it, each a permanent nullifier row. No zero-balance claimant needs this path (unlike the exits), so it pays like
        # any message. `>= 1` is gen 27's SPAM_HARDEN_HEIGHT at its gen-28 value (deleted), kept because this also runs at
        # mempool admission with the tip's height, 0 on a genesis tip, where xmsg was still fee-exempt.
        if block_height is not None and int(block_height) >= 1:
            assert transaction["fee"] >= MIN_TX_FEE, f"xmsg pays the minimum fee {MIN_TX_FEE}"
            _xa = get_account(transaction["sender"], create_on_error=False)
            assert _xa and _xa.get("balance", 0) >= transaction["fee"], "xmsg sender cannot afford the fee"
        else:
            assert transaction["fee"] == 0, "xmsg is fee-exempt"
        data = transaction.get("data") or {}
        from_ns, to_ns = data.get("from_ns", DEFAULT_NS), data.get("to_ns")
        msg, proof = data.get("message"), data.get("proof")
        assert valid_namespace(from_ns) and valid_namespace(to_ns), "xmsg from_ns/to_ns must be valid namespaces"
        assert isinstance(msg, dict) and isinstance(proof, dict), "bad xmsg message/proof"
        seq = msg.get("seq")
        assert isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0, "xmsg message seq must be a non-negative int"
        assert msg.get("to_ns") == to_ns, "xmsg message.to_ns must match the delivery to_ns"
        # WINDOWED like dividend/bridge claims (same bug class); the (from_ns, seq) nullifier still
        # guarantees at-most-once delivery.
        # LONE-SETTLER DRAIN (audit 2026-09-25 HIGH): the window is only as strong as settlement_justified, whose stake
        # floor (protocol.SETTLE_FLOOR_NUM/DEN of all bonded) is what stops one fresh 10-NADO bond settling a made-up root and
        # proving this exit against it. INVARIANT: read the settled roots through recent_settled_roots only.
        from ops.settlement_ops import recent_settled_roots
        _window = recent_settled_roots(from_ns, k=3)
        assert _window, "sending namespace has no settled root yet"
        assert any(ER.verify_outbox_msg(_root, seq, msg.get("from"), msg.get("to_ns"), msg.get("data"), proof)
                   for _c, _root in _window), \
            "message is not proven against from_ns's settled root window"
        assert not kv_ops.xmsg_nullifier_exists(from_ns, seq), "this cross-domain message was already delivered"
    elif recipient == "dividend_withdraw":
        # DIVIDEND COLLECTION (doc/presence-dividend.md): prove {addr, amount, nonce} is in the bonded-quorum
        # SETTLED execution-layer root; L1 verifies that ONE Merkle proof, checks the nullifier + pool funding,
        # then releases `amount` from the DIVIDEND_POOL to the claimant. Fee-exempt, self-claimed.
        from ops.settlement_ops import latest_settled
        from execnode import exec_root as ER
        assert transaction["amount"] == 0, "dividend_withdraw carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "dividend_withdraw is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        assert addr == transaction["sender"], "dividend_withdraw must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad dividend amount"
        exit_amount_check(amount, block_height)       # no amount + k*P aliasing (review 2026-09-24)
        assert isinstance(nonce, str) and isinstance(proof, dict), "bad dividend nonce/proof"
        # WINDOWED settlement validity (2026-08-18): a claim proven against ONLY the newest settled
        # root died the moment the next settle landed — permanently unminable, rebuilt each epoch, a
        # growing pool graveyard some peers held and others refused (the dominant residual fork/slow-
        # block driver). Any of the last K justified roots now proves the claim; the (addr, nonce)
        # NULLIFIER below still guarantees at-most-once payout. Deterministic: the window is a pure
        # read of on-chain attestations (see settlement_ops.recent_settled_roots).
        # LONE-SETTLER DRAIN (audit 2026-09-25 HIGH): the window is only as strong as settlement_justified, whose stake
        # floor (protocol.SETTLE_FLOOR_NUM/DEN of all bonded) is what stops one fresh 10-NADO bond settling a made-up root and
        # proving this exit against it. INVARIANT: read the settled roots through recent_settled_roots only.
        from ops.settlement_ops import recent_settled_roots
        _window = recent_settled_roots(k=3)
        assert _window, "no settled execution-layer root yet"
        assert any(ER.verify_dividend(_root, addr, amount, nonce, proof) for _c, _root in _window), \
            "dividend collection is not proven against the settled execution-layer root window"
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
        # recipient: a normal address — or the reserved FAUCET escrow, the one treasury->reserved payout that
        # makes sense (governance tops up the prize bank; the exec layer mirrors it like a donation).
        from protocol import FAUCET_ESCROW
        assert isinstance(sr, str) and (sr == FAUCET_ESCROW or (is_address(sr)
            and sr not in RESERVED_RECIPIENTS)), "treasury spend recipient must be a normal address or 'faucet'"
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
        # same recipient rule as treasury_vote: normal address, or the FAUCET escrow (prize-bank top-up).
        from protocol import FAUCET_ESCROW
        assert isinstance(sr, str) and (sr == FAUCET_ESCROW or (is_address(sr)
            and sr not in RESERVED_RECIPIENTS)), "treasury spend recipient must be a normal address or 'faucet'"
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
        assert isinstance(claimant, str) and is_address(claimant), "bad HTLC claimant address"
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
    elif recipient in ("invite", "invite_lock", "invite_claim", "invite_refund"):
        validate_invite(transaction, block_height)
    elif recipient == "shield":
        # SHIELD DEPOSIT into the shielded pool: lock coins in escrow; the exec node adds the note commitment(s).
        assert transaction["amount"] > 0, "shield amount must be positive"
        assert transaction["fee"] >= MIN_TX_FEE, f"shield fee below minimum {MIN_TX_FEE}"
        data = transaction.get("data") or {}
        if data.get("field"):                                        # Phase-2 field-native note (single commitment)
            field_shield_check(data, block_height)
        else:                                                        # transparent-phase note openings
            assert isinstance(data.get("out_commitments"), list) and data.get("out_commitments"), "shield needs output note commitments"
    elif recipient == "unshield":
        # UNSHIELD EXIT: prove {addr, amount, nonce} is in the bonded-quorum SETTLED exec root; release escrow.
        from ops.settlement_ops import latest_settled
        from execnode import exec_root as ER
        assert transaction["amount"] == 0, "unshield carries no L1 amount (amount is in data)"
        assert transaction["fee"] == 0, "unshield is fee-exempt"
        data = transaction.get("data") or {}
        addr, amount, nonce, proof = data.get("addr"), data.get("amount"), data.get("nonce"), data.get("proof")
        assert addr == transaction["sender"], "unshield must be self-claimed (sender == addr)"
        assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0, "bad unshield amount"
        exit_amount_check(amount, block_height)       # no amount + k*P aliasing (review 2026-09-24)
        assert isinstance(nonce, str) and isinstance(proof, dict), "bad unshield nonce/proof"
        # WINDOWED like the other settlement-proven claims (same bug class); the (addr, nonce)
        # nullifier still guarantees at-most-once release.
        # LONE-SETTLER DRAIN (audit 2026-09-25 HIGH): the window is only as strong as settlement_justified, whose stake
        # floor (protocol.SETTLE_FLOOR_NUM/DEN of all bonded) is what stops one fresh 10-NADO bond settling a made-up root and
        # proving this exit against it. INVARIANT: read the settled roots through recent_settled_roots only.
        from ops.settlement_ops import recent_settled_roots
        _window = recent_settled_roots(k=3)
        assert _window, "no settled execution-layer root yet"
        assert any(ER.verify_unshield(_root, addr, amount, nonce, proof) for _c, _root in _window), \
            "unshield is not proven against the settled execution-layer root window"
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




def register_referrer(transaction: dict):
    """The referrer a register tx names (data {"referrer": address}), or None. Shape is validated separately."""
    d = transaction.get("data")
    return d.get("referrer") if isinstance(d, dict) else None


def validate_register_referrer(transaction: dict, block_height: int):
    """REFERRALS (protocol.REFERRAL_HEIGHT): from the gate a register's `data` is "" or exactly {"referrer": <keyed
    address other than the sender>}. Before it, `data` is left as it always was (nothing read it), so every older block
    validates byte for byte as before. Whether the link is WRITTEN is apply's call (first attested registration only);
    a renewal naming a referrer is accepted and simply writes nothing, so a wallet that retries is never stuck."""
    from protocol import REFERRAL_HEIGHT
    if int(block_height) < REFERRAL_HEIGHT:
        return
    d = transaction.get("data")
    if d in ("", None):
        return
    assert isinstance(d, dict) and set(d) == {"referrer"}, 'register data must be "" or {"referrer": <address>}'
    ref = d["referrer"]
    assert isinstance(ref, str) and is_address(ref), "register referrer must be a keyed address"
    assert ref != transaction["sender"], "an identity cannot name itself as its referrer"


def invite_id_of(key_hex: str) -> str:
    """An invite's id: a domain-tagged hash of its throwaway public key (the wallet computes the same)."""
    from protocol import CHAIN_ID
    return blake2b_hash(["invite-id-v1", CHAIN_ID, key_hex])


def invite_claim_message(invite_id: str, claimant: str) -> bytes:
    """What the link key signs: (chain, invite, CLAIMANT). Naming the claimant is the point — a copied claim cannot be
    re-pointed at another address, which a revealed hashlock secret could."""
    from protocol import CHAIN_ID
    return bytes.fromhex(blake2b_hash(["invite-claim-v1", CHAIN_ID, invite_id, claimant]))


def validate_invite(transaction: dict, block_height: int):
    """invite_lock / invite_claim / invite_refund (protocol.py "FUNDED INVITE LINKS"). Raises AssertionError.

    BEFORE REFERRAL_HEIGHT EVERY ONE IS REFUSED, and "invite" (the escrow) always is: these names became reserved with
    the gate, and a reserved name with no branch falls through to the ordinary-transfer path — which would ACCEPT a
    send to "invite" that an older node refuses as an unknown alias. INVARIANT: keep the refusal first."""
    from protocol import (REFERRAL_HEIGHT, INVITE_MIN_TIMELOCK, INVITE_MAX_TIMELOCK, INVITE_KEY_HEX)
    from signatures import verify
    recipient = transaction["recipient"]
    assert recipient != "invite", "the invite escrow cannot be paid directly — use invite_lock"
    assert int(block_height) >= REFERRAL_HEIGHT, "invites are not enabled yet"
    data = transaction.get("data") or {}
    assert isinstance(data, dict), "invite data must be an object"
    h = transaction["max_block"]                          # deterministic landing height (mempool == build)
    if recipient == "invite_lock":
        assert set(data) == {"key", "expiry"}, "invite_lock data must be {key, expiry}"
        assert transaction["amount"] > 0, "an invite must carry a positive amount"
        assert transaction["fee"] >= MIN_TX_FEE, f"invite_lock fee below minimum {MIN_TX_FEE}"
        key, expiry = data["key"], data["expiry"]
        assert _is_hex(key) and len(key) == INVITE_KEY_HEX, "invite key must be an ML-DSA-44 public key (hex)"
        assert isinstance(expiry, int) and not isinstance(expiry, bool), "invite expiry must be an int block height"
        assert h + INVITE_MIN_TIMELOCK <= expiry <= h + INVITE_MAX_TIMELOCK, "invite expiry outside the allowed window"
        assert kv_ops.invite_get(invite_id_of(key)) is None, "an invite with this key already exists"
        return
    assert transaction["amount"] == 0, f"{recipient} carries no amount"
    assert transaction["fee"] == 0, f"{recipient} is fee-exempt"
    iid = data.get("id")
    assert isinstance(iid, str) and len(iid) == 64 and _is_hex(iid), "bad invite id"
    rec = kv_ops.invite_get(iid)
    assert rec is not None and rec[3] == "open", "no OPEN invite with that id"
    sender, _amount, expiry, _status, _claimant = rec
    if recipient == "invite_claim":
        assert set(data) == {"id", "key", "sig"}, "invite_claim data must be {id, key, sig}"
        assert h < int(expiry), "this invite has expired"
        claimant = transaction["sender"]
        assert claimant != sender, "the referrer cannot claim their own invite"
        # AN ATTESTED IDENTITY: a device statement landed for it (every statement stamps `devkey`) and it holds a
        # recert. The gift is for onboarding a person with a device, not for any address that holds the link.
        acc = get_account(claimant, create_on_error=False) or {}
        assert isinstance(acc.get("devkey"), str) and acc.get("devkey") and kv_ops.recert_latest(claimant) >= 0, \
            "only a registered device identity can claim an invite — register this wallet first"
        key, sig = data["key"], data["sig"]
        assert _is_hex(key) and len(key) == INVITE_KEY_HEX and invite_id_of(key) == iid, "invite key does not match the invite"
        assert _is_hex(sig) and verify(sig, key, invite_claim_message(iid, claimant)), \
            "the invite link's signature does not name this claimant"
        return
    assert recipient == "invite_refund"
    assert set(data) == {"id"}, "invite_refund data must be {id}"
    assert transaction["sender"] == sender, "only the referrer may refund this invite"
    assert h >= int(expiry), "this invite has not expired yet"


def sort_transaction_pool(transactions: list, key="txid") -> list:
    """dedup + sort a tx list by `key` (txid). Dedup is BY TXID, not by deep content — every pooled tx
    passed validate_txid (the txid is the content hash), so txid-equality IS content-equality EXCEPT for the witnesses
    the txid excludes (signature, public_key): those are pinned to one spelling by excluded_witness_check, and
    even then a signer's re-signature or a stripped already-published key is a second valid body for one txid (audit
    2026-09-25; tests/test_excluded_hex_fields_are_canonical.py "KNOWN OPEN") — first-seen wins here; the old
    sort_list_dict deep-froze the full posw payloads (~36 KiB/tx) on a per-second consensus path, which
    starved the event loop at mempool scale. Output is identical for validated inputs."""
    seen = set()
    unique = []
    for transaction in transactions:
        k = transaction[key]
        if k in seen:
            continue
        seen.add(k)
        unique.append(transaction)
    return sorted(unique, key=lambda transaction: transaction[key])


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
    the ledger itself never leaves integers.

    INTEGER-EXACT (divmod, not float division): raw balances can exceed 2**53, at which point
    `raw / 1e10` rounds in float64 and the displayed balance silently loses its low digits. divmod
    on the Python int is exact for any width."""
    raw = int(raw_amount)
    sign = "-" if raw < 0 else ""
    whole, frac = divmod(abs(raw), 10000000000)
    return f"{sign}{whole}.{frac:010d}"


def to_raw_amount(amount: [int, float]) -> int:
    """readable coin amount -> INTEGER raw units (1 coin = 10^10 raw); the float only exists at this
    UI/tooling boundary — everything on-chain stays integer"""
    return int(float(amount) * 10000000000)


def _spend_costs(tx):
    """(spendable-balance cost, bonded-stake cost) of a tx for overspend checks.
    An `unbond` draws its `amount` from bonded stake (only the fee leaves balance); every
    other tx — including `bond` — consumes amount+fee from spendable balance."""
    if tx["recipient"] == "unbond":
        return tx["fee"], tx["amount"]
    return tx["amount"] + tx["fee"], 0


def validate_single_spending(transaction_pool: list, transaction):
    """Validate that `sender`'s TOTAL spend across their pooled txs plus this incoming one stays within
    balance/bonded. Called per admission from merge_transaction.

    Sums the sender's existing pooled txs then adds the incoming tx, instead of copying the whole pool
    (`transaction_pool + [transaction]`) every call — that copy was pure allocation churn on the submit
    hot path (a single-sender flood re-copied a growing list on every submit; measured as GC noise
    under load). Same accept/reject: costs are non-negative, so checking the final totals is equivalent
    to the old incremental asserts — an overspend in any prefix implies an overspend in the total."""
    sender = transaction["sender"]
    acc = get_account(sender)
    balance, bonded = acc["balance"], acc["bonded"]

    balance_spent = 0
    bonded_spent = 0
    for pool_tx in transaction_pool:
        if pool_tx["sender"] == sender:
            b_cost, bond_cost = _spend_costs(pool_tx)
            balance_spent += b_cost
            bonded_spent += bond_cost
    b_cost, bond_cost = _spend_costs(transaction)     # the incoming tx (was the appended last element)
    balance_spent += b_cost
    bonded_spent += bond_cost
    assert balance_spent <= balance, "Overspending balance"
    assert bonded_spent <= bonded, "Overspending bonded stake"
    return True


def _escrow_release(tx):
    """(escrow_account, amount, bridge_ns_or_None) that `tx` releases from a SHARED escrow, else None. Reads
    only committed state (deterministic). Used to bound CUMULATIVE per-block releases — every escrow exit is
    validated individually against the SAME parent escrow balance, so N valid exits summing above it all pass
    validation yet over-draw at apply (change_balance floor_zero then either MINTS the unbacked credit or
    RAISES inside incorporate_block = halt). The nullifiers stop double-claims of ONE record; this stops
    distinct records collectively draining one pool."""
    from protocol import BRIDGE_ESCROW, SHIELD_ESCROW, HTLC_ESCROW, DIVIDEND_POOL, DEFAULT_NS
    r, d = tx.get("recipient"), (tx.get("data") or {})
    if r == "bridge_withdraw":
        return (BRIDGE_ESCROW, int(d.get("amount", 0) or 0), d.get("ns", DEFAULT_NS))
    if r == "unshield":
        return (SHIELD_ESCROW, int(d.get("amount", 0) or 0), None)
    if r == "dividend_withdraw":
        return (DIVIDEND_POOL, int(d.get("amount", 0) or 0), None)
    if r in ("htlc_claim", "htlc_refund"):
        doc = kv_ops.htlc_get(d.get("htlc_id")) or {}
        return (HTLC_ESCROW, int(doc.get("amount", 0) or 0), None)
    if r in ("invite_claim", "invite_refund"):
        from protocol import INVITE_ESCROW
        rec = kv_ops.invite_get(d.get("id")) if isinstance(d.get("id"), str) else None
        return (INVITE_ESCROW, int(rec[1]) if rec else 0, None)
    return None


class SpendingLedger:
    """Running per-sender and per-escrow spend totals for ONE candidate set or block.

    WHY THIS EXISTS. `validate_all_spending(prefix + [tx])` was called once per pool tx from
    _candidate_pool, and each call re-walked the whole prefix once per unique sender on top of an
    O(n^2) get_senders — so building a candidate was O(P^3). Measured on this box: 45 ms at P=100,
    660 ms at P=200, 20.6 s at P=800, plus ~P^2/2 get_account reads. That loop runs about once a
    second on the block thread holding the GIL, with no rate limit, and the 4 MiB pool cap puts a
    full mempool of ordinary ML-DSA txs (~7 KB each) right in the worst range — an unauthenticated
    party could stop this node producing blocks just by filling the mempool with distinct senders.
    It cost ~0 ms in practice only because the pool is usually empty.

    The accumulation is prefix-monotone, so the prefix never has to be re-examined: keep the running
    totals and add each tx once. add() checks BEFORE it commits, so a rejected tx contributes
    nothing — exactly as re-deriving from `prefix + [tx]` did.

    IDENTICAL ACCEPT/REJECT. Same costs, same per-sender and per-escrow prefix sums, compared against
    the same balances, in the same pool order — only the number of times each sum is recomputed
    changes. What does differ is WHICH assertion fires first when several would: the old form ran all
    sender checks and then all escrow checks, this interleaves them per tx. That is not observable at
    either call site. _candidate_pool feeds an already-valid prefix, so any new violation is caused by
    the tx being added and that tx is the one excluded either way; validate_transactions_in_block
    rejects the whole block on any raise. Nothing parses the message.

    Balances are read once per account and cached for the ledger's life. Both callers run outside a
    write txn against committed state that no one mutates mid-loop, which is the same assumption the
    per-call get_account already relied on."""

    __slots__ = ("_acct", "_spent", "_esc_drawn", "_esc_bal", "_ns_drawn")

    def __init__(self):
        self._acct = {}        # sender -> (balance, bonded)
        self._spent = {}       # sender -> [balance_spent, bonded_spent]
        self._esc_drawn = {}   # escrow account -> total drawn so far
        self._esc_bal = {}     # escrow account -> its balance (None if the account does not exist)
        self._ns_drawn = {}    # bridge namespace -> total drawn so far

    def add(self, transaction):
        """Fold one tx in. Raises (AssertionError) and mutates NOTHING if it would overspend."""
        sender = transaction["sender"]
        spent = self._spent.get(sender)
        if spent is None:
            acc = get_account(sender)
            self._acct[sender] = (acc["balance"], acc["bonded"])
            spent = self._spent[sender] = [0, 0]
        balance, bonded = self._acct[sender]
        b_cost, bond_cost = _spend_costs(transaction)
        new_balance_spent = spent[0] + b_cost
        new_bonded_spent = spent[1] + bond_cost
        assert new_balance_spent <= balance, "Overspending balance"
        assert new_bonded_spent <= bonded, "Overspending bonded stake"

        # CUMULATIVE ESCROW RELEASES: cap the total drawn from each shared escrow (bridge/shield/htlc/
        # dividend) this block at its parent balance, and per-namespace for the bridge — so multiple
        # distinct valid exits can't collectively over-draw one pool (mint or halt at apply).
        rel = _escrow_release(transaction)
        new_esc = new_ns = None
        if rel is not None:
            acct, amt, bns = rel
            if acct not in self._esc_bal:
                eacc = get_account(acct, create_on_error=False)
                self._esc_bal[acct] = eacc.get("balance", 0) if eacc else None
            esc_bal = self._esc_bal[acct]
            new_esc = (acct, self._esc_drawn.get(acct, 0) + amt)
            assert esc_bal is not None and new_esc[1] <= esc_bal, f"escrow {acct} over-drawn in one block"
            if bns is not None:
                new_ns = (bns, self._ns_drawn.get(bns, 0) + amt)
                assert new_ns[1] <= kv_ops.bridge_escrow_ns(bns), "namespace bridge escrow over-drawn in one block"

        # every check passed — commit
        spent[0], spent[1] = new_balance_spent, new_bonded_spent
        if new_esc is not None:
            self._esc_drawn[new_esc[0]] = new_esc[1]
        if new_ns is not None:
            self._ns_drawn[new_ns[0]] = new_ns[1]
        return True


def validate_all_spending(transaction_pool: list):
    """validate spending of all spenders in a transaction pool against their balance AND
    their bonded stake (unbond draws from bonded, not from spendable balance), plus the cumulative
    draw on each shared escrow. O(pool) — see SpendingLedger for why that matters."""
    ledger = SpendingLedger()
    for pool_tx in transaction_pool:
        ledger.add(pool_tx)
    return True


def validate_origin(transaction: dict, block_height=None):
    """signature is verified over the txid (which canonically commits the whole body,
    including chain_id); it is not itself part of the signed message."""

    # MULTISIG spend (ops/multisig_ops.py): the sender is a descriptor-derived account, "signature"
    # is a LIST of member signatures over the txid, and there is no top-level public_key. The whole
    # origin question (descriptor -> sender binding, M distinct valid member sigs) lives there.
    if transaction.get("multisig") is not None:
        from ops.multisig_ops import verify_multisig_origin
        return verify_multisig_origin(transaction)

    # ACCOUNT AUTHENTICATION AS STATE (ops/auth_ops.py, doc/key-rotation.md): a CONFIGURED account — or any
    # tx that signs with a LIST of entries — is judged by its effective config at `block_height`: every
    # entry must be a valid signature by one of the account's authenticators, and the signer set must
    # satisfy the SIGNING policy (an `auth` tx only needs a non-empty verified set here; which policy it
    # satisfies decides its effect in validate_transaction). A legacy account with a string signature
    # takes the unchanged path below, so today's transactions cost exactly what they cost.
    if _P.AUTH_ACTIVE:
        from ops import auth_ops
        _acc = get_account(transaction["sender"], create_on_error=False)
        if auth_ops.is_configured(_acc) or isinstance(transaction.get("signature"), list):
            _cfg = auth_ops.effective_config(transaction["sender"], _acc, block_height)
            _signers = auth_ops.verify_entries(transaction, transaction["sender"], _cfg)
            if transaction.get("recipient") != "auth":
                assert auth_ops.policy_satisfied(_cfg["sign"], _signers), "signers do not satisfy the account's signing policy"
            return True
    else:
        assert not isinstance(transaction.get("signature"), list), "signature lists need account authentication (not active)"

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
    # ADDRESS_KEY_BIND_HEIGHT (review 2026-09-25): the address binds only a CHOOSABLE prefix of the key, so a carried
    # key must also equal the one this account already published. Without it, anyone could spend from any address.
    from ops.address_ops import key_bound
    assert key_bound(transaction["sender"], public_key, block_height), \
        "public_key is not the key this account has on chain"

    assert verify(
        signed=signature,
        message=unhex(transaction["txid"]),
        public_key=public_key,
    ), "Invalid signature"

    return True


def validate_txid(transaction, logger):
    """CONSENSUS: recompute the canonical txid from the body (txid + signature stripped) and require
    an EXACT match. The signature covers only the txid, so this is what binds it to the full body —
    without it an attacker could keep a valid (txid, signature) pair and swap recipient/amount.
    Returns False (never raises) on mismatch or malformed input."""
    try:
        tx_copy = transaction.copy()
        txid_to_check = tx_copy["txid"]
        tx_copy.pop("txid")
        # the signature (string or entry list, each entry's key with it) is outside the txid, so its spelling is pinned
        # by excluded_witness_check, not here (audit 2026-09-25 "sig/pubkey hex re-encoding")
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


def unindex_transactions(block, logger, block_height):
    """Revert a block's txs: undo the balance/state changes AND delete the exact primary + DUPSORT
    secondary index entries written on apply (the block||txid dup encoding makes each delete
    unambiguous). Runs inside the rollback write txn (kv_ops uses the active txn), so it is atomic
    with the rest of the rollback — no per-statement retry loop is needed or possible under LMDB.

    REVERSE-APPLICATION ORDER (consensus-critical): index_transactions APPLIES `sorted_transactions`
    (sort_transaction_pool == sort by txid), so a correct undo must reverse EXACTLY that order. Balances
    commute (addition), but the overwrite-then-restore-prior journals do NOT: apply_bond_since (and the
    hb/msgkey reverts) stash the prior value keyed by txid and restore it on revert, so for two
    non-commutative ops on one address in one block — e.g. two `bond`s from the same sender — reverting in
    any order but reverse-application restores the WRONG intermediate prior value (the earlier tx's revert
    runs last and wins, leaving bond_since at the middle value instead of the original). That is
    path-dependent state, which forks the snapshot root. We re-derive the applied order here (the stored
    body is already txid-sorted, so this is a no-op reorder in practice, but re-sorting makes the symmetry
    exact and robust to any body that was persisted unsorted) and walk it backwards."""
    for transaction in reversed(sort_transaction_pool(block["block_transactions"])):
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
        # PUBKEY-ONCE revert: clear the established pubkey ONLY when the apply-side journal proves THIS
        # tx is the one that set it (pubkey_revert, keyed by txid). The old inference — "carried a key
        # and tx_of_account shows no earlier tx" — is NOT a pure function of consensus state: on a
        # snapshot-bootstrapped or pruned node tx_of_account reads pruned history and returns empty for
        # a long-established sender, so reverting ANY later key-carrying tx deleted a pubkey that a
        # full-history node kept — divergent accounts roots from identical block sequences (observed
        # 2026-07-30 h15076: two accounts culled, node wedged 18h on the resulting state-root mismatch).
        # A missing journal row (legacy apply, or a tx that carried the key redundantly) now correctly
        # deletes nothing, because such an apply set nothing. (Re-applies reverted-at-reroll 942f41f1.)
        if transaction.get("public_key") and kv_ops.pubkey_revert_pop(transaction["txid"]):
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
        # STORED VERBATIM, SO ITS SPELLING IS CONSENSUS: key_bound later compares this string exactly, and
        # without excluded_witness_check (all of betanet-8) a relayer could re-case a first tx's key (same txid, still valid) and lock the owner's
        # own lowercase-key transactions out (audit 2026-09-25). INVARIANT: never normalise here instead — rewriting
        # the stored spelling changes the accounts root of blocks already applied; excluded_witness_check refuses it
        # upstream.
        # AND ONLY AN AUTHENTICATED KEY MAY LAND HERE: with an entry-list signature nothing verifies the top-level key,
        # so storing it let a relayer install its own key as a never-sent account's authenticator (reproduced; refused
        # by excluded_witness_check from block 1). A new path that stores a key must store a VERIFIED one.
        pk = transaction.get("public_key")
        if pk:
            sender_acc = get_account(transaction["sender"], create_on_error=False)
            if sender_acc is not None and not sender_acc.get("public_key"):
                kv_ops.account_set_field(transaction["sender"], "public_key", pk)
                # JOURNAL the establishment (node-local, txid-keyed) so the revert deletes the field
                # exactly when THIS apply set it — never by inference from pruned history. See the
                # matching pop in unindex_transactions. (Re-applies reverted-at-reroll 942f41f1.)
                kv_ops.pubkey_revert_put(transaction["txid"])
