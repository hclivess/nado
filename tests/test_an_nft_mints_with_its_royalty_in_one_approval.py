"""An NFT mints with its royalty in ONE wallet approval (objkt / fxhash: everything configured before the mint).

Before 2026-11-04 a mint was two popups minutes apart. The royalty prompt came only after the asset landed, and only in the
minting tab, so creators missed it (Discord: "an other popup for the royalty follows a few minutes later"). Two NFTs had no
royalty and were invisible on the site. Now the page computes the asset's id before it exists. The `register` call rides
the mint's own confirm as its `then` step (nadodapp signBlob opts.then), and the wallet submits both from that confirm.

Pins:
  1. the page's assetId (lifted from static/nft.js, run in node with the real static/blake2s.js) equals
     execnode/state.asset_id, including the live Nacho1 record;
  2. ORDER-INDEPENDENCE through the real ExecState: `register` applied BEFORE the asset_create it names is accepted, and
     the royalty is then paid on a sale exactly as for register-after-mint. The two transactions may land either way;
  3. the page: mint() passes the register call as `then`, with the computed id, and nothing asks a second time (no
     finishMint / pendingMint / uiConfirm left);
  4. the SDK: opts.then rides the request as `then`, forces the visible confirm and never the hidden frame;
  5. the wallet: the follow-up must be a VALUE-FREE contract call (value / asset / amount / to / spender refused); it is
     shown as a row, never autosigned, never signed in the hidden frame, and submitted only after the first is accepted.

Run: python3 tests/test_an_nft_mints_with_its_royalty_in_one_approval.py
"""
import _harness
HOME = _harness.isolate("nado-test-nft-one-approval-")
import json
import os
import re
import subprocess
import tempfile

from execnode.state import ExecState, asset_id
from execnode.games import nft as N

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rd = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
fails = 0


def check(name, good, detail=""):
    global fails
    print(("PASS  " if good else "FAIL  ") + name + ("" if good else f": {detail}"))
    fails += 0 if good else 1


# ---- 1. the page's asset id == the node's -------------------------------------------------------------------------
nft = rd("static/nft.js")
m = re.search(r"^const ADDR_PERSON = .*?\nfunction assetId\(addr, seed\) \{\n.*?\n\}\n", nft, re.S | re.M)
check("static/nft.js defines assetId", bool(m))
CASES = [("6c29de76c487be78f3af402f892fe80c0eb7d9a9d92093f1ac", 459491175),      # the live Nacho1 record
         ("8989bff323ebf069dd441fb6b858226e4b9e64ecfae1fd2d24", 581609062),
         ("ndoAAAA" + "A" * 41, 1), ("ndoAAAA" + "A" * 41, 4294967295)]
if m:
    d = tempfile.mkdtemp(prefix="nado-assetid-")
    js = os.path.join(d, "t.mjs")
    open(js, "w").write(f'import {{ blake2s, personOf, bytesWord, hashWords }} from {json.dumps("file://" + os.path.join(ROOT, "static/blake2s.js"))};\n'
                        + m.group(0) + f"\nfor (const [a, s] of {json.dumps(CASES)}) console.log(assetId(a, s).toString());\n")
    out = subprocess.run(["node", js], capture_output=True, text=True, timeout=60)
    got = out.stdout.split()
    want = [str(asset_id(a, s)) for a, s in CASES]
    check("the page's assetId equals execnode.state.asset_id on every case", got == want, f"{got} vs {want} {out.stderr[:300]}")
    check("Nacho1's live id is reproduced",
          got[:1] == ["103579237298085460809362190746374487925450207846825330358672677419320046395104"], got[:1])

# ---- 2. register before the asset exists, through the real ExecState ----------------------------------------------
ARTIST, BUYER = "ndoAAAA" + "A" * 41, "ndoCCCC" + "C" * 41
st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_nft1_"), "s.json"))
st.cursor = 1000
code = N.build()
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": N.ABI, "nonce": "n"}, ARTIST, "d")
cid = st.contract_id(ARTIST, code, "n")
for w in (ARTIST, BUYER):
    st.credit_deposit(w, 10 ** 15)
seed = 77
aid = int(asset_id(ARTIST, seed))
r1 = st.apply_blob({"op": "call", "contract": cid, "method": "register", "args": [11, aid, seed, 1000, 0]}, ARTIST, "r")
check("register applied BEFORE its asset_create is accepted", "-> ok" in str(r1), r1)
r2 = st.apply_blob({"op": "asset_create", "seed": seed, "name": "One", "sym": "NFT", "dec": 0, "supply": 1,
                    "mintable": False, "uri": "ipfs://bafyx"}, ARTIST, "m")
