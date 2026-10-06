"""Referrals (protocol.py "REFERRALS", gate REFERRAL_HEIGHT): the referrer earns a slice of the NEWCOMER'S OWN dividend
weight, never a bonus from the pool — so a farm that refers itself gains nothing.

Pins, through the real apply path (reflect_transaction on a register, with only the certificate parser stubbed to give
each fake device a fixed key):
  * the link is written only on a FIRST attested registration — not before the gate, not on a renewal, not for a
    device already bound to another identity (a move is not a newcomer), never twice — and is immutable;
  * the link's revert is exact: the rollback of the block that wrote it deletes it, and nothing else does;
  * register data: from the gate "" or exactly {"referrer": <keyed address, not the sender>}; before it, untouched;
then on the weights (dividend_ops.referral_split, the one function every weight consumer uses):
  * before the gate's epoch the weights are byte-for-byte what they were;
  * from it every weight is scaled by REFERRAL_SCALE and the total is exactly SCALE x the old total;
  * an identity outside any referral keeps exactly its share;
  * a FARM RING (each identity refers the next) moves nothing out of or into the ring as a whole, and with equal
    weights every member ends exactly where it started;
  * an absent referrer earns nothing (the newcomer keeps it all); the window closes after REFERRAL_EPOCHS; a link made
    after an epoch never changes that epoch; a chain pays one level per link, never compounding.

Run: python3 tests/test_referral_slice_is_farm_neutral.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_referral_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("referral"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from ops import kv_ops
from ops import device_attest as DA
from ops.account_ops import create_account, reflect_transaction
from ops.transaction_ops import validate_register_referrer
from ops.dividend_ops import referral_split
from signatures import generate_keydict

GATE = 6000                                   # block 6000 = epoch 100
P.REFERRAL_HEIGHT = GATE
E0 = GATE // P.EPOCH_LENGTH                    # the gate's epoch
SCALE, SHARE, WIN = P.REFERRAL_SCALE, P.REFERRAL_SHARE, P.REFERRAL_EPOCHS

# the certificate parser, stubbed: a fake statement {"k": <device key>} binds to that key (the real parse is pinned by
# tests/test_device_binding.py; this test is about what happens AROUND the binding)
DA.device_binding_key = lambda dev, *_a, **_k: dev["k"]
DA.credential_public_key = lambda dev: None

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def addr():
    a = generate_keydict()["address"]
    create_account(a, balance=0)
    return a


def register(sender, height, device=None, referrer=None, revert=False):
    tx = {"sender": sender, "recipient": "register", "amount": 0, "fee": 0, "txid": f"reg-{sender[:8]}-{height}",
          "max_block": height, "data": {"referrer": referrer} if referrer else "",
          "device": {"k": device} if device else None}
    if device is None:
        tx.pop("device")
    reflect_transaction(tx, logger, block_height=height, revert=revert)


REF = addr()


def t_first_registration_links():
    a = addr()
    register(a, GATE + 60, device="webauthn:dev-a", referrer=REF)
    assert kv_ops.referral_get(a) == (REF, GATE + 60), kv_ops.referral_get(a)
    # renewal naming someone else: accepted, writes nothing, the link is immutable
    other = addr()
    register(a, GATE + 60 * 300, device="webauthn:dev-a", referrer=other)
    assert kv_ops.referral_get(a) == (REF, GATE + 60), "a renewal never rewrites the link"
    # rolling back the RENEWAL leaves the link; rolling back the FIRST registration removes it
    register(a, GATE + 60 * 300, device="webauthn:dev-a", referrer=other, revert=True)
    assert kv_ops.referral_get(a) == (REF, GATE + 60), "rolling back a renewal leaves the link"
    register(a, GATE + 60, device="webauthn:dev-a", referrer=REF, revert=True)
    assert kv_ops.referral_get(a) is None, "rolling back the first registration deletes the link exactly"
    assert kv_ops.referral_get(a) is None and kv_ops.recert_latest(a) < 0


def t_no_link_before_gate_or_without_device_or_on_a_moved_device():
    b = addr()
    register(b, GATE - 60, device="webauthn:dev-b", referrer=REF)
    assert kv_ops.referral_get(b) is None, "no link before the gate"
    c = addr()
    register(c, GATE + 120, device="webauthn:dev-c")
    d = addr()                                                       # dev-c MOVES to d: a move, not a newcomer
    register(d, GATE + 180, device="webauthn:dev-c", referrer=REF)
    assert kv_ops.referral_get(d) is None, "a device already bound elsewhere does not make a newcomer"
    e = addr()
    kv_ops.account_set_field(e, "devkey", "webauthn:older")          # stamped by an earlier statement
    register(e, GATE + 240, device="webauthn:dev-e", referrer=REF)
    assert kv_ops.referral_get(e) is None, "an account that already carries a device stamp is not new"
    f = addr()
    register(f, GATE + 300, device="webauthn:dev-f")                 # no referrer named
    assert kv_ops.referral_get(f) is None


def t_register_data_shape():
    s = generate_keydict()["address"]
    ok = lambda d, h=GATE: validate_register_referrer({"sender": s, "data": d}, h)
    ok(""); ok({"referrer": REF})
    ok({"anything": [1, 2]}, GATE - 1)                               # before the gate: untouched
    for bad, why in (({"referrer": s}, "cannot name itself"), ({"referrer": "nope"}, "keyed address"),
                     ({"referrer": REF, "x": 1}, "must be"), ("junk", "must be"), ({"referrer": "bond"}, "keyed address")):
        try:
            ok(bad); raise RuntimeError(f"accepted {bad}")
        except AssertionError as e:
            assert why in str(e), (bad, str(e))


def link(newcomer, referrer, epoch):
    kv_ops.referral_set(newcomer, referrer, epoch * P.EPOCH_LENGTH + 5)


def t_split_rules():
    A, B, C, X, Y, Z = (f"w{i}" for i in "ABCXYZ")
    base = {A: 15, B: 9, C: 4, X: 7}
    assert referral_split(dict(base), E0 - 1) == base, "before the gate's epoch the weights are untouched"
    assert referral_split(dict(base), E0) == {k: SCALE * v for k, v in base.items()}, "no links: scaled only"
    # farm ring A <- B <- C <- A
    link(B, A, E0); link(C, B, E0); link(A, C, E0)
    out = referral_split(dict(base), E0 + 1)
    assert sum(out.values()) == SCALE * sum(base.values()), "the total is exactly SCALE x the old total"
    assert out[X] == SCALE * base[X], "an identity outside every referral keeps exactly its share"
    assert out[A] + out[B] + out[C] == SCALE * (base[A] + base[B] + base[C]), "the ring as a whole gains nothing"
    assert out[B] == SCALE * 9 - SHARE * 9 + SHARE * 4 and out[A] == SCALE * 15 - SHARE * 15 + SHARE * 9
    eq = referral_split({A: 10, B: 10, C: 10, X: 10}, E0 + 1)
    assert eq == {A: 100, B: 100, C: 100, X: 100}, f"an equal-weight ring nets exactly zero for every member: {eq}"
    # absent referrer: Y named Z, Z is not in the set this epoch
    link(Y, Z, E0)
    o2 = referral_split({Y: 12, X: 7}, E0 + 1)
    assert o2[Y] == SCALE * 12, "an absent referrer earns nothing; the newcomer keeps it all"
    o3 = referral_split({Y: 12, Z: 3}, E0 + 1)
    assert o3[Z] == SCALE * 3 + SHARE * 12 and o3[Y] == (SCALE - SHARE) * 12, "a present referrer earns its slice"
    # the window
    assert referral_split({Y: 12, Z: 3}, E0 + WIN - 1)[Z] == SCALE * 3 + SHARE * 12, "last epoch of the window pays"
    assert referral_split({Y: 12, Z: 3}, E0 + WIN)[Z] == SCALE * 3, "the window closes after REFERRAL_EPOCHS"
    # a link made AFTER an epoch never changes that epoch (a past epoch reconstructs identically)
    N, R = "wN", "wR"
    link(N, R, E0 + 50)
    assert referral_split({N: 8, R: 8}, E0 + 49) == {N: 80, R: 80}, "a later link never reaches back into an earlier epoch"
    assert referral_split({N: 8, R: 8}, E0 + 50) == {N: 72, R: 88}


def t_one_function_everywhere():
    d = open(os.path.join(ROOT, "ops", "dividend_ops.py")).read()
    n = open(os.path.join(ROOT, "nado.py")).read()
    wa = d[d.index("def weights_at_epoch"):d.index("def referral_split")]
    assert "return referral_split(out, epoch)" in wa, "the committed weights and the exec accrual go through the split"
    live = n[n.index("async def get_open_weights"):n.index("async def duty_committee")]
    assert "referral_split(weights, epoch)" in live, "the live /get_open_weights cuts the same way"


def t_link_rows_are_not_devices():
    kv_ops.referral_set("wQ", "wP", 7)
    assert all(not k.startswith("referral:") for k, *_ in kv_ops.devbind_rows()), "a link is never read as a device binding"
    assert ("wQ", 7) in kv_ops.referrals_by("wP")


for name, fn in [("the link is written on the first attested registration only, immutable, reverted exactly",
                  t_first_registration_links),
                 ("no link before the gate, for a moved device, or an already-stamped account", t_no_link_before_gate_or_without_device_or_on_a_moved_device),
                 ("register data is \"\" or exactly {referrer: <other keyed address>} from the gate", t_register_data_shape),
                 ("the split: scaled, total-preserving, farm-ring neutral, windowed, one level", t_split_rules),
                 ("one split function feeds every weight consumer", t_one_function_everywhere),
                 ("a referral row is never mistaken for a device binding", t_link_rows_are_not_devices)]:
    check(name, fn)
print("ALL PASS — a referral moves the newcomer's own weight and nothing else" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
