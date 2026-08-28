#!/usr/bin/env node
// The browser Solana client (static/solsign.js) driven against a real validator.
//
// Two kinds of check, both necessary:
//   * BYTE PARITY with solders — the same swap, the same keys, the same blockhash must serialise to the
//     identical transaction. This is how btcsign.js was proven against the Python Bitcoin leg: a signer
//     that merely "works" can still disagree about account ordering in a way only some chains reject.
//   * A LIVE LIFECYCLE — fund, refuse the wrong preimage, refuse an early refund, claim, refuse the second
//     claim — submitted by this client and judged by the actual program.
//
//   solana-test-validator --reset --ledger /tmp/svl/test-ledger --rpc-port 8999 ...
//   node tests/test_solsign.mjs <program_id> [rpc_url]
import * as s from "../static/solsign.js";
import * as ed from "../static/vendor/noble-ed25519.js";
const hex2 = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));

const PID = process.argv[2], URL = process.argv[3] || "http://127.0.0.1:8999";
if (!PID) { console.error("usage: test_solsign.mjs <program_id> [rpc]"); process.exit(2); }
const SOL = 1_000_000_000n;
let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log("  ok   " + m)) : (fail++, console.log("  FAIL " + m)); };
const hex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha256b = async (b) => new Uint8Array(await crypto.subtle.digest("SHA-256", b));
const sha = async (h) => hex(new Uint8Array(await crypto.subtle.digest("SHA-256",
  new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16))))));
