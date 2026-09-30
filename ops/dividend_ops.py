"""
Deterministic, historically-reconstructible inputs for the presence-dividend fraud proof
(doc/dividend-fraud-proof.md, Phase-2b).

The dividend's per-address split must be a PURE FUNCTION of finalized L1 state so every honest node computes
the identical root and a dishonest settlement is provably wrong. The tricky input is each present miner's
fidelity-weight AS OF a past epoch `e`: `get_open_registry` returns historical MEMBERSHIP but reads each
account's CURRENT fidelity, not fidelity at `e`. Fidelity, however, is a deterministic function of the
immutable, revert-safe recert history — so we replay the exact ramp `apply_register` applies:

  each continuous recert (gap <= POSW_LEASE_EPOCHS) adds FIDELITY_GAIN; a lapse (or the first recert) RESETS
  the streak to FIDELITY_GAIN.

`fidelity_at_epoch` MUST stay byte-identical to that ramp (ops/account_ops.apply_register) — a fraud proof
that miscomputes it would false-slash honest settlers. test_dividend_fidelity.py pins the two together.
"""
from protocol import LEASE_EPOCHS_MAX, fidelity_step, dividend_weight
from ops import kv_ops

_CARRIED = [None]


def carried_identities() -> dict:
    """{address: carried fidelity} for the identities THIS generation's carry named as present — read once from the same
    files genesis built this chain from (genesis_data/genesis_carry.dat "present", only when it names this generation;
    the allocation from private/ first, else the repo copy, exactly as genesis.py resolves it). Static for the life of a
    chain, identical on every node that built the same genesis. {} on a chain without a carry."""
    if _CARRIED[0] is not None:
        return _CARRIED[0]
    import json, os
    from protocol import CHAIN_GENERATION
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = {}
    try:
        carry_path = os.environ.get("NADO_GENESIS_CARRY") or os.path.join(here, "genesis_data", "genesis_carry.dat")
        with open(carry_path) as f:
            carry = json.load(f)
        if int(carry.get("generation", -1)) == int(CHAIN_GENERATION):
            present = set(carry.get("present") or [])
            from ops.data_ops import get_home
            alloc_path = f"{get_home()}/private/genesis_alloc.dat"
            if not os.path.exists(alloc_path):
                alloc_path = os.path.join(here, "genesis_data", "genesis_alloc.dat")
            fid = {}
            if os.path.exists(alloc_path):
                with open(alloc_path) as f:
                    fid = {e["address"]: int(e.get("fidelity") or 0) for e in json.load(f) if isinstance(e, dict)}
            out = {a: fid.get(a, 0) for a in present}
    except (OSError, ValueError, TypeError):
        out = {}
    _CARRIED[0] = out
    return out


def fidelity_at_epoch(address: str, epoch: int) -> int:
    """Reconstruct `address`'s raw fidelity AS OF `epoch`, from its recert history (recerts <= epoch), by
    replaying the exact apply_register ramp (protocol.fidelity_step). Returns 0 if it had no recert at/behind
    `epoch` (uncapped — dividend_weight() applies the FIDELITY_CAP saturation, matching the live path)."""
    fid = 0
    prev = -1
    # Every epoch: gen 27's DIVIDEND_CARRY_EPOCH was 0 from gen 28 (deleted). A negative epoch holds no recert, so the
    # loop below never reads the carry there.
    carried = carried_identities()
    for r in kv_ops.recert_epochs(address, upto_epoch=epoch):    # ascending, only recerts <= epoch
        if r == 0 and address in carried:
            # THE CARRY'S LEASE (our reroll commit 302215f2): the epoch-0 recert of a carried identity continues its
            # previous generation — its fidelity starts at the carried value, exactly as the live apply continued from
            # the carried account field. Replaying it as a fresh first recert reset every carried veteran to a newcomer.
            fid, prev = int(carried[address]), 0
            continue
        # continuity by the PREVIOUS recert's own grant (kv_ops.lease_of; pre-gate recerts read POSW_LEASE_EPOCHS) —
        # the same reader and the same rule as the live apply
        continuous = prev >= 0 and (r - prev) <= kv_ops.lease_of(address, prev)
        # THE SAME FUNCTION the live apply uses (protocol.fidelity_step) — not a mirror of it. This replay is
        # what a dividend fraud proof checks against, so the two cannot be allowed to drift.
        fid = fidelity_step(fid, continuous, r - prev, r)
        prev = r
    return fid


