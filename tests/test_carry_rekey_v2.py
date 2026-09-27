"""The gen-28 carry moves every account to its format-2 address, and every owner finds their coins with nothing to do.

WHY. Format 2 (protocol.ADDRESS_FORMAT) hashes the whole public key into the address, so every address changes at the
reroll ("they will change so what"). The operator's requirement: "they wont just derive the new address from the
private keys????" — "we need this to be fucking smooth". The wallet derives the new address from the key it already
holds, so the carry must put each balance at exactly that address. It can only do so for accounts whose key some chain
recorded: 871 of 1,240 gen-27 accounts had never sent on gen 27, and 535 of them (674 NADO) had sent on an older
generation — tools/recover_keys.py reads those keys out of the old backups.

Pins (tools/rekey_v2.py, tools/recover_keys.py, tools/alphanet6_carryforward.py):
  1. a keyed account lands at the format-2 address of its key, which a format-2 chain accepts;
  2. a keyless account whose key an older generation recorded re-keys the same way, and its key is carried;
  3. a "recovered" key that does not derive the account's address is ignored — never trusted;
  4. a keyless account nobody can re-key stays at its old address (rejected by shape on format 2), bond released;
  5. supply is conserved exactly; reserved accounts are untouched; a funded multisig is refused;
  6. device bindings, aliases, auth histories, the present set and the relay seeds move with their account, and a
     reference to an account that cannot be re-keyed refuses the carry instead of pointing at a dead address;
  7. recover_keys refuses the running node's own database, and drops an address two generations disagree on;
  8. the carry refuses a format-2 carry without --known-keys, so the recovery step cannot be forgotten.

Run: python3 tests/test_carry_rekey_v2.py
"""
import json, os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-rekey-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops import address_ops as A
from signatures import generate_keydict
from tools.rekey_v2 import rekey, v2_address
from tools import recover_keys as RK

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def refuses(fn):
    try:
        fn()
    except SystemExit:
        return True
    return False


K = [generate_keydict()["public_key"] for _ in range(5)]
keyed, recov, liar, lost, bonded_lost = (A.legacy_address(k) for k in K)
alloc = [
    {"address": keyed, "balance": 100, "bonded": 50, "public_key": K[0], "fidelity": 7},
    {"address": recov, "balance": 200, "bonded": 0},
    {"address": liar, "balance": 300, "bonded": 0},
    {"address": lost, "balance": 400, "bonded": 0},
    {"address": bonded_lost, "balance": 1, "bonded": 60},
    {"address": "treasury", "balance": 1000, "bonded": 0},
]
known = {recov: K[1], liar: K[0]}                      # the liar's "recovered" key derives someone else's address
extra = {"devbind": [["dk1", keyed, "tpm"], ["dk2", recov, "webauthn"]], "aliases": [["alice", recov]],
         "auth_history": [[keyed, 1, ["k"]]], "present": [recov, keyed]}
seeds = [keyed]
out, x, s2, rep = rekey(alloc, extra, seeds, known)
by = {r["address"]: r for r in out}

# 1
check("a keyed account lands at the format-2 address of its key", v2_address(K[0]) in by
      and by[v2_address(K[0])]["balance"] == 100 and by[v2_address(K[0])]["bonded"] == 50
      and by[v2_address(K[0])]["fidelity"] == 7, by.get(v2_address(K[0])))
_saved = (P.ADDRESS_FORMAT, P.ADDRESS_CHECKSUM, P.ADDRESS_LENGTH)
try:
    P.ADDRESS_FORMAT, P.ADDRESS_CHECKSUM, P.ADDRESS_LENGTH = 2, 4, len(P.ADDRESS_PREFIX) + P.ADDRESS_BODY + 8
    check("...which is exactly what the owner's key derives on a format-2 chain",
          A.make_address(K[0]) == v2_address(K[0]) and A.validate_address(v2_address(K[0])))
    check("an account that cannot be re-keyed is rejected by shape on format 2", not A.validate_address(lost))
finally:
    P.ADDRESS_FORMAT, P.ADDRESS_CHECKSUM, P.ADDRESS_LENGTH = _saved
check("the old address is gone for a re-keyed account", keyed not in by)
# 2
check("a keyless account with a key from an older generation re-keys too",
      v2_address(K[1]) in by and by[v2_address(K[1])]["balance"] == 200 and recov not in by)
