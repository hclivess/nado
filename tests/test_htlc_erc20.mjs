// ERC-20 leg (doc/dex-bridge.md §6.5) against a real EVM, with hostile tokens.
// Run: /root/tools/anvil --port 8611 --silent &  then  node tests/test_htlc_erc20.mjs
// Covers: a standard token, a USDT-style no-return token, a fee-on-transfer token (the escrow must be
// what ARRIVED), and a token that re-enters the HTLC during transferFrom (the guard must stop it).
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
const HERE = dirname(fileURLToPath(import.meta.url));
const E = await import(join(HERE, "..", "static", "ethsign.js"));
const URL_ = process.env.RPC || "http://127.0.0.1:8611";
const K0 = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
const A0 = E.ethAddress(K0);
let pass = 0, fail = 0;
const ok = (c, m) => { c ? pass++ : fail++; console.log((c ? "  ok   " : "  FAIL ") + m); };
const sel = (sig) => E.htlcAbi.__sel ? E.htlcAbi.__sel(sig) : null;

const keccakSel = async (sig) => {
  const { keccak_256 } = await import(join(HERE, "..", "static", "vendor", "noble-sha3.js"));
  return Array.from(keccak_256(new TextEncoder().encode(sig)).slice(0, 4), x => x.toString(16).padStart(2, "0")).join("");
};
const pad = (h) => h.replace(/^0x/, "").padStart(64, "0");
const num = (n) => BigInt(n).toString(16).padStart(64, "0");
async function deploy(binPath) {
  const bin = readFileSync(binPath, "utf8").trim();
  const r = await E.deployHtlc(URL_, K0, "0x" + bin);
  return r.address;
}
async function call(to, data, from = K0) { return E.sendTx(URL_, { privHex: from, to, gasLimit: 900000n, dataHex: data }); }
async function view(to, data) { return E.rpc(URL_, "eth_call", [{ to, data: "0x" + data.replace(/^0x/, "") }, "latest"]); }

const HTLC = await deploy(join(HERE, "..", "scripts", "HtlcErc20.bin"));
ok(!!HTLC, "HtlcErc20 deployed at " + HTLC);
const s = "ab".repeat(32);
const H = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(32).fill(0xab))), x => x.toString(16).padStart(2, "0")).join("");
const bob = E.ethKeypair();
await E.sendTx(URL_, { privHex: K0, to: bob.addr, valueWei: 100n * 10n ** 18n, gasLimit: 21000n });

const S_APPROVE = await keccakSel("approve(address,uint256)");
const S_BAL = await keccakSel("balanceOf(address)");
const S_FUND = await keccakSel("fund(address,address,bytes32,uint256,uint256)");
const S_CLAIM = await keccakSel("claim(bytes32,bytes32)");
const S_REFUND = await keccakSel("refund(bytes32)");
const S_KEY = await keccakSel("lockKey(address,bytes32,address,address,uint256)");
const now = async () => Number(BigInt((await E.rpc(URL_, "eth_getBlockByNumber", ["latest", false])).timestamp));

async function scenario(name, binName, amount, expectEscrow) {
  const tok = await deploy(join("/tmp/erc20t/out", binName));
  if (binName === "Evil.bin") await call(tok, "0x" + await keccakSel("setHtlc(address)") + pad(HTLC));
  await call(tok, "0x" + S_APPROVE + pad(HTLC) + num(amount));
  const dl = (await now()) + 3600;
  await call(HTLC, "0x" + S_FUND + pad(tok) + pad(bob.addr) + pad("0x" + H) + num(dl) + num(amount));
  const key = (await view(HTLC, S_KEY + pad(tok) + pad("0x" + H) + pad(bob.addr) + pad(A0) + num(dl))).slice(2);
  const held = BigInt(await view(tok, S_BAL + pad(HTLC)));
  ok(held === expectEscrow, `${name}: contract escrowed what ARRIVED (${held}, expected ${expectEscrow})`);
  const b0 = BigInt(await view(tok, S_BAL + pad(bob.addr)));
  await call(HTLC, "0x" + S_CLAIM + pad("0x" + key) + pad("0x" + s), bob.k);
  const b1 = BigInt(await view(tok, S_BAL + pad(bob.addr)));
  ok(b1 > b0, `${name}: claim with the secret paid the claimant (+${b1 - b0})`);
  return { tok, key };
}

await scenario("standard token", "Good.bin", 1000n, 1000n);
await scenario("USDT-style (no return value)", "NoReturn.bin", 1000n, 1000n);
await scenario("fee-on-transfer (10%)", "FeeOnTransfer.bin", 1000n, 900n);

// the re-entering token: the guard must reject the nested call, and the fund must still succeed
const { tok: evil } = await scenario("re-entering token", "Evil.bin", 1000n, 1000n);
const triedSel = await keccakSel("tried()"), revSel = await keccakSel("reverted_()");
ok(BigInt(await view(evil, triedSel)) === 1n, "re-entering token DID attempt a nested call");
ok(BigInt(await view(evil, revSel)) === 1n, "the nested call was REJECTED by the reentrancy guard");

// wrong secret / early refund / late refund on a standard token
const tok = await deploy(join("/tmp/erc20t/out", "Good.bin"));
await call(tok, "0x" + S_APPROVE + pad(HTLC) + num(500));
const dl2 = (await now()) + 600;
await call(HTLC, "0x" + S_FUND + pad(tok) + pad(bob.addr) + pad("0x" + H) + num(dl2) + num(500));
const key2 = (await view(HTLC, S_KEY + pad(tok) + pad("0x" + H) + pad(bob.addr) + pad(A0) + num(dl2))).slice(2);
let bad = ""; try { await call(HTLC, "0x" + S_CLAIM + pad("0x" + key2) + pad("0x" + "cd".repeat(32)), bob.k); } catch (e) { bad = e.message; }
ok(/preimage|revert/i.test(bad), "wrong secret rejected: " + bad.slice(0, 40));
let early = ""; try { await call(HTLC, "0x" + S_REFUND + pad("0x" + key2)); } catch (e) { early = e.message; }
ok(/not yet|revert/i.test(early), "premature refund rejected: " + early.slice(0, 30));
await E.rpc(URL_, "evm_increaseTime", [1200]); await E.rpc(URL_, "evm_mine", []);
const f0 = BigInt(await view(tok, S_BAL + pad(A0)));
await call(HTLC, "0x" + S_REFUND + pad("0x" + key2), bob.k);          // anyone may trigger it
ok(BigInt(await view(tok, S_BAL + pad(A0))) - f0 === 500n, "post-deadline refund returns the tokens to the funder, exactly");

console.log(`\n[htlc-erc20] ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