check("the asset_create landing after it creates the asset it named", str(aid) in st.assets, r2)
OTHER = "ndoOOOO" + "O" * 41
st.credit_deposit(OTHER, 10 ** 15)
P = 10 ** 10
st.apply_blob({"op": "call", "contract": cid, "method": "list", "args": [21, aid, P], "value": 1, "asset": str(aid)}, ARTIST, "l")
r3 = st.apply_blob({"op": "call", "contract": cid, "method": "buy", "args": [21, 1], "value": P}, BUYER, "b")
check("a sale of it settles", "-> ok" in str(r3), r3)
check("the buyer holds it", int((st.abal.get(str(aid)) or {}).get(BUYER, 0)) == 1, st.abal.get(str(aid)))
# the resale is where a royalty shows: the creator is paid 10 % of a sale between two other people
st.apply_blob({"op": "call", "contract": cid, "method": "list", "args": [22, aid, P], "value": 1, "asset": str(aid)}, BUYER, "l2")
a0, b0 = st.bridge.get(ARTIST, 0), st.bridge.get(BUYER, 0)
r5 = st.apply_blob({"op": "call", "contract": cid, "method": "buy", "args": [22, 1], "value": P}, OTHER, "b2")
check("on a resale the creator is paid the royalty registered before the mint (10 %)",
      "-> ok" in str(r5) and st.bridge.get(ARTIST, 0) - a0 == P // 10 and st.bridge.get(BUYER, 0) - b0 == P - P // 10,
      (r5, st.bridge.get(ARTIST, 0) - a0, st.bridge.get(BUYER, 0) - b0))
r4 = st.apply_blob({"op": "call", "contract": cid, "method": "register", "args": [12, aid, seed, 2500, 0]}, ARTIST, "r2")
check("a second register of the same asset is still refused (once per asset)", "-> ok" not in str(r4), r4)

# ---- 3. the page -------------------------------------------------------------------------------------------------
mint = re.search(r"^function mint\(\) \{\n.*?\n\}\n", nft, re.S | re.M)
mint = mint.group(0) if mint else ""
check("mint() sends register as the mint's `then`, with the computed asset id",
      'then: { op: "call", contract: CID, method: "register", args: [randId(), assetId(dapp.me, seed), seed, bps, coll] }' in mint, mint[-400:])
check("mint() forces the wallet's confirm", "confirm: true" in mint)
check("nothing asks a second time: no finishMint, pendingMint or page confirm left",
      not re.search(r"finishMint|pendingMint|nft_pending_mint|uiConfirm", nft))

# ---- 4. the SDK ----------------------------------------------------------------------------------------------------
sdk = rd("static/nadodapp.js")
sb = re.search(r"^  signBlob\(blob, label, pend, opts\) \{\n.*?\n  \}\n", sdk, re.S | re.M)
sb = sb.group(0) if sb else ""
check("signBlob carries opts.then as `then` with a forced confirm", "then: encBig(opts.then), confirm: 1" in sb, sb)
check("signBlob never sends a two-step request to the hidden frame", "&& !opts.then" in sb, sb)
check("a failed follow-up reaches the page (err2)", "this._onReturn(pend, ok, err, err2)" in sdk and 'p.get("err2")' in sdk)

# ---- 5. the wallet -----------------------------------------------------------------------------------------------
w = rd("static/interface.js")
check("the follow-up must be a value-free contract call",
      'thenBlob.op === "call"' in w and '["value", "asset", "amount", "to", "spender"].every((k) => thenBlob[k] === undefined)' in w)
check("a two-step request in the hidden frame asks for the visible confirm", "if (bg) return needUI();\n  }" in w)
check("a two-step request is never autosigned", "if (!thenBlob && (autosignAll || (valueFree && autosignOn) || smallBet))" in w)
check("the follow-up is shown on the confirm", 'i18("dapp.then", "Then, in the same approval")' in w)
sub = w[w.find("const submitBlob = async () => {"):]
sub = sub[:sub.find("\n  };\n")]
check("the follow-up is submitted only after the first is accepted",
      sub.find("if (!(res && res.data && res.data.result))") < sub.find("buildBlobTx(signer, thenBlob") and "thenBlob" in sub, sub[:200])

print("ALL PASS — one approval mints the NFT with its royalty" if not fails else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