check("...and carries that key, so address-key binding holds from block 1",
      by.get(v2_address(K[1]), {}).get("public_key") == K[1])
check("...and the report counts it", rep["recovered_from_older_generations"] == 1, rep)
# 3
check("a recovered key that does not derive the account's address is ignored",
      liar in by and not by[liar].get("public_key") and by[liar]["balance"] == 300)
# 4
check("an account no chain saw the key of stays at its old address", lost in by and by[lost]["balance"] == 400)
check("...and its bond is released into its balance", by[bonded_lost]["bonded"] == 0 and by[bonded_lost]["balance"] == 61)
check("...and the report counts them", rep["keyless_kept_at_old_address"] == 3 and rep["bond_released_raw"] == 60, rep)
# 5
tot = lambda rows: sum(int(r["balance"]) + int(r["bonded"]) for r in rows)
check("supply is conserved exactly", tot(out) == tot(alloc), (tot(out), tot(alloc)))
check("reserved accounts are untouched", by.get("treasury", {}).get("balance") == 1000)
check("a funded multisig refuses the carry",
      refuses(lambda: rekey([{"address": P.MSIG_PREFIX + "ab" * 21, "balance": 5, "bonded": 0}], {}, [])))
check("an empty multisig row is simply dropped",
      rekey([{"address": P.MSIG_PREFIX + "ab" * 21, "balance": 0, "bonded": 0}], {}, [])[0] == [])
# 6
check("device bindings follow their account", x["devbind"] == sorted([["dk1", v2_address(K[0]), "tpm"],
                                                                      ["dk2", v2_address(K[1]), "webauthn"]]), x["devbind"])
check("aliases follow their account", x["aliases"] == [["alice", v2_address(K[1])]], x["aliases"])
check("auth histories follow their account", x["auth_history"] == [[v2_address(K[0]), 1, ["k"]]], x["auth_history"])
check("the present set follows its accounts", x["present"] == sorted([v2_address(K[0]), v2_address(K[1])]), x["present"])
check("relay seeds follow their account", s2 == [v2_address(K[0])], s2)
check("a binding that names an account nobody can re-key refuses the carry",
      refuses(lambda: rekey(alloc, {"devbind": [["dk3", lost, "tpm"]]}, [], known)))
check("so does a seed that names one", refuses(lambda: rekey(alloc, {}, [lost], known)))

# 7 recover_keys over real LMDB tables
import lmdb
from ops import codec


def make_state(path, rows):
    env = lmdb.open(path, max_dbs=8, map_size=1 << 24)
    db = env.open_db(b"accounts")
    with env.begin(write=True, db=db) as t:
        for a, doc in rows.items():
            t.put(a.encode(), codec.pack(doc))
    env.close()


d1, d2 = (os.path.join(os.environ["HOME"], n) for n in ("g25", "g26"))
make_state(d1, {recov: {"balance": 1, "public_key": K[1]}, lost: {"balance": 1, "public_key": K[0]},
                bonded_lost: {"balance": 1, "public_key": K[4]}})
make_state(d2, {bonded_lost: {"balance": 1, "public_key": K[3]}})
got = RK.recover([d1, d2])
check("recover_keys returns the key an older generation recorded", got.get(recov) == K[1], got.keys())
check("...but never a key that does not derive its address", lost not in got)
# K[3] does not derive bonded_lost either, so plant a real conflict: same address, two valid-looking keys is only
# possible for a forged key — build one by copying the first 21 bytes
forged = K[4][:P.ADDRESS_BODY] + ("0" if K[4][P.ADDRESS_BODY] != "0" else "1") + K[4][P.ADDRESS_BODY + 1:]
make_state(d2, {bonded_lost: {"balance": 1, "public_key": forged}})
got = RK.recover([d1, d2])
check("an address two generations recorded different keys for is left out, never guessed", bonded_lost not in got, got.keys())
live = os.path.join(os.environ["HOME"], "nado", "index", "state")
os.makedirs(live)
make_state(live, {})
check("recover_keys refuses the running node's own database", refuses(lambda: RK.recover([live])))

# 8
src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
check("a format-2 carry refuses to run without --known-keys",
      'raise SystemExit("format 2: pass --known-keys' in src and "rekey(alloc, extra, _seeds, _known)" in src)

print("ALL PASS — every owner's coins are at the address their key derives" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
