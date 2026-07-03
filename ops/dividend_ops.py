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
from protocol import POSW_LEASE_EPOCHS, FIDELITY_GAIN
from ops import kv_ops
from ops.mining_ops import open_shares


def fidelity_at_epoch(address: str, epoch: int) -> int:
    """Reconstruct `address`'s raw fidelity AS OF `epoch`, from its recert history (recerts <= epoch), by
    replaying the exact apply_register ramp. Returns 0 if it had no recert at/behind `epoch` (uncapped —
    open_shares() applies the FIDELITY_CAP saturation to the weight, matching the live path)."""
    fid = 0
    prev = -1
    for r in kv_ops.recert_epochs(address, upto_epoch=epoch):    # ascending, only recerts <= epoch
        continuous = prev >= 0 and (r - prev) <= POSW_LEASE_EPOCHS
        fid = (fid + FIDELITY_GAIN) if continuous else FIDELITY_GAIN   # lapse/first -> reset to GAIN
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
    """{address: open_shares(fidelity_at_epoch(address, epoch))} for the present set at `epoch` — the
    fidelity-weighted open-lane weights the dividend distributes by, as of that epoch. Deterministic and
    reconstructible: this is what the exec node accrues against and what an L1 challenge re-derives."""
    return {addr: open_shares(fidelity_at_epoch(addr, epoch)) for addr in present_at_epoch(epoch)}
