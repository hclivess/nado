/*
 * test_the_townspeoples_name_tags_follow_a_language_change_while_playing.mjs — playtest 2026-11-16: the language switched
 * to Arabic while playing, the page turned Arabic but the townspeople's tags still said "Elder" and "Smith" until a
 * reload: a tag is drawn into its own picture once (label). On the language change (the "nado-lang" event) every
 * townsperson's tag is drawn again in the new language, in place, the old picture freed; the quest mark stays. The
 * page's relabelNpcs runs here.
 * Run: node tests/test_the_townspeoples_name_tags_follow_a_language_change_while_playing.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("function relabelNpcs() {"), src = page.slice(i0, page.indexOf("\n}\n", i0) + 2);
let lang = "ar"; const freed = [];
const sprite = (text, sub, mark) => ({ isSprite: true, text, sub, userData: mark ? { mark: true, textW: 0 } : { textW: 0.4 }, position: { x: 0, y: 2.05, z: 0, copy(p) { this.y = p.y; } },
  material: { map: { dispose: () => freed.push(text) }, dispose() {} } });
const mesh = (kids) => ({ children: kids, remove(c) { this.children = this.children.filter((x) => x !== c); }, add(c) { this.children.push(c); } });
const maren = { name: "Maren", role: "elder", mesh: mesh([sprite("Maren", "Elder"), sprite("!", null, true)]) };
const ida = { name: "Ida", role: "smith", mesh: mesh([sprite("Ida", "Smith")]) };
const roles = { ar: { elder: "الحكيمة", smith: "الحدّادة" } };
const relabel = new Function("npcs", "label", "roleName", src + "\nreturn relabelNpcs;")(
  new Map([["elder", maren], ["smith", ida]]), (t, s) => sprite(t, s), (r) => roles[lang][r]);
relabel();
const tag = (m) => m.mesh.children.find((c) => c.userData.textW);
ok(tag(maren).sub === "الحكيمة" && tag(ida).sub === "الحدّادة", "after a change to Arabic both tags read the Arabic role");
ok(tag(maren).text === "Maren" && tag(maren).position.y === 2.05, "…the name kept, the tag in its old place");
ok(maren.mesh.children.filter((c) => c.userData.textW).length === 1 && maren.mesh.children.some((c) => c.userData.mark), "…one tag each, the quest mark left alone");
ok(freed.includes("Maren") && freed.includes("Ida") && !freed.includes("!"), "…and the old pictures freed");
ok(/window\.addEventListener\("nado-lang", \(\) => \{[^\n]*relabelNpcs\(\); \}\);/.test(page), "it runs on the language change");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
