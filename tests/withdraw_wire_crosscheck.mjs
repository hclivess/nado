/*
 * WITHDRAW WIRE FORMAT: the browser's withdraw tx must carry data.amount as a JSON *integer*.
 * Run: node tests/withdraw_wire_crosscheck.mjs
 *
 * WHY THIS FILE EXISTS. validate_transaction (ops/transaction_ops.py, recipient "withdraw") compares
 * the tx's self-describing data against the pending unbond record with plain ==:
 *
 *     assert data.get("amount") == pending["amount"] and data.get("release_block") == pending["release_block"]
 *
 * pending["amount"] is an int (kv_ops.unbond_put stores int(amount)). In Python "20000000000" != 20000000000,
 * so a wallet that stringifies the amount has EVERY withdraw rejected with "withdraw data does not match the
 * pending unbond" — the coins stay stuck in savings with no way out of the browser. That is exactly what
 * shipped: buildWithdrawUnbondTx used String(amount) from the day the withdraw path was added (1441893b),
 * so the second half of leaving savings never once worked from the wallet, while the Python builder
 * (construct_withdraw_tx, which uses int()) did. The failure is invisible to any JS-only test — the tx
 * builds, signs and submits fine; only the node's == says no.
 *
 * The apply path (ops/account_ops.py) coerces with int(data["amount"]) and would have accepted the string,
 * which is why this survived: nothing downstream of validation ever complained.
 *
 * This reads the SHIPPED static/interface.js, so the guard cannot drift from what users actually run.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { canonicalize } from "../static/nadotx.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "..", "static", "interface.js"), "utf8");

let fails = 0;
const eq = (n, got, want) => {
  const ok = got === want; if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${n}${ok ? "" : `\n   got  ${got}\n   want ${want}`}`);
};

// Pull the `data: { ... }` object literal out of buildWithdrawUnbondTx in the shipped file and evaluate it
// with the same inputs refreshUnbond() feeds it: the pending record as JSON.parse hands it back (Numbers).
const fn = SRC.slice(SRC.indexOf("function buildWithdrawUnbondTx"));
const dataLit = fn.slice(fn.indexOf("data: {"), fn.indexOf("\n", fn.indexOf("data: {")))
                  .replace(/^data:\s*/, "").replace(/,\s*$/, "");
console.log(`shipped literal: ${dataLit}\n`);

const amount = 20000000000;   // 2 NADO at DENOMINATION 1e10 — the amount from the reported failure
const releaseBlock = 15400;
const data = eval(`(${dataLit})`);
const wire = canonicalize(data);
console.log(`canonical wire : ${wire}\n`);

eq("data.amount canonicalizes as a bare JSON integer (no quotes)",
   /"amount":\s*20000000000(,|})/.test(wire), true);
eq("data.amount is NOT a JSON string",
   /"amount":\s*"/.test(wire), false);
eq("data.release_block canonicalizes as a bare JSON integer",
   /"release_block":\s*15400(,|})/.test(wire), true);
eq("full canonical body matches what construct_withdraw_tx would produce",
   wire, '{"amount":20000000000,"release_block":15400}');

// The amount must survive as an EXACT integer regardless of magnitude: a supply-sized stake in raw units
// blows past 2^53, so the builder has to hand canonicalize a BigInt, not a Number.
{
  const big = 99999999999999999999n;
  const wideData = eval(`(${dataLit.replace("amount", "amount")})`.replace(/BigInt\(amount\)/, "BigInt(big)"));
  eq("an amount beyond 2^53 stays exact on the wire",
     canonicalize(wideData).startsWith('{"amount":99999999999999999999'), true);
}

console.log(fails ? `\n${fails} FAILED` : "\nall checks passed");
process.exit(fails ? 1 : 0);
