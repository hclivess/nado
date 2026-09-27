"""THE FOUR-MESSAGE TPM ENROLMENT, AS CONSENSUS SEES IT (doc/tpm-attestation-without-a-ca.md).

A machine proves it holds a vendor-certified TPM without Microsoft and without anyone holding a key that
could mint identities. ops/tpm_aik.verify_enrolment does the arithmetic; this module does the part the
arithmetic cannot do — the ORDERING — because that is where the security actually lives.

WHY FOUR MESSAGES, AND WHY NONE OF THEM CAN BE MERGED:

  1. `tpm_enrol`     client      publishes the endorsement chain + the attestation key's public area.
                                 The challengers cannot act before this: MakeCredential seals to a
                                 SPECIFIC key's name, and the name is a digest of that public area.
  2. `tpm_challenge` challenger  publishes blob = MakeCredential(EKpub, aikName, S) and the wrapped seed.
                                 Only the chip can open it. One tx per drawn challenger.
  3. `tpm_commit`    client      publishes H(S_1 || ... || S_k), having run TPM2_ActivateCredential.
                                 MUST land strictly after every challenge: otherwise the client is
                                 committing to nothing and can pick its answer once the reveals arrive.
  4. `tpm_reveal`    challenger  publishes (S_i, R_i). Every node recomputes the blob from them and checks
                                 it equals the one published at step 2, then checks the commitment.
                                 MUST land strictly after the commit, or the client reads S off the chain
                                 and never touches a TPM.

Collapse any adjacent pair and the proof evaporates. That is why this is on-chain at all rather than a
handshake against a relay: block height is the only ordering every node agrees on.

WHO CHALLENGES. Not whoever the client asks — a client that picks its own challengers picks parties that
will leak S to it. The set is DRAWN from the bonded registry by the epoch beacon keyed on the enrolment id
(the same grind-resistant randomness as producer selection), and the client must recover EVERY drawn
challenger's secret. Forging then requires all DEVICE_ATTEST_EK_CHALLENGERS of them to collude, which is a
property consensus can observe, rather than a key someone promises to guard.

COMMIT, THEN DRAW (protocol.TPM_DRAW_UNGRINDABLE_HEIGHT, audit 2026-09-27). "Keyed on the enrolment id" was the
hole: the id hashes the attestation key's public area, which the CLIENT writes, and the beacon of the enrol's
own epoch is public before the enrol is built. So a client could compute the draw offline and grind public
areas until every seat fell on a pool member it controls — and with every seat colluding the challengers hand
it the secrets and no chip is involved at all. From the gate an enrolment opened at h (epoch E) is drawn from:

    key      the ENDORSEMENT identity             one per chip, fixed by manufacture — nothing the client writes
    weights  the challenger pool as of block h    frozen before the dice exist, so nobody can join it to aim
    dice     epoch_beacon(E + DELAY)              anchored on block (E+1)*EPOCH_LENGTH > h: unknown at commit

and the record is written with NO challengers; the first tpm_challenge from the draw epoch on materialises the
set into it (transaction_ops.tpm_materialise_draw). Retrying still works exactly as before: an expired record is
superseded at a later height, whose own draw epoch has different dice and whose pool is re-read.

WHAT AN ENROLMENT CONFERS. Nothing by itself. It records that a specific attestation key lives in a
specific vendor-certified chip. A `register` still has to produce a fresh TPM2_Certify over that block's
own challenge under that key, and the identity binds to the ENDORSEMENT key — so enrolling ten attestation
keys in one chip yields one identity, not ten.
"""

from hashing import blake2b_hash
from ops.tpm_aik import aik_name, credential_commitment, make_credential, validate_aik_pub_area

STATE_OPEN = "open"          # published, waiting for its challengers
STATE_COMMITTED = "commit"   # the client answered; waiting for the reveals
STATE_PROVEN = "proven"      # every secret reproduced its blob and the commitment holds


def enrol_id(chain_id: str, ek_identity: str, aik_name_hex: str) -> str:
    """The enrolment's key. Derived from its own public content, so it is the same on every node, cannot
    be chosen by the client, and re-publishing the identical (chip, key) pair collides instead of opening
    a second enrolment. chain_id is in the digest for the same reason every other proof carries it: an
    enrolment from another generation of this chain must not replay onto this one."""
    return blake2b_hash([str(chain_id), str(ek_identity), str(aik_name_hex)])[:32]


