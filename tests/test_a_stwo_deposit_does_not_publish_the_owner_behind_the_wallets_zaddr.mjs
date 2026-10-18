/* A Stwo deposit must not publish, next to the depositing account, the owner digest that the wallet's zaddr IS.
 *
 * ZK review 2026-10-11 (rev-zk). REPRODUCES A LEAK: this test FAILS on 37d076c6 and is the reproduction.
 *
 * The wallet's shielded owner is ONE stable digest per wallet (shieldOwner() = ownerOf(shieldNskStwo()), nsk derived
 * from the account key), and the zaddr is that digest in base36 ("zaddr_" + base36(owner)). doShield() publishes
 * {owner, rho, cm} in the clear in the L1 shield transaction, which the account itself signs. So:
 *   - anyone given a zaddr finds the transparent account behind it by scanning shield txs for data.owner — the exact
 *     link test_zbill_delivery.js and the delivery design ("registering shieldOwner -> kem_pub on-chain publishes the
 *     same link, permanently") exist to avoid;
 *   - every deposit by one account carries the same owner, and every note paid to that zaddr is that owner's note.
 * The proof hides the input note's owner; the deposit has already published it, with the account's signature on it.
 *
 * FIXED: deposit i is owned by ownerOf(nsk_i), nsk_i = stwo_js.js depositNsk(shieldNskStwo(), i) — a fresh,
 * unlinkable owner per deposit, derived from the deposit's own rho (interface.js stwoDepositNsk); the zaddr stays the
 * stable owner, for receiving.
 *
 * The check RUNS the wallet's own doShield / shieldOwner / shieldAddr / parseShieldAddr (extracted from
 * static/interface.js) with the Stwo pool live, a generated throwaway key (never a real one) and the network stubbed,
 * and reads what the shield transaction would publish.
 *
 * Run: node tests/test_a_stwo_deposit_does_not_publish_the_owner_behind_the_wallets_zaddr.mjs
 */
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const stwo = await import(path.join(HERE, "..", "static", "stark", "stwo_js.js"));

function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found in interface.js");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
const constSrc = (name) => { const m = SRC.match(new RegExp("const " + name + " = [^;]+;")); if (!m) throw new Error(name); return m[0]; };

const js = (x) => JSON.stringify(x, (k, v) => (typeof v === "bigint" ? v.toString() : v));
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const published = [], stored = [];
const env = {
  state: { wallet: { address: "ndo_test_account", privateKey: crypto.randomBytes(32).toString("hex"), publicKey: "pk" } },
  _stwo: stwo,
  blake2bHash: (parts) => crypto.createHash("blake2b512").update(JSON.stringify(parts)).digest("hex").slice(0, 64),
  shieldStwo: () => true, shieldWide: () => false, ensureShielded: () => {}, refreshShieldRules: async () => {},
  shieldPaused: () => false, wideDepositClosed: () => false, _shieldTip: 0, nadoToRaw: (s) => BigInt(s) * 10000000000n, rawToNado: (x) => String(x),
  $: () => ({ value: "5" }), log: () => {}, i18: (k, fb) => fb,
  _randField: () => BigInt("0x" + crypto.randomBytes(7).toString("hex")).toString(),
  noteCommit: (v, owner, rho) => stwo.commit(v, owner, rho),
  getLatestBlock: async () => ({ block_number: 100 }), MIN_TX_FEE: 1, nowSeconds: () => 0,
  buildTransferTx: (wallet, kind, amount, fee, target, data) => { published.push({ signer: wallet.address, kind, amount, data }); return {}; },
  submitTransaction: async () => ({ data: { result: true } }),
  loadNotes: () => stored.map((n) => ({ ...n })), saveNotes: (ns) => { stored.length = 0; stored.push(...ns); },
  setTimeout: () => {}, renderShield: async () => {},
};
const body = [constSrc("ZADDR_STWO"), fnSrc("shieldNskStwo"), fnSrc("shieldOwner"), fnSrc("ownerStr"), fnSrc("cmStr"),
  fnSrc("shieldAddr"), fnSrc("_b36"), fnSrc("stwoDepositNsk"),
  fnSrc("doShield", true),
  "return { doShield, shieldOwner, shieldAddr, ownerStr, stwoDepositNsk };"].join("\n");
const constName = constSrc("DOMAIN_SHIELD_NSK_STWO");
const W = new Function(...Object.keys(env), constName + "\n" + body)(...Object.values(env));

await W.doShield();
await W.doShield();
check("doShield published two shield transactions", published.length === 2, js(published));

const owner = W.ownerStr(W.shieldOwner());
const zaddrOwner = (() => { const a = W.shieldAddr(); return BigInt(a.slice("zaddr_".length).split("").reduce((x, c) => x * 36n + BigInt("0123456789abcdefghijklmnopqrstuvwxyz".indexOf(c)), 0n)).toString(16).padStart(64, "0"); })();
check("the zaddr encodes the wallet's owner digest (sanity)", zaddrOwner === owner, `${zaddrOwner} vs ${owner}`);

for (const [i, p] of published.entries()) {
  const leaked = js(p.data).includes(owner);
  check(`deposit ${i + 1} (signed by ${p.signer}) does not publish the owner digest the wallet's zaddr encodes`, !leaked,
        `data.owner = ${p.data && p.data.owner} = base16 of the zaddr ${W.shieldAddr().slice(0, 16)}…: the zaddr is linked to the account`);
}
if (published.length === 2)
  check("two deposits of one wallet publish no common identifier", published[0].data.owner !== published[1].data.owner,
        "both carry the same owner: every deposit of the account is linkable, and to every note paid to its zaddr");

// THE WALLET CAN STILL SPEND EACH: every deposit's note is stored marked `dep`, and the key derived from its rho owns it
// (the real spend of each, proved and applied, is tests/test_each_stwo_deposit_has_its_own_owner_and_the_wallet_spends_each.py)
for (const [i, p] of published.entries()) {
  const n = stored.find((x) => x.cm === p.data.cm);
  const ok = n && n.dep === true && stwo.ownerOf(W.stwoDepositNsk(n.rho)) === p.data.owner
    && stwo.commit(BigInt(p.amount), p.data.owner, BigInt(p.data.rho)) === n.cm;
  check(`deposit ${i + 1}'s note is stored as a deposit note whose rho-derived spend key owns it`, !!ok, js({ n, p: p.data }));
}
check("each deposit used a different spend key", stored.length === 2 && W.stwoDepositNsk(stored[0].rho) !== W.stwoDepositNsk(stored[1].rho), js(stored));
check("a deposit's spend key is not the wallet's stable one (one-way, domain-separated derivation)",
      stored.every((n) => stwo.ownerOf(W.stwoDepositNsk(n.rho)) !== owner));

process.exit(fails ? 1 : 0);
