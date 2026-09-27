// ERC-20 leg (doc/dex-bridge.md §6.5) against a real EVM, with hostile tokens.
// Run: node tests/test_htlc_erc20.mjs   (starts its own anvil; or RPC=<url> to use a running EVM)
// Covers: a standard token, a USDT-style no-return token, a fee-on-transfer token (the escrow must be
// what ARRIVED), and a token that re-enters the HTLC during transferFrom (the guard must stop it).
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
const HERE = dirname(fileURLToPath(import.meta.url));
const E = await import(join(HERE, "..", "static", "ethsign.js"));
// A PRIVATE devnet unless RPC names one: the runner never had an anvil on 8611, so this test failed on every full run
// ("fetch failed … ECONNREFUSED"). It starts its own anvil on a free port and stops it on exit; with no anvil
// installed it SKIPs, saying why, instead of failing.
import { spawn } from "child_process";
import { existsSync } from "fs";
const ANVIL = process.env.ANVIL || "/root/tools/anvil";
let URL_ = process.env.RPC || "";
let _anvil = null;
if (!URL_) {
  if (!existsSync(ANVIL)) { console.log(`SKIP  no anvil at ${ANVIL} and no RPC given — the ERC-20 leg needs an EVM`); process.exit(0); }
  const port = 20000 + (process.pid % 20000);
  _anvil = spawn(ANVIL, ["--port", String(port), "--silent"], { stdio: "ignore" });
  process.on("exit", () => { try { _anvil.kill(); } catch (e) {} });
  URL_ = `http://127.0.0.1:${port}`;
  let up = false;
  for (let i = 0; i < 100 && !up; i++) {
    try { const r = await fetch(URL_, { method: "POST", headers: { "content-type": "application/json" },
                                        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }) });
          up = r.ok; } catch (e) { await new Promise((z) => setTimeout(z, 100)); }
  }
  if (!up) { console.log("FAIL  the private anvil did not come up"); process.exit(1); }
}
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
// The test tokens are COMPILED from tests/fixtures/erc20_test_tokens.sol on every run (they used to be hand-built into
// /tmp/erc20t/out, whose sources were never committed). No solc -> SKIP, saying why.
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { execFileSync } from "child_process";
const SOLC = process.env.SOLC || "/root/tools/solc";
if (!existsSync(SOLC)) { console.log(`SKIP  no solc at ${SOLC} — the hostile test tokens are compiled per run`); process.exit(0); }
const TOK = mkdtempSync(join(tmpdir(), "erc20t-"));
execFileSync(SOLC, ["--bin", "--optimize", "-o", TOK, "--overwrite", join(HERE, "fixtures", "erc20_test_tokens.sol")], { stdio: "ignore" });
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
const S_FUND = await keccakSel("fund(address,address,address,bytes32,uint256,uint256)");
const S_CLAIM = await keccakSel("claim(bytes32,bytes32)");
const S_REFUND = await keccakSel("refund(bytes32)");
const S_KEY = await keccakSel("lockKey(address,bytes32,address,address,uint256,uint256)");
const now = async () => Number(BigInt((await E.rpc(URL_, "eth_getBlockByNumber", ["latest", false])).timestamp));

