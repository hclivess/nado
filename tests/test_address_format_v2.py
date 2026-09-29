"""Address format 2: an address commits to the WHOLE public key (gen 28; protocol.py "ADDRESS FORMAT 2").

THE HOLE IT CLOSES. A format-1 address is the first 21 bytes of the public key. An ML-DSA public key begins with rho,
a public seed the key generator chooses, so anyone could build a valid keypair whose first 21 bytes equal any address
and spend from every account that had not yet published its key (audit 2026-09-25; ~817 NADO measured 2026-09-27).
Gen 27 ran format 1 behind a generation gate (ADDRESS_FORMAT); the gate was deleted after the betanet-9 reroll and
format 2 is unconditional. The format-1 name of a key survives only as legacy_address, for the legacy claim.

Pins:
  1. the chain runs format 2: a 4-byte checksum, 50 characters, and no format switch left to flip;
  2. format 2 = checksum(blake2b([DOMAIN_ADDRESS_V2, lowercase key hex], 21 bytes)); a key's hex case does not change
     its address; the old format-1 address of a key is no address at all;
  3. the property: a key sharing a victim's first 21 bytes derives the victim's FORMAT-1 address (legacy_address — the
     forgery) but not its FORMAT-2 address;
  4. multisig addresses keep format 1's body rule, byte for byte: MSIG_PREFIX + the descriptor hash's first 42 hex +
     an 8-hex checksum (54 chars), and they validate as senders;
  5. the browser derives the identical address (static/nadotx.js), and no JS copy carries a format switch or a
     46-character address.

Run: python3 tests/test_address_format_v2.py
"""
import os, re, subprocess, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-addrv2-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops import address_ops as A
from hashing import blake2b_hash

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


from signatures import generate_keydict
kd = generate_keydict()
pk = kd["public_key"]
victim_v1 = A.legacy_address(pk)

# 1. the live chain
check("the chain runs format 2: a 4-byte checksum, 50 characters", P.ADDRESS_CHECKSUM == 4 and P.ADDRESS_LENGTH == 50)
check("...and there is no format switch left (ADDRESS_FORMAT deleted after the betanet-9 reroll)",
      not hasattr(P, "ADDRESS_FORMAT"))

# 2. the derivation
v2 = A.make_address(pk)
want_body = blake2b_hash([P.DOMAIN_ADDRESS_V2, pk.lower()], size=P.ADDRESS_BODY // 2)
check("format 2 hashes the whole key", v2 == want_body + blake2b_hash(want_body, size=4), v2)
check("...a 50-character address that validates", len(v2) == 50 and A.validate_address(v2) and A.is_address(v2), v2)
check("...and one key has one address whatever the hex case", A.make_address(pk.upper()) == v2)
check("generate_keydict hands out the format-2 address", kd["address"] == v2, (kd["address"], v2))
check("THE OLD FORMAT IS REJECTED: a key's format-1 address is not an address",
      len(victim_v1) == 46 and not A.validate_address(victim_v1) and not A.is_address(victim_v1), victim_v1)
check("...nor is a format-2 body with a format-1 checksum", not A.validate_address(v2[:-8] + A.make_checksum(v2[:-8], 2)))
check("legacy_address is format 1 exactly: the key's first 42 hex + a 2-byte checksum",
      victim_v1 == pk[:42] + blake2b_hash(pk[:42], size=2))

# 3. the forgery the format closes
forger = pk[:P.ADDRESS_BODY] + ("0" if pk[P.ADDRESS_BODY] != "0" else "1") + pk[P.ADDRESS_BODY + 1:]
check("a key sharing the victim's first 21 bytes derives the victim's FORMAT-1 address (the hole)",
      A.legacy_address(forger) == victim_v1)
check("...but NOT its FORMAT-2 address", A.make_address(forger) != v2)

# 4. multisig: format 1's body rule with the 4-byte checksum — its exact bytes
from ops import multisig_ops as M
members = [generate_keydict()["address"], generate_keydict()["address"]]
vpk = M.multisig_virtual_pubkey(1, members)
ms = M.multisig_address(1, members)
_ms_body = P.MSIG_PREFIX + vpk[:P.ADDRESS_BODY]
check("a multisig address is MSIG_PREFIX + the descriptor hash's first 42 hex + an 8-hex checksum (byte-identical)",
      ms == _ms_body + blake2b_hash(_ms_body, size=4) and len(ms) == len(P.MSIG_PREFIX) + P.ADDRESS_BODY + 8, ms)
# on a format-2 chain a multisig address (msig + 42 + 8 = 54 chars) still VALIDATES as a sender: the exact-length rule
# once admitted only the 50-char key address and refused every M-of-N spend (gen-28 rehearsal)
check("a multisig address validates under the 4-byte checksum (every M-of-N sender)",
      A.validate_address(ms, allow_reserved=False) and not A.is_address(ms), ms)
check("...and a multisig address of the wrong length does not", not A.validate_address(ms[:-2]))

# 5. the browser agrees, and no JS copy carries a format switch
js = {n: open(os.path.join(ROOT, "static", n)).read() for n in ("nadotx.js", "interface.js", "nadodapp.js")}
for n, src in js.items():
    check(f"{n} carries no address-format switch", "ADDR_FORMAT" not in src)
    check(f"{n} carries the 4-byte checksum", re.search(r"(?:export )?const ADDR_CK = 4;", src) is not None)
    check(f"{n} hard-codes no 46-character address", not re.search(r"\{46\}|ADDR_BODY \+ 4\b", src))
check("the wallet's makeAddress hashes every key-derived body (multisig keeps its slice)",
      "const body = prefix + (prefix === ADDR_PREFIX" in js["interface.js"])
check("the games keep their format-2 session key byte-identical (changing it signs every player out)",
      'this.LS_ME = "nado_" + slug + "_me_v2";' in js["nadodapp.js"])
node = shutil.which("node")
if node:
    probe = f"""
import * as T from '{os.path.join(ROOT, "static", "nadotx.js")}';
const pk = {pk!r};
console.log(T.makeAddress(pk) + " " + T.legacyAddress(pk) + " " + T.ADDR_LEN);
"""
    f = os.path.join(os.environ["HOME"], "probe.mjs"); open(f, "w").write(probe)
    r = subprocess.run([node, f], capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = (r.stdout.strip().splitlines() or [""])[-1]
    check("the browser's address, legacy address and length are byte-identical to the node's",
          out == f"{v2} {victim_v1} 50", (out, r.stderr[-300:]))

print("ALL PASS — an address commits to the whole key" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