def challenger_set(enrol_id_hex: str, weights: dict, beacon: str, k: int) -> list:
    """The `k` challengers for one enrolment: a stake-weighted draw WITHOUT replacement, keyed on the
    beacon and the enrolment id — mining_ops.duty_committee's discipline, and deterministic from committed
    parent state for exactly the same reason.

    Without replacement because the whole point is INDEPENDENT parties: seating one validator twice would
    let it hold two of the k secrets and cut the collusion it takes to forge. Stake-weighted because an
    unweighted draw over the bonded set is a Sybil target — cheap identities would crowd the ballot.

    Returns fewer than k (possibly none) when the registry cannot supply k distinct weighted entries. The
    caller must refuse an enrolment whose set is short: a smaller set is a weaker proof, and an attacker
    who can shrink the registry must not thereby weaken what it takes to forge.
    """
    cumulative, total = [], 0
    for address in sorted(weights):
        # WEIGHTS ARE PLAIN INTEGERS, not registry entries. This took the value of `bonded_registry[a]["bonded"]`
        # until the draw moved to recent block producers, and the signature change without the body change
        # meant every enrolment died with "'int' object is not subscriptable" — a TypeError escaping a
        # function whose contract is to raise AssertionError, which in block verification is the difference
        # between a rejected block and a fork.
        raw = weights[address]
        # A SHAPE ERROR MUST BE A REJECTION, NOT A TypeError. validate_transaction's contract is to raise
        # AssertionError on the first violation, and it runs in block verification as well as the mempool —
        # an unexpected exception type there is the difference between a cleanly rejected block and nodes
        # disagreeing on block validity. This assert is what the previous signature/body mismatch needed.
        assert isinstance(raw, int) and not isinstance(raw, bool), \
            f"challenger weight for {address} must be an integer, got {type(raw).__name__}"
        w = int(raw)
        if w > 0:
            total += w
            cumulative.append((total, address))
    if total == 0:
        return []
    picked, seen = [], set()
    # Bounded attempts: a heavily concentrated weight distribution re-draws the same large holder over and
    # over, and this must terminate identically on every node rather than loop until it happens to succeed.
    for i in range(k * 16):
        if len(picked) >= k:
            break
        draw = int(blake2b_hash([str(beacon), f"tpmenrol:{enrol_id_hex}:{i}"]), 16) % total
        lo, hi = 0, len(cumulative) - 1
        while lo < hi:                                   # first band with cumulative > draw
            mid = (lo + hi) // 2
            if draw < cumulative[mid][0]:
                hi = mid
            else:
                lo = mid + 1
        addr = cumulative[lo][1]
        if addr not in seen:
            seen.add(addr)
            picked.append(addr)
    return picked


def draw_is_delayed(created_height: int) -> bool:
    """True when an enrolment opened at `created_height` is drawn COMMIT-THEN-DRAW (see the module docstring).
    A pure function of the record's own height, so a record's rule never changes under it and a replay of an
    old block reaches the verdict it had."""
    from protocol import TPM_DRAW_UNGRINDABLE_HEIGHT
    return int(created_height) >= TPM_DRAW_UNGRINDABLE_HEIGHT


def draw_epoch(created_height: int) -> int:
    """The epoch whose beacon draws a delayed enrolment's challengers. INVARIANT: its anchor block
    ((draw_epoch - 1) * EPOCH_LENGTH) must lie STRICTLY AFTER created_height, or the client knows the dice when it
    commits and the grind is back; TPM_DRAW_DELAY_EPOCHS >= 2 is what guarantees it for every height in the epoch."""
    from protocol import EPOCH_LENGTH, TPM_DRAW_DELAY_EPOCHS
    return int(created_height) // EPOCH_LENGTH + TPM_DRAW_DELAY_EPOCHS


def draw_opens(created_height: int) -> int:
    """The first block at which a delayed enrolment's challengers exist (the first block of its draw epoch).
    By then the beacon's anchor is EPOCH_LENGTH blocks deep and its RANDAO reveal window has closed, so the value
    every node reads is final."""
    from protocol import EPOCH_LENGTH
    return draw_epoch(created_height) * EPOCH_LENGTH


def draw_key(ek_identity: str) -> str:
    """What a delayed draw is keyed on: the endorsement identity and NOTHING the client writes.
    INVARIANT: never mix the enrolment id, the attestation key's public area or name, the owner or any tx field in
    here — each is a free choice of the client, and a free choice in the key is a grind (the 2026-09-27 finding).
    Two attestation keys of one chip therefore draw the same set in the same draw epoch, which is the point."""
    return "ek:" + str(ek_identity)


