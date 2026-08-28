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
//   node scripts/otc_eth_leg.mjs claim    --rpc URL --key HEX --htlc ADDR --hash H --claimant ADDR --refundee ADDR --deadline UNIX --value WEI --secret S
//   node scripts/otc_eth_leg.mjs refund   --rpc URL --key HEX --htlc ADDR --hash H --claimant ADDR --refundee ADDR --deadline UNIX --value WEI
//   node scripts/otc_eth_leg.mjs show     --rpc URL --htlc ADDR --hash H --claimant ADDR --refundee ADDR --deadline UNIX --value WEI
//
// The lock KEY binds hashlock, claimant, refundee, deadline AND amount (the audit's one-wei fix), so every
// command after fund names the amount too: --value in wei, or --amount in whole tokens with --token.
//
// ERC-20 swaps: add --token ADDR to deploy/fund/claim/refund/show. `deploy --token any` deploys HtlcErc20
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
  const hashOf = () => { const h = need("hash").replace(/^0x/, ""); if (!/^[0-9a-fA-F]{64}$/.test(h)) { console.error("--hash must be 32 bytes of hex"); process.exit(2); } return h; };
  const amountOf = async () => {
    if (tok && args.amount) return E.toUnitsDec(args.amount, (await E.erc20Meta(need("rpc"), tok)).decimals);
    return BigInt(need("value"));
  };
  const keyOf = async () => {
    const amt = await amountOf();
    return tok
      ? E.htlcErc20Abi.lockKey(tok, hashOf(), need("claimant"), need("refundee"), Number(need("deadline")), amt)
      : E.htlcAbi.lockKey(hashOf(), need("claimant"), need("refundee"), Number(need("deadline")), amt);
  };
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
      const data = E.htlcErc20Abi.fund(tok, need("claimant"), E.ethAddress(pk), hashOf(), Number(need("deadline")), amt);
      console.log(JSON.stringify({ txid: await E.sendTx(rpc, { privHex: pk, to: htlc, gasLimit: 300000n, dataHex: data }) }));
    } else {
      const pk = need("key");                              // the funder IS the refundee, by the contract's rule
      const data = E.htlcAbi.fund(need("claimant"), E.ethAddress(pk), hashOf(), Number(need("deadline")));
      console.log(JSON.stringify({ txid: await E.sendTx(need("rpc"), { privHex: pk, to: need("htlc"), valueWei: BigInt(need("value")), gasLimit: 200000n, dataHex: data }) }));
    }
  } else if (cmd === "show") {
    // read the lock back under the exact key the terms imply — the counterparty's check before funding
    const key = await keyOf();
    const r = await E.rpc(need("rpc"), "eth_call", [{ to: need("htlc"), data: (tok ? E.htlcErc20Abi : E.htlcAbi).locks(key) }, "latest"]);
    const words = String(r || "0x").replace(/^0x/, "").match(/.{64}/g) || [];
    const held = words.length ? BigInt("0x" + words[tok ? 3 : 2]) : 0n;
    console.log(JSON.stringify({ key: "0x" + key, held: held.toString(), matchesTerms: held >= await amountOf() && held > 0n }));
  } else if (cmd === "claim") {
    const key = await keyOf();
    const data = tok ? E.htlcErc20Abi.claim(key, need("secret")) : E.htlcAbi.claim(key, need("secret"));
    console.log(JSON.stringify({ txid: await E.sendTx(need("rpc"), { privHex: need("key"), to: need("htlc"), gasLimit: 300000n, dataHex: data }) }));
  } else if (cmd === "refund") {
    const key = await keyOf();
    const data = tok ? E.htlcErc20Abi.refund(key) : E.htlcAbi.refund(key);
    console.log(JSON.stringify({ txid: await E.sendTx(need("rpc"), { privHex: need("key"), to: need("htlc"), gasLimit: 300000n, dataHex: data }) }));
  } else { console.error("commands: key | deploy | fund | claim | refund | show"); process.exit(2); }
} catch (e) { console.error("error:", e.message); process.exit(1); }
