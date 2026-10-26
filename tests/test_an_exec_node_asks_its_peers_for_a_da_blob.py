"""An exec node asks its PEERS for a DA blob (execnode/execnode.py _da_sources).

L1's /peers answers {"peers": [...]} (nado.py _dump_handler) — measured on the live relay 2026-10-26 — and _da_sources
iterated that object as if it were the list: its only "peer" was the key "peers", i.e. http://peers:9173. No exec node
ever fetched a DA blob from another node, only from its own store. A DA-carried op — every relayed Stwo spend — was
applied by the node that published it and REFUSED at the DA deadline by every other: an exec-state fork, found by the
gen-29 rehearsal's two-user shielded walk (two exec nodes on root 97aa3b03…, the relaying one on b4a0561e…, and the
settle quorum frozen). The live pool never held a note, so it never fired on the fleet.

Pins, by running the real _da_sources against a stub L1: the object form and a bare list both give every peer's L1 port
(which proxies /da to its exec node), after this node's own exec node; an ip:port peer keeps only its ip; an IPv6 peer
keeps its whole address in brackets (split(":")[0] used to cut 2001:b07:... to "2001").

Run: python3 tests/test_an_exec_node_asks_its_peers_for_a_da_blob.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-dasources-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_L1_URL"] = "http://127.0.0.1:9173"
os.environ["NADO_EXEC_GENESIS"] = os.path.join(os.environ["HOME"], "no_exec_genesis.json")   # not the tree's carried contracts
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import execnode as E

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


class _Resp:
    def __init__(self, body):
        self.status, self._body = 200, body

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, body):
        self.body, self.asked = body, []

    def get(self, url, **kw):
        self.asked.append(url)
        return _Resp(self.body)


def sources(body):
    s = _Session(body)
    return asyncio.run(E._da_sources(s)), s.asked


live_shape = {"peers": ["185.100.232.131", "89.143.197.26:9173", "2001:b07:646c:7473:6e4b:90ff:fea2:7bae"]}
out, asked = sources(live_shape)
own = f"http://127.0.0.1:{E.PORT}"
check("it reads L1's /peers", asked == ["http://127.0.0.1:9173/peers"], asked)
check("its own exec node is asked first", out[:1] == [own], out)
check("every peer of the live {\"peers\": [...]} answer is asked on its L1 port",
      "http://185.100.232.131:9173" in out and "http://89.143.197.26:9173" in out, out)
check("...an IPv6 peer keeps its whole address", "http://[2001:b07:646c:7473:6e4b:90ff:fea2:7bae]:9173" in out, out)
check("...and no source is the object's key", not any("peers" in u for u in out), out)
out2, _ = sources(["185.100.232.131"])
check("a bare list (older L1) still works", out2 == [own, "http://185.100.232.131:9173"], out2)
out3, _ = sources({"error": "x"})
check("an answer with no peers leaves only the node itself", out3 == [own], out3)

print("\nALL PASS — an exec node asks its peers for a DA blob" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
