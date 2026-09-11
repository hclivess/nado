"""AN ATTESTATION KEY CREATED AS A CHILD OF THE ENDORSEMENT KEY, CERTIFYING ITS OWN CREATION.

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the TPM commands work: an endorsement key can parent
an attestation key, and that key can certify its own creation. It was written to support an
architecture that would replace the four-message exchange with a single offline-verifiable message.

THAT ARCHITECTURE IS FORGEABLE AND WAS RETRACTED THE SAME DAY — see
tests/test_certify_creation_is_forgeable.py, which builds a message passing every one of those checks
with no TPM at all. The commands below are genuine; the verification built on them was not. This test
is kept because the command sequence is correct and may be useful, not because the design was.

The binding works because TPMS_CREATION_DATA carries `parentName`, the endorsement key's name is
nameAlg || H(pubArea) and its public area is derivable by any verifier from the vendor certificate plus
the fixed TCG template, and the creation ticket proves the TPM itself produced that creation data. The
child is `restricted`, so it signs only structures the TPM generated.

WHAT THIS DOES NOT PROVE: that an AMD or Intel firmware TPM behaves the same. swtpm accepts templates a
firmware TPM may reject, and the endorsement key being usable as a storage parent is exactly the sort
of thing a constrained fTPM might refuse. Until it runs on real silicon the commit-reveal stays.

Run: python3 tests/test_tpm_certify_creation.py
"""
import os,socket,struct,subprocess,sys,tempfile,time,shutil,hashlib
sys.path.insert(0,'/srv/nado-home/nado')
os.environ.setdefault("HOME", tempfile.mkdtemp())
from ops.tpm_linux import (LinuxTpm, ek_template, aik_template, RH_ENDORSEMENT, ST_SESSIONS,
                           ST_NO_SESSIONS, tpm2b, ALG_RSASSA, ALG_SHA256, _take2b)
from ops.tpm_aik import aik_name, verify_rsassa_sha256, pub_area_rsa

CC_CREATE=0x00000153; CC_LOAD=0x00000157; CC_CERTIFY_CREATION=0x0000014A

class Sim:
    def __init__(s,port): s.sock=socket.create_connection(("127.0.0.1",port),timeout=10)
    def transmit(s,cmd):
        s.sock.sendall(struct.pack(">IBI",8,0,len(cmd))+cmd)
        n=struct.unpack(">I",s._r(4))[0]; r=s._r(n); s._r(4); return r
    def _r(s,n):
        b=b""
        while len(b)<n:
            c=s.sock.recv(n-len(b))
            if not c: raise IOError("closed")
            b+=c
        return b

if not shutil.which("swtpm"):
    print("SKIP  swtpm is not installed")
    sys.exit(0)
_fails=[]
state=tempfile.mkdtemp(); sk=socket.socket(); sk.bind(("127.0.0.1",0)); port=sk.getsockname()[1]; sk.close()
p=subprocess.Popen(["swtpm","socket","--tpm2","--tpmstate",f"dir={state}","--server",f"type=tcp,port={port}",
                    "--ctrl",f"type=tcp,port={port+1}","--flags","startup-clear","--log","level=0"],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
sim=None
for _ in range(100):
    try: sim=Sim(port); break
    except OSError: time.sleep(0.05)
t=LinuxTpm.__new__(LinuxTpm); t.transmit=sim.transmit
def ok(n,c,d=""):
    print(("PASS  " if c else "FAIL  ")+n+("" if c else f": {d}"))
    if not c: _fails.append(n)
try:
    ek_h, ek_pub, ek_nm = t.create_primary(RH_ENDORSEMENT, ek_template())
    ok("endorsement key derives", len(ek_pub)==314)
    ek_name = b"\x00\x0b"+hashlib.sha256(ek_pub).digest()
    ok("EK name is derivable from its public area (so a verifier can recompute it)", ek_name==ek_nm, ek_nm.hex()[:24])

    sess=t.start_policy_session(); t.policy_secret_endorsement(sess)
    auth=(struct.pack(">I",sess)+b"\x00\x00"+b"\x01"+b"\x00\x00")
    params=(tpm2b(tpm2b(b"")+tpm2b(b"")) + tpm2b(aik_template()) + tpm2b(b"") + struct.pack(">I",0))
    r=t._call(ST_SESSIONS, CC_CREATE, struct.pack(">I",ek_h), auth, params, "Create")
    o=4
    priv,o=_take2b(r,o); pub,o=_take2b(r,o); cdata,o=_take2b(r,o); chash,o=_take2b(r,o)
    tk_tag=r[o:o+2]; tk_hier=r[o+2:o+6]; o+=6; tkd,o=_take2b(r,o)
    ticket=tk_tag+tk_hier+tpm2b(tkd)
    ok("TPM2_Create under the ENDORSEMENT KEY as parent", len(pub)>0 and len(priv)>0,
       f"pub {len(pub)} priv {len(priv)}")
    t.flush(sess)

    # parentName lives inside creationData
    q=0; _pcrsel_len=struct.unpack(">I",cdata[0:4])[0]
    q=4+_pcrsel_len*4 if False else 4
    for _ in range(_pcrsel_len):
        sz=cdata[q+2]; q+=3+sz
    pcrdig,q=_take2b(cdata,q); q+=1                      # locality
    parent_name_alg=cdata[q:q+2]; q+=2
    parent_name,q=_take2b(cdata,q)
    ok("creationData names the parent, and it is the EK", parent_name==ek_name,
       f"{parent_name.hex()[:28]} vs {ek_name.hex()[:28]}")

    sess2=t.start_policy_session(); t.policy_secret_endorsement(sess2)
    auth2=(struct.pack(">I",sess2)+b"\x00\x00"+b"\x01"+b"\x00\x00")
    r=t._call(ST_SESSIONS, CC_LOAD, struct.pack(">I",ek_h), auth2, tpm2b(priv)+tpm2b(pub), "Load")
    aik_h=struct.unpack(">I",r[:4])[0]; t.flush(sess2)
    ok("the child key loads", aik_h!=0, hex(aik_h))

    qual=os.urandom(32)
    pw=t._pw_auth()
    r=t._call(ST_SESSIONS, CC_CERTIFY_CREATION, struct.pack(">II",aik_h,aik_h), pw,
              tpm2b(qual)+tpm2b(chash)+struct.pack(">HH",ALG_RSASSA,ALG_SHA256)+ticket, "CertifyCreation")
    o=4; info,o=_take2b(r,o); o+=4; sig,o=_take2b(r,o)
    ok("TPM2_CertifyCreation signs it", len(info)>0 and len(sig)==256, f"info {len(info)} sig {len(sig)}")
    magic=struct.unpack(">I",info[:4])[0]; typ=struct.unpack(">H",info[4:6])[0]
    ok("it is TPM_GENERATED / TPM_ST_ATTEST_CREATION", magic==0xFF544347 and typ==0x801A, hex(typ))
    n,e=pub_area_rsa(pub)
    ok("the signature verifies under the child's own public key", verify_rsassa_sha256(n,e,info,sig))
    ok("the creation hash matches what we certified", chash in info, chash.hex()[:20])
    for h in (aik_h, ek_h): t.flush(h)
    print("\n==> ONE MESSAGE CARRIES: EK cert chain + child pubArea + creationData + certifyInfo + sig")
    print("    verified offline by anyone, with no challengers and no ordering")
finally:
    p.terminate(); p.wait(timeout=10); shutil.rmtree(state,ignore_errors=True)
print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
sys.exit(1 if _fails else 0)
