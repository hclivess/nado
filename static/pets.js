// pets.js — NADO Pets: tamagotchi NFTs on the execution layer, built on the shared game SDK (nadodapp.js).
// Every pet is an on-chain asset: a future block hash decides its species/rarity/stats at hatch (via
// pets-genes.js, byte-identical to the contract and differentially verified), it eats real NADO to stay
// alive, trains with a rarity-scaled limit-function success chance, battles other pets for stakes (loser
// has a 20% chance to die), and transfers between wallets like any NFT. All money moves happen in the
// contract (execnode/contracts/pets.json); this file is reads + UI + the wallet-signed calls.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, alertBar, notify, blocksToTime, lsLoad, lsSave, wireWallet, stickyInputs, renderWallet, loadQR, drawQR, resolveAliases, disp, shareInvite, esc } from "./nadodapp.js";
import * as G from "./pets-genes.js";
import { HAND_ART } from "./pets-art-hand.js";   // bespoke per-animal art (grows toward the full roster)
import { loadCrypto, ADDR_PREFIX } from "./nadotx.js";

const CID = "5db6cb731ec1f39cc19a418475517829";   // execnode/games/pets.py (zkVM, nonce "a5")
const dapp = new NadoDapp({ cid: CID, app: "Pets" });

const petSlug = (x) => String(x).toLowerCase().replace(/[^a-z0-9]+/g, "");
const AN = (a) => a ? window.t("pets.an_" + petSlug(a.n), a.n) : "";     // translated animal name
const CN = (c) => c ? window.t("pets.coat_" + petSlug(c.name), c.name) : "";  // translated coat name
const BLOCK_SECS = 6, BLOCKS_PER_DAY = 86400 / BLOCK_SECS;
const LS_P = "nado_pets_mine";                    // {pid: {ts, hatchPending?, trainPending?}} local flags


let active = null, activeBattle = null;
let PETS = {}, BATTLES = {}, OFFERS = {}, hatchPlaying = false, battlePlaying = null;

// ---- SVG art -----------------------------------------------------------------------------------------
// One drawing function per body ARCHETYPE; the 100-animal roster (pets-genes.js) picks an archetype, a
// palette and variant flags `v`. Every moving part sits in its own <g class="…"> — the CSS in pets.html
// animates transform/opacity only (GPU-cheap) with transform-box:fill-box, so origins are geometry-proof.
const INK = "#20242a", BEAKC = "#f2a03b", BEAKL = "#a86a10";
function pomPath(cx, cy, r, n = 8) {
  const pts = [];
  for (let k = 0; k < n; k++) { const a = (-90 + 360 * k / n) * Math.PI / 180; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
  const ar = (r * Math.sin(Math.PI / n) * 1.35).toFixed(1);   // bump radius > half-chord => each arc bulges out
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let k = 1; k <= n; k++) { const [x, y] = pts[k % n]; d += `A${ar} ${ar} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`; }
  return d + "Z";
}
const pom = (cx, cy, r, fill, line, n = 8, w = 2) => `<path d="${pomPath(cx, cy, r, n)}" fill="${fill}" stroke="${line}" stroke-width="${w}" stroke-linejoin="round"/>`;
// FIERCE: challenger-card mode — the same faces render angry (slanted brows, narrowed eyes, a frown).
// Set around a single render, never during normal play.
let FIERCE = 0;
const brow = (x, y, r, col, dir) => `<path d="M${(x - dir * (r + 2.4)).toFixed(1)} ${(y - r - 3.6).toFixed(1)} L${(x + dir * (r + 1.2)).toFixed(1)} ${(y - r - 0.4).toFixed(1)}" stroke="${col}" stroke-width="2.3" stroke-linecap="round"/>`;
const eyes2 = (x1, x2, y, r = 2.6, col = INK) => `<g class="blink">${[[x1, 1], [x2, -1]].map(([x, dir]) =>
  (FIERCE ? `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * .72).toFixed(2)}" fill="${col}"/>` + brow(x, y, r, col, dir)
          : `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}"/>`)
  + `<circle cx="${(x + r * .38).toFixed(1)}" cy="${(y - r * .38).toFixed(1)}" r="${(r * .34).toFixed(2)}" fill="#fff" opacity=".9"/>`).join("")}</g>`;
const eye1 = (x, y, r = 3, col = INK) => `<g class="blink">${FIERCE
  ? `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * .72).toFixed(2)}" fill="${col}"/>` + brow(x, y, r, col, 1)
  : `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}"/>`}<circle cx="${(x + r * .38).toFixed(1)}" cy="${(y - r * .38).toFixed(1)}" r="${(r * .34).toFixed(2)}" fill="#fff" opacity=".9"/></g>`;
// eyes must contrast the coat: dark-bodied animals (black cat, crow, gorilla…) get pale eyes
const lum = (hex) => { const n = parseInt(hex.slice(1), 16); return ((n >> 16) * 3 + ((n >> 8) & 255) * 6 + (n & 255)) / 2550; };
const eyeCol = (c) => lum(c.body) < 0.32 ? "#e9edf2" : INK;
const smilew = (x, y, w2 = 3.4, col = INK) => FIERCE
  ? `<path d="M${x - w2} ${y + 3.2} Q${x} ${y - 1.4} ${x + w2} ${y + 3.2}" stroke="${col}" stroke-width="1.7" fill="none" stroke-linecap="round"/>`
  : `<path d="M${x} ${y} q0 ${w2} -${w2} ${w2 + 1} M${x} ${y} q0 ${w2} ${w2} ${w2 + 1}" stroke="${col}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;
// tube(): an outlined "sausage" stroke — the line color first, the fill color over it (tails, arms, coils)
const tube = (d, fill, line, w = 6) => `<path d="${d}" fill="none" stroke="${line}" stroke-width="${w + 3}" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${fill}" stroke-width="${w}" stroke-linecap="round"/>`;
const MIRROR = (inner) => `<g transform="translate(120 0) scale(-1 1)">${inner}</g>`;   // mirror around x=60