def present_at_epoch(epoch: int) -> set:
    """The OPEN-lane present set AT `epoch`: addresses whose lease was valid then — a recert in
    (epoch - POSW_LEASE_EPOCHS, epoch]. Reconstructed from the recert history (not the live `registered`
    flag), so it is well-defined for any past epoch, identically on every node."""
    floor = epoch - LEASE_EPOCHS_MAX                          # the widest candidate net any class's grant can reach
    present = set()
    for addr in kv_ops.recert_addresses_after(floor):           # a recert in some epoch > floor (may be > epoch)
        recs = kv_ops.recert_epochs(addr, upto_epoch=epoch)
        # PER-CLASS LEASES: valid at `epoch` iff the latest recert's OWN grant still covers it (kv_ops.lease_of; a pre-gate
        # recert reads POSW_LEASE_EPOCHS, so every historical epoch reconstructs exactly as before)
        if recs and epoch - recs[-1] < kv_ops.lease_of(addr, recs[-1]):
            # EVICTED (an instant device move): a device move at or before `epoch` voided this lease — only a recert
            # newer than the voided one counts. Eviction rows are epoch-stamped consensus state, so this reconstructs
            # identically for any past epoch (the same rule get_open_registry applies live).
            if recs[-1] <= kv_ops.devevict_voided(addr, epoch):
                continue
            present.add(addr)
    return present


def weights_at_epoch(epoch: int) -> dict:
    """{address: dividend_weight(fidelity_at_epoch(address, epoch))} for the present set at `epoch` — the
    fidelity-weighted weights the dividend distributes by, as of that epoch (protocol.dividend_weight, one
    clean line min(fidelity, 30) over every level — fidelity 1 pays from the first lease since gen 25).
    Deterministic and reconstructible: this is what the exec node accrues against and what an L1 challenge
    re-derives."""
    # A 0 weight (no fidelity at all) means ABSENT from the set — the exec accrual floors listed weights to 1, so
    # listing is the grant. Gen 24 used this omission for probation; gen 25 has none, so only fidelity 0 is absent.
    out = {}
    for addr in present_at_epoch(epoch):
        # DIVIDENDS REQUIRE ATTESTATION: a genesis-seeded identity (only recert at epoch 0, never attested) produces
        # blocks but takes no dividend. Same recert history the present set is derived from, so every node and the
        # fraud-proof replay agree. Unconditional: gen 25's DIVIDEND_ATTESTED_EPOCH was 0 from gen 26 (deleted), and a
        # present address has a recert <= epoch, so `epoch >= 0` always held here.
        recs = kv_ops.recert_epochs(addr, upto_epoch=epoch)
        if not recs or recs[-1] <= 0:
            # ...EXCEPT AN IDENTITY THE CARRY NAMED AS PRESENT (our reroll commit 302215f2): it attested on the previous
            # chain and was leased at epoch 0 for exactly that reason; the exclusion is for genesis seeds that never did.
            # Every epoch: gen 27's DIVIDEND_CARRY_EPOCH was 0 from gen 28 (deleted), and `recs[-1] == 0` means epoch >= 0.
            if not (recs and recs[-1] == 0 and addr in carried_identities()):
                continue
        w = dividend_weight(fidelity_at_epoch(addr, epoch), epoch)
        if w > 0:
            out[addr] = w
    return out
