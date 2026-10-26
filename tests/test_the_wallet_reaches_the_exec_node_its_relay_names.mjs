/* The wallet reaches the exec node its relay names (nado.py /status "exec_port", static/interface.js execBase).
 *
 * The wallet assumed every relay's exec node is on :9273 of the relay's host. A node run with another NADO_EXEC_PORT
 * therefore served a wallet that read SOME OTHER exec node on 9273 of the same host — on a box that also runs the fleet's
 * exec node, the live one: the gen-29 rehearsal's loopback walk read the live pool's root this way (2026-10-26, GETs only).
 * Pins, by RUNNING the wallet's own functions: a relay that advertises exec_port is reached there; one that advertises
 * none (or garbage) keeps 9273; a relay behind a reverse proxy (no port) keeps /exec on its origin; and the node
 * advertises the port it uses itself (nado.py source pin: "exec_port": _EXEC_PORT, from NADO_EXEC_PORT).
 *
 * Run: node tests/test_the_wallet_reaches_the_exec_node_its_relay_names.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
const NADO = fs.readFileSync(path.join(HERE, "..", "nado.py"), "utf8");
function fnSrc(name) {
  const i = SRC.indexOf("function " + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const env = { relay: "http://127.0.0.3:9583", state: {} };
const W = new Function("env", "const state = env.state; const relayBase = () => env.relay;\nconst relayExecPort = new Map();\n" +
  fnSrc("noteRelayExecPort") + fnSrc("execBase") + "return { noteRelayExecPort, execBase };")(env);
check("a relay that names no exec port keeps :9273", W.execBase() === "http://127.0.0.3:9273", W.execBase());
W.noteRelayExecPort(env.relay, { exec_port: 9701 });
check("a relay that names its exec port is reached there", W.execBase() === "http://127.0.0.3:9701", W.execBase());
env.relay = "http://127.0.0.4:9583";
check("...per relay: another relay still defaults to :9273", W.execBase() === "http://127.0.0.4:9273", W.execBase());
for (const bad of ["9701", 0, 70000, 9.5, null]) W.noteRelayExecPort(env.relay, { exec_port: bad });
check("a port that is not an integer in 1..65535 is ignored", W.execBase() === "http://127.0.0.4:9273", W.execBase());
env.relay = "https://get.nadochain.com";
check("a relay behind a reverse proxy (no port) keeps /exec on its own origin", W.execBase() === "https://get.nadochain.com", W.execBase());
check("the node advertises the exec port it uses itself", /"exec_port": _EXEC_PORT,/.test(NADO)
  && /^_EXEC_PORT = int\(os\.environ\.get\("NADO_EXEC_PORT", "9273"\)\)/m.test(NADO));
check("the wallet notes it wherever it reads a relay's /status (identity and failover)",
  /noteRelayExecPort\(relayBase\(\), st\);/.test(fnSrc("refreshNetIdentity")) && /noteRelayExecPort\(relayBase\(\), st\);/.test(fnSrc("adoptRelay")));
console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — the wallet reaches the exec node its relay names");
process.exit(fails ? 1 : 0);
