"""A STWO SPEND NAMES EVERY DIGEST IN ONE SPELLING, AND A REFUSED SPEND MOVES NOTHING (execnode/state.py
_apply_stwo_transfer / _apply_stwo_shield, execnode/shielded_stwo.is_digest, execnode/stark/stwo_js_native._digest).

Review 2026-10-11, reproduced through the real binding: bytes.fromhex skips whitespace, so `nf[:62] + "  "` passed the
binding's `len == 64` check as 31 bytes, the native verifier read a 32nd byte past it (the bytes object's NUL), and the
SAME proof verified for the canonical nullifier and for each whitespace spelling of it whenever the real one ends in
0x00 — while the exec layer's spent set, keyed by the string, saw a new nullifier each time: one note, many spends.
A whitespace output commitment got through the verifier too, and then raised in the pool's append AFTER the nullifier
was spent — a half-applied transfer that apply_blob's catch-all reported as a skip. Pins (no native library needed:
every refusal here happens before the verifier, and the library path points nowhere to prove it):
  1. the binding decodes a digest only in its canonical spelling, to exactly 32 bytes;
  2. the pool stores, spends and appends canonical digests only;
  3. every non-canonical spelling of root / nf / cm_out1 / cm_out2 (whitespace, upper case, short), a non-hex proof,
     and a non-integer unshield or fee is refused BEFORE the verifier, and the state is byte-identical afterwards;
  4. a whitespace spelling of an already-spent nullifier ending in 0x00 is refused, not counted as new;
  5. a duplicate output is refused before the verifier, and a spend that reaches the verifier is all-or-nothing
     (the verifier is the last check; with it unavailable, nothing has moved);
  6. a deposit with a non-canonical owner is refused and moves nothing.

Run: python3 tests/test_a_stwo_spend_names_digests_in_one_spelling_and_a_refused_one_moves_nothing.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-spelling-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_STWO_JS_LIB"] = os.path.join(os.environ["HOME"], "no-such-libnado_stwo_js.so")
import sys, copy, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from execnode.stark import stwo_js_native as SJ
from execnode.stark.native_guard import NativeMissing

import _harness
_report = _harness.Report()
check = _report.check


NF = "ab" * 31 + "00"                                     # a nullifier whose last byte is 0x00: the aliasable kind
ALIASES = [NF[:62] + "  ", " " + NF[:62] + "\t", NF[:30] + " " + NF[30:62] + "\n", NF.upper()]

# 1. the binding
check("1. the binding decodes a canonical digest to 32 bytes", SJ._digest(NF) == bytes.fromhex(NF))
check("...and refuses every other spelling (whitespace, upper case) instead of decoding it short",
      all(SJ._digest(a) is None for a in ALIASES), [SJ._digest(a) for a in ALIASES])
check("...a whitespace spelling is exactly the 31-byte decode that used to reach the C side",
      all(len(bytes.fromhex(a)) == 31 for a in ALIASES[:3]))

# 2. the pool
pool = SP.StwoShieldedPool()
for bad in ALIASES:
    for f in (pool.spend, pool.append):
        try:
            f(bad)
            check(f"2. the pool refuses {f.__name__}({bad!r})", False)
        except ValueError:
            pass
check("2. the pool stores, spends and appends canonical digests only", not pool.commitments and not pool.nullifiers)

GATE = 700
P.STWO_POOL_HEIGHT = GATE


def gate_state():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = GATE - 1
    owner = SP.owner_of("11" * 32)
    for i in range(3):
        r = st.apply_field_shield(1000 + i, owner, i)
        assert "stwo note" in r, r
    return st


def bundle(st, **over):
    js = {"proof": "00" * 8, "root": st.stwo_pool.root(), "nf": NF, "cm_out1": "c1" * 32, "cm_out2": "c2" * 32,
          "unshield": 0, "fee": 0}
    js.update(over)
    return {"stark": {"stwo_js": js}}


def refused_before_verifier(st, b, want):
    before = copy.deepcopy(st._snapshot())
    try:
        r = st.apply_field_transfer(copy.deepcopy(b))
    except NativeMissing as e:                            # reaching the verifier IS the failure here
        return False, f"reached the verifier: {e}"
    return (r.startswith("skip") and want in r and st._snapshot() == before), r


st = gate_state()
cases = []
for k in ("root", "nf", "cm_out1", "cm_out2"):
    canon = bundle(st)["stark"]["stwo_js"][k]
    for a in (canon[:62] + "  ", canon.upper() if canon.upper() != canon else "AB" * 32, canon[:62], " " + canon[:63]):
        cases.append((f"{k}={a!r}", bundle(st, **{k: a}), "64 lowercase hex"))
cases += [("proof with whitespace", bundle(st, proof="00 " * 4 + "0"), "lowercase hex"),
          ("proof upper case", bundle(st, proof="AB" * 8), "lowercase hex"),
          ("fee as a float", bundle(st, fee=1.0), "integers"),
          ("fee as a bool", bundle(st, fee=True), "integers"),
          ("fee in non-ASCII digits", bundle(st, fee="١٢"), "integers"),
          ("unshield as a float string", bundle(st, unshield="5.0"), "integers")]
for name, b, want in cases:
    ok, r = refused_before_verifier(st, b, want)
    check(f"3. refused before the verifier, state byte-identical: {name}", ok, r)

# 4. an already-spent nullifier in another spelling
st = gate_state()
st.stwo_pool.spend(NF)
for a in ALIASES:
    ok, r = refused_before_verifier(st, bundle(st, nf=a), "64 lowercase hex")
    check(f"4. a second spelling of a SPENT nullifier is refused, not counted as new: {a!r}", ok, r)
ok, r = refused_before_verifier(st, bundle(st), "double-spend")
check("...and the canonical one is a double-spend, refused before the verifier", ok, r)
check("...the spent set still holds exactly one entry", st.stwo_pool.nullifiers == {NF}, st.stwo_pool.nullifiers)

# 5. all-or-nothing
st = gate_state()
existing = st.stwo_pool.commitments[0]
for name, b in (("cm_out1 already in the pool", bundle(st, cm_out1=existing)),
                ("cm_out2 already in the pool", bundle(st, cm_out2=existing)),
                ("cm_out1 == cm_out2", bundle(st, cm_out2="c1" * 32))):
    ok, r = refused_before_verifier(st, b, "duplicate")
    check(f"5. {name}: refused before the verifier, nothing moved", ok, r)
before = copy.deepcopy(st._snapshot())
try:
    st.apply_field_transfer(copy.deepcopy(bundle(st)))
    check("5. a well-formed spend reaches the verifier (unavailable here) as its LAST check", False, "no NativeMissing")
except NativeMissing:
    check("5. a well-formed spend reaches the verifier last, and with it unavailable NOTHING has moved",
          st._snapshot() == before)
blob = {"op": "field_transfer", "bundle_json": json.dumps(bundle(st, nf=NF[:62] + "  "))}
r = st.apply_blob(blob, "ndoA" + "a" * 44, "t1")
check("...and through apply_blob a whitespace nullifier is a skip that names the spelling, state unchanged",
      "64 lowercase hex" in r and st._snapshot() == before, r)

# 6. deposits
st = gate_state()
before = copy.deepcopy(st._snapshot())
for bad in (SP.owner_of("22" * 32).upper(), SP.owner_of("22" * 32)[:62] + "  "):
    r = st.apply_field_shield(5, bad, 9)
    check(f"6. a deposit to a non-canonical owner {bad[-4:]!r} is refused and moves nothing",
          r.startswith("skip") and st._snapshot() == before, r)

print("ALL PASS — a Stwo spend names its digests in one spelling, and a refused one moves nothing" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
