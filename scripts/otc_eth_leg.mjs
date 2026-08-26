#!/usr/bin/env node
// otc_eth_leg.mjs — Ethereum leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5), headless.
// The counterpart to scripts/otc_btc_leg.py: deploy the ownerless HtlcEth once per chain, then fund /
// claim / refund a lock — all signed locally with the vendored @noble/secp256k1 (static/ethsign.js), no
// browser and no injected wallet. The hashlock is the SAME 32-byte SHA-256 image the NADO otc contract
// bound; claiming publishes the preimage in calldata, which is what lets the NADO side settle.
//
//   node scripts/otc_eth_leg.mjs key                              # a fresh EVM key + address
//   node scripts/otc_eth_leg.mjs deploy   --rpc URL --key HEX     # deploy HtlcEth -> prints its address
//   node scripts/otc_eth_leg.mjs fund     --rpc URL --key HEX --htlc ADDR --claimant ADDR --hash H --deadline UNIX --value WEI
//   node scripts/otc_eth_leg.mjs claim    --rpc URL --key HEX --htlc ADDR --hash H --claimant ADDR --refundee ADDR --deadline UNIX --secret S
//   node scripts/otc_eth_leg.mjs refund   --rpc URL --key HEX --htlc ADDR --hash H --claimant ADDR --refundee ADDR --deadline UNIX
//
// ERC-20 swaps: add --token ADDR to deploy/fund/claim/refund. `deploy --token any` deploys HtlcErc20
// instead of HtlcEth; fund approves the token first, and the amount is given in whole tokens (--amount
// 12.5) because the decimals are read from the token itself.
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
const HERE = dirname(fileURLToPath(import.meta.url));
const E = await import(join(HERE, "..", "static", "ethsign.js"));
const args = Object.fromEntries(process.argv.slice(3).join(" ").split("--").filter(Boolean)
  .map((s) => { const [k, ...v] = s.trim().split(/\s+/); return [k, v.join(" ")]; }));
const cmd = process.argv[2];
const need = (k) => { if (!args[k]) { console.error("missing --" + k); process.exit(2); } return args[k]; };
const solBin = (file = "HtlcEth.bin") => "0x" + (function () {
  try { return readFileSync(join(HERE, file), "utf8").trim(); }
  catch (e) { console.error(`${file} not found — build it with /root/tools/solc --bin --optimize`); process.exit(2); }
})();
try {
  const tok = args.token && /^0x[0-9a-fA-F]{40}$/.test(args.token) ? args.token : null;
  const keyOf = () => tok
    ? E.htlcErc20Abi.lockKey(tok, need("hash"), need("claimant"), need("refundee"), Number(need("deadline")))
    : E.htlcAbi.lockKey(need("hash"), need("claimant"), need("refundee"), Number(need("deadline")));
  if (cmd === "key") { const k = E.ethKeypair(); console.log(JSON.stringify(k)); }
  else if (cmd === "deploy") {
    const which = args.token ? "HtlcErc20.bin" : "HtlcEth.bin";
    console.log(JSON.stringify(await E.deployHtlc(need("rpc"), need("key"), solBin(which))));
  } else if (cmd === "fund") {
    if (tok) {
      const rpc = need("rpc"), htlc = need("htlc"), pk = need("key");
      const meta = await E.erc20Meta(rpc, tok);
      const amt = args.amount ? E.toUnitsDec(args.amount, meta.decimals) : BigInt(need("value"));
      console.log(`approving ${args.amount || amt} ${meta.symbol}…`);
      await E.sendTx(rpc, { privHex: pk, to: tok, gasLimit: 120000n, dataHex: E.erc20Abi.approve(htlc, amt) });
      const data = E.htlcErc20Abi.fund(tok, need("claimant"), need("hash"), Number(need("deadline")), amt);
      console.log(await E.sendTx(rpc, { privHex: pk, to: htlc, gasLimit: 300000n, dataHex: data }));
    } else {
      const data = E.htlcAbi.fund(need("claimant"), need("hash"), Number(need("deadline")));
      console.log(await E.sendTx(need("rpc"), { privHex: need("key"), to: need("htlc"), valueWei: BigInt(need("value")), gasLimit: 200000n, dataHex: data }));
    }
  } else if (cmd === "claim") {
    const key = keyOf();
    const data = tok ? E.htlcErc20Abi.claim(key, need("secret")) : E.htlcAbi.claim(key, need("secret"));
    console.log(await E.sendTx(need("rpc"), { privHex: need("key"), to: need("htlc"), gasLimit: 300000n, dataHex: data }));
  } else if (cmd === "refund") {
    const key = keyOf();
    const data = tok ? E.htlcErc20Abi.refund(key) : E.htlcAbi.refund(key);
    console.log(await E.sendTx(need("rpc"), { privHex: need("key"), to: need("htlc"), gasLimit: 300000n, dataHex: data }));
  } else { console.error("commands: key | deploy | fund | claim | refund"); process.exit(2); }
} catch (e) { console.error("error:", e.message); process.exit(1); }
