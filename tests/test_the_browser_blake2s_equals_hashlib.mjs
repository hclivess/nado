// The browser BLAKE2s equals Python's hashlib, and the browser VM hash equals zkvm2.hash_words.
//
// static/blake2s.js is the client half of the gen-29 hashes (Goldilocks retirement G3/G6): a game page recomputes the
// contract VM's hash (zkvm2.hash_words) to show a roll before it settles, and one wrong bit is a page that disagrees
// with the chain it shows. Checked against python3's hashlib over every message length 0..300 (so every block boundary
// and the empty message), with and without a personalization, and hashWords against zkvm2.hash_words over word lists
// with 0, 1, 2^255 and random 256-bit words.
// Run: node tests/test_the_browser_blake2s_equals_hashlib.mjs
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { blake2s, personOf, hashWords } from "../static/blake2s.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };
const hex = (b) => Buffer.from(b).toString("hex");

// deterministic messages: byte i of message n is (n * 31 + i * 7) & 255
const msg = (n) => Uint8Array.from({ length: n }, (_, i) => (n * 31 + i * 7) & 255);
const lengths = Array.from({ length: 301 }, (_, i) => i);
const people = ["", "NADOvmH1", "NADOcsL1", "abcdefgh"];
const py = `
import hashlib, json, sys
out = []
for person in ${JSON.stringify(people)}:
    for n in range(301):
        m = bytes((n * 31 + i * 7) & 255 for i in range(n))
        out.append(hashlib.blake2s(m, digest_size=32, person=person.encode()).hexdigest())
words = [[], [0], [1, 2], [1 << 255, 0, (1 << 256) - 1], [12345678901234567890123456789, 99]]
sys.path.insert(0, ${JSON.stringify(ROOT)})
from execnode import zkvm2
print(json.dumps({"b2": out, "hw": [str(zkvm2.hash_words(w)) for w in words]}))
`;
const ref = JSON.parse(execFileSync("python3", ["-c", py], { env: { ...process.env, HOME: process.env.HOME || "/tmp" } }).toString());
let k = 0, bad = [];
for (const person of people) {
  for (const n of lengths) {
    const got = hex(blake2s(msg(n), person ? personOf(person) : new Uint8Array(0)));
    if (got !== ref.b2[k]) bad.push(`${person || "-"}:${n}`);
    k++;
  }
}
check(`blake2s equals hashlib for ${k} (length, personalization) pairs`, bad.length === 0, bad.slice(0, 5).join(" "));
const words = [[], [0n], [1n, 2n], [1n << 255n, 0n, (1n << 256n) - 1n], [12345678901234567890123456789n, 99n]];
const hw = words.map((w) => hashWords(w).toString());
check("hashWords equals zkvm2.hash_words", JSON.stringify(hw) === JSON.stringify(ref.hw), `${hw} vs ${ref.hw}`);
let threw = false;
try { blake2s(new Uint8Array(1), new Uint8Array(3)); } catch { threw = true; }
check("a personalization that is not 8 bytes is refused", threw);
console.log(fails ? `${fails} FAILURE(S)` : "ALL PASS — the browser BLAKE2s equals hashlib");
process.exit(fails ? 1 : 0);
