"""PER-CLASS LEASES, GAP-PROPORTIONAL FIDELITY AND SIGNATURE RENEWALS (protocol.LEASE_V2_EPOCH; operator decision
2026-09-14; doc/scaling-open-lane.md phases 1a/1b). Pins, on a scratch chain DB, across the gate:

  * the grant: a recert at/after the gate writes lease_of(address, epoch) = the class's lease; before it nothing is
    written and lease_of reads POSW_LEASE_EPOCHS; an identity with no class is on the historical lease;
  * presence: a 7-day class is present six days after its recert and a phone is not; BOTH readers — the live registry
    (account_ops.get_open_registry) and the fraud-proof reconstruction (dividend_ops.present_at_epoch) — agree at every
    epoch of a scripted history that crosses the gate;
  * continuity is judged by the previous recert's own grant, and the ramp pays per FIDELITY_MIN_GAP_EPOCHS of gap from
    the gate: a weekly renewal earns 8, a 36-hour one earns 1, and the replay (fidelity_at_epoch) equals the live value
    at every recert;
  * devkey is stamped for every class from the gate, devcred for a WebAuthn statement, and a revert restores both and
    removes the grant — byte-identical rows;
  * the lookback and retention functions widen from the gate without refusing the epochs just before it;
  * the wiring: validation judges an assertion before the statement/statement-free split, apply passes the credential.

Run: python3 tests/test_lease_v2.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_lease2_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("lease2"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from ops import kv_ops
from ops.account_ops import apply_register, get_open_registry
from ops import dividend_ops as D

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails.append(name)


G = 0                               # the per-class rules hold from epoch 0 (gen 25's LEASE_V2_EPOCH, deleted)
check("the epoch gate stays deleted", not hasattr(P, "LEASE_V2_EPOCH") and not hasattr(P, "lease_v2_at"))
PC, PHONE, NOKEY = "p" * 46, "a" * 46, "n" * 46
TPMKEY, ANDKEY = "tpm:" + "11" * 32, "android-key:" + "22" * 32
for a in (PC, PHONE, NOKEY):
    kv_ops.account_set(a, "balance", 0)

# ---------------------------------------------------------------- the grant, and the reader
apply_register(PC, G + 1, logger, device_key=TPMKEY, cred_pub="a5010203262001" + "00" * 8)
check("a Windows Hello recert at the gate is granted the 7-day lease", kv_ops.lease_of(PC, G + 1) == P.LEASE_EPOCHS_BY_CLASS["tpm"] == 1680)
check("...and the account carries devkey AND the credential", (kv_ops.get_account(PC) or {}).get("devkey") == TPMKEY
      and (kv_ops.get_account(PC) or {}).get("devcred", "").startswith("a5010203"))
apply_register(PHONE, G + 1, logger, device_key=ANDKEY, cred_pub="a5" + "00" * 12)
check("a phone recert at the gate is granted 36 h", kv_ops.lease_of(PHONE, G + 1) == 360)
apply_register(NOKEY, G + 1, logger)
check("an identity with no class on chain stays on the historical lease", kv_ops.lease_of(NOKEY, G + 1) == P.POSW_LEASE_EPOCHS)
check("the table names every bindable class and nothing longer than LEASE_EPOCHS_MAX",
      set(P.LEASE_EPOCHS_BY_CLASS) == {"android-key", "tpm", "ledger", "trezor", "ek"} and max(P.LEASE_EPOCHS_BY_CLASS.values()) == P.LEASE_EPOCHS_MAX)
check("android keeps the 36-hour lease (its certificate rotates)", P.LEASE_EPOCHS_BY_CLASS["android-key"] == 360)
check("signature renewals are for the Windows Hello class only", P.LEASE_ASSERT_CLASSES == frozenset(("tpm",)))

# ---------------------------------------------------------------- presence: both readers, per class
E6D = G + 1 + 1440              # six days later
reg = get_open_registry(E6D)
check("six days after the recert the PC is present and the phone is not (live registry)", PC in reg and PHONE not in reg and NOKEY not in reg, sorted(reg))
pres = D.present_at_epoch(E6D)
check("...and the reconstruction says the same", pres == set(reg), (sorted(pres), sorted(reg)))
check("at 7 days the PC lapses too", PC not in get_open_registry(G + 1 + 1680) and PC not in D.present_at_epoch(G + 1 + 1680))
check("one hour after the recert everyone is present", D.present_at_epoch(G + 2) >= {PC, PHONE, NOKEY} and set(get_open_registry(G + 2)) >= {PC, PHONE, NOKEY})

# ---------------------------------------------------------------- continuity by the previous grant; gap-proportional ramp
fid = lambda a: int((kv_ops.get_account(a) or {}).get("fidelity", 0))
f0 = fid(PC)
apply_register(PC, G + 1 + 1400, logger)                     # a statement-free/signature renewal 5.8 days later: continuous
check("a 5.8-day gap under a 7-day grant is continuous and earns 1400 // 192 = 7", fid(PC) - f0 == 7 * P.FIDELITY_GAIN, fid(PC) - f0)
f1 = fid(PHONE)
apply_register(PHONE, G + 1 + 1400, logger, device_key=ANDKEY)   # the same gap under a 36-hour grant: a lapse
check("the same gap under a 36-hour grant is a lapse (halved, floor GAIN)", fid(PHONE) == max(P.FIDELITY_GAIN, f1 // 2), (f1, fid(PHONE)))
f2 = fid(PHONE)
apply_register(PHONE, G + 1 + 1400 + 300, logger, device_key=ANDKEY)   # 30 h later: continuous, one step
check("a 30-hour renewal on the phone earns exactly 1, as before", fid(PHONE) - f2 == P.FIDELITY_GAIN, fid(PHONE) - f2)
check("the ramp at the gate pays 8 for a full week and 1 for 36 hours",
      P.fidelity_step(0, True, 1680, G) == 8 * P.FIDELITY_GAIN and P.fidelity_step(0, True, 360, G) == P.FIDELITY_GAIN)
check("...and a caller with no epoch still gets the historical rule (a week paid 1)", P.fidelity_step(0, True, 1680, None) == P.FIDELITY_GAIN)
check("...a gap below the minimum still earns nothing", P.fidelity_step(5, True, 100, G) == 5)
for a in (PC, PHONE):
    live, replay = fid(a), D.fidelity_at_epoch(a, G + 1 + 1400 + 300)
    check(f"the replay reconstructs the live fidelity across the gate rule ({a[:1]}…)", live == replay, (live, replay))

# ---------------------------------------------------------------- revert: grant, devkey, devcred restored exactly
raw_before = {k: kv_ops.devbind_get(k) for k in (TPMKEY, ANDKEY)}
acc_before = dict(kv_ops.get_account(PC) or {})
E9 = G + 1 + 1400 + 400
apply_register(PC, E9, logger, device_key=TPMKEY, cred_pub="a5" + "ff" * 12)
check("a new statement overwrites the credential", (kv_ops.get_account(PC) or {}).get("devcred") == "a5" + "ff" * 12)
apply_register(PC, E9, logger, revert=True)
acc_after = dict(kv_ops.get_account(PC) or {})
check("reverting it restores devkey, devcred and fidelity exactly and removes its grant",
      acc_after == acc_before and kv_ops.lease_grant_get(PC, E9) is None and kv_ops.recert_latest(PC) < E9, (acc_before, acc_after))
apply_register(NOKEY, E9, logger)
apply_register(NOKEY, E9, logger, revert=True)
check("a statement-free recert's revert leaves no grant behind", kv_ops.lease_grant_get(NOKEY, E9) is None)

# ---------------------------------------------------------------- lookback / retention widen without a cliff
check("retention is the widened horizon at every epoch and exceeds the saturation bound",
      P.recert_history_epochs(G) == P.RECERT_HISTORY_EPOCHS_V2 > (P.FIDELITY_CAP + 1) * P.LEASE_EPOCHS_MAX
      and P.recert_history_epochs(None) == P.RECERT_HISTORY_EPOCHS)
old = (P.FIDELITY_CAP + 1) * P.POSW_LEASE_EPOCHS
check("the lookback at the gate equals the old bound (no epoch is refused the day the leases lengthen)", P.saturation_lookback_at(G) == old)
check("...and reaches the 7-day bound only once that much history can exist", P.saturation_lookback_at(G + 100_000) == (P.FIDELITY_CAP + 1) * P.LEASE_EPOCHS_MAX
      and P.saturation_lookback_at(G + 1000) == old + 1000)

# ---------------------------------------------------------------- wiring
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
to = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
ao = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
check("validation judges an assertion before the statement / statement-free split",
      to.index("if is_assert_device(transaction.get(\"device\")):") < to.index("elif stmt_free:"))
check("apply derives the credential from the tx bytes and passes it to apply_register", "cred_pub = credential_public_key(transaction.get(\"device\") or {})" in ao and "cred_pub=cred_pub" in ao)
check("an assertion occupies no device key in a block", "not is_assert_device(tx.get(\"device\"))" in to)
check("the GC horizon is gated", "recert_history_epochs(epoch)" in open(os.path.join(ROOT, "ops", "gc_ops.py")).read())

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
