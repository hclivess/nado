"""The wide shielded pool takes no deposits from WIDE_DEPOSIT_CLOSE_HEIGHT (review 2026-10-11, gate blocker 2).

From STWO_POOL_HEIGHT only a `stwo_js` bundle spends, so a wide note deposited before that gate could never move again.
The wide pool never held a note, so closing its deposits well ahead of the Stwo gate keeps it provably empty:

  1. L1 admits a well-formed wide deposit one block below the close and refuses it at the close (both rule sets);
  2. a Stwo deposit at the Stwo gate is still judged by the Stwo rules (the close sits after that branch);
  3. the live gates keep their order: the Stwo gate is never (0) or above the close;
  4. the wallet reads the close from /protocol.js and stops a wide deposit at tip + 1 >= close with a translated
     reason, but never once the Stwo pool is live.

Run: python3 tests/test_the_wide_pool_takes_no_deposits_after_its_close.py
"""
import os, sys, tempfile, json, re, shutil, subprocess
_T = tempfile.mkdtemp(prefix="nado-test-wide-close-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops.transaction_ops import field_shield_check

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(data, h):
    try:
        field_shield_check(data, h)
        return "admitted"
    except Exception as e:                                             # noqa: BLE001
        return str(e)


WIDE = {"field": True, "owner": "00" * 31 + "01", "rho": "12345"}
STWO = {"field": True, "pool": "stwo", "owner": "ab" * 32, "rho": "7"}
CLOSE = P.WIDE_DEPOSIT_CLOSE_HEIGHT

check("1. a wide deposit one block below the close is admitted", verdict(WIDE, CLOSE - 1) == "admitted",
      verdict(WIDE, CLOSE - 1))
v = verdict(WIDE, CLOSE)
check("...and refused at the close", "takes no new deposits" in v, v)
check("...and after it", "takes no new deposits" in verdict(WIDE, CLOSE + 5000))
_old = P.STWO_POOL_HEIGHT
P.STWO_POOL_HEIGHT = CLOSE + 100
check("2. a Stwo deposit at the Stwo gate is judged by the Stwo rules", verdict(STWO, CLOSE + 100) == "admitted",
      verdict(STWO, CLOSE + 100))
check("...and an untagged deposit there is still the Stwo branch's refusal", "must name pool" in verdict(WIDE, CLOSE + 100))
P.STWO_POOL_HEIGHT = _old
check("3. the Stwo gate is never or above the close", P.STWO_POOL_HEIGHT == 0 or P.STWO_POOL_HEIGHT > CLOSE,
      (P.STWO_POOL_HEIGHT, CLOSE))
check("...and the close reaches clients through /protocol.js", "WIDE_DEPOSIT_CLOSE_HEIGHT" in P.CLIENT_EXPORTS)

SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
check("4. the wallet imports the close from /protocol.js",
      re.search(r"import \{[^}]*WIDE_DEPOSIT_CLOSE_HEIGHT[^}]*\} from \"/protocol\.js\"", SRC) is not None)
# the close is checked where EVERY deposit is built (shieldDeposit: doShield, and a shadow account returning its coins)
body = SRC[SRC.index("async function shieldDeposit("):]
body = body[:body.index("\nasync function ", 10)]
i_closed, i_build = body.find("wideDepositClosed(_shieldTip)"), body.find("noteCommit(")
check("...every deposit stops before it is built", 0 < i_closed < i_build, (i_closed, i_build))
check("...with a translated reason", 'i18("shield.depositsClosed"' in body)
m = re.search(r"function wideDepositClosed\(tip\) \{.*?\n\}", SRC, re.S)
if m and shutil.which("node"):
    probe = """
const out = [];
for (const [stwo, close, tip] of JSON.parse(process.argv[1])) {
  const f = new Function("WIDE_DEPOSIT_CLOSE_HEIGHT", "shieldStwo", %s + "; return wideDepositClosed;")(close, () => stwo);
  out.push(f(tip));
}
console.log(JSON.stringify(out));
""" % json.dumps(m.group(0))
    cases = [[False, 1000, 998], [False, 1000, 999], [False, 1000, 5000], [True, 1000, 5000], [False, 0, 5000]]
    r = subprocess.run(["node", "-e", probe, json.dumps(cases)], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-500:]
    check("...the wallet's rule: open below tip + 1 = close, closed from it, never once Stwo is live, never with no gate",
          got == [False, True, True, False, False], got)
else:
    check("...the wallet defines wideDepositClosed (and node runs it)", False, "missing function or node")

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