async function rejects(what, fn) {
  try { await fn(); ok(false, what + " (it was ACCEPTED)"); }
  catch (e) { ok(true, what); }
}
const airdrop = async (addr, lamports) => {
  const sig = await s.solRpc(URL, "requestAirdrop", [addr, Number(lamports)]);
  for (let i = 0; i < 40; i++) {
    const st = (await s.solRpc(URL, "getSignatureStatuses", [[sig]])).value[0];
    if (st && st.confirmationStatus !== "processed") return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("airdrop never confirmed");
};

// ---- byte parity ----------------------------------------------------------------------------------------
console.log("[solsign] parity with solders");
{
  const fk = "aa".repeat(32), ck = "bb".repeat(32);
  const funder = await s.solAddressOf(fk), claimant = await s.solAddressOf(ck);
  ok(funder === "GZXyfzSTCBmA7rpeDLrmUbiSA45H5EEwJhoBeR6ZNb3u" &&
     claimant === "9SKMfAuZCbrG8kfjWviV8zYkuSXeuq2bMseV4J4TNgiu", "ed25519 addresses match solders");
  const hl = await sha("cc".repeat(32));
  const { address: lock } = await s.htlcPda(PID, hl, claimant, funder, 1900000000, 50000000);
  ok(lock === "B2H3aKWq8yXLPVetSGLaDRe1ekJ7zBJED1xmnXxsZkcM", "PDA matches find_program_address");
  const raw = await s.buildTx(funder, [s.ixFund(PID, funder, lock, hl, claimant, 1900000000, 50000000)],
                              "11111111111111111111111111111112", { [funder]: fk });
  // Recorded from solders (scripts/solana-htlc/README.md documents how to regenerate it). Every byte of the
  // account list, the ordering, the instruction data and the signature has to agree.
  ok(hex(await sha256b(raw)) === "5e4b0c3ef70c17d69a249dd7f391de8501736a7838ab3c03ebdeb7182afffeff",
     "the signed fund transaction is byte-identical to solders (" + raw.length + " bytes)");
}

// ---- live lifecycle -------------------------------------------------------------------------------------
console.log("[solsign] live lifecycle on " + URL);
const funder = await s.solKeypair(), claimant = await s.solKeypair(), stranger = await s.solKeypair();
const keys = { [funder.address]: funder.k, [claimant.address]: claimant.k, [stranger.address]: stranger.k };
await airdrop(funder.address, 2n * SOL);
await airdrop(stranger.address, SOL / 2n);
ok(await s.solBalance(URL, funder.address) === 2n * SOL, "funder holds 2 SOL");

const secret = hex(crypto.getRandomValues(new Uint8Array(32)));
const hashlock = await sha(secret);
const now = Math.floor(Date.now() / 1000);
const deadline = now + 3600, amount = 100_000_000;        // 0.1 SOL, one hour
const { address: lock } = await s.htlcPda(PID, hashlock, claimant.address, funder.address, deadline, amount);

await s.solSend(URL, funder.address,
  [s.ixFund(PID, funder.address, lock, hashlock, claimant.address, deadline, amount)], keys);
const info = (await s.solRpc(URL, "getAccountInfo", [lock, { encoding: "base64", commitment: "confirmed" }])).value;
ok(!!info, "the lock account exists at the derived address");
ok(info && info.owner === PID, "it is owned by the HTLC program — no key can move it");
ok(info && BigInt(info.lamports) > BigInt(amount), "it holds the swap amount plus rent");

// The amount is a seed, so a lock for a different amount is a different account entirely.
const { address: other } = await s.htlcPda(PID, hashlock, claimant.address, funder.address, deadline, 1);
ok(other !== lock, "a 1-lamport lock for the same swap lands at a different address");

await rejects("a wrong preimage is refused", () => s.solSend(URL, claimant.address,
  [s.ixClaim(PID, claimant.address, lock, claimant.address, "00".repeat(32))], keys));
await rejects("the funder cannot refund before the deadline", () => s.solSend(URL, funder.address,
  [s.ixRefund(PID, funder.address, lock, funder.address)], keys));
await rejects("a stranger cannot redirect the payout to themselves", () => s.solSend(URL, stranger.address,
  [s.ixClaim(PID, stranger.address, lock, stranger.address, secret)], keys));
await rejects("a deadline beyond the maximum window is refused", async () => {
  const far = now + 400 * 24 * 3600;
  const { address: l2 } = await s.htlcPda(PID, hashlock, claimant.address, funder.address, far, amount);
  await s.solSend(URL, funder.address,
    [s.ixFund(PID, funder.address, lock === l2 ? lock : l2, hashlock, claimant.address, far, amount)], keys);
});

// Anyone may submit the claim; the money still goes only to the recorded claimant.
const before = await s.solBalance(URL, claimant.address);
await s.solSend(URL, stranger.address, [s.ixClaim(PID, stranger.address, lock, claimant.address, secret)], keys);
const after = await s.solBalance(URL, claimant.address);
ok(after - before >= BigInt(amount), "a third party submitted the claim and the claimant was paid " +
   (after - before) + " lamports");
// The NADO side settles by reading the preimage back off Solana — nobody has to paste anything.
const found = await s.solFoundSecret(URL, lock, hashlock);
ok(found === secret, "the secret was recovered from the claim transaction on chain");
ok((await s.solLockInfo(URL, PID, lock)) === null, "the lock record is gone once claimed");
await rejects("the same lock cannot be claimed twice", () => s.solSend(URL, stranger.address,
  [s.ixClaim(PID, stranger.address, lock, claimant.address, secret)], keys));

// The browser path: an injected wallet. No extension exists here, so a stub provider stands in — one that
// behaves like Phantom's low-level request API (base58 MESSAGE in, signature out) and really signs and
// sends. This proves the page-side assembly, the connect flow and the send flow, not the extension itself.
{
  const wal = await s.solKeypair();
  await airdrop(wal.address, 2n * SOL);
  const stub = {
    publicKey: { toString: () => wal.address },
    connect: async () => ({ publicKey: { toString: () => wal.address } }),
    request: async ({ method, params }) => {
      if (method !== "signAndSendTransaction") throw new Error("unexpected " + method);
      const msg = s.b58decode(params.message);
      const sig = await ed.signAsync(msg, hex2(wal.k));
      const raw = new Uint8Array([1, ...sig, ...msg]);
      let b64 = ""; for (const b of raw) b64 += String.fromCharCode(b);
      return { signature: await s.solRpc(URL, "sendTransaction", [btoa(b64), { encoding: "base64", preflightCommitment: "processed" }]) };
    },
  };
  globalThis.window = { phantom: { solana: stub } };
  const { provider, address } = await s.solWalletConnect();
  ok(address === wal.address && provider === stub, "wallet connect returns the provider's account");
  const dl = now + 7200, hl2 = hex(await sha256b(new Uint8Array(32).fill(7)));
  const { address: wl } = await s.htlcPda(PID, hl2, claimant.address, wal.address, dl, amount);
  const sig = await s.solWalletSend(URL, provider, wal.address, [s.ixFund(PID, wal.address, wl, hl2, claimant.address, dl, amount)]);
  for (let i = 0; i < 40; i++) {
    const st = (await s.solRpc(URL, "getSignatureStatuses", [[sig]])).value[0];
    if (st && st.confirmationStatus !== "processed") break;
    await new Promise((r) => setTimeout(r, 300));
  }
  const info = await s.solLockInfo(URL, PID, wl);
  ok(info && info.owner === PID && info.amount === BigInt(amount), "a wallet-signed fund (base58 message via request) landed as a valid lock");
  ok((await s.solWalletSend(URL, { }, wal.address, []).catch((e) => e.message)).includes("Phantom"), "a wallet without the request API is refused plainly");
  delete globalThis.window;
}

// ---- SPL tokens through the client: mint via the CLI, then fund / claim with solsign's builders ---------
{
  const { execFileSync } = await import("child_process");
  const PAYER = process.env.SOL_PAYER || "/tmp/svl/payer.json";
  const cli = (...a) => execFileSync("spl-token", ["-u", URL, "--fee-payer", PAYER, ...a], { encoding: "utf8", timeout: 120000 });
  const mint = JSON.parse(cli("create-token", "--mint-authority", PAYER, "--decimals", "6", "--output", "json")).commandOutput.address;
  const tf = await s.solKeypair(), tc = await s.solKeypair(), tw = await s.solKeypair();   // funder, claimant, watchtower
  for (const k of [tf, tc, tw]) await airdrop(k.address, 2n * SOL);
  cli("create-account", mint, "--owner", tf.address);
  cli("mint", mint, "500", await s.ataOf(tf.address, mint), "--mint-authority", PAYER);
  const tkeys = { [tf.address]: tf.k, [tc.address]: tc.k, [tw.address]: tw.k };
  const tsecret = "ee".repeat(32), thash = hex(await sha256b(hex2(tsecret)));
  const tdl = Math.floor(Date.now() / 1000) + 3600, tamt = 125_000_000;   // 125 tokens at 6 dp
  const { address: tl } = await s.htlcPdaTok(PID, thash, tc.address, tf.address, tdl, tamt, mint);
  const bal = async (owner) => { try { return BigInt((await s.solRpc(URL, "getTokenAccountBalance", [await s.ataOf(owner, mint), { commitment: "confirmed" }])).value.amount); } catch (e) { return 0n; } };
  await s.solSend(URL, tf.address, [s.ixFundToken(PID, tf.address, tl, thash, tc.address, tdl, tamt, mint, await s.ataOf(tf.address, mint), await s.ataOf(tl, mint))], tkeys);
  ok(await bal(tl) === BigInt(tamt) && await bal(tf.address) === 375_000_000n, "token lock: 125 tokens sit in the escrow's own token account");
  const tinfo = await s.solLockInfo(URL, PID, tl);
  ok(tinfo && tinfo.mint === mint && tinfo.amount === BigInt(tamt), "the lock record names the mint and the amount");
  await rejects("a wrong preimage is refused on a token lock", async () => s.solSend(URL, tc.address,
    [s.ixClaimToken(PID, tc.address, tl, tc.address, "ab".repeat(32), mint, await s.ataOf(tl, mint), await s.ataOf(tc.address, mint))], tkeys));
  await s.solSend(URL, tw.address, [s.ixClaimToken(PID, tw.address, tl, tc.address, tsecret, mint, await s.ataOf(tl, mint), await s.ataOf(tc.address, mint))], tkeys);
  ok(await bal(tc.address) === BigInt(tamt), "a watchtower submitted the token claim; the claimant (who had no token account) holds the 125");
  ok((await s.solFoundSecret(URL, tl, thash)) === tsecret, "the secret is recovered from the token claim exactly as from a native one");
}

console.log(`\n[solsign] ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