def challenger_set_exact(key: str, weights: dict, beacon: str, k: int) -> list:
    """The delayed draw: `k` distinct challengers by weighted sampling WITHOUT replacement — each pick removes its
    band and the next draw runs over what is left. The same distribution challenger_set's redraw-on-duplicate
    reaches when it succeeds, minus its attempt cap, so a pool with >= k positively weighted members ALWAYS seats k.
    That matters here and not there: the enrol is checked against the pool up front, and the set only exists two
    epochs later, so a short set could not be refused any more — it would silently waste the whole window.
    Deterministic: sorted addresses, integer weights, the draw hashed from (beacon, key, round)."""
    pool = []
    for address in sorted(weights):
        raw = weights[address]
        # same shape rule as challenger_set: a non-integer weight is a REJECTION (AssertionError), never a TypeError
        assert isinstance(raw, int) and not isinstance(raw, bool), \
            f"challenger weight for {address} must be an integer, got {type(raw).__name__}"
        if raw > 0:
            pool.append((address, int(raw)))
    picked = []
    for i in range(int(k)):
        total = sum(w for _a, w in pool)
        if total == 0:
            break
        draw = int(blake2b_hash([str(beacon), f"tpmdraw:{key}:{i}"]), 16) % total
        acc = 0
        for j, (address, w) in enumerate(pool):
            acc += w
            if draw < acc:
                picked.append(address)
                del pool[j]
                break
    return picked


def pool_can_seat(weights: dict, k: int) -> bool:
    """Whether challenger_set_exact over `weights` will seat k — the enrol-time check for a delayed draw."""
    return sum(1 for w in weights.values() if isinstance(w, int) and not isinstance(w, bool) and w > 0) >= int(k)


def new_record(ek_identity: str, ek_spki: bytes, aik_name_hex: str, aik_pub: bytes, owner: str,
               height: int, challengers: list) -> dict:
    """The endorsement PUBLIC KEY is stored, not just its digest: every node has to re-derive the credential
    blob from the revealed (secret, seed) at step 4, and MakeCredential needs the key itself. Keeping it in
    the record also means the reveal check never re-parses a certificate — the kernel read it once, when the
    vendor signature was verified, and consensus reads the same bytes forever after."""
    return {"state": STATE_OPEN, "ek": str(ek_identity), "ekpub": ek_spki.hex(),
            "name": str(aik_name_hex),
            "pub": aik_pub.hex(), "owner": str(owner), "h": int(height),
            "challengers": sorted(str(a) for a in challengers),
            "blobs": [], "commit": "", "hc": -1, "reveals": [], "hp": -1}


def _pairs(rec: dict, field: str) -> dict:
    """The sorted-pair lists are stored, not dicts: msgpack preserves insertion order and a dict built in
    a different order on two nodes is two different bytes for the same state — a root split."""
    return {p[0]: p[1:] for p in rec.get(field) or []}


def apply_challenge(rec: dict, challenger: str, blob: bytes, enc_secret: bytes, height: int) -> dict:
    """Step 2. Refuses anyone not drawn, a second challenge from the same challenger, and any challenge
    that does not land strictly after the enrolment (the challenger must have SEEN the key's name to seal
    to it; same-block is not "after" — transactions inside a block have no ordering consensus relies on)."""
    assert rec.get("state") == STATE_OPEN, "enrolment is no longer accepting challenges"
    assert challenger in rec["challengers"], "not a drawn challenger for this enrolment"
    assert int(height) > int(rec["h"]), "a challenge must land in a later block than the enrolment"
    have = _pairs(rec, "blobs")
    assert challenger not in have, "this challenger already challenged this enrolment"
    assert 0 < len(blob) <= 1024 and 0 < len(enc_secret) <= 1024, "credential sizes out of bounds"
    rec = dict(rec)
    rec["blobs"] = sorted(rec["blobs"] + [[challenger, blob.hex(), enc_secret.hex(), int(height)]])
    return rec


def apply_commit(rec: dict, sender: str, commitment: str, height: int) -> dict:
    """Step 3. The client answers. EVERY drawn challenger must already have challenged, and this must land
    strictly after the last of them — a commit that races a challenge is a commit to a secret the client
    has not been asked for yet, which is worth nothing."""
    assert rec.get("state") == STATE_OPEN, "enrolment is not awaiting a commitment"
    assert sender == rec["owner"], "only the identity that opened an enrolment may answer it"
    # A DELAYED DRAW STARTS WITH NO CHALLENGERS (COMMIT, THEN DRAW), and an empty set equals an empty set of blobs:
    # without this a commitment to nothing would pass the check below and then die on max() of nothing — a
    # ValueError, not a rejection. INVARIANT: a commitment needs a drawn, non-empty set; every pre-gate record was
    # written with k challengers, so this moves no verdict for them.
    assert rec.get("challengers"), "the challengers for this enrolment have not been drawn yet"
    blobs = _pairs(rec, "blobs")
    assert set(blobs) == set(rec["challengers"]), "not every drawn challenger has issued its challenge"
    assert int(height) > max(int(v[2]) for v in blobs.values()), \
        "the commitment must land in a later block than every challenge"
    assert isinstance(commitment, str) and len(commitment) == 64 and _is_hex(commitment), "malformed commitment"
    rec = dict(rec)
    rec["state"], rec["commit"], rec["hc"] = STATE_COMMITTED, commitment.lower(), int(height)
    return rec


