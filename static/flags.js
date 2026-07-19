// flags.js — tiny inline-SVG country flags for the network-nodes table.
//
// Why not emoji: 🇳🇱 and friends are REGIONAL INDICATOR pairs, and Windows ships no flag glyphs for them —
// it renders the two letters instead, so a Windows user just sees "NL". Any image approach is out too: the
// pages run under a strict no-external-host policy, so a flag CDN can never load. These are therefore drawn
// inline, as a few rects per flag, from a compact spec table.
//
// Coverage is deliberately partial — most flags are stripes, so those come from one generic renderer, a
// handful of common patterns (Nordic cross, plain cross, centred disc) get their own, and a few bespoke
// ones are hand-drawn. Anything unknown falls back to a neat two-letter badge, which is honest and still
// tells you where the node is. Add a country by adding one line, not a file.
const W = 21, H = 15;   // 7:5, the usual flag ratio

const stripes = (cols, vertical) => {
  const n = cols.length, step = (vertical ? W : H) / n;
  return cols.map((c, i) => vertical
    ? `<rect x="${(i * step).toFixed(2)}" y="0" width="${step.toFixed(2)}" height="${H}" fill="${c}"/>`
    : `<rect x="0" y="${(i * step).toFixed(2)}" width="${W}" height="${step.toFixed(2)}" fill="${c}"/>`).join("");
};
// Nordic cross: offset vertical bar, centred horizontal bar
const nordic = (bg, cr, inner) => {
  const t = 3, x = 6.5, y = (H - t) / 2;
  const band = (c, w) => `<rect x="${x - (w - t) / 2}" y="0" width="${w}" height="${H}" fill="${c}"/>`
    + `<rect x="0" y="${y - (w - t) / 2}" width="${W}" height="${w}" fill="${c}"/>`;
  return `<rect width="${W}" height="${H}" fill="${bg}"/>` + (inner ? band(inner, t + 2) : "") + band(cr, t);
};
const swissCross = (bg, cr) => `<rect width="${W}" height="${H}" fill="${bg}"/>`
  + `<rect x="9" y="3.2" width="3" height="8.6" fill="${cr}"/><rect x="6.2" y="6" width="8.6" height="3" fill="${cr}"/>`;
const disc = (bg, c, r = 4) => `<rect width="${W}" height="${H}" fill="${bg}"/>`
  + `<circle cx="${W / 2}" cy="${H / 2}" r="${r}" fill="${c}"/>`;
const star = (cx, cy, r, fill) => {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5, rad = i % 2 ? r * 0.4 : r;
    pts.push((cx + rad * Math.cos(a)).toFixed(2) + "," + (cy + rad * Math.sin(a)).toFixed(2));
  }
  return `<polygon points="${pts.join(" ")}" fill="${fill}"/>`;
};

