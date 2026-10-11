/* A restored wallet reads EVERY page of its own transactions, and every amount exactly (interface.js
 * stwoOwnTransactions, used by stwoRecoverDeposits to find the fresh-owner deposits on a new device).
 *
 * Review 2026-10-12 of the relay/fresh-owner build. Two ways the first restore lost deposits silently:
 *  - /get_transactions_of_account answers at most ~1000 index entries per call; the restore read one call, so an
 *    active account's later deposits were never found. The node now says `more` + `last_block`; the wallet pages from
 *    there, deduped by txid (the page can stop inside a block).
 *  - JSON.parse rounds an integer above 2^53 raw (~900,719 NADO): the recomputed commitment then matched no leaf. Every
 *    "amount" is quoted before parsing, so it reaches BigInt as its exact digits.
 * The function is RUN from static/interface.js with the network stubbed.
 *
 * Run: node tests/test_a_restored_wallet_reads_every_deposit_page_with_exact_amounts.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found in interface.js");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const BIG = "1152921504606846977";                 // 2^60 + 1 raw: not representable as a double
const tx = (id, amount) => `{"txid":"${id}","recipient":"shield","sender":"a","amount":${amount},"data":{"pool":"stwo","owner":"x","rho":"5"}}`;
// page 1 stops inside block 7 (t3 is in block 7 too, and comes again on page 2)
const pages = {
  0: `{"transactions":[${tx("t1", 5)},${tx("t2", BIG)},${tx("t3", 7)}],"more":true,"last_block":7}`,
  7: `{"transactions":[${tx("t3", 7)},${tx("t4", BIG)}]}`,
};
const asked = [];
const env = {
  relayBase: () => "http://relay",
  fetchWithTimeout: async (url) => {
    const mb = Number(new URL(url).searchParams.get("min_block"));
    asked.push(mb);
    const body = pages[mb];
    return { status: body ? 200 : 404, text: async () => body || "Not found" };
  },
};
const f = new Function(...Object.keys(env), fnSrc("stwoOwnTransactions", true) + "\nreturn stwoOwnTransactions;")(...Object.values(env));
const got = await f("a");
check("both pages were read, the second from the block the first stopped in", JSON.stringify(asked) === "[0,7]", JSON.stringify(asked));
check("every transaction once (the repeat at the page seam is deduped)", got && got.map((t) => t.txid).join() === "t1,t2,t3,t4",
      JSON.stringify(got && got.map((t) => t.txid)));
check("an amount above 2^53 raw reaches BigInt exactly", got && BigInt(got[1].amount) === BigInt(BIG) && BigInt(got[3].amount) === BigInt(BIG),
      got && String(got[1].amount));
check("small amounts too", got && BigInt(got[0].amount) === 5n);
// a node without paging (no `more`) is read once, as before
asked.length = 0;
pages[0] = `{"transactions":[${tx("t1", 5)}]}`;
const one = await f("a");
check("a reply without `more` is the last page", JSON.stringify(asked) === "[0]" && one.length === 1);
// a relay failure is null (the restore retries later), never an empty list that would mark the scan done
env.fetchWithTimeout = async () => { throw new Error("down"); };
const g = new Function(...Object.keys(env), fnSrc("stwoOwnTransactions", true) + "\nreturn stwoOwnTransactions;")(...Object.values(env));
check("a relay failure is null, not an empty history", (await g("a")) === null);
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a restored wallet reads every deposit page with exact amounts");
process.exit(fails ? 1 : 0);
