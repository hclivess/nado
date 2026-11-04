/*
 * An NFT minted on nft.nadochain.com whose second signature (register, the royalty) never happened is still an NFT:
 * it is listed in Explore and on its creator's profile, and its page offers the creator the register step.
 *
 * Why: the second signature lived only in the minting tab (localStorage + a prompt cleared before it was answered), and
 * every list on the page was built from REGISTERED tokens only. On 2026-11-04 two of seven NFTs on chain (Nacho1, a
 * Korachi1) were minted, in their creator's wallet with their media pinned, and appeared nowhere on the site.
 *
 * This evaluates the REAL page code (isNft / nftAssets / registeredAssets lifted verbatim from static/nft.js) against
 * the shapes /exec/assets returns, then pins that every view and the register action use them.
 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../static/nft.js", import.meta.url), "utf8");
let fails = 0;
const ok = (name, good, detail = "") => { if (!good) fails++; console.log(`${good ? "PASS" : "FAIL"}  ${name}${good ? "" : ": " + detail}`); };

const lift = (re, what) => { const m = src.match(re); if (!m) { console.log(`FAIL  static/nft.js: no ${what}`); process.exit(1); } return m[0]; };
const code = [
  lift(/^const registeredAssets = .*$/m, "registeredAssets"),
  lift(/^const isNft = .*$/m, "isNft"),
  lift(/^const nftAssets = \(\) => \{\n[\s\S]*?\n\};$/m, "nftAssets"),
].join("\n");

// /exec/assets shapes (the 2026-11-04 Nacho1 row, verbatim apart from the id)
const nacho = { dec: 0, issuer: "6c29de", mintable: false, name: "Nacho1", seed: 459491175, supply: "1", sym: "NFT",
  uri: "ipfs://bafybeiezulyhit7c6dmyupo7zpeosgpjcst75ivmkaauxighvwy25viymi", id: "1035", holders: 1 };
const assets = {
  "1035": nacho,
  "7653": { ...nacho, name: "Korachi1 (registered)", id: "7653" },
  "9001": { ...nacho, name: "a fungible token", sym: "TOK", dec: 8, id: "9001" },
  "9002": { ...nacho, name: "mintable", mintable: true, id: "9002" },
  "9003": { ...nacho, name: "no media", uri: "javascript:alert(1)", id: "9003" },
  "9004": { ...nacho, name: "another sym", sym: "GOLD", id: "9004" },
};
const sto = { t_mk: { "801712978": 1 }, t_asset: { "801712978": "7653" } };
const _m = (s, n) => (s && s[n]) || {};
const ids = (map) => Object.keys(_m(sto, map)).map(Number).sort((a, b) => b - a);
const field = (map, id) => _m(sto, map)[String(id)];
const mediaUrl = (u) => (/^(ipfs:\/\/|https:\/\/)/.test(String(u || "")) ? "u" : "");
const { registeredAssets, isNft, nftAssets } = new Function("assets", "ids", "field", "mediaUrl",
  code + "\nreturn { registeredAssets, isNft, nftAssets };")(assets, ids, field, mediaUrl);

const all = nftAssets();
ok("an NFT minted without its register signature is listed", all.includes("1035"), JSON.stringify(all));
ok("a registered NFT is listed, once", all.filter((a) => a === "7653").length === 1, JSON.stringify(all));
ok("a token with decimals, a mintable asset, an unusable media link and a non-NFT symbol are not",
  !["9001", "9002", "9003", "9004"].some((a) => all.includes(a)), JSON.stringify(all));
ok("negative control: the registered-only list (what the page showed before) misses it", !registeredAssets().includes("1035"));

// every list a person looks for their NFT in is built from nftAssets
const body = (name) => lift(new RegExp(`^function ${name}\\([^)]*\\) \\{\\n[\\s\\S]*?\\n\\}$`, "m"), name);
ok("Explore lists nftAssets()", /const all = nftAssets\(\)/.test(body("viewExplore")));
ok("a profile's created list is nftAssets()", /const created = nftAssets\(\)/.test(body("viewUser")));
ok("a profile's owned list keeps an unregistered NFT", /registered \|\| isNft\(/.test(body("viewUser")));

// the token page offers the register step to its creator only, and the button is wired
const vt = body("viewToken");
ok("the token page renders a register form for an unregistered NFT", /const regForm = !k\.registered && me && me === k\.creator/.test(vt) && /\$\{regForm\}/.test(vt));
ok("the register button is wired to registerLater", /register: \(\) => registerLater\(aid\)/.test(src));
const rl = body("registerLater");
ok("registerLater is the issuer's register call with the asset's own seed (the contract proves hash(issuer, seed))",
  /a\.issuer !== dapp\.me/.test(rl) && /dapp\.call\("register", \[randId\(\), big\(a\.id\), Number\(a\.seed\), bps, coll\]/.test(rl));
ok("registerLater refuses a royalty above the contract's cap", /roy <= MAX_ROYALTY_PCT/.test(rl));

console.log(fails ? `${fails} FAILED` : "ALL PASS — an unregistered mint is shown and its creator can register it");
process.exit(fails ? 1 : 0);