function poodleArt(c) {
  const leg = (x) => `<rect x="${x}" y="88" width="7.5" height="16" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`;
  return `<g class="tail-wag"><path d="M36 78 Q28 70 25 61" stroke="${c.line}" stroke-width="3" fill="none" stroke-linecap="round"/>${pom(23, 55, 8, c.shade, c.line, 7)}</g>
    ${leg(46)}${leg(64)}${pom(49.8, 99.5, 5.4, c.shade, c.line, 6)}${pom(67.8, 99.5, 5.4, c.shade, c.line, 6)}
    <g class="breathe">${pom(42, 84, 15, c.shade, c.line, 9)}${pom(58, 82, 19, c.body, c.line, 10)}</g>
    <rect x="70" y="56" width="10" height="20" rx="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="head-tilt">${pom(63, 50, 8.5, c.shade, c.line, 7)}${pom(97, 50, 8.5, c.shade, c.line, 7)}
      <circle cx="80" cy="44" r="14.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${pom(80, 25.5, 10.5, c.body, c.line, 8)}
      <ellipse cx="80" cy="52.5" rx="7.5" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="80" cy="50.6" rx="3.1" ry="2.3" fill="${eyeCol(c)}"/>${smilew(80, 53.2, 3.4, eyeCol(c))}${eyes2(73.5, 86.5, 42.5, 2.5, eyeCol(c))}</g>`;
}
function quadArt(c, v) {
  const chub = v.chubby ? 3 : 0, W = [], H = [];
  // ears (drawn behind the head)
  if (v.ears === "point") H.push(`<path d="M68 40 L62 22 L78 32 Z M92 40 L98 22 L82 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M68 36 L65 27 L73 32 Z M92 36 L95 27 L87 32 Z" fill="${c.shade}"/>`);
  if (v.ears === "floppy") H.push(`<ellipse cx="66" cy="47" rx="6.2" ry="11.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(14 66 47)"/><ellipse cx="94" cy="47" rx="6.2" ry="11.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(-14 94 47)"/>`);
  if (v.ears === "round") H.push(`<circle cx="67" cy="33" r="7.5" fill="${v.panda ? c.line : c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="93" cy="33" r="7.5" fill="${v.panda ? c.line : c.body}" stroke="${c.line}" stroke-width="2"/>${v.panda ? "" : `<circle cx="67" cy="33" r="4" fill="${c.shade}"/><circle cx="93" cy="33" r="4" fill="${c.shade}"/>`}`);
  if (v.ears === "tall") H.push(`<ellipse cx="72" cy="21" rx="5.6" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2" transform="rotate(-7 72 21)"/><ellipse cx="88" cy="21" rx="5.6" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2" transform="rotate(7 88 21)"/><ellipse cx="72" cy="23" rx="2.6" ry="10" fill="${c.shade}" transform="rotate(-7 72 23)"/><ellipse cx="88" cy="23" rx="2.6" ry="10" fill="${c.shade}" transform="rotate(7 88 23)"/>`);
  if (v.horns) H.push(`<path d="M70 34 C66 26 68 20 75 19 C71 24 72 29 74 33 Z M90 34 C94 26 92 20 85 19 C89 24 88 29 86 33 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`);
  // ANTLERS: branched deer/moose/elk rack (drawn behind the head)
  if (v.antlers) H.push(`<g stroke="${c.shade}" stroke-width="2.6" fill="none" stroke-linecap="round"><path d="M72 33 C66 22 64 14 66 6 M67 18 l-7 -4 M65 11 l-8 -2 M69 24 l-8 -3"/><path d="M88 33 C94 22 96 14 94 6 M93 18 l7 -4 M95 11 l8 -2 M91 24 l8 -3"/></g>`);
  // BIG EARS: elephant / fennec / bat — broad ears fanning out behind the head
  if (v.bigear) H.push(`<ellipse cx="60" cy="44" rx="13" ry="16" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(18 60 44)"/><ellipse cx="100" cy="44" rx="13" ry="16" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(-18 100 44)"/>`);
  // MANE: a full crest running from the poll down the neck to the withers, its outer edge broken into
  // three overlapping locks (+ hair lines) so it reads as a mane of many strands, not the single hanging
  // strand it used to be. Drawn behind the head; the forelock (below, after the face) completes it in front.
  if (v.mane) H.push(`<path d="M71 37 C55 40 46 54 44 72 C43 80 46 89 52 88 C56 82 58 66 64 52 C67 46 70 42 71 37 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/><path d="M67 41 C58 44 51 51 48 61 C52 57 58 53 66 51 Z M64 53 C55 57 49 65 47 76 C51 71 57 67 64 65 Z M60 66 C53 71 49 79 49 88 C53 83 58 80 62 79 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/><path d="M63 45 C56 51 51 61 49 74 M67 48 C60 55 55 66 54 80 M59 60 C54 67 52 76 53 85" stroke="${c.line}" stroke-width="1" fill="none" opacity=".5"/>`);
  if (v.horn) H.push(`<path d="M80 8 L76.5 30 L83.5 30 Z" fill="#f2c94c" stroke="#b58a1a" stroke-width="1.6"/><path d="M77.6 24 l5 -1.6 M78.4 18.5 l4 -1.4 M79.2 13.5 l2.6 -1" stroke="#b58a1a" stroke-width="1.2"/>`);
  // head + face
  H.push(`<circle cx="80" cy="46" r="15" fill="${v.wool ? c.shade : c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  if (v.wool) H.push(pom(80, 30, 10, c.body, c.line, 8));
  if (v.panda) H.push(`<ellipse cx="73.5" cy="45" rx="4.6" ry="6" fill="${c.line}" transform="rotate(-14 73.5 45)"/><ellipse cx="86.5" cy="45" rx="4.6" ry="6" fill="${c.line}" transform="rotate(14 86.5 45)"/>`);
  if (v.mask) H.push(`<path d="M66 41 Q80 35 94 41 L92 49 Q80 43 68 49 Z" fill="${c.line}" opacity=".85"/>`);
  if (v.patch) H.push(`<circle cx="87" cy="44" r="6" fill="${c.shade}" opacity=".9"/>`);
  const eyeY = v.panda || v.mask ? 45.5 : 44;
  H.push(eyes2(74, 86, eyeY, 2.5, v.panda || v.mask ? "#f5f3ee" : eyeCol(c)));
  if (v.snout) H.push(`<ellipse cx="80" cy="55" rx="7" ry="5.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/><circle cx="77.4" cy="55" r="1.2" fill="${INK}"/><circle cx="82.6" cy="55" r="1.2" fill="${INK}"/>`);
  else if (v.bignose) H.push(`<ellipse cx="80" cy="52.5" rx="4.6" ry="6" fill="${INK}"/>${smilew(80, 58, 2.6)}`);
  else H.push(`<ellipse cx="80" cy="52.8" rx="6.8" ry="5" fill="${v.wool || v.panda ? c.body : c.shade}" opacity=".55"/><ellipse cx="80" cy="51" rx="2.9" ry="2.2" fill="${eyeCol(c)}"/>${smilew(80, 53.4, 3.4, eyeCol(c))}`);
  if (v.teeth) H.push(`<rect x="77.4" y="56.5" width="2.4" height="3.6" rx="0.8" fill="#fff" stroke="${c.line}" stroke-width="0.8"/><rect x="80.2" y="56.5" width="2.4" height="3.6" rx="0.8" fill="#fff" stroke="${c.line}" stroke-width="0.8"/>`);
  if (v.whiskers) H.push(`<path d="M70 51 h-9 M70.5 54 l-8.5 2.5 M89.5 51 h9 M89 54 l8.5 2.5" stroke="${INK}" stroke-width="1.1" opacity=".7"/>`);
  if (v.beard) H.push(`<path d="M76 58 Q80 68 84 58 Q82 64 80 65 Q78 64 76 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`);
  // FORELOCK: a short mane crest between the ears on the upper forehead — drawn in FRONT of the head but
  // kept above the eyes so it never crowds the face. The finishing touch that reads unmistakably "equine".
  if (v.mane) H.push(`<path d="M80 29 C74 31 72 36 75 42 C76 38 78 38 79 39 C80 37 81 37 82 39 C85 35 85 31 80 29 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/><path d="M78 33 C77 36 77 39 78 41 M82 33 C82 36 81 39 80 41" stroke="${c.line}" stroke-width="0.9" fill="none" opacity=".45"/>`);
  // tail
  const T = { curl: tube("M30 82 Q18 78 20 66 Q21 58 29 58", c.body, c.line, 5),
    thin: `${tube("M30 86 Q16 88 12 78", c.body, c.line, 3)}<circle cx="12" cy="77" r="2.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`,
    fluff: `<path d="M34 80 C16 86 8 70 15 56 C21 63 30 68 36 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`,
    rings: `<path d="M34 80 C16 86 8 70 15 56 C21 63 30 68 36 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M20 62 q6 3 10 8 M15 68 q7 3 13 8" stroke="${c.line}" stroke-width="3.4" opacity=".8"/>`,
    pom: pom(26, 74, 6.5, c.shade, c.line, 6),
    hair: tube("M32 80 Q22 84 24 100", c.shade, c.line, 6),
    paddle: `<rect x="14" y="82" width="15" height="22" rx="7" fill="${c.line}" opacity=".9" transform="rotate(35 21 93)"/><path d="M17 88 l9 4 M15 94 l9 4" stroke="#0b0d10" stroke-width="1.4" transform="rotate(35 21 93)" opacity=".6"/>` };
  const W2 = [];
  W2.push(`<g class="tail-wag">${T[v.tail] || T.curl}</g>`);
  // legs (far pair shaded, near pair body-colored)
  const legY = 88 - chub / 2;
  W2.push(`<rect x="44" y="${legY}" width="7" height="${104 - legY}" rx="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/><rect x="72" y="${legY}" width="7" height="${104 - legY}" rx="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`);
  W2.push(`<rect x="36" y="${legY}" width="7.5" height="${105 - legY}" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><rect x="64" y="${legY}" width="7.5" height="${105 - legY}" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`);
  // neck: bridge head->body so it doesn't read as a floating head (drawn behind the body, which covers its
  // base for a seamless join). Its shape varies by ear type — a good stand-in for the animal's build — so
  // categories differ at a glance: pricked-ear hunters (cat/fox/squirrel/pony) get a slim upright neck,
  // floppy-ear stock (dogs/cattle/pigs) a thick one, round-ear critters (mice/hamster/bears) a short one,
  // tall-ear (rabbit/donkey) a long slender one. Mane animals additionally get the mane crest on top.
  // each neck TAPERS from a slim throat under the head to wider shoulders (a straight column reads as
  // "sturdy" — wrong on a mouse). Width scales with build: rodents get a delicate throat, stock a thick one.
  const neckD = v.mane ? "M69 45 C63 58 58 70 57 84 L74 84 C78 67 79 55 78 46 Z"           // equine: long, slender
    : v.ears === "floppy" ? "M64 51 C60 63 55 74 54 84 L82 84 C83 71 82 60 80 51 Z"        // dogs/cattle/pigs: thick
    : v.ears === "round" || v.ears === "tall" ? "M71 53 C68 63 65 73 64 83 L76 83 C77 72 77 62 77 54 Z"  // rodents/rabbit: thin & short
    : "M68 50 C63 61 59 72 58 84 L78 84 C80 71 80 60 78 50 Z";                             // cats/foxes: slim upright
  W2.push(`<path d="${neckD}" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>`);
  // body
  if (v.spikes) W2.push(`<path d="M30 82 L34 62 L42 72 L48 56 L57 68 L64 54 L72 66 L80 58 L84 72 L84 84 Z" fill="${c.line}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round" opacity=".92"/>`);
  W2.push(`<g class="breathe">${v.wool ? pom(54, 83, 20 + chub, c.body, c.line, 10)
    : `<ellipse cx="54" cy="${85 - chub / 2}" rx="${26 + chub}" ry="${16 + chub}" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`}`);
  if (v.stripeback) W2.push(`<path d="M30 78 Q54 64 78 76 L78 82 Q54 70 30 84 Z" fill="#f5f3ee" opacity=".92"/>`);
  if (v.stripes) W2.push(`<path d="M44 71 q3 7 0 13 M55 69 q3 8 0 15 M66 71 q3 7 0 13" stroke="${c.shade}" stroke-width="3.2" fill="none" stroke-linecap="round"/>`);
  if (v.spots) W2.push(`<circle cx="44" cy="80" r="3.4" fill="${c.shade}"/><circle cx="58" cy="74" r="2.8" fill="${c.shade}"/><circle cx="52" cy="90" r="2.6" fill="${c.shade}"/><circle cx="68" cy="86" r="3" fill="${c.shade}"/>`);
  if (v.patch) W2.push(`<ellipse cx="46" cy="82" rx="8" ry="6.5" fill="${c.shade}" opacity=".85" transform="rotate(-14 46 82)"/>`);
  if (v.chest) W2.push(`<ellipse cx="68" cy="84" rx="10" ry="10" fill="#f5f0e6" opacity=".85"/>`);
  W2.push(`</g>`);
  return W.join("") + W2.join("") + `<g class="head-tilt">${H.join("")}</g>`;
}
function birdArt(c, v) {
  const B = [], scale = v.tiny ? `transform="translate(13 16) scale(.78)"` : "";
  const legC = "#d98a2b";
  if (v.peafan) B.push(MIRROR("") + `<g class="fan-sway">${[-52, -30, -8, 14, 36].map((a) => `<g transform="rotate(${a} 60 74)"><path d="M60 74 L57 22 Q60 18 63 22 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/><circle cx="60" cy="27" r="5.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.4"/><circle cx="60" cy="27" r="2.4" fill="#f2c040"/></g>`).join("")}</g>`);
  if (v.fan) B.push(`<g class="fan-sway">${[-56, -34, -12, 10, 32, 54].map((a) => `<g transform="rotate(${a} 60 76)"><path d="M60 76 L54 30 Q60 24 66 30 Z" fill="${a % 3 ? c.shade : c.body}" stroke="${c.line}" stroke-width="1.6"/></g>`).join("")}</g>`);
  if (v.flame) B.push(`<g class="flamet flick2">${tube("M50 96 Q42 110 30 112", "#ef8b3a", "#c2571a", 5)}${tube("M60 98 Q58 112 48 118", "#f2c040", "#c2871a", 5)}</g>`);
  else B.push(`<path d="M52 92 C46 104 48 110 54 114 L62 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`);
  const legTop = v.longlegs ? 88 : 94, legBot = v.longlegs ? 116 : 104;
  B.push(`<path d="M55 ${legTop} L53 ${legBot} m-4 0 h8 M65 ${legTop} L67 ${legBot} m-4 0 h8" stroke="${legC}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`);
  B.push(`<g class="breathe"><ellipse cx="60" cy="${v.longlegs ? 64 : 74}" rx="20" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  const chest = v.chest || (v.flame ? "#f2c040" : "");
  if (chest) B.push(`<ellipse cx="60" cy="${v.longlegs ? 70 : 80}" rx="11" ry="13" fill="${chest}" opacity=".92"/>`);
  B.push(`</g>`);
  const wy = v.longlegs ? 52 : 60;
  B.push(`<g class="wing-flap"><path d="M44 ${wy} C30 ${wy + 6} 28 ${wy + 28} 40 ${wy + 36} C48 ${wy + 30} 50 ${wy + 12} 44 ${wy} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>`);
  B.push(`<g class="wing-flap right"><path d="M76 ${wy} C90 ${wy + 6} 92 ${wy + 28} 80 ${wy + 36} C72 ${wy + 30} 70 ${wy + 12} 76 ${wy} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/></g>`);
  const hy = v.longlegs ? 30 : 40;
  const HD = [];
  if (v.tufts) HD.push(`<path d="M48 ${hy - 10} L44 ${hy - 22} L56 ${hy - 14} Z M72 ${hy - 10} L76 ${hy - 22} L64 ${hy - 14} Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`);
  if (v.comb) HD.push(`<circle cx="52" cy="${hy - 14}" r="3.6" fill="#d0362b"/><circle cx="60" cy="${hy - 16.5}" r="4" fill="#d0362b"/><circle cx="68" cy="${hy - 14}" r="3.6" fill="#d0362b"/>`);
  if (v.crest && !v.flame) HD.push(`<path d="M54 ${hy - 13} Q52 ${hy - 26} 60 ${hy - 27} Q58 ${hy - 20} 61 ${hy - 15} Q63 ${hy - 26} 70 ${hy - 24} Q66 ${hy - 18} 66 ${hy - 13} Z" fill="${chest || c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`);
  if (v.flame) HD.push(`<g class="flamet">${tube(`M56 ${hy - 13} Q52 ${hy - 26} 58 ${hy - 32}`, "#ef8b3a", "#c2571a", 4)}${tube(`M62 ${hy - 13} Q64 ${hy - 26} 72 ${hy - 28}`, "#f2c040", "#c2871a", 4)}</g>`);
  HD.push(`<circle cx="60" cy="${hy}" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  if (v.owl) {
    HD.push(`<circle cx="53" cy="${hy}" r="6.8" fill="#f2ead2" stroke="${c.line}" stroke-width="1.5"/><circle cx="67" cy="${hy}" r="6.8" fill="#f2ead2" stroke="${c.line}" stroke-width="1.5"/>`);
    HD.push(`<g class="blink"><circle cx="53" cy="${hy}" r="3.4" fill="#e8a83b"/><circle cx="67" cy="${hy}" r="3.4" fill="#e8a83b"/><circle cx="53" cy="${hy}" r="1.7" fill="${INK}"/><circle cx="67" cy="${hy}" r="1.7" fill="${INK}"/></g>`);
    HD.push(`<path d="M60 ${hy + 2} L57 ${hy + 6} L60 ${hy + 9} L63 ${hy + 6} Z" fill="${BEAKC}" stroke="${BEAKL}" stroke-width="1.4" stroke-linejoin="round"/>`);
  } else if (v.beak === "flat") {
    HD.push(eyes2(53.5, 66.5, hy - 3, 2.6, eyeCol(c)));
    HD.push(`<ellipse cx="60" cy="${hy + 7}" rx="8.4" ry="4.4" fill="${BEAKC}" stroke="${BEAKL}" stroke-width="1.6"/><circle cx="57" cy="${hy + 6}" r="0.9" fill="${BEAKL}"/><circle cx="63" cy="${hy + 6}" r="0.9" fill="${BEAKL}"/>`);
  } else {
    HD.push(eyes2(53.5, 66.5, hy - 3, 2.6, eyeCol(c)));
    HD.push(`<path d="M54.5 ${hy + 3} L65.5 ${hy + 3} L60 ${hy + 10.5} Z" fill="${BEAKC}" stroke="${BEAKL}" stroke-width="1.5" stroke-linejoin="round"/>`);
  }
  if (v.wattle) HD.push(`<path d="M58 ${hy + 9} q2 7 4 0 q-1 6 -2 6 t-2 -6 Z" fill="#d0362b" stroke="#8a1a12" stroke-width="1.2"/>`);
  B.push(`<g class="head-tilt">${HD.join("")}</g>`);
  return scale ? `<g ${scale}>${B.join("")}</g>` : B.join("");
}
function parrotArt(c, v) {
  const tail = v.tail || "#d0362b", B = [];
  B.push(`<g class="tail-bob"><path d="M53 90 Q50 106 55 116 L59 116 Q56 104 58 92 Z" fill="${tail}" stroke="${INK}" stroke-width="1.6" opacity=".92"/><path d="M61 92 Q60 106 64 118 L68 117 Q66 104 66 93 Z" fill="${tail}" stroke="${INK}" stroke-width="1.6"/></g>`);
  B.push(`<path d="M50 98 l-3 6 m3 -6 l0 7 m0 -7 l3 6 M68 98 l-3 6 m3 -6 l0 7 m0 -7 l3 6" stroke="#6b6f76" stroke-width="2" stroke-linecap="round"/>`);
  B.push(`<g class="breathe"><ellipse cx="59" cy="72" rx="21" ry="24" fill="${c.shade}" stroke="${c.line}" stroke-width="2.5"/>
    <ellipse cx="59" cy="78" rx="13" ry="15" fill="${c.body}"/>
    <path d="M50 72 q9 5 18 0 M49 80 q10 5 20 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".8"/></g>`);
  B.push(`<g class="wing-flap"><path d="M42 58 C28 64 26 86 38 96 C46 90 48 70 42 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M38 70 q-2 10 2 18 M42 66 q-3 12 0 22" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".55"/></g>`);
  B.push(`<g class="wing-flap right"><path d="M76 58 C90 64 92 86 80 96 C72 90 70 70 76 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M80 70 q2 10 -2 18 M76 66 q3 12 0 22" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".55"/></g>`);
  const HD = [];
  if (v.bigcrest) HD.push(`<g class="fan-sway">${[-36, -16, 4, 22].map((a) => `<path d="M59 26 Q${59 + a} ${8 - Math.abs(a) / 4} ${59 + a * 1.4} ${14 - Math.abs(a) / 5}" stroke="${v.tail}" stroke-width="4.5" fill="none" stroke-linecap="round"/>`).join("")}</g>`);
  else if (v.crest) HD.push(`<path d="M52 25 Q50 12 58 10 Q56 18 60 24 Q62 12 70 13 Q65 19 65 25 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`);
  HD.push(`<circle cx="59" cy="38" r="16.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  if (v.bigbeak) {
    HD.push(`<ellipse cx="53" cy="36" rx="6.6" ry="8" fill="#eef1f4" stroke="${c.shade}" stroke-width="1.4"/>${eye1(53, 36, 2.7)}`);
    HD.push(`<path d="M62 32 C84 28 94 36 90 47 C84 55 70 52 63 46 Q60 39 62 32 Z" fill="${v.bigbeak}" stroke="${BEAKL}" stroke-width="1.8" stroke-linejoin="round"/><path d="M64 34 Q78 32 86 38" stroke="${BEAKL}" stroke-width="1.2" fill="none" opacity=".6"/><circle cx="87" cy="45" r="2.8" fill="#2b2b2b" opacity=".35"/>`);
  } else {
    // the African-grey signature: bare white eye patches + a SMOOTH centered hook beak (no stray lines)
    HD.push(`<ellipse cx="51.5" cy="36.5" rx="6.4" ry="7.8" fill="#eef1f4" stroke="${c.shade}" stroke-width="1.4"/><ellipse cx="66.5" cy="36.5" rx="6.4" ry="7.8" fill="#eef1f4" stroke="${c.shade}" stroke-width="1.4"/>`);
    HD.push(eyes2(51.5, 66.5, 36.5, 2.6));
    HD.push(`<ellipse cx="59" cy="54.2" rx="3.7" ry="2.3" fill="#23262b"/>`);
    HD.push(`<path d="M52.6 40.5 C52.6 35.2 55.5 33 59 33 C62.5 33 65.4 35.2 65.4 40.5 C65.4 46.4 62.9 52.3 59.8 55.6 C59.4 56.1 58.7 56.1 58.4 55.6 C55.5 51.2 52.9 45.6 52.6 40.5 Z" fill="#3a3f45" stroke="#16181c" stroke-width="1.7" stroke-linejoin="round"/>`);
    HD.push(`<circle cx="56.6" cy="36.8" r="0.85" fill="#16181c"/><circle cx="61.4" cy="36.8" r="0.85" fill="#16181c"/><path d="M55 38.5 Q59 36.6 63 38.5" stroke="#565b63" stroke-width="1" fill="none" opacity=".8"/>`);
  }
  return B.join("") + `<g class="head-tilt">${HD.join("")}</g>`;
}
function penguinArt(c) {
  return `<path d="M48 100 l-5 4 h11 Z M72 100 l5 4 h-11 Z" fill="${BEAKC}" stroke="${BEAKL}" stroke-width="1.6" stroke-linejoin="round"/>
    <g class="breathe"><path d="M60 18 C40 18 37 44 39 68 C41 92 48 102 60 102 C72 102 79 92 81 68 C83 44 80 18 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M60 34 C50 34 46 52 47 70 C48 88 53 98 60 98 C67 98 72 88 73 70 C74 52 70 34 60 34 Z" fill="#f2f4f6"/></g>
    <g class="wing-flap"><path d="M41 52 C33 62 33 82 40 90 C45 84 46 64 44 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="wing-flap right"><path d="M79 52 C87 62 87 82 80 90 C75 84 74 64 76 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="head-tilt"><circle cx="53" cy="32" r="5.8" fill="#f2f4f6"/><circle cx="67" cy="32" r="5.8" fill="#f2f4f6"/>
    ${eyes2(53, 67, 32, 2.4)}
    <path d="M55 39 L65 39 L60 46 Z" fill="${BEAKC}" stroke="${BEAKL}" stroke-width="1.5" stroke-linejoin="round"/></g>`;
}
function fishArt(c, v) {
  const big = v.big ? 1.15 : 1, F = [];
  const cy = 64;
  if (v.puffer) {
    F.push(`<g class="breathe2">${[...Array(12)].map((_, i) => { const a = i * 30 * Math.PI / 180; return `<path d="M${60 + 19 * Math.cos(a)} ${cy + 19 * Math.sin(a)} L${60 + 27 * Math.cos(a)} ${cy + 27 * Math.sin(a)}" stroke="${c.shade}" stroke-width="2.6" stroke-linecap="round"/>`; }).join("")}
      <circle cx="60" cy="${cy}" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <circle cx="53" cy="${cy + 6}" r="1.6" fill="${c.shade}"/><circle cx="63" cy="${cy + 8}" r="1.4" fill="${c.shade}"/><circle cx="58" cy="${cy - 6}" r="1.5" fill="${c.shade}"/></g>`);
    F.push(`<g class="fin-wave"><path d="M42 ${cy - 4} L30 ${cy - 12} Q32 ${cy} 30 ${cy + 10} L42 ${cy + 4} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/></g>`);
    F.push(`${eyes2(66, 78, cy - 6, 2.8)}<path d="M70 ${cy + 4} q3 2.5 6 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>`);
  } else {
    const rx = 24 * big, ry = (v.tall ? 20 : 15) * big;
    F.push(`<g class="fin-wave"><path d="M${60 - rx + 3} ${cy} L${60 - rx - 14} ${cy - 15} Q${60 - rx - 9} ${cy} ${60 - rx - 14} ${cy + 15} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>`);
    if (v.fan) F.push(`<g class="fin-wave"><path d="M${60 - rx + 4} ${cy} C${60 - rx - 18} ${cy - 22} ${60 - rx - 24} ${cy + 2} ${60 - rx - 16} ${cy + 20} C${60 - rx - 8} ${cy + 12} ${60 - rx - 4} ${cy + 4} ${60 - rx + 4} ${cy} Z" fill="${c.body}" opacity=".7" stroke="${c.line}" stroke-width="1.6"/></g>`);
    F.push(`<path d="M${60 - rx / 2} ${cy - ry + 4} Q60 ${cy - ry - (v.dorsal ? 20 : v.tall ? 16 : 9)} ${60 + rx / 3} ${cy - ry + 3} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`);
    if (v.tall) F.push(`<path d="M${60 - rx / 3} ${cy + ry - 4} Q60 ${cy + ry + 14} ${60 + rx / 3} ${cy + ry - 3} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`);
    F.push(`<g class="breathe2"><ellipse cx="60" cy="${cy}" rx="${rx}" ry="${ry}" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
    if (v.dorsal) F.push(`<path d="M${60 - rx} ${cy} Q60 ${cy + ry * 0.9} ${60 + rx - 4} ${cy + 4} Q60 ${cy + ry * 0.4} ${60 - rx} ${cy} Z" fill="#e9ecf2" opacity=".9"/>`);
    if (v.stripes) F.push(`<path d="M50 ${cy - ry + 2} q3 ${ry} 0 ${2 * ry - 4} M64 ${cy - ry + 2} q3 ${ry} 0 ${2 * ry - 4}" stroke="#f2f4f6" stroke-width="5" fill="none"/><path d="M50 ${cy - ry + 2} q3 ${ry} 0 ${2 * ry - 4} M64 ${cy - ry + 2} q3 ${ry} 0 ${2 * ry - 4}" stroke="${c.line}" stroke-width="6.5" fill="none" opacity=".25"/>`);
    if (v.patch) F.push(`<circle cx="52" cy="${cy - 6}" r="5.5" fill="#e05a3a" opacity=".9"/><circle cx="68" cy="${cy + 5}" r="4" fill="#e05a3a" opacity=".8"/>`);
    F.push(`</g>`);
    F.push(`<g class="fin-wave2"><path d="M58 ${cy + 6} Q50 ${cy + 16} 56 ${cy + 20} Q62 ${cy + 16} 62 ${cy + 8} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/></g>`);
    F.push(`${eye1(72 * big > 74 ? 74 : 72, cy - 5, 3)}`);
    F.push(v.dorsal ? `<path d="M${60 + rx - 10} ${cy + 5} q4 3 8 0" stroke="${INK}" stroke-width="1.7" fill="none" stroke-linecap="round"/><path d="M${60 + rx - 8.5} ${cy + 6.5} l1.5 2 l1.6 -2 l1.6 2 l1.5 -2" stroke="#fff" stroke-width="1.4" fill="none"/>` : `<path d="M${60 + rx - 6} ${cy + 3} q2.5 2 5 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>`);
    F.push(`<path d="M${60 + rx * 0.45} ${cy - 4} q-3 4.5 0 9" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".55"/>`);
  }
  F.push(`<g class="bub"><circle cx="92" cy="44" r="2.6" fill="none" stroke="#9fd4f2" stroke-width="1.4"/></g><g class="bub b2"><circle cx="97" cy="50" r="1.8" fill="none" stroke="#9fd4f2" stroke-width="1.3"/></g>`);
  return F.join("");
}
function whaleArt(c, v) {
  const W = [];
  W.push(`<g class="fin-wave"><path d="M32 74 L15 60 Q21 73 15 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>`);
  W.push(`<g class="breathe2"><path d="M28 76 C28 52 44 44 62 44 C82 44 92 58 92 70 C92 84 82 92 60 92 C40 92 28 88 28 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M34 82 C46 90 74 90 88 78 L88 82 C76 92 44 92 32 84 Z" fill="#e9ecf2" opacity=".85"/>
    <path d="M40 84 q4 3 9 4 M54 88 q5 1.5 10 1" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/></g>`);
  if (v.snout) W.push(`<ellipse cx="92" cy="76" rx="7" ry="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`);
  W.push(`<g class="fin-wave2"><path d="M56 88 Q50 100 58 104 Q64 98 62 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/></g>`);
  W.push(`${eye1(78, 66, 2.9)}<path d="M84 74 q4 3 8 0" stroke="${INK}" stroke-width="1.7" fill="none" stroke-linecap="round"/>`);
  W.push(`<g class="spout"><path d="M64 42 Q62 32 54 28 M64 42 Q66 31 74 27 M64 42 Q64 30 64 24" stroke="#9fd4f2" stroke-width="2.4" fill="none" stroke-linecap="round"/><circle cx="52" cy="26" r="1.6" fill="#9fd4f2"/><circle cx="76" cy="25" r="1.6" fill="#9fd4f2"/><circle cx="64" cy="21" r="1.8" fill="#9fd4f2"/></g>`);
  if (v.stars) W.push(`<g class="twinkle"><path d="M48 62 l1.4 3 3 1.4 -3 1.4 -1.4 3 -1.4 -3 -3 -1.4 3 -1.4 Z" fill="#ffe08a"/></g><g class="twinkle t2"><path d="M68 56 l1.1 2.4 2.4 1.1 -2.4 1.1 -1.1 2.4 -1.1 -2.4 -2.4 -1.1 2.4 -1.1 Z" fill="#bfe4ff"/></g><g class="twinkle t3"><circle cx="58" cy="70" r="1.4" fill="#ffe08a"/></g>`);
  return W.join("");
}
function octoArt(c, v) {
  const big = v.big ? 1.12 : 1, O = [];
  const arms = [[42, -1], [50, 1], [58, -1], [66, 1], [74, -1]];
  O.push(arms.map(([x, s], i) => `<g class="${i % 2 ? "tenA" : "tenB"}">${tube(`M${x} 72 C${x - 2 * s} 86 ${x - 10 * s} 92 ${x - 8 * s} 100 Q${x - 7 * s} 105 ${x - 1 * s} 103`, c.body, c.line, 5.5)}</g>`).join(""));
  if (v.cone) O.push(`<path d="M60 6 L44 46 L76 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`);
  O.push(`<g class="breathe"><path d="M${60 - 22 * big} 62 C${60 - 22 * big} ${62 - 34 * big} ${60 + 22 * big} ${62 - 34 * big} ${60 + 22 * big} 62 C${60 + 22 * big} 70 ${60 + 18 * big} 74 ${60 + 14 * big} 74 L${60 - 14 * big} 74 C${60 - 18 * big} 74 ${60 - 22 * big} 70 ${60 - 22 * big} 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  O.push(`<circle cx="50" cy="46" r="2" fill="${c.shade}"/><circle cx="70" cy="44" r="2.4" fill="${c.shade}"/><circle cx="60" cy="38" r="1.8" fill="${c.shade}"/></g>`);
  const eyec = v.glow ? "#ffd35a" : INK;
  O.push(v.glow ? `<g class="blink"><circle cx="52" cy="56" r="3.4" fill="${eyec}" class="glowpulse"/><circle cx="68" cy="56" r="3.4" fill="${eyec}" class="glowpulse"/></g>` : eyes2(52, 68, 56, 3.2));
  O.push(`<path d="M56 64 q4 3.5 8 0" stroke="${v.glow ? "#e9ecf2" : INK}" stroke-width="1.7" fill="none" stroke-linecap="round"/>`);
  O.push(`<g class="bub"><circle cx="90" cy="40" r="2.4" fill="none" stroke="#9fd4f2" stroke-width="1.4"/></g>`);
  return O.join("");
}
function jellyArt(c) {
  return `${[[46, "tenA"], [55, "tenB"], [65, "tenA"], [74, "tenB"]].map(([x, k]) =>
      `<g class="${k}"><path d="M${x} 66 Q${x - 5} 80 ${x + 2} 90 Q${x + 6} 98 ${x - 2} 104" stroke="${c.shade}" stroke-width="2.6" fill="none" stroke-linecap="round" opacity=".8"/></g>`).join("")}
    <g class="breathe"><path d="M36 56 Q36 26 60 26 Q84 26 84 56 Q84 66 60 66 Q36 66 36 56 Z" fill="${c.body}" opacity=".85" stroke="${c.line}" stroke-width="2.2"/>
    <path d="M38 58 q5.5 6 11 0 q5.5 6 11 0 q5.5 6 11 0 q5.5 6 11 0" stroke="${c.line}" stroke-width="1.6" fill="none" opacity=".6"/>
    <ellipse cx="54" cy="40" rx="9" ry="7" fill="#fff" opacity=".35"/></g>
    ${eyes2(53, 67, 50, 2.6)}<path d="M56 57 q4 3 8 0" stroke="${INK}" stroke-width="1.6" fill="none" stroke-linecap="round"/>`;
}
function turtleArt(c, v) {
  const T = [];
  T.push(`<g class="tail-wag">${tube("M34 92 Q26 92 24 87", c.body, c.line, 4)}</g>`);
  if (v.flippers) T.push(`<g class="fin-wave"><path d="M44 94 Q30 102 24 98 Q32 90 42 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g><g class="fin-wave2"><path d="M72 94 Q80 104 90 102 Q84 92 74 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>`);
  else T.push(`<ellipse cx="42" cy="98" rx="6.5" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><ellipse cx="72" cy="98" rx="6.5" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`);
  T.push(`<g class="head-tilt"><circle cx="93" cy="80" r="9.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>${eye1(95.5, 77.5, 2.2)}<path d="M96 84 q2.5 1.8 5 0" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/></g>`);
  T.push(`<g class="breathe"><path d="M30 86 Q30 54 59 54 Q88 54 88 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="M45 60 Q45 76 45 84 M59 56 L59 86 M73 60 Q73 76 73 84 M34 74 Q59 66 84 74" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".5"/>
    <path d="M28 86 Q59 80 90 86 L90 90 Q59 96 28 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>`);
  return T.join("");
}
function snailArt(c) {
  return `<path d="M34 96 Q34 88 44 88 L82 88 Q94 88 96 96 Q97 102 88 102 L41 102 Q34 102 34 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
    <g class="head-tilt"><path d="M80 90 Q88 88 90 80 Q91 76 91 72" stroke="${c.body}" stroke-width="9" fill="none" stroke-linecap="round"/><path d="M80 90 Q88 88 90 80 Q91 76 91 72" stroke="${c.line}" stroke-width="11" fill="none" stroke-linecap="round" opacity=".28"/>
    <circle cx="91" cy="70" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="antA">${tube("M88 64 Q86 56 83 53", c.body, c.line, 2.4)}<circle cx="82.6" cy="52" r="2.6" fill="${INK}"/></g>
    <g class="antB">${tube("M94 64 Q96 56 99 53", c.body, c.line, 2.4)}<circle cx="99.4" cy="52" r="2.6" fill="${INK}"/></g>
    <path d="M92 76 q2.5 2 5 0" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/></g>
    <g class="breathe"><circle cx="52" cy="70" r="21" fill="${c.shade}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M52 70 m0 -15 a15 15 0 1 1 -15 15 a11 11 0 1 0 11 -11 a7 7 0 1 1 -7 7" stroke="${c.line}" stroke-width="1.8" fill="none" opacity=".65"/></g>`;
}
function crabArt(c, v) {
  if (v.slim) {   // shrimp: a curled, segmented tail + long antennae
    return `<g class="antA">${tube("M76 52 Q94 42 104 44", c.shade, c.line, 1.8)}</g><g class="antB">${tube("M76 56 Q96 52 106 58", c.shade, c.line, 1.8)}</g>
      <g class="breathe"><path d="M72 52 C88 56 90 74 76 84 C64 92 46 92 38 84 L46 78 C54 84 66 84 72 78 C78 70 74 60 66 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 60 q8 4 8 14 M50 64 q8 6 6 16 M42 72 q6 4 6 10" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".5"/>
      <path d="M38 84 L26 78 Q30 88 26 94 L40 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
      ${eye1(72, 50, 2.6)}
      <path d="M70 66 l-4 8 m8 -6 l-3 8 m9 -6 l-4 7" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>`;
  }
  const K = [];
  K.push(`<g class="antA"><path d="M50 62 L46 50" stroke="${c.line}" stroke-width="2"/><circle cx="45.4" cy="48" r="3" fill="${INK}"/><circle cx="46.4" cy="47" r="1" fill="#fff" opacity=".9"/></g>`);
  K.push(`<g class="antB"><path d="M70 62 L74 50" stroke="${c.line}" stroke-width="2"/><circle cx="74.6" cy="48" r="3" fill="${INK}"/><circle cx="75.6" cy="47" r="1" fill="#fff" opacity=".9"/></g>`);
  K.push([[-1, 0], [-1, 8], [-1, 16], [1, 0], [1, 8], [1, 16]].map(([s, dy]) =>
    `<path d="M${60 + 18 * s} ${80 + dy / 2} L${60 + 32 * s} ${76 + dy} L${60 + 38 * s} ${86 + dy}" stroke="${c.line}" stroke-width="2.6" fill="none" stroke-linecap="round"/>`).join(""));
  K.push(`<g class="clawL">${tube("M44 76 Q32 70 28 62", c.body, c.line, 5)}<path d="M30 48 Q19 51 21 61 Q27 67 35 62 Q38 52 30 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M25 54 l7 5" stroke="${c.line}" stroke-width="1.6"/></g>`);
  K.push(`<g class="clawR">${tube("M76 76 Q88 70 92 62", c.body, c.line, 5)}<path d="M90 48 Q101 51 99 61 Q93 67 85 62 Q82 52 90 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M95 54 l-7 5" stroke="${c.line}" stroke-width="1.6"/></g>`);
  if (v.shell) K.push(`<g class="breathe"><circle cx="60" cy="68" r="20" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/><path d="M60 68 m0 -14 a14 14 0 1 1 -14 14 a10 10 0 1 0 10 -10 a6 6 0 1 1 -6 6" stroke="${c.line}" stroke-width="1.6" fill="none" opacity=".6"/></g><ellipse cx="60" cy="88" rx="19" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`);
  else K.push(`<g class="breathe"><ellipse cx="60" cy="80" rx="22" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/><path d="M46 74 q14 -7 28 0" stroke="${c.line}" stroke-width="1.3" fill="none" opacity=".45"/></g>`);
  K.push(`<path d="M54 ${v.shell ? 92 : 84} q6 4 12 0" stroke="${INK}" stroke-width="1.7" fill="none" stroke-linecap="round"/>`);
  return K.join("");
}
function bugArt(c, v) {
  const B = [];
  if (v.jumper) {   // grasshopper/cricket: side profile — hind jumping legs plus front & mid walking legs
    return `<g class="antA">${tube("M84 58 Q96 44 108 40", c.shade, c.line, 1.8)}</g><g class="antB">${tube("M82 56 Q90 42 98 34", c.shade, c.line, 1.8)}</g>
      <path d="M76 82 L79 95 L87 100 M62 84 L60 96 L69 101" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <g class="breathe"><path d="M28 78 Q40 64 66 66 L84 68 Q92 70 90 76 Q86 84 66 86 Q40 88 28 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 70 Q64 64 84 70" stroke="${c.shade}" stroke-width="2.4" fill="none"/><path d="M46 74 l-2 8 M56 72 l-1 10 M66 72 l0 10" stroke="${c.line}" stroke-width="1.2" opacity=".45" fill="none"/></g>
      <g class="hopleg"><path d="M21 55 L36 101 L44 103" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M50 80 Q22 82 20 53 Q26 68 42 76 Q50 79 50 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M44 78 Q30 78 24 60" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/></g>
      <circle cx="86" cy="64" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>${eye1(89, 62, 2.6)}
      <path d="M90 68 q2.5 1.6 5 -0.5" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>`;
  }
  if (v.legs8) B.push([[-1, -6], [-1, 2], [-1, 10], [-1, 18], [1, -6], [1, 2], [1, 10], [1, 18]].map(([s, dy]) =>
    `<path d="M${60 + 12 * s} ${72 + dy / 2} Q${60 + 30 * s} ${62 + dy} ${60 + 36 * s} ${76 + dy}" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join(""));
  else B.push([[-1, 0], [-1, 9], [-1, 18], [1, 0], [1, 9], [1, 18]].map(([s, dy]) =>
    `<path d="M${60 + 13 * s} ${64 + dy} L${60 + 28 * s} ${58 + dy} L${60 + 33 * s} ${68 + dy}" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join(""));
  B.push(`<g class="antA">${tube("M54 42 Q48 32 42 28", c.shade, c.line, 2)}<circle cx="41" cy="27" r="2" fill="${c.line}"/></g>`);
  B.push(`<g class="antB">${tube("M66 42 Q72 32 78 28", c.shade, c.line, 2)}<circle cx="79" cy="27" r="2" fill="${c.line}"/></g>`);
  if (v.pincers) B.push(`<path d="M50 40 C42 30 44 20 54 18 C48 24 50 32 56 36 Z M70 40 C78 30 76 20 66 18 C72 24 70 32 64 36 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`);
  if (v.wings) B.push(`<g class="buzzL"><ellipse cx="38" cy="58" rx="16" ry="8" fill="#eef4f8" opacity=".65" stroke="#b9c6d2" stroke-width="1.4" transform="rotate(-24 38 58)"/></g><g class="buzzR"><ellipse cx="82" cy="58" rx="16" ry="8" fill="#eef4f8" opacity=".65" stroke="#b9c6d2" stroke-width="1.4" transform="rotate(24 82 58)"/></g>`);
  const slim = v.slim ? 4 : 0, ab = v.chubby ? 2 : 0;
  if (v.legs8) B.push(`<g class="breathe"><circle cx="60" cy="80" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/><circle cx="60" cy="56" r="10" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/><path d="M56 78 q4 8 8 0 M52 86 q8 6 16 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".8"/></g>`);
  else if (v.wasp) B.push(`<g class="breathe"><ellipse cx="60" cy="56" rx="9" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><path d="M55.5 63 h9 l-1 5 h-7 Z" fill="${c.line}"/><path d="M51 71 Q60 66 69 71 Q67 91 60 102 Q53 91 51 71 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>${v.stripes ? `<path d="M53 77 q7 3 14 0 M55 85 q5 3 10 0" stroke="${INK}" stroke-width="4.2" fill="none"/>` : ""}<path d="M60 102 l-2.4 7 l2.4 2.4 l2.4 -2.4 Z" fill="${c.line}"/></g>`);
  else {
    const brx = v.bumble ? 20 : 16 - slim + ab, bry = v.bumble ? 19 : 20 + ab, bcy = 76 + (v.bumble ? 2 : ab);
    B.push(`<g class="breathe">`);
    if (v.bumble) B.push(`<g>${[...Array(22)].map((_, k) => { const a = k * Math.PI * 2 / 22, x = 60 + brx * Math.cos(a), y = bcy + bry * Math.sin(a); return `<path d="M${x.toFixed(1)} ${y.toFixed(1)} l${(3.2 * Math.cos(a)).toFixed(1)} ${(3.2 * Math.sin(a)).toFixed(1)}" stroke="${c.shade}" stroke-width="1.8" stroke-linecap="round"/>`; }).join("")}</g>`);
    B.push(`<ellipse cx="60" cy="${bcy}" rx="${brx}" ry="${bry}" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>`);
    if (!v.slim && !v.bumble) B.push(`<path d="M60 ${57 + ab} L60 ${95 + ab}" stroke="${c.line}" stroke-width="1.6" opacity=".7"/>`);
    if (v.stripes) B.push(v.bumble
      ? `<path d="M41 68 q19 8 38 0 M42 82 q18 8 36 0 M46 94 q14 6 28 0" stroke="${INK}" stroke-width="6.5" fill="none"/>`
      : `<path d="M${46 + slim} 68 q14 5 ${28 - 2 * slim} 0 M${45 + slim} 78 q15 5 ${30 - 2 * slim} 0 M${47 + slim} 88 q13 5 ${26 - 2 * slim} 0" stroke="${INK}" stroke-width="4.6" fill="none"/>`);
    if (v.spots) B.push(`<circle cx="52" cy="68" r="3" fill="${INK}"/><circle cx="68" cy="68" r="3" fill="${INK}"/><circle cx="50" cy="82" r="2.6" fill="${INK}"/><circle cx="70" cy="82" r="2.6" fill="${INK}"/><circle cx="60" cy="91" r="2.8" fill="${INK}"/>`);
    if (v.sheen) B.push(`<ellipse cx="53" cy="68" rx="4.5" ry="8" fill="#fff" opacity=".28" transform="rotate(16 53 68)"/>`);
    if (v.glow) B.push(`<ellipse cx="60" cy="90" rx="9" ry="7" fill="#ffe08a" class="glowpulse"/>`);
    if (v.slim) B.push(`<ellipse cx="60" cy="58" rx="8.5" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`);
    else B.push(`<ellipse cx="60" cy="55" rx="10" ry="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`);
    B.push(`</g>`);
  }
  B.push(`<circle cx="60" cy="${v.legs8 ? 52 : 44}" r="${v.legs8 ? 0 : 8.5}" fill="${c.shade}" stroke="${c.line}" stroke-width="${v.legs8 ? 0 : 2.2}"/>`);
  const bec = lum(c.shade) < 0.32 ? "#e9edf2" : INK;   // bug faces sit on the shade color
  B.push(v.legs8 ? `${eyes2(56, 64, 54, 2.6, bec)}<circle cx="52" cy="58" r="1.2" fill="${bec}"/><circle cx="68" cy="58" r="1.2" fill="${bec}"/>` : `${eyes2(56.5, 63.5, 43, 2.2, bec)}<path d="M57.5 48 q2.5 1.8 5 0" stroke="${bec}" stroke-width="1.4" fill="none" stroke-linecap="round"/>`);
  return B.join("");
}
function butterflyArt(c, v) {
  const upper = v.slim
    ? `<ellipse cx="34" cy="56" rx="22" ry="6" fill="${c.body}" opacity=".8" stroke="${c.line}" stroke-width="1.6" transform="rotate(-12 34 56)"/><ellipse cx="36" cy="68" rx="19" ry="5" fill="${c.shade}" opacity=".75" stroke="${c.line}" stroke-width="1.5" transform="rotate(6 36 68)"/>`
    : `<path d="M56 62 C42 38 20 40 21 58 C22 72 40 78 56 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
       <path d="M56 74 C44 82 34 94 43 99 C52 102 57 90 57 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
       ${v.veins ? `<path d="M54 66 L30 52 M54 68 L26 60 M54 70 L34 72 M55 78 L44 90" stroke="${c.line}" stroke-width="1.3" opacity=".7" fill="none"/><circle cx="27" cy="50" r="1.5" fill="#fff"/><circle cx="23" cy="60" r="1.5" fill="#fff"/><circle cx="33" cy="70" r="1.5" fill="#fff"/>` : `<circle cx="36" cy="56" r="4.5" fill="#fff" opacity=".55"/><circle cx="44" cy="88" r="2.6" fill="#fff" opacity=".5"/>`}`;
  const wingL = `<g class="bwing">${upper}</g>`;
  return `${wingL}${MIRROR(wingL)}
    <ellipse cx="60" cy="${v.slim ? 74 : 72}" rx="4.2" ry="${v.slim ? 22 : 16}" fill="${v.fuzz ? c.shade : INK}" stroke="${v.fuzz ? c.line : "#0c0e10"}" stroke-width="1.6"/>
    ${v.slim ? `<path d="M60 88 L60 100 m-2.5 -10 h5 m-5 5 h5" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>` : ""}
    <circle cx="60" cy="52" r="6" fill="${v.fuzz ? c.shade : INK}" stroke="${v.fuzz ? c.line : "#0c0e10"}" stroke-width="1.6"/>
    <g class="antA">${tube("M57 48 Q52 38 46 35", v.fuzz ? c.shade : INK, "#0c0e10", 1.8)}<circle cx="45" cy="34" r="1.8" fill="${INK}"/></g>
    <g class="antB">${tube("M63 48 Q68 38 74 35", v.fuzz ? c.shade : INK, "#0c0e10", 1.8)}<circle cx="75" cy="34" r="1.8" fill="${INK}"/></g>
    <circle cx="57.6" cy="51" r="1.5" fill="#fff"/><circle cx="62.4" cy="51" r="1.5" fill="#fff"/>`;
}
function frogArt(c, v) {
  const F = [];
  if (v.fintail) F.push(`<g class="tail-wag"><path d="M36 86 C22 84 16 74 20 62 C26 70 34 76 40 80 Z" fill="${c.shade}" opacity=".85" stroke="${c.line}" stroke-width="2"/></g>`);
  F.push(`<ellipse cx="40" cy="90" rx="10.5" ry="9" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>`);
  F.push(`<g class="breathe"><path d="M34 92 Q30 64 60 62 Q90 64 86 92 Q88 101 76 101 L44 101 Q32 101 34 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
    <ellipse cx="60" cy="90" rx="16" ry="9.5" fill="#f5efd8" opacity="${v.gills ? ".55" : ".8"}"/></g>`);
  if (v.warts) F.push(`<circle cx="48" cy="72" r="2" fill="${c.shade}"/><circle cx="66" cy="69" r="2.2" fill="${c.shade}"/><circle cx="74" cy="78" r="1.8" fill="${c.shade}"/><circle cx="42" cy="80" r="1.8" fill="${c.shade}"/>`);
  F.push(`<path d="M50 96 l-3 5 m3 -5 l1 6 m-1 -6 l4 5 M70 96 l3 5 m-3 -5 l-1 6 m1 -6 l-4 5" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>`);
  if (v.gills) F.push(`<g class="antA">${tube("M40 58 Q30 54 26 48", "#e87a9a", "#b04a66", 3)}${tube("M40 62 Q28 62 24 58", "#e87a9a", "#b04a66", 3)}</g><g class="antB">${tube("M80 58 Q90 54 94 48", "#e87a9a", "#b04a66", 3)}${tube("M80 62 Q92 62 96 58", "#e87a9a", "#b04a66", 3)}</g>`);
  F.push(`<circle cx="47" cy="58" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="73" cy="58" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`);
  F.push(`<g class="blink"><circle cx="47" cy="57" r="4.6" fill="#fff"/><circle cx="73" cy="57" r="4.6" fill="#fff"/><circle cx="47.5" cy="57.5" r="2.4" fill="${INK}"/><circle cx="72.5" cy="57.5" r="2.4" fill="${INK}"/></g>`);
  F.push(`<path d="M44 76 Q60 ${v.gills ? 82 : 86} 76 76" stroke="${INK}" stroke-width="1.8" fill="none" stroke-linecap="round"/><circle cx="56" cy="68" r="1" fill="${INK}"/><circle cx="64" cy="68" r="1" fill="${INK}"/>`);
  if (v.gills) F.push(`<g class="bub"><circle cx="92" cy="38" r="2.2" fill="none" stroke="#9fd4f2" stroke-width="1.3"/></g>`);
  return F.join("");
}
function snakeArt(c) {
  return `<g class="breathe"><ellipse cx="56" cy="92" rx="27" ry="10.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
    <ellipse cx="56" cy="78" rx="20" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
    <path d="M36 90 q8 -4 14 0 M60 88 q8 -4 14 0 M44 76 q7 -4 13 0" stroke="${c.shade}" stroke-width="2.6" fill="none" stroke-linecap="round"/></g>
    <g class="head-tilt">${tube("M62 72 Q76 68 78 56", c.body, c.line, 8)}
    <ellipse cx="80" cy="50" rx="10.5" ry="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
    ${eyes2(76.5, 84.5, 48, 2.2)}<circle cx="78.5" cy="54.5" r="0.9" fill="${INK}"/><circle cx="83.5" cy="54.5" r="0.9" fill="${INK}"/>
    <g class="tongue"><path d="M90 52 h7 m0 0 l4 -2.4 m-4 2.4 l4 2.4" stroke="#d0362b" stroke-width="1.7" fill="none" stroke-linecap="round"/></g></g>`;
}
function lizardArt(c, v) {
  const L = [];
  L.push(v.curl ? `<g class="tail-wag">${tube("M38 84 C20 90 8 78 16 66 C22 58 32 62 28 70 C26 74 20 72 22 68", c.body, c.line, 5)}</g>`
                : `<g class="tail-wag">${tube("M38 86 C22 90 10 84 12 70", c.body, c.line, 5)}</g>`);
  const toe = (x, y) => `<circle cx="${x - 3}" cy="${y}" r="1.7" fill="${c.body}" stroke="${c.line}" stroke-width="1"/><circle cx="${x}" cy="${y + 1.5}" r="1.7" fill="${c.body}" stroke="${c.line}" stroke-width="1"/><circle cx="${x + 3}" cy="${y}" r="1.7" fill="${c.body}" stroke="${c.line}" stroke-width="1"/>`;
  L.push(`${tube("M48 88 L42 98", c.body, c.line, 4)}${toe(41, 100)}${tube("M74 88 L80 98", c.body, c.line, 4)}${toe(81, 100)}`);
  L.push(`<g class="breathe"><ellipse cx="60" cy="82" rx="25" ry="11.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
    <path d="M42 76 q18 -7 36 0" stroke="${c.shade}" stroke-width="2.2" fill="none" opacity=".8"/><circle cx="50" cy="84" r="1.8" fill="${c.shade}"/><circle cx="62" cy="87" r="1.8" fill="${c.shade}"/><circle cx="72" cy="83" r="1.6" fill="${c.shade}"/></g>`);
  const HD = [];
  if (v.crest) HD.push(`<path d="M84 66 L96 54 L94 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`);
  HD.push(`<ellipse cx="88" cy="72" rx="12" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>`);
  if (v.curl) HD.push(`<circle cx="88" cy="68" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>${eye1(88, 68, 2.2)}`);
  else HD.push(eye1(90, 68.5, 2.6));
  HD.push(`<path d="M94 76 q3 1.6 6 -1" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`);
  L.push(`<g class="head-tilt">${HD.join("")}</g>`);
  return L.join("");
}
function monkeyArt(c, v) {
  const M = [], face = v.big ? c.shade : "#e8cfae", big = v.big ? 1 : 0;
  if (!v.big) M.push(`<g class="tail-wag">${tube("M42 92 C24 90 18 72 28 60 C34 53 44 56 41 63 C39 68 32 66 34 61", c.body, c.line, 4.5)}${v.tail === "rings" ? `<path d="M28 84 q6 -2 8 -7 M22 74 q7 -1 10 -6 M24 62 q6 1 9 -3" stroke="${c.line}" stroke-width="3.4" opacity=".85"/>` : ""}</g>`);
  M.push(`<g class="breathe"><ellipse cx="59" cy="${86 - big * 2}" rx="${19 + 5 * big}" ry="${15 + 3 * big}" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <ellipse cx="59" cy="${88 - big * 2}" rx="${10 + 3 * big}" ry="${9 + 2 * big}" fill="${face}" opacity=".9"/></g>`);
  M.push(`${tube(`M${46 - 4 * big} ${80 - 2 * big} Q${38 - 6 * big} 92 ${40 - 6 * big} 100`, c.body, c.line, 5 + big)}${tube(`M${72 + 4 * big} ${80 - 2 * big} Q${80 + 6 * big} 92 ${78 + 6 * big} 100`, c.body, c.line, 5 + big)}`);
  const HD = [];
  HD.push(`<circle cx="44" cy="50" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="74" cy="50" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="44" cy="50" r="3.2" fill="${face}"/><circle cx="74" cy="50" r="3.2" fill="${face}"/>`);
  HD.push(`<circle cx="59" cy="49" r="${15.5 + big * 1.5}" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`);
  if (v.big) HD.push(`<path d="M50 36 Q59 30 68 36" stroke="${c.line}" stroke-width="3" fill="none"/>`);
  HD.push(`<path d="M49 45 Q49 38 55 39 Q59 33 63 39 Q69 38 69 45 Q69 52 66 55 L52 55 Q49 52 49 45 Z" fill="${face}" stroke="${c.line}" stroke-width="1.4" opacity=".95"/>`);
  HD.push(`<ellipse cx="59" cy="55.5" rx="8" ry="6" fill="${face}"/>`);
  const mec = lum(face) < 0.32 ? "#e9edf2" : INK;   // gorilla's face is dark — keep its eyes readable
  HD.push(eyes2(54, 64, 46.5, 2.4, mec));
  HD.push(`<circle cx="57" cy="54" r="1.1" fill="${mec}"/><circle cx="61" cy="54" r="1.1" fill="${mec}"/><path d="M54.5 57.5 Q59 61 63.5 57.5" stroke="${mec}" stroke-width="1.8" fill="none" stroke-linecap="round"/>`);
  M.push(`<g class="head-tilt">${HD.join("")}</g>`);
  return M.join("");
}
function wigglerArt(c, v) {
  const segs = [[26, 95], [39, 90], [52, 94], [65, 89], [78, 93]];
  return segs.map(([x, y], i) => `<g class="seg s${i}">
      ${v.fuzz ? `<path d="M${x - 5} ${y - 7} l-2 -5 M${x} ${y - 8.5} l0 -5.5 M${x + 5} ${y - 7} l2 -5" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>` : ""}
      <circle cx="${x}" cy="${y}" r="9" fill="${i % 2 ? c.shade : c.body}" stroke="${c.line}" stroke-width="2.2"/>
      ${!v.fuzz && i === 2 ? `<path d="M${x - 6} ${y - 3} a6.5 6.5 0 0 1 12 0" stroke="#fff" stroke-width="2.4" fill="none" opacity=".5"/>` : ""}</g>`).join("")
    + `<g class="seg s5"><circle cx="90" cy="86" r="10.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${v.fuzz ? `<g class="antA">${tube("M86 77 Q84 70 80 68", c.shade, c.line, 1.8)}</g><g class="antB">${tube("M94 77 Q96 70 100 68", c.shade, c.line, 1.8)}</g>` : ""}
      ${eyes2(86.5, 94, 84, 2.2)}${smilew(90.5, 89, 2.6)}</g>`;
}
function dragonArt(c, v) {
  const wing = `<path d="M44 60 C36 34 16 26 6 35 C15 37 17 44 12 50 C21 47 25 52 23 59 C31 55 37 59 40 67 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M40 61 L15 39 M40 63 L14 50 M41 65 L25 57" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>`;
  return `<g class="tail-wag">${tube("M34 84 C18 88 8 80 12 66", c.body, c.line, 5.5)}<path d="M14 68 L4 60 L15 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="wing-flap">${wing}</g><g class="wing-flap right">${MIRROR(wing)}</g>
    <path d="M46 92 l-2 10 m8 -9 l0 10 M70 92 l2 10 m-8 -9 l0 10" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>
    <g class="breathe"><ellipse cx="58" cy="80" rx="25" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M38 66 Q41 55 46 64 Q47 66 44 67 Z M51 60 Q55 48 60 59 Q61 62 57 62 Z M65 61 Q70 51 73 62 Q73 64 70 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
    <ellipse cx="58" cy="87" rx="14.5" ry="10" fill="#cfeee2" opacity=".72"/>
    <path d="M47 82 q11 4 22 0 M46 88 q12 4 24 0 M48 94 q10 3.5 20 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".45"/></g>
    <g class="head-tilt"><path d="M76 34 C73 22 80 14 89 17 C82 21 82 28 85 35 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
    <path d="M89 36 C89 27 95 22 101 25 C96 28 95 33 96 38 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
    <ellipse cx="84" cy="46" rx="16.5" ry="13.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
    <path d="M93 50 Q102 48 103 54 Q103 60 94 59 Q88 58 88 54 Q88 51 93 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <circle cx="98" cy="53" r="1.1" fill="${INK}"/><circle cx="98" cy="56.5" r="1.1" fill="${INK}"/>
    <path d="M90 59 q4 1.6 8 0" stroke="${c.line}" stroke-width="1.4" fill="none"/>
    <path d="M74 40 q4 -3 8 -1 M88 39 q4 -2 7 0" stroke="${c.line}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    ${eyes2(79, 91, 44, 2.7, lum(c.body) < 0.32 ? "#bfe8dc" : "#083b32")}
    <g class="smoke"><circle cx="106" cy="52" r="3.2" fill="#9fb8b2"/></g><g class="smoke s2"><circle cx="108" cy="49" r="2.4" fill="#9fb8b2"/></g></g>`;
}
const ART = { poodle: poodleArt, quad: quadArt, bird: birdArt, parrot: parrotArt, penguin: penguinArt,
  fishy: fishArt, whale: whaleArt, octo: octoArt, jelly: jellyArt, turtle: turtleArt, snail: snailArt,
  crab: crabArt, bug: bugArt, butterfly: butterflyArt, frog: frogArt, snake: snakeArt, lizard: lizardArt,
  monkey: monkeyArt, wiggler: wigglerArt, dragon: dragonArt };
Object.assign(ART, HAND_ART);   // bespoke hand-drawn per-animal art (pets-art-hand.js) overrides archetypes
const FLOATERS = new Set(["fishy", "whale", "octo", "jelly", "butterfly"]);   // these drift; land pets bob
const wrap = (cls, inner, floats) => `<svg viewBox="0 0 120 120">
  <ellipse class="gshadow" cx="60" cy="107" rx="${floats ? 17 : 25}" ry="4.2" fill="#000" opacity="${floats ? ".1" : ".2"}"/>
  <g class="${cls}">${inner}</g></svg>`;

function eggSvg(cls, cracks) {
  return `<svg viewBox="0 0 120 120"><ellipse class="gshadow" cx="60" cy="107" rx="25" ry="4.2" fill="#000" opacity=".2"/><g class="${cls}">
    <g class="shellwrap${cracks >= 4 ? " popped" : ""}">
      <g class="shellL"><path d="M60 16 C38 16 26 44 26 70 C26 88 36 102 48 106 L60 104 L60 16 Z" fill="#f5e9d0" stroke="#c8a96a" stroke-width="2.5"/></g>
      <g class="shellR"><path d="M60 16 C82 16 94 44 94 70 C94 88 84 102 72 106 L60 104 L60 16 Z" fill="#efe0c0" stroke="#c8a96a" stroke-width="2.5"/></g>
      <circle cx="48" cy="46" r="4" fill="#d9c49a"/><circle cx="70" cy="66" r="5" fill="#d9c49a"/><circle cx="56" cy="84" r="3.4" fill="#d9c49a"/><circle cx="72" cy="34" r="3" fill="#d9c49a"/>
      <path class="crack${cracks >= 1 ? " show" : ""}" d="M52 40 l7 8 -6 7 8 9" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
      <path class="crack${cracks >= 2 ? " show" : ""}" d="M72 52 l-6 9 7 6 -5 10" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
      <path class="crack${cracks >= 3 ? " show" : ""}" d="M44 68 l9 6 -4 9 10 7" stroke="#8a6f42" stroke-width="2.2" fill="none"/>
    </g></g></svg>`;
}
function graveSvg() {
  return `<svg viewBox="0 0 120 120"><g>
    <ellipse cx="60" cy="104" rx="34" ry="8" fill="#1c2733"/>
    <path d="M38 104 L38 56 Q38 34 60 34 Q82 34 82 56 L82 104 Z" fill="#67788a" stroke="#43525f" stroke-width="2.5"/>
    <text x="60" y="62" text-anchor="middle" font-size="13" font-weight="800" fill="#2c3944" font-family="system-ui">RIP</text>
    <path d="M52 74 h16 M60 66 v16" stroke="#2c3944" stroke-width="3"/>
    <g class="ghostup"><text x="60" y="30" text-anchor="middle" font-size="16">👻</text></g></g></svg>`;
}
// draw a pet: its animal's archetype body in its gene-derived coat, inside a rarity-aura span
function drawOf(a) { return ART[petSlug(a.n)] || ART[a.a] || quadArt; }   // per-animal HAND art wins; archetype is the fallback
function petBody(p, cls = "pet-idle") {
  const a = p.animal, coat = G.coatOf(p.gene, a);
  const aura = G.auraOf(p.sp, coat.shiny);
  const floats = a.float || FLOATERS.has(a.a);
  return `<span class="aura ${aura}">${wrap(cls + (floats && cls ? " swim" : ""), drawOf(a)(coat, a.v || {}), floats)}</span>`;
}
const petArt = (p, cls = "pet-idle") => p.dead ? graveSvg() : (p.hatched ? petBody(p, cls) : eggSvg(p.hatchReady ? "egg-ready egg-glow" : "egg-idle", 0));

// ---- CHALLENGER CARD: a downloadable PNG — the pet's WARRIOR face, name, power and a QR to its page ---
const rr = (x, y, w, h, r) => { const p = new Path2D(); p.roundRect(x, y, w, h, r); return p; };
async function challengerCanvas(p) {
  const an = p.animal, coat = G.coatOf(p.gene, an), tier = p.tier;
  FIERCE = 1;                                    // same body, angry face
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="4 4 112 112">${drawOf(an)(coat, an.v || {})}</svg>`;
  FIERCE = 0;
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try { await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; }); }
  catch { URL.revokeObjectURL(url); return alertBar(window.t("pets.cardRenderFail", "Couldn't render the card image — try again.")); }
  const W = 640, H = 900, cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const x = cv.getContext("2d");
  // background: night gradient + a menacing tier-colored arena glow
  const bg = x.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#0b0f14"); bg.addColorStop(0.55, "#12080d"); bg.addColorStop(1, "#1a0708");
  x.fillStyle = bg; x.fillRect(0, 0, W, H);
  const glow = x.createRadialGradient(W / 2, 400, 40, W / 2, 400, 330);
  glow.addColorStop(0, tier.color + "55"); glow.addColorStop(0.6, tier.color + "18"); glow.addColorStop(1, "transparent");
  x.fillStyle = glow; x.fillRect(0, 0, W, H);
  // flame licks around the pet
  x.save(); x.globalAlpha = 0.5;
  for (let i = 0; i < 14; i++) {
    const a = (i / 14) * Math.PI * 2, R = 235 + (i % 3) * 22;
    const fx = W / 2 + Math.cos(a) * R, fy = 400 + Math.sin(a) * R * 0.78;
    const fl = x.createRadialGradient(fx, fy, 2, fx, fy, 26 + (i % 4) * 9);
    fl.addColorStop(0, "#ff8d3a"); fl.addColorStop(0.5, "#d0362b44"); fl.addColorStop(1, "transparent");
    x.fillStyle = fl; x.beginPath(); x.arc(fx, fy, 26 + (i % 4) * 9, 0, 7); x.fill();
  }
  x.restore();
  // frame
  x.strokeStyle = tier.color; x.lineWidth = 6; x.stroke(rr(14, 14, W - 28, H - 28, 24));
  x.strokeStyle = "#e3b34188"; x.lineWidth = 2; x.stroke(rr(26, 26, W - 52, H - 52, 16));
  // header
  x.textAlign = "center"; x.fillStyle = "#e3b341"; x.font = "800 26px system-ui";
  x.fillText(window.t("pets.cardHeader", "⚔  C H A L L E N G E R  ⚔"), W / 2, 78);
  const name = p.label;
  x.fillStyle = "#f2f4f6"; x.font = `900 ${name.length > 14 ? 40 : 52}px system-ui`;
  x.shadowColor = tier.color; x.shadowBlur = 18;
  x.fillText(name, W / 2, name.length > 14 ? 130 : 138, W - 90);
  x.shadowBlur = 0;
  x.fillStyle = tier.color; x.font = "700 24px system-ui";
  x.fillText(`${an.e}  ${CN(coat)} ${AN(an)} · ${tier.rarity}${coat.shiny ? " ✦" : ""}`, W / 2, 176, W - 80);
  // the warrior
  x.drawImage(img, W / 2 - 190, 192, 380, 380);
  URL.revokeObjectURL(url);
  // power plate
  x.fillStyle = "#0b0f14cc"; x.fill(rr(W / 2 - 190, 586, 380, 72, 16));
  x.strokeStyle = "#e3b341"; x.lineWidth = 2.5; x.stroke(rr(W / 2 - 190, 586, 380, 72, 16));
  x.fillStyle = "#ffd35a"; x.font = "900 38px system-ui";
  x.fillText(window.t("pets.cardPower", "⚡ POWER {pw}", { pw: p.pw }), W / 2, 636);
  x.fillStyle = "#93a1b0"; x.font = "700 20px system-ui";
  x.fillText(window.t("pets.cardRecord", "Lv {lv} · record {rec}", { lv: p.level, rec: recordOf(p) }), W / 2, 688);
  // QR to this pet (scan -> its page, Challenge button and all)
  const qcv = document.createElement("canvas");
  drawQR(qcv, null, base() + "/?pet=" + p.id, 150);
  if (qcv.width > 2) {
    x.fillStyle = "#fff"; x.fill(rr(W - 182, 722, 144, 144, 10));
    x.drawImage(qcv, W - 175, 729, 130, 130);
  }
  // CHALLENGE ME + the scan invitation (left column, clear of the QR tile)
  x.textAlign = "left";
  x.fillStyle = "#f85149"; x.font = "900 42px system-ui";
  x.shadowColor = "#f85149"; x.shadowBlur = 20;
  x.fillText(window.t("pets.cardChallengeMe", "CHALLENGE ME"), 46, 764);
  x.shadowBlur = 0;
  x.fillStyle = "#93a1b0"; x.font = "600 17px system-ui";
  x.fillText(window.t("pets.cardScan", "scan to face me on-chain:"), 46, 798);
  x.fillStyle = "#00c9a7"; x.font = "700 19px system-ui";
  x.fillText("pets.nadochain.com", 46, 826);
  x.fillStyle = "#5d6b7a"; x.font = "600 14px system-ui";
  x.fillText(window.t("pets.cardFooter", "NADO PETS · every fight is decided by the chain"), 46, 854);
  return cv;
}
async function challengerCard(p) {
  const cv = await challengerCanvas(p);
  if (!cv) return;
  cv.toBlob((b) => {
    if (!b) return alertBar(window.t("pets.cardExportFail", "Couldn't export the card PNG."));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = "challenger-" + String(p.nm || p.animal.n).replace(/\W+/g, "-").toLowerCase() + "-" + p.id + ".png";
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  });
}

// ---- reads: everything derives from the contract's storage maps -----------------------------------
// A pet's gene string (gs) is immutable once set (rebirth mints a NEW gs), so the heavy decode —
// BigInt parse + species lookup + base-stat decode — is memoized by pid|gs. petsFrom runs over the WHOLE
// global roster twice per poll and every 3s; without this cache that gene-decode dominates the main thread
// at thousands of pets. Cache size tracks the roster (one small entry per distinct gene), never re-decodes.
const _geneCache = {};
function petsFrom(sto) {
  const ow = _m(sto, "ow"), cur = dapp.cursor, out = {};
  for (const pid of Object.keys(ow)) {
    const gl = _m(sto, "gl")[pid], gh = _m(sto, "gh")[pid];
    const gs = gl != null || gh != null ? G.geneFromHalves(gl || 0, gh || 0).toString() : null;
    const p = { id: pid, owner: ow[pid], bh: _m(sto, "bh")[pid] || 0, gs, sp: _m(sto, "sp")[pid] || 0,
      si: _m(sto, "si")[pid] || 0, ex: _m(sto, "ex")[pid] || 0,
      ap: _m(sto, "ap")[pid] || 0, pw: _m(sto, "pw")[pid] || 0, fu: _m(sto, "fu")[pid] || 0,
      tf: _m(sto, "tf")[pid] || 0, nm: _m(sto, "nm")[pid] || "", th: _m(sto, "th")[pid] || 0,
      ti: _m(sto, "ti")[pid] || 0, tr: _m(sto, "tr")[pid] || 0, price: _m(sto, "mp")[pid] || 0,
      wins: _m(sto, "wins")[pid] || 0, loss: _m(sto, "loss")[pid] || 0 };
    p.hatched = !!gs;
    if (gs) {   // memoized immutable decode (gene / species / base stats) — keyed by the immutable gene
      const k = pid + "|" + gs;
      let d = _geneCache[k];
      // species is re-derived from the IMMUTABLE gene (not the stored si) so the 1007-animal roster remap
      // applies to every pet with zero on-chain writes — stored si is legacy/ignored. sp is unchanged (TIER_CUM).
      if (!d) { const gene = BigInt(gs); d = _geneCache[k] = { gene, animal: G.animalOf(G.speciesIdOf(gene, p.sp), p.sp), base: G.baseStats(gene, p.sp) }; }
      p.gene = d.gene; p.animal = d.animal; p.base = d.base;
    } else { p.gene = null; p.animal = null; p.base = null; }
    p.dead = cur != null && cur > p.fu;
    p.tier = G.TIERS[p.sp] || null;
    p.resting = !p.dead && cur != null && cur < p.ex;       // post-battle exhaustion (no new fights)
    p.restBlocks = p.resting ? p.ex - cur : 0;
    p.mine = dapp.me && p.owner === dapp.me;
    p.hatchReady = !p.hatched && !!(dapp.bh(p.bh) && dapp.bh(p.bh + 1));
    p.stale = !p.hatched && cur != null && cur >= p.bh + G.STALE;         // gene block pruned -> rebirth
    p.bonus = p.gene ? G.STAT_NAMES.map((_n, i) => _m(sto, "tb")[pid + "|" + i] || 0) : null;
    p.level = G.levelOf(p.tf || 0);
    p.label = p.nm ? p.nm : (p.hatched ? AN(p.animal) : window.t("pets.egg", "Egg")) + " #" + String(pid).slice(-4);
    out[pid] = p;
  }
  return out;
}
function offersFrom(sto) {
  const os = _m(sto, "os"), out = {};
  for (const oid of Object.keys(os)) {
    out[oid] = { id: oid, buyer: String(_m(sto, "ob")[oid] || ""), pet: String(_m(sto, "op")[oid] || ""),
      value: _m(sto, "ov")[oid] || 0, state: _m(sto, "os")[oid] || 0 };
  }
  return out;
}
function battlesFrom(sto) {
  const wa = _m(sto, "wa"), out = {};
  for (const bid of Object.keys(wa)) {
    out[bid] = { id: bid, a: String(wa[bid]), b: String(_m(sto, "wb")[bid]), ws: _m(sto, "ws")[bid] || 0,
      wp: _m(sto, "wp")[bid] || 0, wh: _m(sto, "wh")[bid] || 0, wn: _m(sto, "wn")[bid] || 0,
      ww: String(_m(sto, "ww")[bid] || ""), wd: _m(sto, "wd")[bid] || 0 };
  }
  return out;
}
const myPets = () => Object.values(PETS).filter((p) => p.mine);
// effective stats (base gene stat + trained bonus) — what the turn-based battle actually fights with
const effOf = (p) => (p.base && p.bonus) ? p.base.map((b, i) => b + p.bonus[i]) : null;
const recordOf = (p) => (p.wins || 0) + "W–" + (p.loss || 0) + "L";
const lifeBlocks = (p) => dapp.cursor == null ? null : p.fu - dapp.cursor;
const dhm = (b) => { const d = Math.floor(b / BLOCKS_PER_DAY), h = Math.floor((b % BLOCKS_PER_DAY) * BLOCK_SECS / 3600);
  return d > 0 ? d + "d " + h + "h" : h > 0 ? h + "h " + Math.floor((b * BLOCK_SECS % 3600) / 60) + "m" : blocksToTime(b) + " min"; };
const lifeText = (p) => { const b = lifeBlocks(p); return b == null ? "…" : b <= 0 ? window.t("pets.lifeNone", "none") : dhm(b); };
// hunger moods drive the CSS animations: hungry under 3 days of belly, starving under 12 hours.
// Only HATCHED pets get them — an egg can't be fed, so nagging for food would be a lie.
const moodOf = (p) => { if (p.dead) return "dead"; if (!p.hatched) return ""; const b = lifeBlocks(p);
  return b == null ? "" : b < BLOCKS_PER_DAY / 2 ? "starving" : b < 3 * BLOCKS_PER_DAY ? "hungry" : ""; };

// ---- actions ---------------------------------------------------------------------------------------
const L = () => lsLoad(LS_P), Lsave = (v) => lsSave(LS_P, v);
function mint() {
  if (!canPay(dapp, G.MINT_FEE, "Adopting an egg")) return;
  const pid = randId(); const l = L(); l[pid] = { ts: Date.now() }; Lsave(l); active = pid;
  dapp.call("mint", [pid], G.MINT_FEE, "adopt egg #" + pid + " · 1 NADO", { pid, phase: "mint" });
}
// BUY MULTIPLE: adopt N eggs in one go. Each mint BURNS 1 NADO and takes a wallet round-trip, so they're
// chained — mint one, and on return maybeAutoMint() fires the next until the batch is done. The remaining
// count lives in localStorage so it survives the redirects. A shortfall stops the batch (canPay guards each).
function mintMany() {
  const n = Math.max(1, Math.min(20, parseInt($("mintQty").value, 10) || 1));
  if (n === 1) return mint();
  const total = G.MINT_FEE * BigInt(n);
  if (!canPay(dapp, total, "Adopting " + n + " eggs")) return;
  try { localStorage.setItem("nado_pets_mintq", String(n)); } catch (e) {}
  mintNext();
}
function mintNext() {
  let left = 0; try { left = parseInt(localStorage.getItem("nado_pets_mintq") || "0", 10) || 0; } catch (e) {}
  if (left <= 0) { try { localStorage.removeItem("nado_pets_mintq"); } catch (e) {} return; }
  try { localStorage.setItem("nado_pets_mintq", String(left - 1)); } catch (e) {}
  if (left - 1 <= 0) { try { localStorage.removeItem("nado_pets_mintq"); } catch (e) {} }
  mint();   // decrement BEFORE the redirect so the count is right when we come back
}
function maybeAutoMint() {
  let left = 0; try { left = parseInt(localStorage.getItem("nado_pets_mintq") || "0", 10) || 0; } catch (e) {}
  if (left <= 0 || !dapp.me || dapp.inflight || dapp.busy("mint")) return;   // wait for the current mint to confirm first (incl. the click→sign gap)
  if (dapp.exec < G.MINT_FEE) { try { localStorage.removeItem("nado_pets_mintq"); } catch (e) {} return; }   // out of funds — stop
  mintNext();
}
function hatch(pid) {
  if (dapp.busy("hatch", "pid", pid)) return;   // click-time SDK gate (button gating is also busy()-driven in render)
  const l = L(); (l[pid] = l[pid] || { ts: Date.now() }).hatchPending = Date.now(); Lsave(l);   // stamp: marks "I hatched this one" so maybePlayHatch plays the crack animation for MY egg only
  dapp.call("hatch", [Number(pid)], null, "hatch egg #" + pid, { pid, phase: "hatch" });   // pid MUST be an int: the contract computes gene = HASH(bh0+bh1+pid); a string pid reverts on the ADD
}
// HATCH ALL: spam-adopting leaves several ready eggs; hatching them one card at a time feels stuck. This
// hatches EVERY ready egg — the wallet redirect serialises each (value-free hatch → auto-signs, a quick
// bounce), and on return maybeAutoHatch() fires the next until none remain. Flag survives the round-trips.
const readyEggs = () => myPets().filter((p) => !p.hatched && !p.dead && p.hatchReady);
function hatchAll() {
  const eggs = readyEggs();
  if (!eggs.length) return;
  try { localStorage.setItem("nado_pets_hatchall", "1"); } catch (e) {}
  active = eggs[0].id; hatch(eggs[0].id);
}
function maybeAutoHatch() {
  if (localStorage.getItem("nado_pets_hatchall") !== "1") return;
  if (!dapp.me || dapp.inflight || dapp.busy("hatch")) return;   // wait for the current hatch to confirm first (busy() covers the click→sign gap the 3s tick could race into)
  const eggs = readyEggs();
  if (!eggs.length) { try { localStorage.removeItem("nado_pets_hatchall"); } catch (e) {} return; }
  hatch(eggs[0].id);
}
const rebirth = (pid) => dapp.call("rebirth", [Number(pid)], null, "re-roll egg #" + pid, { pid, phase: "hatch" });   // int pid (consistency + the pid rides into the gene at the next hatch)
function feed(pid, raw) {
  const p = PETS[pid]; if (!p) return;
  const blocks = G.feedBlocks(raw, p.ap);
  if (blocks < 1) return alertBar(window.t("pets.mealTooSmall", "That meal is too small — it wouldn't buy a single block of life (this pet's appetite costs {cost} NADO per block).", { cost: rawToNado(G.feedCost(1, p.ap)) }));
  if (lifeBlocks(p) + blocks > G.BELLY_CAP) return alertBar(window.t("pets.tooMuchFood", "Too much food — the belly holds at most 30 days ahead. Use the fill-belly preset instead."));
  if (!canPay(dapp, raw, "This meal")) return;
  dapp.call("feed", [Number(pid)], raw, "feed " + PETS[pid].label + " · " + rawToNado(raw) + " NADO (+" + (blocks / BLOCKS_PER_DAY).toFixed(1) + "d)", { pid, phase: "feed", fu0: p.fu });
}
// trainBusy(pid): a train call is between click and its session appearing on-chain. The contract allows ONE
// session per pet (a second `train` while p.th is set just REVERTS, fee refunded) — so during the whole
// submit→land window (sign ~1s + mine + poll, easily 10-20s) every extra click would burn a wallet round-trip
// on a guaranteed no-op with zero feedback ("I clicked and nothing happened"). The SDK's click-time pending
// registry (dapp.busy is TRUE from the click until the session is seen on-chain) carries the whole window.
const trainBusy = (pid) => {
  const p = PETS[pid];
  return !!(p && p.th) || dapp.busy("train", "pid", pid);   // session open on-chain, or clicked/confirming
};
function train(pid, i) {
  if (trainBusy(pid)) return notify(window.t("pets.trainBusy", "One training session at a time — this one is still confirming on-chain…"));
  if (!canPay(dapp, G.TRAIN_FEE, "Training")) return;
  const l = L(); const r = (l[pid] = l[pid] || { ts: Date.now() }); r.trainPending = 1; r.trainStat = G.STAT_NAMES[i]; Lsave(l);
  dapp.call("train", [Number(pid), i], G.TRAIN_FEE, "train " + PETS[pid].label + " · " + G.STAT_NAMES[i] + " · 0.5 NADO", { pid, phase: "train" });
}
const trainResolve = (pid) => dapp.call("train_resolve", [Number(pid)], null, "reveal training result for " + PETS[pid].label, { pid, phase: "trainres" });
// AUTO-REVEAL: a finished training session settles itself the moment its result blocks finalize (value-free →
// signs silently in the background), so you never have to tap "Reveal the result". One per refresh tick.
function maybeAutoReveal() {
  const ready = myPets().filter((p) => p.th && dapp.cursor != null && dapp.cursor >= p.th + 1 && dapp.bh(p.th) && dapp.bh(p.th + 1));
  dapp.autoCollect(ready, (p) => trainResolve(p.id), { key: (p) => "reveal:" + p.id });
}
function challenge(theirPid) {
  const myPid = parseInt($("myPetSel").value, 10);
  if (!myPid) return alertBar(window.t("pets.pickFighter", "Pick which of your pets fights — you need a living, hatched pet (adopt one below)."));
  const mine = PETS[myPid], theirs = PETS[theirPid];
  if (mine && mine.resting) return alertBar(window.t("pets.mineExhausted", "{label} is exhausted from its last battle — rested again in {time}.", { label: mine.label, time: dhm(mine.restBlocks) }));
  if (theirs && theirs.resting) return alertBar(window.t("pets.theirsExhausted", "{label} is exhausted from its last battle — challenge it again in {time}.", { label: theirs.label, time: dhm(theirs.restBlocks) }));
  const stake = $("stakeAmt").value.trim() === "" || $("stakeAmt").value.trim() === "0" ? 0n : nadoToRaw($("stakeAmt").value);
  if (stake == null) return alertBar(window.t("pets.enterStake", "Enter a stake in NADO (0 for a friendly-but-deadly match)."));
  if (stake > 0n && !canPay(dapp, stake, "This challenge")) return;
  const bid = randId();
  dapp.call("challenge", [bid, myPid, Number(theirPid)], stake > 0n ? stake : null,
    "challenge " + PETS[theirPid].label + " with " + PETS[myPid].label + (stake > 0n ? " · stake " + rawToNado(stake) + " NADO" : ""),
    { bid, phase: "challenge" });   // no forced confirm — the WALLET decides (like chess/farkle joins): default wallets still get the visible confirm via needui→redirect, auto-sign-all plays uninterrupted
}
function acceptBattle(bid) {
  const b = BATTLES[bid]; if (!b) return;
  const stake = BigInt(b.ws || 0);
  if (stake > 0n && !canPay(dapp, stake, "Accepting this battle")) return;
  dapp.call("accept", [Number(bid)], stake > 0n ? stake : null, "accept battle #" + bid + (stake > 0n ? " · stake " + rawToNado(stake) + " NADO" : ""), { bid, phase: "accept" });   // wallet-policy confirm (see challenge)
}
const resolveBattle = (bid) => dapp.call("resolve_battle", [Number(bid)], null, "settle battle #" + bid, { bid, phase: "resolveb" });
const cancelBattle = (bid) => dapp.call("cancel_battle", [Number(bid)], null, "withdraw challenge #" + bid, { bid, phase: "cancelb" });
const refundBattle = (bid) => dapp.call("refund_battle", [Number(bid)], null, "reclaim stakes of battle #" + bid, { bid, phase: "cancelb" });
function nameIt(pid) {
  const name = $("nameInput").value.trim().slice(0, 24);
  if (!name) return alertBar(window.t("pets.pickName", "Pick a name — it's permanent, like a real pet's."));
  dapp.call("name", [Number(pid), name], null, 'name pet #' + pid + ' "' + name + '" (permanent)', { pid, phase: "rename" }, { confirm: 1 });
}
function listPet(pid) {
  const raw = nadoToRaw($("listPrice").value);
  if (!raw) return alertBar(window.t("pets.enterAsk", "Enter your ask price in NADO."));
  dapp.call("list", [Number(pid), raw], null, "sell " + PETS[pid].label + " · ask " + rawToNado(raw) + " NADO", { pid, phase: "market", mp0: PETS[pid].price }, { confirm: 1 });
}
const unlistPet = (pid) => dapp.call("unlist", [Number(pid)], null, "remove " + PETS[pid].label + " from the market", { pid, phase: "market", mp0: PETS[pid].price });
function buyPet(pid) {
  const p = PETS[pid]; if (!p || !p.price) return;
  const price = BigInt(p.price);
  if (!canPay(dapp, price, "Buying this pet")) return;
  dapp.call("buy", [Number(pid)], price, "buy " + p.label + " · " + rawToNado(price) + " NADO", { pid, phase: "buy" }, { confirm: 1 });
}
function makeOffer(pid) {
  const p = PETS[pid]; if (!p) return;
  const raw = nadoToRaw($("offerAmt").value);
  if (!raw) return alertBar(window.t("pets.enterOffer", "Enter your offer in NADO."));
  if (!canPay(dapp, raw, "This offer")) return;
  const oid = randId();
  dapp.call("offer", [oid, Number(pid)], raw, "offer " + rawToNado(raw) + " NADO for " + p.label, { pid, oid, phase: "offer" }, { confirm: 1 });
}
const acceptOffer = (oid, label) => dapp.call("accept_offer", [Number(oid)], null, "accept offer #" + oid + (label ? " for " + label : ""), { oid, phase: "offeract" }, { confirm: 1 });
const cancelOffer = (oid) => dapp.call("cancel_offer", [Number(oid)], null, "withdraw offer #" + oid, { oid, phase: "offeract" });
async function transfer(pid) {
  let to = $("xferTo").value.trim();
  if (to.startsWith("@")) {
    try { const r = await (await fetch(base() + "/resolve_alias?name=" + encodeURIComponent(to.slice(1)), { cache: "no-store" })).json(); to = r.address || r.owner || ""; }
    catch { to = ""; }
    if (!to) return alertBar(window.t("pets.aliasNoResolve", "That @alias doesn't resolve to an address."));
  }
  if (!to || !to.startsWith(ADDR_PREFIX)) return alertBar(window.t("pets.enterRecipient", "Enter the receiving NADO address or a registered @alias."));
  if (to === dapp.me) return alertBar(window.t("pets.thatsYou", "That's you — pick another wallet."));
  dapp.call("transfer", [Number(pid), to], null, "transfer " + PETS[pid].label + " to " + to.slice(0, 10) + "…", { pid, phase: "xfer" }, { confirm: 1 });
}
// same-species duplicates you own that could be MERGED INTO p (hatched + rested; dead ones count — they're
// cleanup fodder). `q.animal === p.animal` is exact-species (animalOf returns the one roster object per si).
function combineDups(p) {
  if (!p || !p.hatched || !p.animal) return [];
  const cur = dapp.cursor;
  return myPets().filter((q) => q.id !== p.id && q.hatched && q.animal === p.animal && cur != null && cur >= q.ex);
}
function combine(keepPid) {
  const p = PETS[keepPid]; if (!p || !p.mine || p.dead) return;
  const dups = combineDups(p);
  if (!dups.length) return alertBar(window.t("pets.noDup", "You need a second pet of the same species — hatched and not in a battle — to combine into this one."));
  dups.sort((a, b) => (a.dead ? 0 : 1) - (b.dead ? 0 : 1) || a.pw - b.pw);   // spend a dead dupe first, else the weakest
  const fodder = dups[0], i = G.combineStatOf(p.gene, fodder.gene);
  dapp.call("combine", [Number(keepPid), Number(fodder.id)], null,
    window.t("pets.combineDesc", "combine {c} into {k} → +1 {stat} (the merged pet is gone)", { c: fodder.label, k: p.label, stat: G.STAT_NAMES[i] }),
    { pid: keepPid, phase: "combine" }, { confirm: 1 });
}
function release(pid) {
  const p = PETS[pid]; if (!p || !p.mine) return;
  dapp.call("release", [Number(pid)], null,
    window.t("pets.releaseDesc", "release {n} into the wild — gone forever, frees your roster (no reward)", { n: p.label }),
    { pid, phase: "release" }, { confirm: 1 });
}

// ---- refresh loop ----------------------------------------------------------------------------------
let BURNED = 0n;
async function refreshAll() {
  await dapp.refresh();
  try { BURNED = BigInt((await (await fetch(base() + "/exec/bridge?ns=default&provisional=1", { cache: "no-store" })).json()).balances.burn || 0); } catch {}
  const sto = await dapp.storage();
  if (sto) {
    BATTLES = battlesFrom(sto); OFFERS = offersFrom(sto);
    // hashes we need: the active egg's gene blocks, pending trainings, accepted battles
    const want = [];
    const pre = petsFrom(sto);
    for (const p of Object.values(pre)) {
      if (!p.hatched && dapp.cursor != null && dapp.cursor >= p.bh + 1 && dapp.cursor < p.bh + G.STALE) want.push(p.bh, p.bh + 1);
      if (p.th && dapp.cursor != null && dapp.cursor >= p.th + 1) want.push(p.th, p.th + 1);
    }
    for (const b of Object.values(BATTLES)) if (b.wn === 2 && dapp.cursor != null && dapp.cursor >= b.wh + 1) want.push(b.wh, b.wh + 1);
    // FAST provisional: genes/training/battles are PUBLIC randomness the contract re-validates at
    // hatch/resolve — a pre-finality reorg just reverts that tx visibly, never a silent unfairness
    if (want.length) await dapp.blockHashes(want.slice(0, 40), { fast: true });
    PETS = petsFrom(sto);                       // re-derive with hashes cached (hatchReady)
    // prune local records that never landed
    const l = L(); let ch = false;
    for (const pid of Object.keys(l)) if (!PETS[pid] && Date.now() - (l[pid].ts || 0) > 600000) { delete l[pid]; ch = true; }
    if (ch) Lsave(l);
    await resolveAliases(Object.values(PETS).map((p) => p.owner).concat([dapp.me]).filter(Boolean).slice(0, 60));
    // retire the optimistic "confirming…" line once the action's effect is visible on-chain (SDK also
    // covers the 3-min expiry + tip-advance fallback). EVERY phase must be covered by this predicate.
    dapp.settleInflight((f) => {
      const p = PETS[f.pid], b = BATTLES[f.bid], o = OFFERS[f.oid];
      return (f.phase === "mint" && p) || (f.phase === "hatch" && p && p.hatched)
        || (f.phase === "buy" && p && p.mine) || (f.phase === "feed" && p && p.fu > (f.fu0 || 0))
        || (f.phase === "train" && p && p.th) || (f.phase === "trainres" && p && !p.th)
        || (f.phase === "rename" && p && p.nm) || (f.phase === "xfer" && p && !p.mine)
        || (f.phase === "market" && p && String(p.price) !== String(f.mp0))
        || (f.phase === "offer" && o) || (f.phase === "offeract" && o && o.state === 2)
        || (f.phase === "challenge" && b) || (f.phase === "accept" && b && b.wn >= 2)
        || ((f.phase === "resolveb" || f.phase === "cancelb") && b && b.wn === 3);
    });
    maybeAutoHatch();   // continue a "Hatch all" run once the previous hatch has confirmed
    maybeAutoMint();    // continue a "Adopt N eggs" batch once the previous mint has confirmed
    maybeAutoReveal();  // auto-reveal any finished training the moment its result blocks finalize
  }
  render();
}

// ---- render ----------------------------------------------------------------------------------------
function statRow(p, i, busy) {
  const base = p.base[i], bonus = p.bonus[i], val = base + bonus, chance = G.trainChance(p.sp, val);
  const canTrain = p.mine && !p.dead && !p.th && !busy;
  // two-segment bar: teal = base (locked at hatch), gold = trained bonus you added
  const baseW = Math.min(100, base), bonusW = Math.min(100 - baseW, bonus);
  const bar = `<div class="bar sbar"><i style="width:${baseW}%"></i>${bonusW > 0 ? `<b style="width:${bonusW}%" title="+${bonus} from training"></b>` : ""}</div>`;
  return `<div class="statrow"><span title="${G.STAT_ROLES[i]}">${G.STAT_ICONS[i]}</span><span title="In battle: ${G.STAT_ROLES[i]}">${G.STAT_NAMES[i]}</span>
    <span class="sv">${val}${bonus ? ` <span class="up" title="+${bonus} from training${i === 9 ? " — battle bonus only; the food bill stays at the hatched appetite" : ""}">+${bonus}</span>` : ""}</span>
    ${bar}
    ${canTrain ? `<button class="mini train" data-train="${i}" title="Train ${G.STAT_NAMES[i]} — 0.5 NADO, ${chance.toFixed(0)}% chance to gain +1">🏋 Train · ${chance.toFixed(0)}%</button>` : `<span class="small dim" title="${busy && !p.th ? "training session confirming on-chain…" : "train success chance"}">${busy && !p.th ? "⏳" : chance.toFixed(0) + "%"}</span>`}
  </div>`;
}
function renderActive() {
  dapp.reflectUrl("pet", active);   // address bar = the shareable link to the selected pet
  const p = PETS[active];
  gate({ activePet: active != null });
  if (active == null) return;
  const local = L()[active] || {};
  if (!p) {                                        // not on-chain (yet)
    $("petId").textContent = "#" + active; $("petRar").innerHTML = "";
    $("petStage").innerHTML = eggSvg("egg-idle", 0);
    $("petName").textContent = "Egg #" + String(active).slice(-4);
    $("petSpecies").textContent = "";
    $("petMsg").textContent = dapp.whereIs("pet", active, local.ts);
    gate({ lifeWrap: false, restWrap: false, hatchRow: false, feedRow: false, statsWrap: false, challengeRow: false, ownRow: false });
    $("btnCard").classList.add("hidden");
    shareInvite("pet", null); return;
  }
  const an = p.animal, tier = p.tier;
  $("petId").textContent = "#" + p.id;
  $("petRar").innerHTML = p.hatched ? `<span class="rar r${p.sp}">${tier.rarity}</span>` : `<span class="rar r1">${window.t("pets.egg", "Egg")}</span>`;
  if (!hatchPlaying) {
    $("activePet").className = "card " + moodOf(p);
    $("petStage").innerHTML = petArt(p);
  }
  $("petName").textContent = p.label + (p.dead ? " ✝" : "");
  const coat = p.gene && an ? G.coatOf(p.gene, an) : null;
  $("petSpecies").innerHTML = p.hatched
    ? an.e + " " + esc(CN(coat)) + " " + esc(AN(an)) + (coat.shiny ? ' <span style="color:#ffd35a">' + window.t("pets.shiny", "✦ shiny") + '</span>' : "") + ' · <span class="dim">' + window.t("pets.oneOfN", "1 of {n} animals", { n: G.ANIMALS.length }) + '</span>' + (p.nm ? ' · <span class="dim">#' + p.id + "</span>" : "")
    : window.t("pets.unhatchedEgg", "Unhatched egg");
  $("petOwner").innerHTML = esc(disp(p.owner)) + (p.mine ? ' <span class="b ok">' + window.t("pets.yours", "yours") + '</span>' : "");
  $("petLp").textContent = p.hatched ? "Lv " + p.level + " · ⚡ " + p.pw + " · " + recordOf(p) : "—";
  $("petUpkeep").textContent = p.hatched ? window.t("pets.upkeepLine", "{ap} (locked at hatch) · {perday} NADO/day", { ap: p.ap, perday: rawToNado(G.feedCost(BLOCKS_PER_DAY, p.ap)) }) : window.t("pets.decidedAtHatch", "decided at hatch");
  if ($("petInvested")) $("petInvested").textContent = p.hatched || p.tf ? rawToNado(p.tf) + " NADO" : "—";
  if ($("petGene")) { $("petGene").textContent = p.gs ? "0x" + p.gene.toString(16) : "—"; $("petGene").title = p.gs || ""; }
  // life bar
  const lb = lifeBlocks(p), pct = lb == null ? 0 : Math.max(0, Math.min(100, 100 * lb / G.BELLY_CAP));
  $("lifeBar").className = "bar" + (p.dead ? " crit" : lb < BLOCKS_PER_DAY / 2 ? " crit" : lb < 3 * BLOCKS_PER_DAY ? " low" : "");
  $("lifeBar").firstElementChild.style.width = pct + "%";
  $("lifeLabel").textContent = p.dead ? window.t("pets.starvedFallen", "☠ starved / fallen") : lifeText(p) + (lb != null && lb < 3 * BLOCKS_PER_DAY && !p.dead ? window.t("pets.feedSoon", " — FEED SOON") : "");
  // exhaustion (post-battle rest): recovery bar counts UP to ready
  if (p.resting) {
    $("restLabel").textContent = dhm(p.restBlocks);
    $("restBar").firstElementChild.style.width = Math.max(2, Math.min(100, 100 * (1 - p.restBlocks / G.EXHAUST))) + "%";
  }
  $("petMsg").textContent = p.dead ? (p.hatched ? window.t("pets.petDied", "This pet has died. Its record stays on-chain forever.") : window.t("pets.eggExpired", "This egg expired unhatched."))
    : !p.hatched ? (p.hatchReady ? window.t("pets.genesFinal", "The gene blocks are final — hatch it!") : p.stale ? window.t("pets.genePruned", "Its gene block was pruned — re-roll below.") : window.t("pets.incubating", "Incubating… the chain is minting its gene blocks (~2 min).")) : "";
  // sections
  const canOffer = p.hatched && !p.dead && !p.mine && dapp.me;
  const incoming = Object.values(OFFERS).filter((o) => o.state === 1 && o.pet === p.id);
  gate({ lifeWrap: true, restWrap: p.hatched && !p.dead && p.resting,
         hatchRow: !p.hatched && !p.dead, feedRow: p.hatched && !p.dead,
         statsWrap: p.hatched, challengeRow: p.hatched && !p.dead && !p.mine && dapp.me,
         ownRow: p.mine && !p.dead, buyRow: !!p.price && !p.mine && !p.dead && dapp.me,
         releaseRow: p.mine,
         offerRow: canOffer, offersInRow: p.mine && !p.dead && incoming.length > 0 });
  if (canOffer) {
    const mine = Object.values(OFFERS).filter((o) => o.state === 1 && o.pet === p.id && o.buyer === dapp.me);
    $("myOffersOut").innerHTML = mine.length
      ? window.t("pets.yourOpenOffer", "Your open offer:") + " " + mine.map((o) => rawToNado(o.value) + " NADO <button class='mini ghost' data-canceloffer='" + o.id + "'>" + window.t("pets.withdrawLc", "withdraw") + "</button>").join(" ")
      : window.t("pets.bidAny", "Bid any amount; it's escrowed and refunded if you withdraw or it's never accepted.");
    $("myOffersOut").querySelectorAll("[data-canceloffer]").forEach((b) => b.onclick = () => cancelOffer(b.dataset.canceloffer));
  }
  if (p.mine && !p.dead && incoming.length) {
    incoming.sort((a, b) => b.value - a.value);
    $("offersInList").innerHTML = incoming.map((o) => '<div class="btl">💬 <b>' + rawToNado(o.value) + " NADO</b> from " + esc(disp(o.buyer))
      + ' <div class="act"><button class="mini primary" data-acceptoffer="' + o.id + '">' + window.t("pets.acceptSell", "Accept &amp; sell") + '</button></div></div>').join("");
    $("offersInList").querySelectorAll("[data-acceptoffer]").forEach((b) => b.onclick = () => acceptOffer(b.dataset.acceptoffer, p.label));
  }
  if (p.price && !p.mine && !p.dead) {
    const busyBuy = dapp.busy("buy", "pid", p.id);
    $("btnBuy").textContent = busyBuy ? window.t("pets.buyingConfirm", "⏳ Buying — confirming on-chain…") : window.t("pets.buyBtn", "🛒 Buy {label} · {price} NADO", { label: p.label, price: rawToNado(p.price) });
    $("btnBuy").disabled = busyBuy;
  }
  if (p.mine && !p.dead) {
    $("btnList").classList.toggle("hidden", !!p.price);
    $("listPrice").classList.toggle("hidden", !!p.price);
    $("btnUnlist").classList.toggle("hidden", !p.price);
    if (p.price) $("btnUnlist").textContent = window.t("pets.removeListingPrice", "Remove listing (ask {price} NADO)", { price: rawToNado(p.price) });
  }
  if (p.mine) {
    const cur = dapp.cursor, rested = cur != null && cur >= p.ex;
    const dups = !p.dead ? combineDups(p) : [];
    const cb = dapp.busy("combine", "pid", p.id);
    $("btnCombine").classList.toggle("hidden", !dups.length && !cb);
    $("mergeHint").classList.toggle("hidden", !dups.length);
    $("btnCombine").disabled = cb || dapp.inflight;
    $("btnCombine").textContent = cb ? window.t("pets.combiningConfirm", "⏳ Combining — confirming on-chain…")
      : window.t("pets.combineN", "⊕ Combine a duplicate → +1 random stat · {n} spare", { n: dups.length });
    if (dups.length) $("mergeHint").innerHTML = window.t("pets.mergeHintDup", "You own <b>{n}</b> spare <b>{sp}</b> — combine one in for a permanent <b>+1 to a random stat</b>. The spare is consumed (a dead one is spent first).", { n: dups.length, sp: esc(AN(p.animal)) });
    const rb = dapp.busy("release", "pid", p.id);
    $("btnRelease").disabled = rb || dapp.inflight || !rested;
    $("btnRelease").textContent = rb ? window.t("pets.releasingConfirm", "⏳ Releasing — confirming on-chain…")
      : (!rested ? window.t("pets.releaseResting", "🕊 Release — resting until the battle cooldown ends")
                 : window.t("pets.release", "🕊 Release into the wild — free your roster"));
  }
  if (!p.hatched && !p.dead) {
    // busy() is click-instant AND mempool-covering now (SDK click-time pending registry): true from the
    // click until refreshAll's landedFn sees p.hatched, self-expiring so a lost tx can still be retried.
    const _hatchBusy = dapp.busy("hatch", "pid", p.id);
    $("btnHatch").disabled = !p.hatchReady || _hatchBusy;
    $("btnHatch").classList.toggle("pulse", p.hatchReady && !_hatchBusy);
    $("btnHatch").textContent = _hatchBusy ? window.t("pets.hatchingConfirm", "⏳ Hatching — confirming on-chain…") : window.t("pets.hatchEgg", "🐣 Hatch the egg");
    $("hatchHint").textContent = p.hatchReady ? window.t("pets.hatchReadyHint", "Anyone may hatch it; the animal was already decided by blocks {a}–{b}.", { a: p.bh, b: p.bh + 1 })
      : window.t("pets.hatchWaitHint", "Hatchable once blocks {a}–{b} are finalized", { a: p.bh, b: p.bh + 1 }) + (dapp.cursor ? window.t("pets.hatchWaitNow", " (now at {cur}, ~{time} + finality)", { cur: dapp.cursor, time: blocksToTime(Math.max(0, p.bh + 1 - dapp.cursor)) }) : "") + ".";
    $("btnRebirth").classList.toggle("hidden", !(p.stale && p.mine));
  }
  if (p.hatched && !p.dead) {
    $("feed1d").textContent = window.t("pets.feed1d", "+7 days · {cost} N", { cost: rawToNado(G.feedCost(7 * BLOCKS_PER_DAY, p.ap)) });
    $("feed3d").textContent = window.t("pets.feed3d", "+14 days · {cost} N", { cost: rawToNado(G.feedCost(14 * BLOCKS_PER_DAY, p.ap)) });
    const fillB = Math.max(0, G.BELLY_CAP - (lb || 0) - 60);
    $("feedFull").textContent = window.t("pets.feedFull", "fill belly (30d) · {cost} N", { cost: rawToNado(G.feedCost(fillB, p.ap)) });
    $("feedFull").dataset.blocks = fillB;
    $("feedHint").textContent = window.t("pets.feedHint1", "Hatched appetite {ap}: 1 NADO buys {days} days", { ap: p.ap, days: (G.feedBlocks(10n ** 10n, p.ap) / BLOCKS_PER_DAY).toFixed(1) })
      + (p.bonus && p.bonus[9] ? window.t("pets.feedHintTrained", " (trained Appetite +{b} is battle muscle only — the food bill never changes)", { b: p.bonus[9] }) : "")
      + window.t("pets.feedHint2", ". Anyone may feed any pet — a gift (the belly still tops out 30 days ahead).");
    dapp.syncPctSlider("feed", { slider: "feedSlider", input: "feedAmt" }, dapp.exec);   // feed: % of playable balance
  }
  if (p.hatched) {
    const tb = trainBusy(p.id);   // ONE session per pet — computed once, drives all 10 stat rows + the panel
    $("statList").innerHTML = G.STAT_NAMES.map((_n, i) => statRow(p, i, tb)).join("");
    $("statList").querySelectorAll("[data-train]").forEach((b) => b.onclick = () => train(p.id, parseInt(b.dataset.train, 10)));
    const tp = $("trainPending");
    if (p.th && local.trainPending === 1) { const l = L(); l[p.id].trainPending = 2; Lsave(l); local.trainPending = 2; }   // session seen on-chain
    if (!p.th && tb) {
      // the session was CLICKED but hasn't landed yet — show the panel NOW, so the very first click has an
      // immediate, in-place answer (the old p.th-only gate left this window silent: the exact "I click and
      // nothing happens" report). The stamp self-expires (trainBusy) so a lost tx re-opens the buttons.
      tp.classList.remove("hidden");
      tp.innerHTML = window.t("pets.trainingStat", "🏋 Training <b>{stat}</b>… ", { stat: local.trainStat || "" })
        + '<span class="waitpulse">' + window.t("pets.trainBooking", "session confirming on-chain…") + "</span>";
    } else if (p.th) {
      const ready = dapp.cursor != null && dapp.cursor >= p.th + 1 && dapp.bh(p.th) && dapp.bh(p.th + 1);
      const i = p.ti - 1;
      tp.classList.remove("hidden");
      tp.innerHTML = window.t("pets.trainingStat", "🏋 Training <b>{stat}</b>… ", { stat: G.STAT_NAMES[i] }) + (ready
        ? '<button class="mini primary" id="btnTrainRes">' + window.t("pets.revealResult", "Reveal the result") + '</button>'
        : '<span class="waitpulse">' + window.t("pets.resultLocking", "result locking in blocks {a}–{b} (~{time} + finality)…", { a: p.th, b: p.th + 1, time: blocksToTime(Math.max(0, p.th + 1 - (dapp.cursor || p.th))) }) + '</span>');
      if (ready) $("btnTrainRes").onclick = () => trainResolve(p.id);
    } else {
      tp.classList.add("hidden");
      if (local.trainPending === 2 && p.tr) {     // its resolve just landed — announce it once
        const ok = p.tr === 1;
        alertBar(ok ? window.t("pets.trainWin", "🎉 Training paid off — {label} got +1 {stat}!", { label: p.label, stat: local.trainStat || window.t("pets.aStat", "to a stat") }) : window.t("pets.trainFail", "Training didn't stick this time — the fee is spent, try again."));
        const l = L(); delete l[p.id].trainPending; delete l[p.id].trainStat; Lsave(l);
      }
    }
    $("trainHint").innerHTML = '<span style="color:var(--accent2)">' + window.t("pets.legBase", "▮ base") + '</span> ' + window.t("pets.legBaseNote", "(locked at hatch)") + ' · <span style="color:var(--gold)">' + window.t("pets.legTrained", "▮ trained") + '</span> ' + window.t("pets.legTrainedNote", "(your gains).") + ' '
      + window.t("pets.trainFormula", "Each attempt costs 0.5 NADO. Success chance = 100·K/(K+stat), K={k} for a {rarity} — the better the stat, the harder the gain (no cap, ever). Rarer animals train easier.", { k: G.trainK(p.sp), rarity: (tier ? esc(tier.rarity.toLowerCase()) : "") });
  }
  if (p.hatched && !p.dead && !p.mine && dapp.me) {
    const mine = myPets().filter((x) => x.hatched && !x.dead);
    $("myPetSel").innerHTML = mine.length
      ? mine.map((x) => `<option value="${x.id}"${x.resting ? " disabled" : ""}>${esc(x.label)} · ⚡${x.pw}${x.resting ? " · 💤 " + window.t("pets.restingLc", "resting") : ""}</option>`).join("")
      : '<option value="">' + window.t("pets.noLivingPet", "no living pet — adopt below") + '</option>';
    $("btnChallenge").disabled = p.resting;
    $("btnChallenge").textContent = p.resting ? window.t("pets.restingReady", "💤 Resting · ready in {time}", { time: dhm(p.restBlocks) }) : window.t("pets.challenge", "⚔ Challenge");
  }
  if (p.mine && !p.dead) {
    const named = !!p.nm;
    $("nameInput").classList.toggle("hidden", named);
    $("btnRename").classList.toggle("hidden", named);
  }
  shareInvite("pet", p.id, (p.hatched ? window.t("pets.shareMeet", "Meet {label}, my {rarity} {animal} on NADO Pets:", { label: p.label, rarity: tier.rarity, animal: AN(an) }) : window.t("pets.shareEgg", "My NADO Pets egg is incubating:")));
  $("btnCard").classList.toggle("hidden", !(p.hatched && !p.dead));
  maybePlayHatch(p);
}
function petCard(p, sel) {
  const cls = "pcard" + (p.dead ? " dead" : "") + (!p.hatched ? " egg" : "") + (sel ? " sel" : "") + " " + moodOf(p);
  const flags = (p.resting ? " 💤" : "") + (!p.dead && moodOf(p) === "hungry" ? " 🍖" : "") + (!p.dead && moodOf(p) === "starving" ? ' <span class="warn">🍖!</span>' : "");
  return `<div class="${cls}" data-pet="${p.id}">${petArt(p, "")}
    <div class="pn">${p.hatched ? p.animal.e + " " : "🥚 "}${esc(p.label)}</div>
    <div class="po">${p.hatched ? `<span style="color:${p.tier.color}">${p.tier.rarity}</span> · ⚡${p.pw}` : window.t("pets.incubatingShort", "incubating")}${p.dead ? " · ✝" : ""}${flags}</div>
    <div class="po">${p.price && !p.dead ? `🏷 ${rawToNado(p.price)} NADO` : esc(disp(p.owner))}</div></div>`;
}
// grid view state: search + sort + how many are shown (pagination keeps 10k pets browsable)
const VIEW = { g: { q: "", sort: "new", n: 24 }, m: { q: "", sort: "priceAsc", n: 24 }, me: { n: 24 } };
const SORTS = {
  new: (a, b) => b.bh - a.bh,                                        // mint block = age
  rarity: (a, b) => b.sp - a.sp || b.pw - a.pw,
  power: (a, b) => b.pw - a.pw,
  level: (a, b) => b.level - a.level || b.pw - a.pw,
  priceAsc: (a, b) => a.price - b.price,
  priceDesc: (a, b) => b.price - a.price,
};
function matches(p, q) {
  if (!q) return true;
  q = q.toLowerCase().replace(/^[@#]/, "");
  return (p.nm && p.nm.toLowerCase().includes(q)) || p.id.includes(q)
    || (p.hatched && (p.animal.n.toLowerCase().includes(q) || AN(p.animal).toLowerCase().includes(q)))
    || (p.hatched && p.tier.rarity.toLowerCase().includes(q))
    || p.owner.toLowerCase().startsWith(q) || disp(p.owner).toLowerCase().replace(/^@/, "").includes(q);
}
function grid(el, moreBtn, list, v, empty) {
  const shown = list.slice(0, v.n);
  el.innerHTML = shown.map((p) => petCard(p, String(active) === p.id)).join("") || `<span class="dim small">${empty}</span>`;
  moreBtn.classList.toggle("hidden", list.length <= v.n);
  if (list.length > v.n) moreBtn.textContent = window.t("pets.showMoreN", "Show more ({n} more)", { n: list.length - v.n });
}
function renderGrids() {
  const all = Object.values(PETS);
  const mine = myPets();
  const pendings = Object.keys(L()).filter((pid) => !PETS[pid]);
  // Cap owned pets like the gallery — each card is an animated SVG, so a whale holding thousands would
  // otherwise inject thousands of simultaneously-animating SVGs every poll. Pending eggs (in-flight adoptions)
  // are inherently few, so they always show.
  const mineShown = mine.slice(0, VIEW.me.n);
  $("myPetGrid").innerHTML = (mineShown.map((p) => petCard(p, String(active) === p.id)).join("")
    + pendings.map((pid) => `<div class="pcard egg pending" data-pet="${pid}">${eggSvg("egg-idle", 0)}<div class="pn">🥚 #${String(pid).slice(-4)}</div><div class="po">${window.t("pets.confirming", "confirming ⏳")}</div></div>`).join(""))
    || '<span class="dim small">' + window.t("pets.noPetsYet", "No pets yet — adopt your first egg below.") + '</span>';
  const bmm = $("btnMoreMine");
  if (bmm) {
    bmm.classList.toggle("hidden", mine.length <= VIEW.me.n);
    if (mine.length > VIEW.me.n) bmm.textContent = window.t("pets.showMoreN", "Show more ({n} more)", { n: mine.length - VIEW.me.n });
  }
  const nReady = readyEggs().length, running = localStorage.getItem("nado_pets_hatchall") === "1";
  const bha = $("btnHatchAll");
  if (bha) {
    bha.classList.toggle("hidden", nReady === 0 && !running);
    bha.disabled = !!dapp.inflight || nReady === 0;
    bha.textContent = running ? window.t("pets.hatchingAll", "🐣 Hatching all… ({n} left)", { n: nReady }) : window.t("pets.hatchAllN", "🐣 Hatch all ready eggs ({n})", { n: nReady });
  }
  $("petCount").textContent = all.length ? "— " + all.length : "";
  grid($("gallery"), $("btnMoreGallery"),
    all.filter((p) => matches(p, VIEW.g.q)).sort(SORTS[VIEW.g.sort] || SORTS.new),
    VIEW.g, window.t("pets.galleryEmpty", "No pets exist yet. Yours could be the very first."));
  grid($("marketGrid"), $("btnMoreMarket"),
    all.filter((p) => p.price && !p.dead && matches(p, VIEW.m.q)).sort(SORTS[VIEW.m.sort] || SORTS.priceAsc),
    VIEW.m, VIEW.m.q ? window.t("pets.marketNoMatch", "No listed pet matches your search.") : window.t("pets.marketEmpty", "Nothing for sale right now — list one of yours from its pet card."));
  // pet-card selection uses ONE delegated listener (wired once in wireUI), not a per-card rebind every poll.
  // hall of fame
  const top = Object.values(PETS).filter((p) => p.hatched && !p.dead).sort((a, b) => b.pw - a.pw).slice(0, 10);
  $("fameList").innerHTML = top.length ? '<table class="score"><thead><tr><th>#</th><th>' + window.t("pets.thPet", "Pet") + '</th><th>' + window.t("pets.thAnimal", "Animal") + '</th><th>' + window.t("pets.thPower", "Power") + '</th><th>' + window.t("pets.thOwner", "Owner") + '</th></tr></thead><tbody>'
    + top.map((p, i) => `<tr${p.mine ? ' class="me"' : ""}><td>${i + 1}</td><td>${p.animal.e} ${esc(p.label)}</td><td style="color:${p.tier.color}">${esc(AN(p.animal))}</td><td class="mono">⚡${p.pw} · Lv${p.level}</td><td>${esc(disp(p.owner))}</td></tr>`).join("") + "</tbody></table>"
    : '<span class="dim small">' + window.t("pets.noLivingPets", "No living pets yet.") + '</span>';
}
function renderBattles() {
  const rows = [];
  const mineIds = new Set(myPets().map((p) => p.id));
  // Only battles I'm in (or the one I'm actively viewing) ever render, so filter to those BEFORE sorting —
  // otherwise we'd sort the entire unbounded battle history every 3s just to drop almost all of it. The scan
  // itself is cheap boolean checks; the sort + row-building then run on a handful, not thousands.
  const bs = Object.values(BATTLES)
    .filter((b) => mineIds.has(b.a) || mineIds.has(b.b) || String(activeBattle) === b.id)
    .sort((a, b) => Number(b.id) - Number(a.id));
  for (const b of bs) {
    if (rows.length >= 60) break;   // hard safety cap on rendered rows
    const pa = PETS[b.a], pb = PETS[b.b]; if (!pa || !pb) continue;
    const inc = mineIds.has(b.b), out = mineIds.has(b.a), involved = inc || out;
    const stakeTxt = b.ws ? window.t("pets.stakeEach", "{price} NADO each", { price: rawToNado(b.ws) }) : window.t("pets.noStake", "no stake (still deadly)");
    if (b.wn === 1 && (involved || String(activeBattle) === b.id)) {
      const tired = pa.resting || pb.resting;   // accept would revert until both fighters are rested
      rows.push(`<div class="btl"><span class="who">${esc(pa.label)}</span>${window.t("pets.challengesMid", " ⚔ challenges ")}<span class="who">${esc(pb.label)}</span> · ${stakeTxt}
        <div class="act">${inc ? (tired ? `<span class="small dim">${window.t("pets.isResting", "💤 {label} is resting — acceptable in {time}", { label: esc((pa.resting ? pa : pb).label), time: dhm(Math.max(pa.restBlocks, pb.restBlocks)) })}</span>`
          : `<button class="mini primary" data-acc="${b.id}">${window.t("pets.acceptBattle", "Accept the battle")}</button>`) : ""}
        ${out ? `<button class="mini ghost" data-cxl="${b.id}">${window.t("pets.withdraw", "Withdraw")}</button>` : ""}
        <button class="mini ghost" data-view="${b.id}">${window.t("pets.view", "View")}</button></div></div>`);
    } else if (b.wn === 2 && (involved || String(activeBattle) === b.id)) {
      rows.push(`<div class="btl">⚡ <span class="who">${esc(pa.label)}</span> ${window.t("pets.vsLc", "vs")} <span class="who">${esc(pb.label)}</span> ${window.t("pets.fighting", "— fighting!")} · ${stakeTxt}
        <div class="act"><button class="mini primary" data-view="${b.id}">${window.t("pets.watchBattle", "Watch the battle")}</button></div></div>`);
    } else if (b.wn === 3 && involved && rows.length < 14 && b.ww) {
      const w = PETS[b.ww];
      rows.push(`<div class="btl">✓ <span class="who">${esc(w ? w.label : "#" + b.ww)}</span> ${window.t("pets.wonResult", "won {a} vs {b}", { a: esc(pa.label), b: esc(pb.label) })}${b.wd ? window.t("pets.diedSuffix", " · ☠ {d} died", { d: esc((PETS[b.wd] || {}).label || "#" + b.wd) }) : ""}
        <div class="act"><button class="mini ghost" data-view="${b.id}">${window.t("pets.replay", "Replay")}</button></div></div>`);
    }
  }
  $("battleList").innerHTML = rows.join("") || '<span class="dim small">' + window.t("pets.noChallenges", "No challenges. Pick a pet in the gallery and challenge it.") + '</span>';
  // button clicks are handled by ONE delegated listener on #battleList (wired once in wireUI), not per-row.
}
function renderArena() {
  gate({ arenaCard: activeBattle != null });
  if (activeBattle == null) return;
  const b = BATTLES[activeBattle], hint = $("arenaHint");
  $("arenaId").textContent = "#" + activeBattle;
  if (!b) { hint.textContent = dapp.whereIs("battle", activeBattle); return; }
  const pa = PETS[b.a], pb = PETS[b.b]; if (!pa || !pb) return;
  if (battlePlaying !== activeBattle) {           // (re)stage the fighters, idle
    $("arenaL").innerHTML = pa.hatched ? petBody(pa, "pet-idle") : eggSvg("egg-idle", 0);
    $("arenaR").innerHTML = pb.hatched ? petBody(pb, "pet-idle") : eggSvg("egg-idle", 0);
  }
  $("arenaLName").textContent = pa.label; $("arenaRName").textContent = pb.label;
  $("arenaLPow").textContent = "⚡ " + pa.pw + " · " + recordOf(pa); $("arenaRPow").textContent = "⚡ " + pb.pw + " · " + recordOf(pb);
  const effA = effOf(pa), effB = effOf(pb);
  const res = (b.wh && effA && effB) ? G.battleOf(dapp.bh(b.wh), dapp.bh(b.wh + 1), Number(b.id), effA, effB) : null;
  gate({ btnResolve: b.wn === 2 && !!res && !dapp.busy("resolveb", "bid", b.id),
         btnCancelBattle: b.wn === 1 && pa.mine,
         btnRefundBattle: b.wn === 2 && !res && dapp.cursor != null && dapp.cursor > b.wh + G.STALE });
  $("btnResolve").onclick = () => resolveBattle(b.id);
  $("btnCancelBattle").onclick = () => cancelBattle(b.id);
  $("btnRefundBattle").onclick = () => refundBattle(b.id);
  if (b.wn === 1) { $("arenaVerdict").textContent = window.t("pets.awaitingConsent", "Awaiting consent…"); hint.textContent = window.t("pets.awaitConsentHint", "The challenged pet's owner must accept (matching the stake) before the chain schedules the fight."); }
  else if (b.wn === 2 && !res) { $("arenaVerdict").textContent = window.t("pets.fightLocked", "⚡ Fight locked to blocks {a}–{b}", { a: b.wh, b: b.wh + 1 }); hint.textContent = window.t("pets.fightLockedHint", "Nobody can know the outcome until those blocks are finalized (~{time} + finality).", { time: blocksToTime(Math.max(0, b.wh + 1 - (dapp.cursor || b.wh))) }); }
  else if ((b.wn === 2 && res) || b.wn === 3) {
    const aWins = b.wn === 3 ? b.ww === b.a : res.aWins;
    const died = b.wn === 3 ? b.wd : (res.dies ? (aWins ? b.b : b.a) : 0);
    playBattle(b, pa, pb, aWins, died, res);
    hint.textContent = b.wn === 3 ? window.t("pets.settledOnchain", "Settled on-chain.") + (b.ws ? "" : window.t("pets.friendlyNoStake", " (friendly match — no stakes moved)")) : window.t("pets.chainDecided1", "The chain has decided — settling records it and pays the pot") + (b.ws ? window.t("pets.potAmount", " ({amt} NADO) ", { amt: rawToNado(2 * b.ws) }) : " ") + window.t("pets.chainDecided2", "to the winner's owner. Anyone may settle.");
  }
}
function playBattle(b, pa, pb, aWins, died, res) {
  if (battlePlaying === b.id) return;
  battlePlaying = b.id;
  const L_ = $("arenaL"), R_ = $("arenaR"), V = $("arenaVerdict"), LOG = $("arenaLog");
  const hpL = $("arenaLHP"), hpR = $("arenaRHP");
  const step = (el, cls, other, hurt) => { el.classList.remove("lungeL", "lungeR", "hitshake"); void el.offsetWidth; el.classList.add(cls); if (hurt) { other.classList.add("hitshake"); setTimeout(() => other.classList.remove("hitshake"), 380); } };
  // if we have the real turn log, play it out; otherwise fall back to a short flourish
  const log = res && res.log ? res.log.filter((e) => e.dmg > 0 || e.hit) : null;
  const hp0max = res ? res.hpA : 100, hp1max = res ? res.hpB : 100;
  if (hpL) hpL.style.width = "100%"; if (hpR) hpR.style.width = "100%";
  V.textContent = window.t("pets.fight", "⚔ FIGHT!"); if (LOG) LOG.textContent = "";
  let t = 300;
  const turns = log && log.length ? log.slice(0, 14) : [{ atk: aWins ? 0 : 1, dmg: 1, hit: 1 }];
  turns.forEach((e) => {
    setTimeout(() => {
      if (e.atk === 0) step(L_, "lungeL", R_, e.hit); else step(R_, "lungeR", L_, e.hit);
      if (res) {
        if (hpL) hpL.style.width = Math.max(0, 100 * e.h0 / hp0max) + "%";
        if (hpR) hpR.style.width = Math.max(0, 100 * e.h1 / hp1max) + "%";
      }
      if (LOG) LOG.textContent = (e.atk === 0 ? pa.label : pb.label) + (e.hit ? window.t(e.crit ? "pets.critsFor" : "pets.hitsFor", e.crit ? " CRITS 💥 for " : " hits for ") + e.dmg : window.t("pets.misses", " misses"));
    }, t);
    t += 560;
  });
  setTimeout(() => {
    const w = aWins ? L_ : R_, l = aWins ? R_ : L_;
    w.classList.add("winglow");
    if (died) l.innerHTML = graveSvg(); else l.classList.add("faint");
    const wp2 = aWins ? pa : pb, lp = aWins ? pb : pa;
    if (LOG) LOG.textContent = "";
    V.innerHTML = window.t("pets.wins", "🏆 <b>{w}</b> wins!", { w: esc(wp2.label) }) + (died
      ? window.t("pets.fell", " ☠ <b>{l}</b> fell in battle.", { l: esc(lp.label) })
      : window.t("pets.claims", " <b>{w}</b>'s owner claims <b>{l}</b>.", { w: esc(wp2.label), l: esc(lp.label) }));
  }, t + 300);
}
let hatchDone = {};
function maybePlayHatch(p) {
  if (!p.hatched || hatchPlaying || hatchDone[p.id]) return;
  const l = L();
  if (!(l[p.id] && l[p.id].hatchPending)) return;
  delete l[p.id].hatchPending; Lsave(l);
  hatchDone[p.id] = 1; hatchPlaying = true;
  const stage = $("petStage");
  stage.innerHTML = eggSvg("egg-shake", 0);
  let t = 900;
  [1, 2, 3].forEach((c, i) => setTimeout(() => { stage.innerHTML = eggSvg("egg-shake", c); }, t + i * 450));
  t += 3 * 450 + 250;
  setTimeout(() => { stage.innerHTML = eggSvg("", 4); }, t);          // shells fly
  setTimeout(() => {
    stage.innerHTML = petBody(p, "pet-idle pet-pop flash");
    for (let s = 0; s < 8; s++) {
      const sp = document.createElement("span"); sp.className = "spark"; sp.textContent = ["✨", "⭐", "💫"][s % 3];
      sp.style.setProperty("--dx", (Math.cos(s * 0.785) * 70) + "px"); sp.style.setProperty("--dy", (Math.sin(s * 0.785) * 70 - 20) + "px");
      stage.style.position = "relative"; sp.style.left = "50%"; sp.style.top = "45%"; stage.appendChild(sp);
      setTimeout(() => sp.remove(), 1100);
    }
    const an = p.animal, coat = G.coatOf(p.gene, an);
    alertBar(window.t("pets.hatchReveal", "🎉 It's a {rarity} — {coat} {emoji} {animal}{shiny}! One of {total} possible animals across six rarity tiers — its species, coat and 10 abilities are all written into its gene, locked forever. Name it, feed it, train it.",
      { rarity: p.tier.rarity.toUpperCase(), coat: CN(coat), emoji: an.e, animal: AN(an), total: G.ANIMALS.length, shiny: coat.shiny ? window.t("pets.shinySuffix", " ✦ SHINY") : "" }), null, null, { tone: "ok" });
  }, t + 600);
  setTimeout(() => { hatchPlaying = false; render(); }, t + 2400);
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ bankroll: signedIn, myPets: signedIn, adopt: signedIn, battlesCard: signedIn });
  let mintLeft = 0; try { mintLeft = parseInt(localStorage.getItem("nado_pets_mintq") || "0", 10) || 0; } catch (e) {}
  const qty = Math.max(1, Math.min(20, parseInt(($("mintQty") || {}).value, 10) || 1));
  $("btnMint").disabled = dapp.busy("mint") || mintLeft > 0;
  $("btnMint").textContent = mintLeft > 0 ? window.t("pets.adoptingN", "⏳ Adopting… ({n} left)", { n: mintLeft }) : dapp.busy("mint") ? window.t("pets.eggConfirming", "⏳ Egg confirming on-chain…")
    : qty > 1 ? window.t("pets.adoptManyBtn", "🥚 Adopt {n} eggs · burn {n} NADO", { n: qty }) : window.t("pets.adoptOneBtn", "🥚 Adopt an egg · burn 1 NADO");
  if ($("burnTally")) $("burnTally").textContent = BURNED > 0n ? window.t("pets.burnTally", "🔥 {amt} NADO burned by pets so far — adoption, food and training all destroy supply.", { amt: rawToNado(BURNED) }) : "";
  renderActive(); renderGrids(); renderBattles(); renderArena();
}

// ---- wire + boot -----------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['feedAmt', 'bankAmt', 'offerAmt', 'listPrice', 'stakeAmt']);   // typed amounts persist across turns
  $("btnMint").onclick = mintMany;
  if ($("mintQty")) $("mintQty").oninput = () => render();
  $("btnHatch").onclick = () => hatch(active);
  if ($("btnHatchAll")) $("btnHatchAll").onclick = hatchAll;
  $("btnRebirth").onclick = () => rebirth(active);
  $("btnFeed").onclick = () => { const raw = nadoToRaw($("feedAmt").value); if (!raw) return alertBar(window.t("pets.enterFeed", "Enter how much NADO to feed.")); feed(active, raw); };
  dapp.wirePctSlider("feed", { slider: "feedSlider", input: "feedAmt" }, () => dapp.exec, render);   // feed: % of your playable balance
  const preset = (blocks) => { const p = PETS[active]; if (p) feed(active, G.feedCost(blocks, p.ap)); };
  $("feed1d").onclick = () => preset(7 * BLOCKS_PER_DAY);
  $("feed3d").onclick = () => preset(14 * BLOCKS_PER_DAY);
  $("feedFull").onclick = () => preset(parseInt($("feedFull").dataset.blocks || "0", 10));
  $("btnChallenge").onclick = () => challenge(active);
  $("btnRename").onclick = () => nameIt(active);
  $("btnTransfer").onclick = () => transfer(active);
  $("btnList").onclick = () => listPet(active);
  $("btnUnlist").onclick = () => unlistPet(active);
  $("btnCombine").onclick = () => combine(active);
  $("btnRelease").onclick = () => release(active);
  $("btnBuy").onclick = () => buyPet(active);
  $("btnOffer").onclick = () => makeOffer(active);
  $("btnCard").onclick = () => { const p = PETS[active]; if (p && p.hatched && !p.dead) challengerCard(p); };
  const wireView = (v, q, s, more) => {
    $(q).oninput = () => { v.q = $(q).value.trim(); v.n = 24; renderGrids(); };
    $(s).onchange = () => { v.sort = $(s).value; v.n = 24; renderGrids(); };
    $(more).onclick = () => { v.n += 48; renderGrids(); };
  };
  wireView(VIEW.g, "galleryQ", "gallerySort", "btnMoreGallery");
  wireView(VIEW.m, "marketQ", "marketSort", "btnMoreMarket");
  if ($("btnMoreMine")) $("btnMoreMine").onclick = () => { VIEW.me.n += 48; renderGrids(); };
  // ONE delegated listener for all battle-row buttons (accept / withdraw / view), not one per row per poll.
  $("battleList").addEventListener("click", (e) => {
    const acc = e.target.closest("[data-acc]"), cxl = e.target.closest("[data-cxl]"), view = e.target.closest("[data-view]");
    if (acc) return acceptBattle(acc.dataset.acc);
    if (cxl) return cancelBattle(cxl.dataset.cxl);
    if (view) { activeBattle = view.dataset.view; battlePlaying = null; render(); try { $("arenaCard").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} }
  });
  // ONE delegated click handler for every pet card across all grids (my pets, gallery, market, pendings) —
  // survives re-renders and stays flat-cost no matter how many cards exist, replacing the per-card rebind.
  document.addEventListener("click", (e) => {
    const card = e.target.closest("[data-pet]");
    if (!card) return;
    active = card.dataset.pet; render();
    try { $("activePet").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  });
}
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.pid != null) active = pend.pid;
  if (pend && pend.bid != null) activeBattle = pend.bid;
  if (pend && pend.phase === "train") {
    const l = L();
    if (l[pend.pid]) {
      if (ok) l[pend.pid].trainPending = 1;
      else { delete l[pend.pid].trainPending; delete l[pend.pid].trainStat; }   // rejected sign → clear the announce markers (the SDK releases the click-guard itself)
      Lsave(l);
    }
  }
  dapp.showReturn(pend, ok, err, {
    mint: window.t("pets.rtMint", "Egg adopted — confirming on-chain (~1 min)…"), hatch: window.t("pets.rtHatch", "Hatching — confirming on-chain…"),
    feed: window.t("pets.rtFeed", "Nom nom — the meal is confirming…"), train: window.t("pets.rtTrain", "Training session booked — confirming…"),
    trainres: window.t("pets.rtTrainres", "Revealing the result — confirming…"), challenge: window.t("pets.rtChallenge", "Challenge sent — the owner must accept it."),
    accept: window.t("pets.rtAccept", "Battle on! The chain decides in ~2 blocks…"), resolveb: window.t("pets.rtResolveb", "Settling the battle…"),
    cancelb: window.t("pets.rtCancelb", "Withdrawing…"), rename: window.t("pets.rtRename", "Naming — it's for life; confirming…"), xfer: window.t("pets.rtXfer", "Transferring your pet — confirming…"),
    market: window.t("pets.rtMarket", "Updating the listing — confirming…"), buy: window.t("pets.rtBuy", "Buying — confirming on-chain (~1 min)…"),
    offer: window.t("pets.rtOffer", "Offer sent — escrowed until the owner accepts."), offeract: window.t("pets.rtOfferact", "Confirming…") });
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("pets.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  orderCards(["activePet", "arenaCard", "battlesCard", "myPets", "adopt", "marketCard", "galleryCard", "fameCard", "walletcard", "bankroll"]);
  const q = new URLSearchParams(location.search);
  if (q.get("pet")) active = q.get("pet");
  if (q.get("battle")) activeBattle = q.get("battle");
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
if ($("btnMint")) boot();   // only boot on the real page — the art gallery imports this module bare
// debug/gallery surface (no game state). initCrypto loads the hash bundle through THIS module graph —
// the static server version-stamps import specifiers, so an outside import would hit a second instance.
export const _art = { ART, wrap, FLOATERS, challengerCanvas, initCrypto: loadCrypto, initQR: loadQR, fierce: (v) => { FIERCE = v ? 1 : 0; } };
