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
from protocol import POSW_LEASE_EPOCHS, fidelity_step, dividend_weight
from ops import kv_ops


def fidelity_at_epoch(address: str, epoch: int) -> int:
    """Reconstruct `address`'s raw fidelity AS OF `epoch`, from its recert history (recerts <= epoch), by
    replaying the exact apply_register ramp (protocol.fidelity_step). Returns 0 if it had no recert at/behind
    `epoch` (uncapped — dividend_weight() applies the FIDELITY_CAP saturation, matching the live path)."""
    fid = 0
    prev = -1
    for r in kv_ops.recert_epochs(address, upto_epoch=epoch):    # ascending, only recerts <= epoch
        continuous = prev >= 0 and (r - prev) <= POSW_LEASE_EPOCHS
        # THE SAME FUNCTION the live apply uses (protocol.fidelity_step) — not a mirror of it. This replay is
        # what a dividend fraud proof checks against, so the two cannot be allowed to drift.
        fid = fidelity_step(fid, continuous, r - prev)
        prev = r
    return fid


def present_at_epoch(epoch: int) -> set:
    """The OPEN-lane present set AT `epoch`: addresses whose lease was valid then — a recert in
    (epoch - POSW_LEASE_EPOCHS, epoch]. Reconstructed from the recert history (not the live `registered`
    flag), so it is well-defined for any past epoch, identically on every node."""
    floor = epoch - POSW_LEASE_EPOCHS
    present = set()
    for addr in kv_ops.recert_addresses_after(floor):           # a recert in some epoch > floor (may be > epoch)
        recs = kv_ops.recert_epochs(addr, upto_epoch=epoch)
        if recs and recs[-1] > floor:                           # a recert within (floor, epoch] -> lease valid at epoch
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
    from protocol import DIVIDEND_ATTESTED_EPOCH
    out = {}
    for addr in present_at_epoch(epoch):
        # DIVIDENDS REQUIRE ATTESTATION (protocol.DIVIDEND_ATTESTED_EPOCH): a genesis-seeded identity (only recert at
        # epoch 0, never attested) produces blocks but takes no dividend from the gate on. Same recert history the
        # present set is derived from, so every node and the fraud-proof replay agree.
        if epoch >= DIVIDEND_ATTESTED_EPOCH:
            recs = kv_ops.recert_epochs(addr, upto_epoch=epoch)
            if not recs or recs[-1] <= 0:
                continue
        w = dividend_weight(fidelity_at_epoch(addr, epoch), epoch)
        if w > 0:
            out[addr] = w
    return out