def apply_reveal(rec: dict, challenger: str, secret: bytes, seed: bytes, height: int) -> dict:
    """Step 4. A challenger opens its own challenge and every node re-derives the blob from (S, R). This is
    where the challenger is held to what it published: it cannot reveal a different secret than the one it
    sealed, because MakeCredential is deterministic in (seed, name, secret) and the blob is already on
    chain. When the last one lands, the commitment is checked and the enrolment is proven."""
    assert rec.get("state") == STATE_COMMITTED, "enrolment is not awaiting reveals"
    assert int(height) > int(rec["hc"]), \
        "a reveal must land in a later block than the commitment — otherwise the client reads the secret"
    blobs = _pairs(rec, "blobs")
    assert challenger in blobs, "this challenger has nothing to reveal for this enrolment"
    assert challenger not in _pairs(rec, "reveals"), "this challenger already revealed"
    published = bytes.fromhex(blobs[challenger][0])
    name = bytes.fromhex(rec["name"])
    derived, _ = make_credential(bytes.fromhex(rec["ekpub"]), name, secret, seed=seed)
    assert derived == published, "the revealed secret and seed do not reproduce the published challenge"
    rec = dict(rec)
    rec["reveals"] = sorted(rec["reveals"] + [[challenger, secret.hex(), seed.hex(), int(height)]])
    if len(rec["reveals"]) == len(rec["challengers"]):
        # THE COMMITMENT IS OVER ALL THE SECRETS AT ONCE, in challenger order. One commitment per secret
        # would let the client answer the challengers it managed to open and abandon the rest, which is
        # exactly the k-of-k requirement dissolving into 1-of-k.
        joined = b"".join(bytes.fromhex(r[1]) for r in rec["reveals"])
        assert credential_commitment(joined) == rec["commit"], \
            "the client's commitment is not to the secrets its challengers sealed"
        rec["state"], rec["hp"] = STATE_PROVEN, int(height)
    return rec


def proven_key(rec: dict) -> str:
    """The attestation key this enrolment proved, as `<ek identity>:<aik name>`. Callers key on the EK half
    for identity (one chip, one identity) and on the name half to find the public area to verify under."""
    assert rec.get("state") == STATE_PROVEN, "enrolment is not proven"
    return f"{rec['ek']}:{rec['name']}"


def enrol_window(created_height: int) -> int:
    """How long an enrolment opened at `created_height` stays alive.

    A FUNCTION OF THE RECORD, NOT OF NOW. Deriving it from the height a record is evaluated at would move
    its deadline under it — a record could be live to one caller and expired to another at the same
    moment, and a supersede valid on one node and invalid on the next, which is a fork over block
    validity rather than a disagreement about a timer.

    Every record is created by a tpm_enrol in a block >= 1 (genesis carries no transactions), and gen 25's
    DEVICE_ATTEST_EK_SHORT_HEIGHT was 1 from gen 26 (deleted), so every record takes the short window.

    A DELAYED DRAW GETS THE SAME WORKING TIME, counted from when its challengers exist: the wait for the draw epoch
    (61..120 blocks) plus the short window. Counting from the enrol instead would leave 60..119 blocks for three
    challenges, a commit and three reveals. Still a pure function of created_height, so a supersede is decided
    identically everywhere; and a superseding enrol lands after draw_opens(h) + SHORT, in a later draw epoch, so
    the retry is always drawn from fresh dice (AN EXPIRED ATTEMPT MUST BE RETRYABLE, transaction_ops)."""
    from protocol import DEVICE_ATTEST_EK_ENROL_SHORT
    if draw_is_delayed(created_height):
        return draw_opens(created_height) - int(created_height) + DEVICE_ATTEST_EK_ENROL_SHORT
    return DEVICE_ATTEST_EK_ENROL_SHORT


def _is_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except ValueError:
        return False


def validate_publication(ek_identity: str, aik_pub: bytes) -> str:
    """Step 1's content check. The endorsement chain itself is verified by the kernel (native/attest ek.rs)
    before this is called; what is left is the public area we are about to let a chip vouch for.

    CERTIFYING AN UNRESTRICTED KEY WOULD END THE WHOLE SCHEME: such a key signs whatever the host hands it,
    including a forged TPMS_ATTEST for a key that never existed in any chip, and our own certify check
    would then accept that forgery under a genuinely enrolled name."""
    assert isinstance(ek_identity, str) and len(ek_identity) == 64 and _is_hex(ek_identity), \
        "malformed endorsement identity"
    assert 0 < len(aik_pub) <= 2048, "attestation public area out of bounds"
    return validate_aik_pub_area(aik_pub)


def aik_name_hex(aik_pub: bytes) -> str:
    return aik_name(aik_pub).hex()
