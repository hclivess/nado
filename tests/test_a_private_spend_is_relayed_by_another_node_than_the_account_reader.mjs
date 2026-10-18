/* A private Stwo spend is offered first to a relay OTHER than the node the wallet reads its account through
 * (interface.js stwoRelays). Review 2026-10-12: relayBase() was tried first, so one node saw the account's reads and the
 * spend from the same IP moments apart — the link the relay exists to remove. It is now the last resort.
 *
 * Run: node tests/test_a_private_spend_is_relayed_by_another_node_than_the_account_reader.mjs
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

function run(pool, up) {
  const asked = [];
  const env = {
    relayBase: () => "https://mine", homeRelay: () => "https://mine", relayPool: { list: pool.map((url) => ({ url })) },
    STWO_RELAY_TRIES: 3,
    stwoRelayInfo: async (u) => { asked.push(u); if (!up.includes(u)) throw new Error("down"); return { url: u, fee: 100000 }; },
  };
  const f = new Function(...Object.keys(env), fnSrc("stwoRelays", true) + "\nreturn stwoRelays;")(...Object.values(env));
  return f().then((out) => ({ asked, out: out.map((i) => i.url) }));
}
let r = await run(["https://mine", "https://a", "https://b"], ["https://mine", "https://a", "https://b"]);
check("another relay is offered the spend before the account's own node", r.out[0] !== "https://mine", JSON.stringify(r));
check("...and the account's node is the last resort", r.out[r.out.length - 1] === "https://mine" || !r.out.includes("https://mine"), JSON.stringify(r));
r = await run(["https://mine", "https://a"], ["https://mine"]);
check("with every other relay down, the account's own node still relays (never no relay)", JSON.stringify(r.out) === '["https://mine"]', JSON.stringify(r));
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a private spend is relayed by another node than the account reader");
process.exit(fails ? 1 : 0);