const FLAGS = {
  // --- horizontal stripes ---
  NL: () => stripes(["#AE1C28", "#FFF", "#21468B"]),
  DE: () => stripes(["#000", "#D00", "#FFCE00"]),
  RU: () => stripes(["#FFF", "#0039A6", "#D52B1E"]),
  AT: () => stripes(["#ED2939", "#FFF", "#ED2939"]),
  LV: () => stripes(["#9E3039", "#FFF", "#9E3039"]),
  EE: () => stripes(["#0072CE", "#000", "#FFF"]),
  LT: () => stripes(["#FDB913", "#006A44", "#C1272D"]),
  HU: () => stripes(["#CE2939", "#FFF", "#477050"]),
  BG: () => stripes(["#FFF", "#00966E", "#D62612"]),
  PL: () => stripes(["#FFF", "#DC143C"]),
  ID: () => stripes(["#CE1126", "#FFF"]),
  UA: () => stripes(["#0057B7", "#FFD700"]),
  IN: () => stripes(["#F93", "#FFF", "#138808"]),
  EG: () => stripes(["#CE1126", "#FFF", "#000"]),
  AR: () => stripes(["#74ACDF", "#FFF", "#74ACDF"]),
  ES: () => stripes(["#AA151B", "#F1BF00", "#AA151B"]),
  // --- vertical stripes ---
  FR: () => stripes(["#002395", "#FFF", "#ED2939"], 1),
  IT: () => stripes(["#009246", "#FFF", "#CE2B37"], 1),
  IE: () => stripes(["#169B62", "#FFF", "#FF883E"], 1),
  BE: () => stripes(["#000", "#FDDA24", "#EF3340"], 1),
  RO: () => stripes(["#002B7F", "#FCD116", "#CE1126"], 1),
  MX: () => stripes(["#006847", "#FFF", "#CE1126"], 1),
  PE: () => stripes(["#D91023", "#FFF", "#D91023"], 1),
  PT: () => stripes(["#060", "#F00"], 1),
  // --- crosses / discs ---
  SE: () => nordic("#006AA7", "#FECC00"),
  NO: () => nordic("#BA0C2F", "#FFF", null) + `<rect x="7.6" y="6" width="0.8" height="3" fill="#00205B"/>`,
  DK: () => nordic("#C8102E", "#FFF"),
  FI: () => nordic("#FFF", "#003580"),
  IS: () => nordic("#02529C", "#DC1E35", "#FFF"),
  CH: () => swissCross("#D52B1E", "#FFF"),
  JP: () => disc("#FFF", "#BC002D", 4),
  BD: () => disc("#006A4E", "#F42A41", 4),
  // --- bespoke, simplified ---
  US: () => stripes(["#B22234", "#FFF", "#B22234", "#FFF", "#B22234", "#FFF", "#B22234"])
        + `<rect width="9" height="8.6" fill="#3C3B6E"/>`
        + [1.6, 4.4, 7.2].map((x) => [1.6, 4.3, 7].map((y) => star(x, y, 1, "#FFF")).join("")).join(""),
  GB: () => `<rect width="${W}" height="${H}" fill="#012169"/>`
        + `<path d="M0,0 L${W},${H} M${W},0 L0,${H}" stroke="#FFF" stroke-width="3"/>`
        + `<path d="M0,0 L${W},${H} M${W},0 L0,${H}" stroke="#C8102E" stroke-width="1.4"/>`
        + `<path d="M${W / 2},0 V${H} M0,${H / 2} H${W}" stroke="#FFF" stroke-width="5"/>`
        + `<path d="M${W / 2},0 V${H} M0,${H / 2} H${W}" stroke="#C8102E" stroke-width="3"/>`,
  CN: () => `<rect width="${W}" height="${H}" fill="#DE2910"/>` + star(4, 4, 2.6, "#FFDE00")
        + [[8.2, 1.6], [9.8, 3.4], [9.8, 5.8], [8.2, 7.4]].map(([x, y]) => star(x, y, 0.9, "#FFDE00")).join(""),
  VN: () => `<rect width="${W}" height="${H}" fill="#DA251D"/>` + star(W / 2, H / 2, 4, "#FF0"),
  TR: () => `<rect width="${W}" height="${H}" fill="#E30A17"/>`
        + `<circle cx="8.4" cy="7.5" r="3.4" fill="#FFF"/><circle cx="9.6" cy="7.5" r="2.7" fill="#E30A17"/>`
        + star(13.2, 7.5, 1.6, "#FFF"),
  CA: () => `<rect width="${W}" height="${H}" fill="#FFF"/><rect width="5.2" height="${H}" fill="#D80621"/>`
        + `<rect x="${W - 5.2}" width="5.2" height="${H}" fill="#D80621"/>`
        + `<path d="M10.5,3.4 11.3,5.6 13.3,4.9 12.6,6.9 14.4,7.2 12.9,8.4 13.4,10.2 11.2,9.6 10.5,11.8 9.8,9.6 7.6,10.2 8.1,8.4 6.6,7.2 8.4,6.9 7.7,4.9 9.7,5.6 Z" fill="#D80621"/>`,
  BR: () => `<rect width="${W}" height="${H}" fill="#009C3B"/>`
        + `<polygon points="${W / 2},1.6 ${W - 2},7.5 ${W / 2},13.4 2,7.5" fill="#FFDF00"/>`
        + `<circle cx="${W / 2}" cy="7.5" r="2.6" fill="#002776"/>`,
  KR: () => `<rect width="${W}" height="${H}" fill="#FFF"/>`
        + `<circle cx="${W / 2}" cy="7.5" r="3.4" fill="#CD2E3A"/>`
        + `<path d="M7.1,7.5 a1.7,1.7 0 0 1 3.4,0 a1.7,1.7 0 0 0 3.4,0 a3.4,3.4 0 0 1-6.8,0" fill="#0047A0"/>`,
  SG: () => `<rect width="${W}" height="${H}" fill="#FFF"/><rect width="${W}" height="7.5" fill="#ED2939"/>`
        + `<circle cx="5.2" cy="3.8" r="2.6" fill="#FFF"/><circle cx="6.4" cy="3.8" r="2.2" fill="#ED2939"/>`,
  AU: () => `<rect width="${W}" height="${H}" fill="#012169"/>`
        + `<path d="M0,0 L10.5,7.5 M10.5,0 L0,7.5" stroke="#FFF" stroke-width="2"/>`
        + `<path d="M5.25,0 V7.5 M0,3.75 H10.5" stroke="#FFF" stroke-width="3"/>`
        + `<path d="M5.25,0 V7.5 M0,3.75 H10.5" stroke="#C8102E" stroke-width="1.6"/>`
        + star(15.5, 10, 1.7, "#FFF") + star(18, 4, 1, "#FFF"),
  NZ: () => `<rect width="${W}" height="${H}" fill="#012169"/>`
        + `<path d="M0,0 L10.5,7.5 M10.5,0 L0,7.5" stroke="#FFF" stroke-width="2"/>`
        + `<path d="M5.25,0 V7.5 M0,3.75 H10.5" stroke="#FFF" stroke-width="3"/>`
        + `<path d="M5.25,0 V7.5 M0,3.75 H10.5" stroke="#C8102E" stroke-width="1.6"/>`
        + [[15, 4], [17.5, 7], [15, 11], [18.5, 10]].map(([x, y]) => star(x, y, 1, "#C8102E")).join(""),
  ZA: () => `<rect width="${W}" height="${H}" fill="#002395"/><rect width="${W}" height="7.5" fill="#DE3831"/>`
        + `<path d="M0,0 L8,7.5 L0,15 Z" fill="#007A4D"/>`,
  TW: () => `<rect width="${W}" height="${H}" fill="#FE0000"/><rect width="10.5" height="7.5" fill="#000095"/>`
        + `<circle cx="5.25" cy="3.75" r="2" fill="#FFF"/>`,
  HK: () => `<rect width="${W}" height="${H}" fill="#DE2910"/><circle cx="${W / 2}" cy="7.5" r="3.2" fill="#FFF"/>`,
  IL: () => `<rect width="${W}" height="${H}" fill="#FFF"/><rect y="2" width="${W}" height="1.8" fill="#0038B8"/>`
        + `<rect y="11.2" width="${W}" height="1.8" fill="#0038B8"/>`
        + `<path d="M10.5,4.6 13,9 8,9 Z M10.5,10.4 8,6 13,6 Z" fill="none" stroke="#0038B8" stroke-width="0.7"/>`,
  CZ: () => `<rect width="${W}" height="${H}" fill="#FFF"/><rect y="7.5" width="${W}" height="7.5" fill="#D7141A"/>`
        + `<polygon points="0,0 10,7.5 0,15" fill="#11457E"/>`,
  SK: () => stripes(["#FFF", "#0B4EA2", "#EE1C25"]),
  GR: () => stripes(["#0D5EAF", "#FFF", "#0D5EAF", "#FFF", "#0D5EAF", "#FFF", "#0D5EAF", "#FFF", "#0D5EAF"])
        + `<rect width="8.4" height="8.4" fill="#0D5EAF"/>`
        + `<path d="M4.2,0 V8.4 M0,4.2 H8.4" stroke="#FFF" stroke-width="1.7"/>`,
};

/**
 * flagSvg(cc) -> an inline <svg> string for a 2-letter country code, or "" when we have no drawing.
 * Sized in ems so it rides the surrounding text; rounded + hairline-bordered so pale flags (JP, CH) still
 * read as a flag against a dark table.
 */
export function flagSvg(cc) {
  if (!cc || cc.length !== 2) return "";
  const f = FLAGS[cc.toUpperCase()];
  if (!f) return "";
  return `<svg viewBox="0 0 ${W} ${H}" width="1.15em" height="0.82em" aria-hidden="true" `
    + `style="vertical-align:-1px;border-radius:2px;flex:none">`
    + `<g>${f()}</g><rect width="${W}" height="${H}" fill="none" stroke="rgba(255,255,255,.25)" stroke-width="0.6"/></svg>`;
}

/** the always-works fallback: a small two-letter badge, so an undrawn country still says where it is */
export function ccBadge(cc) {
  if (!cc || cc.length !== 2) return "";
  return `<span style="display:inline-block;padding:0 3px;border-radius:3px;background:rgba(255,255,255,.09);`
    + `font-size:9px;font-weight:700;letter-spacing:.03em;vertical-align:1px">${cc.toUpperCase()}</span>`;
}