async function scenario(name, binName, amount, expectEscrow) {
  const tok = await deploy(join(TOK, binName));
  if (binName === "Evil.bin") await call(tok, "0x" + await keccakSel("setHtlc(address)") + pad(HTLC));
  await call(tok, "0x" + S_APPROVE + pad(HTLC) + num(amount));
  const dl = (await now()) + 3600;
  await call(HTLC, "0x" + S_FUND + pad(tok) + pad(bob.addr) + pad(A0) + pad("0x" + H) + num(dl) + num(amount));
  const key = (await view(HTLC, S_KEY + pad(tok) + pad("0x" + H) + pad(bob.addr) + pad(A0) + num(dl) + num(amount))).slice(2);
  const held = BigInt(await view(tok, S_BAL + pad(HTLC)));
  ok(held === expectEscrow, `${name}: contract escrowed what ARRIVED (${held}, expected ${expectEscrow})`);
  const b0 = BigInt(await view(tok, S_BAL + pad(bob.addr)));
  await call(HTLC, "0x" + S_CLAIM + pad("0x" + key) + pad("0x" + s), bob.k);
const S_REVEALED = await keccakSel("revealed(bytes32)");
ok((await view(HTLC, S_REVEALED + pad("0x" + key))).slice(-64) === s, "revealed(key) returns the preimage by eth_call — no log scan needed");
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
const tok = await deploy(join(TOK, "Good.bin"));
await call(tok, "0x" + S_APPROVE + pad(HTLC) + num(500));
const dl2 = (await now()) + 1200;
await call(HTLC, "0x" + S_FUND + pad(tok) + pad(bob.addr) + pad(A0) + pad("0x" + H) + num(dl2) + num(500));
const key2 = (await view(HTLC, S_KEY + pad(tok) + pad("0x" + H) + pad(bob.addr) + pad(A0) + num(dl2) + num(500))).slice(2);
let bad = ""; try { await call(HTLC, "0x" + S_CLAIM + pad("0x" + key2) + pad("0x" + "cd".repeat(32)), bob.k); } catch (e) { bad = e.message; }
ok(/preimage|revert/i.test(bad), "wrong secret rejected: " + bad.slice(0, 40));
let early = ""; try { await call(HTLC, "0x" + S_REFUND + pad("0x" + key2)); } catch (e) { early = e.message; }
ok(/not yet|revert/i.test(early), "premature refund rejected: " + early.slice(0, 30));
await E.rpc(URL_, "evm_increaseTime", [1200]); await E.rpc(URL_, "evm_mine", []);
const f0 = BigInt(await view(tok, S_BAL + pad(A0)));
await call(HTLC, "0x" + S_REFUND + pad("0x" + key2), bob.k);          // anyone may trigger it
ok(BigInt(await view(tok, S_BAL + pad(A0))) - f0 === 500n, "post-deadline refund returns the tokens to the funder, exactly");

// ---- audit regressions -------------------------------------------------------------------------------
// the key binds the AMOUNT: an underfunded lock lands elsewhere, so a claim finds nothing and the
// preimage is never revealed (v1 let 1 unit of dust buy the victim's secret).
const tok3 = await deploy(join(TOK, "Good.bin"));
await call(tok3, "0x" + S_APPROVE + pad(HTLC) + num(1000));
const dl3 = (await now()) + 1800;
await call(HTLC, "0x" + S_FUND + pad(tok3) + pad(bob.addr) + pad(A0) + pad("0x" + H) + num(dl3) + num(1));  // 1 unit
const agreedKey = (await view(HTLC, S_KEY + pad(tok3) + pad("0x" + H) + pad(bob.addr) + pad(A0) + num(dl3) + num(1000))).slice(2);
let dust = ""; try { await call(HTLC, "0x" + S_CLAIM + pad("0x" + agreedKey) + pad("0x" + s), bob.k); } catch (e) { dust = e.message; }
ok(/no lock|revert/i.test(dust), "an UNDERFUNDED lock cannot be claimed at the agreed key — the secret stays secret");
// the deadline must sit inside a sane window (v1 accepted 2^256-1, making refunds unreachable forever)
let far = ""; try { await call(HTLC, "0x" + S_FUND + pad(tok3) + pad(bob.addr) + pad(A0) + pad("0x" + H) + num(2n ** 200n) + num(10)); } catch (e) { far = e.message; }
ok(/window|revert/i.test(far), "an absurd deadline is refused");
let near = ""; try { await call(HTLC, "0x" + S_FUND + pad(tok3) + pad(bob.addr) + pad(A0) + pad("0x" + H) + num(await now() + 5) + num(10)); } catch (e) { near = e.message; }
ok(/window|revert/i.test(near), "a deadline inside the minimum window is refused");
// the refundee is explicit: someone else can fund on your behalf and the tokens still come back to YOU
const third = E.ethKeypair();
await E.sendTx(URL_, { privHex: K0, to: third.addr, valueWei: 10n ** 18n, gasLimit: 21000n });
await call(tok3, "0x" + S_APPROVE + pad(HTLC) + num(700));
const dl4 = (await now()) + 1200;
await call(HTLC, "0x" + S_FUND + pad(tok3) + pad(bob.addr) + pad(third.addr) + pad("0x" + H) + num(dl4) + num(700));
const key4 = (await view(HTLC, S_KEY + pad(tok3) + pad("0x" + H) + pad(bob.addr) + pad(third.addr) + num(dl4) + num(700))).slice(2);
await E.rpc(URL_, "evm_increaseTime", [2400]); await E.rpc(URL_, "evm_mine", []);
await call(HTLC, "0x" + S_REFUND + pad("0x" + key4), bob.k);
ok(BigInt(await view(tok3, S_BAL + pad(third.addr))) === 700n, "a nominated refundee receives the refund, not the funder");

console.log(`\n[htlc-erc20] ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
