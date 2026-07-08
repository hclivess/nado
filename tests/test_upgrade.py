"""Contract upgrade op (alphanet): deployer replaces code, storage + cid preserved, others rejected."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import contract_lib as C
FAIL=[]
def check(n,c): print(("  ok  " if c else " FAIL ")+n); FAIL.append(n) if not c else None
s=ExecState(tempfile.mktemp(prefix="nado_up_",suffix=".json"))
DEP="ndoDEPLOYER00000000000000000000000000000000000000"
s.apply_blob({"op":"deploy","code":C.COUNTER,"nonce":"n1"}, DEP, "t1")
cid=s.contract_id(DEP, C.COUNTER, "n1")
s.apply_blob({"op":"call","contract":cid,"method":"inc","args":[]}, "ndoX", "t2")
before=dict(s.contracts[cid]["storage"])
check("counter deployed + has storage", bool(before))
r=s.apply_blob({"op":"upgrade","contract":cid,"code":C.TIP_JAR,"abi":C.ABIS["tip_jar"]}, DEP, "t3")
check("deployer upgrade ok", r.startswith("upgrade"))
check("storage preserved across upgrade", s.contracts[cid]["storage"]==before)
check("code replaced (tip_jar methods now, counter gone)", "add" in s.contracts[cid]["code"] and "inc" not in s.contracts[cid]["code"])
check("abi updated", "add" in (s.contracts[cid]["abi"] or {}))
r2=s.apply_blob({"op":"upgrade","contract":cid,"code":C.COUNTER}, "ndoATTACKER0000000000000000000000000000000000000", "t4")
check("non-deployer rejected", r2.startswith("skip") and "add" in s.contracts[cid]["code"])
check("unknown contract rejected", s.apply_blob({"op":"upgrade","contract":"nope","code":C.COUNTER}, DEP,"t5").startswith("skip"))
check("bad code rejected", s.apply_blob({"op":"upgrade","contract":cid,"code":{"add":[["NOTANOP"]]}}, DEP,"t6").startswith("skip"))
print("\n"+("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
sys.exit(1 if FAIL else 0)
