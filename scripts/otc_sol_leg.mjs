#!/usr/bin/env node
// otc_sol_leg.mjs — Solana leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5), headless.
// The counterpart to scripts/otc_btc_leg.py and scripts/otc_eth_leg.mjs: fund / claim / refund a lock in
// the deployed HTLC program (scripts/solana-htlc), signed locally with the vendored ed25519 in
// static/solsign.js — no browser, no wallet extension. The hashlock is the SAME 32-byte SHA-256 image the
// NADO otc order carries; claiming publishes the preimage on Solana, which is what lets the NADO side
// settle. Used by the watchtower and as the fallback when someone has no Solana wallet in the page.
//
//   node scripts/otc_sol_leg.mjs key                                   # a fresh Solana key + address
//   node scripts/otc_sol_leg.mjs address --key HEX
//   node scripts/otc_sol_leg.mjs lock    --program P --hash H --claimant A --funder A --deadline UNIX --amount LAMPORTS
//   node scripts/otc_sol_leg.mjs fund    --rpc URL --key HEX --program P --hash H --claimant A --deadline UNIX --amount LAMPORTS
//   node scripts/otc_sol_leg.mjs claim   --rpc URL --key HEX --program P --hash H --claimant A --funder A --deadline UNIX --amount LAMPORTS --secret S
//   node scripts/otc_sol_leg.mjs refund  --rpc URL --key HEX --program P --hash H --claimant A --funder A --deadline UNIX --amount LAMPORTS
//   node scripts/otc_sol_leg.mjs show    --rpc URL --program P --hash H --claimant A --funder A --deadline UNIX --amount LAMPORTS
//
// `lock` and `show` need no key: anyone can derive the escrow address from the public terms and read it,
// which is exactly how a counterparty verifies the lock before funding their own side.
import { fileURLToPath } from "url";
import { dirname, join } from "path";
const HERE = dirname(fileURLToPath(import.meta.url));
const S = await import(join(HERE, "..", "static", "solsign.js"));
const args = Object.fromEntries(process.argv.slice(3).join(" ").split("--").filter(Boolean)
  .map((s) => { const [k, ...v] = s.trim().split(/\s+/); return [k, v.join(" ")]; }));
const cmd = process.argv[2];
const need = (k) => { if (!args[k]) { console.error("missing --" + k); process.exit(2); } return args[k]; };
const hexOf = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");

/** The escrow address, derived from the terms alone. Every command below needs it. */
async function lockOf() {
  const program = need("program"), hash = need("hash").replace(/^0x/, "");
  if (!/^[0-9a-f]{64}$/i.test(hash)) { console.error("--hash must be 32 bytes of hex"); process.exit(2); }
  const claimant = need("claimant"), deadline = Number(need("deadline")), amount = Number(need("amount"));
  const funder = args.funder || (args.key ? await S.solAddressOf(args.key) : need("funder"));
  const { address, bump } = await S.htlcPda(program, hash, claimant, funder, deadline, amount);
  return { program, hash, claimant, funder, deadline, amount, address, bump };
}
// Solana is an account model: the SUBMITTER pays the fee, and a freshly generated swap address holds
// nothing. The program lets anyone submit a claim (the lamports still go only to the recorded claimant),
// so the answer is to submit from a funded key — the counterparty's, or a watchtower's — not to give up.
const send = async (payer, ixs, key) => {
  const rpc = need("rpc");
  if ((await S.solBalance(rpc, payer)) === 0n) {
    console.error(`the submitting key ${payer} holds no SOL, so it cannot pay the transaction fee.\n` +
      "Anyone may submit this instruction and the payout still goes to the recorded party — rerun with\n" +
      "--key set to a funded key (the counterparty's or a watchtower's).");
    process.exit(1);
  }
  return S.solSend(rpc, payer, ixs, { [payer]: key });
};

try {
  if (cmd === "key") {
    const kp = await S.solKeypair();
    console.log(JSON.stringify({ key: kp.k, address: kp.address }, null, 2));

  } else if (cmd === "address") {
    console.log(await S.solAddressOf(need("key")));

  } else if (cmd === "lock") {
    const l = await lockOf();
    console.log(JSON.stringify(l, null, 2));

  } else if (cmd === "show") {
    const l = await lockOf();
    const info = (await S.solRpc(need("rpc"), "getAccountInfo",
      [l.address, { encoding: "base64", commitment: "confirmed" }])).value;
    if (!info) { console.log(JSON.stringify({ address: l.address, funded: false }, null, 2)); process.exit(0); }
    const raw = Buffer.from(info.data[0], "base64");
    // Read the record back out of the account rather than trusting what we were told on the command line.
    console.log(JSON.stringify({
      address: l.address, funded: true, owner: info.owner, lamports: info.lamports,
      hashlock: hexOf(raw.subarray(0, 32)),
      claimant: S.b58encode(raw.subarray(32, 64)), refunder: S.b58encode(raw.subarray(64, 96)),
      deadline: Number(raw.readBigInt64LE(96)), amount: Number(raw.readBigUInt64LE(104)),
      matchesTerms: hexOf(raw.subarray(0, 32)) === l.hash && S.b58encode(raw.subarray(32, 64)) === l.claimant
        && Number(raw.readBigUInt64LE(104)) === l.amount && info.owner === l.program,
    }, null, 2));

  } else if (cmd === "fund") {
    const key = need("key"), payer = await S.solAddressOf(key);
    args.funder = payer;                                   // the funder IS the signer, by the program's rule
    const l = await lockOf();
    const sig = await send(payer, [S.ixFund(l.program, payer, l.address, l.hash, l.claimant, l.deadline, l.amount)], key);
    console.log(JSON.stringify({ signature: sig, lock: l.address, amount: l.amount }, null, 2));

  } else if (cmd === "claim") {
    const key = need("key"), payer = await S.solAddressOf(key);
    const secret = need("secret").replace(/^0x/, "");
    const l = await lockOf();
    const sig = await send(payer, [S.ixClaim(l.program, payer, l.address, l.claimant, secret)], key);
    console.log(JSON.stringify({ signature: sig, paid: l.claimant, lock: l.address }, null, 2));

  } else if (cmd === "refund") {
    const key = need("key"), payer = await S.solAddressOf(key);
    const l = await lockOf();
    const sig = await send(payer, [S.ixRefund(l.program, payer, l.address, l.funder)], key);
    console.log(JSON.stringify({ signature: sig, returned: l.funder, lock: l.address }, null, 2));

  } else {
    console.error("commands: key address lock show fund claim refund");
    process.exit(2);
  }
} catch (e) {
  console.error("error: " + (e.message || e));
  process.exit(1);
}
