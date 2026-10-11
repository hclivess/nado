"""A Stwo wallet credits one note per nullifier (static/interface.js shieldDuplicateNote; review 2026-10-11, "faerie gold").

The Stwo circuit leaves an output's rho free and nf = H(nsk, rho) does not depend on the note's position, so a sender can
pay two notes to one owner with the SAME rho (different values, so different cms that both enter the pool). Only one can
ever be spent: the second spend's nullifier is already in the set. A merchant who banked both would credit a payment it
can never collect. The wallet therefore counts received notes by nullifier:

  1. a received note whose rho (so nullifier) this wallet already holds is a duplicate, whatever its value or cm,
     and whether the held note is spent or not;
  2. a note with a fresh rho is not;
  3. the nullifier the wallet compares is the node's (execnode/shielded_stwo.nullifier), so the pool would indeed
     refuse the second spend;
  4. the receive path (doReceiveShielded, which every claim route reaches) asks before banking a Stwo note, and the
     refusal is translated.

Run: python3 tests/test_a_stwo_wallet_credits_one_note_per_nullifier.py
"""
import os, sys, tempfile, json, subprocess, re, hashlib
_T = tempfile.mkdtemp(prefix="nado-test-stwo-one-nf-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode import shielded_stwo as SP

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)

SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
m = re.search(r"function shieldDuplicateNote\(notes, rho, nskStwo, nullifierOf\) \{.*?\n\}", SRC, re.S)
check("the wallet defines shieldDuplicateNote", bool(m))
if not m:
    sys.exit(1)

NSK = hashlib.blake2b(b"wallet-nsk", digest_size=32).hexdigest()
held = [{"value": "500", "rho": "77", "cm": "aa" * 32, "spent": False},
        {"value": "900", "rho": "12345678901234", "cm": "bb" * 32, "spent": True}]
probe = r"""
import * as S from %s;
const dup = (function () { %s; return shieldDuplicateNote; })();
const [notes, nsk] = JSON.parse(process.argv[1]);
console.log(JSON.stringify({
  sameRhoUnspent: dup(notes, "77", nsk, S.nullifier),
  sameRhoSpent: dup(notes, "12345678901234", nsk, S.nullifier),
  freshRho: dup(notes, "78", nsk, S.nullifier),
  empty: dup([], "77", nsk, S.nullifier),
  nf77: S.nullifier(nsk, 77n),
}));
""" % (json.dumps("file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js")), m.group(0))
r = subprocess.run(["node", "--input-type=module", "-e", probe, json.dumps([held, NSK])], capture_output=True, text=True,
                   timeout=120)
if r.returncode != 0:
    print("FAIL  the probe runs in Node", r.stderr[-1500:]); sys.exit(1)
js = json.loads(r.stdout)

check("1. a note with a held unspent note's rho is a duplicate (any value, any cm)", js["sameRhoUnspent"] is True)
check("...and with a spent one's", js["sameRhoSpent"] is True)
check("2. a fresh rho is not a duplicate", js["freshRho"] is False and js["empty"] is False)
check("3. the nullifier the wallet compares is the node's", js["nf77"] == SP.nullifier(NSK, 77))
o = SP.owner_of(NSK)
check("...and two notes with one rho and different values are two commitments with ONE nullifier",
      SP.commit(500, o, 77) != SP.commit(501, o, 77))

body = SRC[SRC.index("async function doReceiveShielded"):]
body = body[:body.index("\nasync function ", 10)]
i_dup, i_push = body.find("shieldDuplicateNote("), body.find("notes.push(")
check("4. the receive path asks before it banks the note", 0 < i_dup < i_push, (i_dup, i_push))
check("...only for the Stwo pool, with the wallet's own Stwo key and the real nullifier",
      "shieldStwo() && shieldDuplicateNote(notes, rho, shieldNskStwo(), _stwo.nullifier)" in body)
check("...and the refusal is a translated string", 'i18("shield.stwoSameNf"' in body)

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
