#!/usr/bin/env python3
"""Cross-chain swap e2e (doc/dex-bridge.md §13 phase 2): ONE secret opens all three legs.

Spins a throwaway regtest bitcoind and an anvil ETH devnode, then proves the whole §6 lifecycle:
  BTC  — lock 0.1 tBTC into the §6.5 P2WSH HTLC, claim it revealing s, watchtower-extract s from the
         claim witness; wrong-secret claim rejected; premature refund rejected (non-final), post-locktime
         refund accepted.
  ETH  — deploy HtlcEth.sol, fund 1 ETH under the SAME H, claim with s (revealed in calldata) before the
         deadline; wrong secret reverts; a second lock refunds only after the deadline (time-warped).
  NADO — with the s EXTRACTED FROM THE BTC WITNESS (not the original variable), drive the real otc
         contract offline (ExecState): post ASK -> fill -> settle pays the taker. The preimage IS the
         bridge; no message is trusted across chains, only observed.

Run: HOME=$(mktemp -d) python3 tests/test_otc_swap_e2e.py     (needs /root/tools: bitcoind, anvil, cast, solc)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import otc_btc_leg as B                                        # noqa: E402
from coincurve import PrivateKey                               # noqa: E402

TOOLS = "/root/tools"
BTCD = f"{TOOLS}/bitcoin-28.1/bin/bitcoind"
BCLI = f"{TOOLS}/bitcoin-28.1/bin/bitcoin-cli"
ANVIL, CAST, SOLC = f"{TOOLS}/anvil", f"{TOOLS}/cast", f"{TOOLS}/solc"
RPCPORT, ETHPORT = 18743, 18745
ETH = f"http://127.0.0.1:{ETHPORT}"
# anvil's default funded dev keys (public knowledge, devnet only)
K0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
K1 = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
A0 = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
A1 = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}", flush=True)
    else: failed += 1; print(f"  FAIL {m}", flush=True)


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, timeout=60, **kw)


def main():
    work = tempfile.mkdtemp(prefix="otc_e2e_")
    btcdir = os.path.join(work, "btc"); os.makedirs(btcdir)
    procs = []
    try:
        # ================= BITCOIN LEG =================
        procs.append(subprocess.Popen([BTCD, "-regtest", f"-datadir={btcdir}", f"-rpcport={RPCPORT}",
                                       "-port=18744", "-listen=0", "-fallbackfee=0.0001", "-txindex=1"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        cli = lambda *a: run([BCLI, "-regtest", f"-datadir={btcdir}", f"-rpcport={RPCPORT}", "-rpcwait", *a])
        assert cli("createwallet", "w").returncode == 0, "bitcoind up + wallet"
        mineaddr = cli("getnewaddress").stdout.strip()
        cli("generatetoaddress", "101", mineaddr)

        alice, bob = PrivateKey(), PrivateKey()                 # claimant / refundee key pair
        s = os.urandom(32)                                      # THE swap secret
        H = hashlib.sha256(s).digest()
        height = int(cli("getblockcount").stdout)
        T2 = height + 30
        script = B.htlc_script(H, alice.public_key.format(True), bob.public_key.format(True), T2)
        addr = B.p2wsh_address(script)
        fund_txid = cli("sendtoaddress", addr, "0.1").stdout.strip()
        cli("generatetoaddress", "1", mineaddr)
        raw = json.loads(cli("getrawtransaction", fund_txid, "true").stdout)
        spk = B.p2wsh_script(script).hex()
        vout = next(o["n"] for o in raw["vout"] if o["scriptPubKey"]["hex"] == spk)
        sats = int(round(next(o["value"] for o in raw["vout"] if o["n"] == vout) * 10 ** 8))
        ok(True, f"BTC HTLC funded at {addr[:24]}… ({sats} sat, locktime {T2})")

        dest = B.p2wpkh_script(alice.public_key.format(True))
        bad = B.claim_tx(script, os.urandom(32), alice.to_hex(), fund_txid, vout, sats, dest)
        r = cli("sendrawtransaction", bad)
        ok(r.returncode != 0, f"wrong-secret claim rejected ({(r.stderr or '').strip()[:60]}…)")
        claim = B.claim_tx(script, s, alice.to_hex(), fund_txid, vout, sats, dest)
        claim_txid = cli("sendrawtransaction", claim).stdout.strip()
        ok(len(claim_txid) == 64, "claim accepted by consensus (script + BIP143 sig valid)")
        cli("generatetoaddress", "1", mineaddr)
        watched = json.loads(cli("getrawtransaction", claim_txid, "true").stdout)
        s_btc = B.extract_secret(watched["hex"], H)
        ok(s_btc == s.hex(), "watchtower extracted the secret from the claim witness")

        # refund path on a second, unclaimed HTLC
        s2 = os.urandom(32)
        script2 = B.htlc_script(hashlib.sha256(s2).digest(), alice.public_key.format(True),
                                bob.public_key.format(True), T2)
        f2 = cli("sendtoaddress", B.p2wsh_address(script2), "0.05").stdout.strip()
        cli("generatetoaddress", "1", mineaddr)
        raw2 = json.loads(cli("getrawtransaction", f2, "true").stdout)
        spk2 = B.p2wsh_script(script2).hex()
        v2 = next(o["n"] for o in raw2["vout"] if o["scriptPubKey"]["hex"] == spk2)
        sat2 = int(round(next(o["value"] for o in raw2["vout"] if o["n"] == v2) * 10 ** 8))
        refund = B.refund_tx(script2, T2, bob.to_hex(), f2, v2, sat2, B.p2wpkh_script(bob.public_key.format(True)))
        r = cli("sendrawtransaction", refund)
        ok(r.returncode != 0 and "non-final" in (r.stderr or ""), "premature refund rejected (CLTV holds)")
        need = T2 - int(cli("getblockcount").stdout)
        cli("generatetoaddress", str(max(need, 1)), mineaddr)
        rid = cli("sendrawtransaction", refund).stdout.strip()
        ok(len(rid) == 64, "post-locktime refund accepted — escrow always drains home")

        # ================= ETHEREUM LEG =================
        procs.append(subprocess.Popen([ANVIL, "--port", str(ETHPORT), "--silent"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(40):
            if run([CAST, "block-number", "--rpc-url", ETH]).returncode == 0: break
            time.sleep(0.5)
        binhex = run([SOLC, "--bin", "--optimize", "scripts/HtlcEth.sol"],
                     cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.strip().splitlines()[-1]
        dep = json.loads(run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K0, "--create", "0x" + binhex]).stdout)
        htlc = dep["contractAddress"]
        ok(bool(htlc), f"HtlcEth deployed at {htlc}")
        now = int(run([CAST, "block", "latest", "-f", "timestamp", "--rpc-url", ETH]).stdout)
        dl = now + 3600
        # Bob (A0) funds 1 ETH for Alice (A1) under the SAME H the BTC leg used
        r = run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K0, htlc,
                 "fund(address,bytes32,uint256)", A1, "0x" + H.hex(), str(dl), "--value", "1ether"])
        ok(json.loads(r.stdout)["status"] in ("0x1", "success"), "ETH lock funded under the same hashlock")
        key = run([CAST, "keccak", run([CAST, "abi-encode", "f(bytes32,address,address,uint256)",
                                        "0x" + H.hex(), A1, A0, str(dl)]).stdout.strip()]).stdout.strip()
        bal0 = int(run([CAST, "balance", A1, "--rpc-url", ETH]).stdout)
        r = run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K1, htlc,
                 "claim(bytes32,bytes32)", key, "0x" + os.urandom(32).hex()])
        ok(r.returncode != 0 or json.loads(r.stdout or "{}").get("status") not in ("0x1", "success"),
           "wrong-secret ETH claim reverts")
        r = json.loads(run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K1, htlc,
                            "claim(bytes32,bytes32)", key, "0x" + s_btc]).stdout)
        ok(r["status"] in ("0x1", "success"), "ETH claim with the BTC-revealed secret")
        gained = int(run([CAST, "balance", A1, "--rpc-url", ETH]).stdout) - bal0
        ok(gained > 9 * 10 ** 17, f"claimant paid ({gained / 10**18:.4f} ETH net of gas)")
        tx_in = run([CAST, "tx", r["transactionHash"], "input", "--rpc-url", ETH]).stdout.strip()
        ok(s_btc in tx_in, "secret is public ETH calldata (the other chain can observe it)")
        # refund path, time-warped past the deadline
        r = run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K0, htlc,
                 "fund(address,bytes32,uint256)", A1, "0x" + hashlib.sha256(s2).hexdigest(), str(dl), "--value", "0.5ether"])
        key2 = run([CAST, "keccak", run([CAST, "abi-encode", "f(bytes32,address,address,uint256)",
                                         "0x" + hashlib.sha256(s2).hexdigest(), A1, A0, str(dl)]).stdout.strip()]).stdout.strip()
        r = run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K1, htlc, "refund(bytes32)", key2])
        ok(r.returncode != 0 or json.loads(r.stdout or "{}").get("status") not in ("0x1", "success"), "premature ETH refund reverts")
        run([CAST, "rpc", "evm_increaseTime", "7200", "--rpc-url", ETH]); run([CAST, "rpc", "evm_mine", "--rpc-url", ETH])
        r = json.loads(run([CAST, "send", "--json", "--rpc-url", ETH, "--private-key", K1, htlc, "refund(bytes32)", key2]).stdout)
        ok(r["status"] in ("0x1", "success"), "post-deadline ETH refund pays the refundee")

        # ================= NADO LEG (the real otc contract, offline state) =================
        from execnode.state import ExecState
        from execnode.games import otc as O
        st = ExecState(os.path.join(work, "s.json")); st.cursor = 100; st.block_ts = int(time.time())
        MK, TK = "ndoALICE", "ndoBOB"
        st.bridge[MK] = st.bridge[TK] = 10 ** 12
        code = O.build()
        st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": O.ABI, "nonce": "n"}, MK, "d")
        cid = st.contract_id(MK, code, "n")
        hi, lo = O.vm_hashlock_parts(s_btc)                      # the EXTRACTED secret, not the original
        st.apply_blob({"op": "call", "contract": cid, "method": "post",
                       "args": [1, O.ASK, 10 ** 10, "btc", "0.1", addr, H.hex(), hi, lo, 600, T2],
                       "value": 10 ** 10}, MK, "p")
        st.apply_blob({"op": "call", "contract": cid, "method": "fill",
                       "args": [1, "bcrt1-bob-refund", fund_txid]}, TK, "f")
        before = st.bridge[TK]
        st.apply_blob({"op": "call", "contract": cid, "method": "settle",
                       "args": [1] + O.preimage_limbs(s_btc)}, TK, "s")
        sl = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
        ok(sl(O.ST, 1) == O.SETTLED and st.bridge[TK] == before + 10 ** 10,
           "NADO escrow settled to the taker with the SAME secret — one preimage, three chains")

        print(f"\n[swap-e2e] {passed} passed, {failed} failed", flush=True)
        return 1 if failed else 0
    finally:
        for p in procs:
            try: p.terminate(); p.wait(timeout=10)
            except Exception: pass
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
