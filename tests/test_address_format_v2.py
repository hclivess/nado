"""Address format 2: an address commits to the WHOLE public key (protocol.ADDRESS_FORMAT, gen 28).

THE HOLE IT CLOSES. A format-1 address is the first 21 bytes of the public key. An ML-DSA public key begins with rho,
a public seed the key generator chooses, so anyone could build a valid keypair whose first 21 bytes equal any address
and spend from every account that had not yet published its key (audit 2026-09-25; ~817 NADO measured 2026-09-27).

Pins:
  1. on gen 27 nothing changes: format 1, every address byte-identical to before (replay unchanged);
  2. format 2 = checksum(blake2b([DOMAIN_ADDRESS_V2, lowercase key hex], 21 bytes)) — same length and checksum rules,
     so validate_address and every UI keep working; a key's hex case does not change its address;
  3. the property: a key sharing a victim's first 21 bytes derives the victim's FORMAT-1 address (the forgery) but
     not its FORMAT-2 address;
  4. multisig addresses keep format 1 (their body is already a descriptor hash);
  5. the browser derives the identical format-2 address (static/nadotx.js), and every JS copy of ADDR_FORMAT equals
     protocol.ADDRESS_FORMAT — the reroll commit cannot flip one without the others.

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

# 1. the live generation
if P.CHAIN_GENERATION == 27:
    check("gen 27 stays on format 1", P.ADDRESS_FORMAT == 1)
    check("...and make_address is byte-identical to the format-1 derivation", A.make_address(pk) == victim_v1)

# 2 + 3 + 4, under format 2 whatever the live generation
_saved = P.ADDRESS_FORMAT
try:
    P.ADDRESS_FORMAT = 2
    v2 = A.make_address(pk)
    want_body = blake2b_hash([P.DOMAIN_ADDRESS_V2, pk.lower()], size=P.ADDRESS_BODY // 2)
    check("format 2 hashes the whole key", v2[:-4] == P.ADDRESS_PREFIX + want_body, v2)
    check("...keeps the address length and a valid checksum", len(v2) == P.ADDRESS_LENGTH and A.validate_address(v2))
    check("...and one key has one address whatever the hex case", A.make_address(pk.upper()) == v2)
    forger = pk[:P.ADDRESS_BODY] + ("0" if pk[P.ADDRESS_BODY] != "0" else "1") + pk[P.ADDRESS_BODY + 1:]
    check("a key sharing the victim's first 21 bytes derives the victim's FORMAT-1 address (the hole)",
          A.legacy_address(forger) == victim_v1)
    check("...but NOT its FORMAT-2 address", A.make_address(forger) != v2)
    from ops import multisig_ops as M
    members = [generate_keydict()["address"], generate_keydict()["address"]]
    ms2 = M.multisig_address(1, members) if hasattr(M, "multisig_address") else None
    P.ADDRESS_FORMAT = 1
    ms1 = M.multisig_address(1, members) if hasattr(M, "multisig_address") else None
    check("multisig addresses keep format 1 (their body is already a descriptor hash)", ms1 is not None and ms1 == ms2,
          (ms1, ms2))
finally:
    P.ADDRESS_FORMAT = _saved

# 5. the browser agrees, and every JS copy of the format follows protocol
js = {n: open(os.path.join(ROOT, "static", n)).read() for n in ("nadotx.js", "interface.js", "nadodapp.js")}
for n, src in js.items():
    m = re.search(r"(?:export )?const ADDR_FORMAT = (\d+);", src)
    check(f"{n} carries ADDR_FORMAT equal to protocol.ADDRESS_FORMAT", bool(m) and int(m.group(1)) == P.ADDRESS_FORMAT,
          m and m.group(1))
node = shutil.which("node")
if node:
    probe = f"""
import * as T from '{os.path.join(ROOT, "static", "nadotx.js")}';
if (T.bind) {{}}
const pk = {pk!r};
console.log(T.blake2bHash([T.DOMAIN_ADDRESS_V2, pk.toLowerCase()], 21));
"""
    f = os.path.join(os.environ["HOME"], "probe.mjs"); open(f, "w").write(probe)
    r = subprocess.run([node, f], capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = (r.stdout.strip().splitlines() or [""])[-1]
    check("the browser's format-2 body is byte-identical to the node's",
          out == blake2b_hash([P.DOMAIN_ADDRESS_V2, pk.lower()], size=21), (out, r.stderr[-300:]))

print("ALL PASS — an address commits to the whole key" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
