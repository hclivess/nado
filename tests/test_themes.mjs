/* Wallet THEMES (static/interface.css + interface.js + i18n.js).
 *
 * A theme replaces the WHOLE palette — page ground, card surfaces, borders, the three text weights and
 * the accent pair. Tinting surfaces toward a hue is precisely how a theme quietly makes text unreadable,
 * so contrast is RECOMPUTED here with the WCAG relative-luminance formula on every run rather than
 * trusted from whoever picked the colours. The bar is the base theme's own behaviour: body text >= 4.5:1
 * against both the page and a card, dim text >= 4.5:1, faint text >= 3:1, accent >= 3:1.
 *
 * The other failure this pins is subtle: rgba() cannot take a hex custom property, so the page wash,
 * button shadow and pill fills were hardcoded to the brand teal — a theme recoloured the buttons and left
 * the page glow teal. --accent-rgb fixes that only if it is arithmetically the same colour as --accent,
 * which is checked, because a mismatch is invisible in review and obvious on screen. */
import { readFileSync } from 'node:fs';
const R = '/srv/nado-home/nado/static/';
const css = readFileSync(R + 'interface.css', 'utf8');
const js  = readFileSync(R + 'interface.js', 'utf8');
const i18 = readFileSync(R + 'i18n.js', 'utf8');
const read = (rel) => readFileSync('/srv/nado-home/nado/' + rel, 'utf8');
let fails = 0;
const check = (n, c) => { console.log((c ? 'PASS  ' : 'FAIL  ') + n); if (!c) fails++; };

const cssIds = [...css.matchAll(/html\[data-theme="([a-z]+)"\]/g)].map(m => m[1]);
const jsIds = [...js.match(/const THEMES = \[([\s\S]*?)\];/)[1].matchAll(/id:\s*"([a-z]+)"/g)].map(m => m[1]);
check(`the picker offers several themes (${jsIds.length})`, jsIds.length >= 5);
check('the default is teal and needs no CSS block (the :root values stay authoritative)',
  jsIds[0] === 'teal' && !cssIds.includes('teal'));
check('every non-default theme has a CSS block', jsIds.slice(1).every(i => cssIds.includes(i)));
check('every CSS block is offered by the picker', [...new Set(cssIds)].every(i => jsIds.includes(i)));

// WCAG relative luminance, so the palettes are measured rather than asserted by their author.
const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (hex) => { const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05); };
const varOf = (blk, name) => (blk.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`)) || [])[1];

const VARS = ['bg', 'bg-elev', 'bg-elev2', 'border', 'txt', 'txt-dim', 'txt-faint', 'accent', 'accent-2'];
for (const id of new Set(cssIds)) {
  // a selector spans SEVERAL blocks (palette + logo ramp); merge them, or the first one wins
  const blk = [...css.matchAll(new RegExp(`html\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`, 'g'))]
    .map((m) => m[1]).join('');

  check(`${id}: replaces the WHOLE palette, not just the accent`,
    VARS.every((v) => new RegExp(`--${v}:`).test(blk)) && /--accent-rgb:/.test(blk));

  const hex = varOf(blk, 'accent');
  const rgb = (blk.match(/--accent-rgb:\s*([0-9, ]+);/) || [])[1]?.split(',').map((n) => +n.trim());
  const want = hex && [0, 2, 4].map((i) => parseInt(hex.replace('#', '').slice(i, i + 2), 16));
  check(`${id}: accent-rgb is the same colour as accent (else the washes disagree with the buttons)`,
    !!want && JSON.stringify(rgb) === JSON.stringify(want));

  // the readability bar — the base theme's own behaviour, recomputed
  const [bg, card, txt, dim, faint, acc] =
    ['bg', 'bg-elev', 'txt', 'txt-dim', 'txt-faint', 'accent'].map((v) => varOf(blk, v));
  const r = (f, b) => ratio(f, b).toFixed(2);
  check(`${id}: body text on the page is legible (${r(txt, bg)}:1 >= 4.5)`, ratio(txt, bg) >= 4.5);
  check(`${id}: body text on a card is legible (${r(txt, card)}:1 >= 4.5)`, ratio(txt, card) >= 4.5);
  check(`${id}: dim text on a card is legible (${r(dim, card)}:1 >= 4.5)`, ratio(dim, card) >= 4.5);
  check(`${id}: faint text clears the large-text bar (${r(faint, card)}:1 >= 3)`, ratio(faint, card) >= 3);
  check(`${id}: the accent is visible on the page (${r(acc, bg)}:1 >= 3)`, ratio(acc, bg) >= 3);
}

check('no accent colour is left hardcoded (a theme must reach the glow and shadows too)',
  !/rgba\(\s*0\s*,\s*173\s*,\s*147/.test(css));
check('the alpha washes go through --accent-rgb', (css.match(/rgba\(var\(--accent-rgb\)/g) || []).length >= 4);

check('the theme is applied before first paint, from a NON-module script',
  /nado_theme/.test(i18) && /data-theme/.test(i18));
check('...and validates the stored value rather than trusting it', /\/\^\[a-z\]\{3,10\}\$\//.test(i18));
check('an unknown stored theme falls back to the default', /THEMES\.find\(\(x\) => x\.id === id\) \|\| THEMES\[0\]/.test(js));
check('the choice is persisted', /localStorage\.setItem\(LS_THEME/.test(js));
check('the picker previews the whole palette — accent gradient over the theme ground',
  /linear-gradient\(135deg, \$\{t\.a\} 0%, \$\{t\.b\} 45%, \$\{t\.bg\} 46%/.test(js));
check('every picker entry carries its page ground for that preview',
  [...js.match(/const THEMES = \[([\s\S]*?)\];/)[1].matchAll(/id:\s*"[a-z]+"/g)].length ===
  [...js.match(/const THEMES = \[([\s\S]*?)\];/)[1].matchAll(/bg:\s*"#/g)].length);
check('the picker is keyboard-reachable and states which is active',
  /aria-pressed/.test(js) && /:focus-visible/.test(css));


// ---- the SDK and the logo must follow the theme too --------------------------------------------------
// A theme that stops at the wallet is the bug this file grew out of: game pages load no shared stylesheet
// and the SDK hardcoded its own palette, so the wallet themed and every game stayed brand teal.
const sdk = readFileSync(R + 'nadodapp.js', 'utf8');
const tok = readFileSync(R + 'theme.css', 'utf8');
const svg = readFileSync(R + 'logo.svg', 'utf8');
const html = readFileSync(R + 'interface.html', 'utf8');

check('the SDK carries the shared tokens to every dapp page', /theme\.css/.test(sdk));
check('...and mirrors the wallet\'s stored choice', /nado_theme/.test(sdk) && /data-theme/.test(sdk));
check('...validating it rather than trusting it', /\/\^\[a-z\]\{3,10\}\$\//.test(sdk));
check('the SDK hardcodes NO palette colour any more',
  !/#(00ad93|00c9a7|131a23|243140|e6edf3|93a1b0|1a232e)/i.test(sdk));
check('the SDK stopped inventing variable names nothing defines',
  !/--accent2|--elev,|--dim,/.test(sdk));
check('theme.css defines every palette', (tok.match(/--accent-rgb:/g) || []).length === new Set(cssIds).size + 1);

check('the logo is driven by variables', (svg.match(/var\(--logo-\d/g) || []).length === 5);
check('...with the brand teal kept as the fallback, so the favicon still renders',
  /var\(--logo-5, #00ad93\)/.test(svg));
check('the header logo is INLINE (an <img src> cannot inherit page variables)',
  /var\(--logo-1/.test(html) && !/<img class="logo"/.test(html));
for (const id of new Set(cssIds)) {
  const merged = [...css.matchAll(new RegExp(`html\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`, 'g'))]
    .map((m) => m[1]).join('');
  check(`${id}: has a 5-step logo ramp`, (merged.match(/--logo-\d:/g) || []).length === 5);
  const acc = (merged.match(/--accent:\s*(#[0-9a-fA-F]{6})/) || [])[1];
  const top = (merged.match(/--logo-5:\s*(#[0-9a-fA-F]{6})/) || [])[1];
  check(`${id}: the logo's lightest step IS the accent`, acc && top && acc.toLowerCase() === top.toLowerCase());
}


// ---- controls and on-accent text ---------------------------------------------------------------------
// `.switch` was a class with no rules behind it, so six Settings/Quorum/Assets toggles were plain native
// checkboxes painted with the BROWSER's accent — green on most platforms — under every theme.
check('native controls take the theme accent', /accent-color:\s*var\(--accent\)/.test(css));
check('...applied to checkboxes generally, so a new control is themed by default',
  /input\[type="checkbox"\][^{]*\{[^}]*accent-color/.test(css));
// ONE toggle implementation, not two. `.tgl` was a hand-built pill (three elements of markup) that lived
// only in interface.css; `.switch` was an unstyled class that fell through to a NATIVE checkbox — a white
// square on a dark card, sitting right below the .tgl pill in the same panel. `.switch` is now that pill
// drawn on the input itself, and .tgl is deleted rather than kept in parallel.
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '');   // prose still explains .tgl; only RULES matter
check('.tgl is gone — a single toggle implementation remains',
  !/\.tgl\b/.test(rules) && !/tgl-track/.test(read('static/interface.html') + read('static/interface.js')));
check('.switch is drawn, not left to the browser',
  /input\[type="checkbox"\]\.switch\s*\{[^}]*appearance:\s*none/.test(css));
check('...with a knob that moves on :checked', /\.switch:checked::after[^}]*translateX/.test(css));
check('an unchecked NATIVE box paints dark, not white', /color-scheme:\s*dark/.test(css));
check('text ON the accent follows the theme ground, not a teal-era constant',
  !/color:\s*#04110a/.test(css));

// A button label is --bg on --accent; on a light accent (toxic, hazard, aqua) a fixed near-black was
// wrong, and a theme whose ground is close to its accent would render an unreadable button.
for (const [sel, id] of [[':root', 'teal'], ...[...new Set(cssIds)].map((i) => [`html[data-theme="${i}"]`, i])]) {
  const blk = [...css.matchAll(new RegExp(sel.replace(/[[\]]/g, '\\$&') + '\\s*\\{([^}]*)\\}', 'g'))]
    .map((m) => m[1]).join('');
  const bg = (blk.match(/--bg:\s*(#[0-9a-fA-F]{6})/) || [])[1];
  const acc = (blk.match(/--accent:\s*(#[0-9a-fA-F]{6})/) || [])[1];
  if (!bg || !acc) continue;
  check(`${id}: the button label is legible on its own accent (${ratio(bg, acc).toFixed(2)}:1 >= 4.5)`,
    ratio(bg, acc) >= 4.5);
}

// ---- UNIVERSALITY: the theme has to reach the game pages, not just the wallet ------------------------
// Game pages carry their own inline <style> and load no shared stylesheet — theme.css is injected by the
// SDK. So anything they need must be IN theme.css: the tokens, the component rules, and the legacy var
// names (--elev/--dim/--accent2) those 24 pages were written against and still hardcode as brand teal.
const theme = read('static/theme.css');
check('theme.css carries the shared component region, not just tokens',
  /SHARED-COMPONENTS/.test(theme) && /\.switch/.test(theme));
check('the toggle is defined ONCE — theme.css copies interface.css verbatim',
  (css.match(/>>> SHARED-COMPONENTS([\s\S]*?)<<< SHARED-COMPONENTS/) || [])[1] ===
  (theme.match(/>>> SHARED-COMPONENTS([\s\S]*?)<<< SHARED-COMPONENTS/) || [])[1]);
for (const a of ['--elev', '--elev2', '--dim', '--faint', '--accent2']) {
  check(`theme.css overrides the legacy name ${a} the game pages use`,
    new RegExp(a.replace('-', '\\-') + ':\\s*var\\(').test(theme));
}
check('the page glow derives from the accent (all 24 game pages hardcoded teal)',
  /radial-gradient\([^)]*rgba\(var\(--accent-rgb\)/.test(theme));
// every palette must supply the aliases, or a theme would half-apply on a game page
for (const id of [...new Set(cssIds)]) {
  const blk = (theme.match(new RegExp(`html\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`)) || [])[1] || '';
  check(`${id}: exports both vocabularies`, /--accent2:/.test(blk) && /--accent-2:/.test(blk));
}

// ---- BACKGROUND ART: the second, independent axis ---------------------------------------------------
// Same universality rule as the palette — the html[data-bg] rules live in the shared region so the SDK
// can mirror the id onto a game page without ever naming an artwork file. The failure this pins is a
// picker entry whose CSS rule was never added: the swatch appears, the click "works", nothing changes.
import { existsSync } from 'node:fs';
const bgIds = [...js.match(/const BACKGROUNDS = \[([\s\S]*?)\];/)[1].matchAll(/id:\s*"([a-z]+)"/g)].map(m => m[1]);
const cssBgIds = [...new Set([...css.matchAll(/html\[data-bg="([a-z]+)"\]/g)].map(m => m[1]))];
check(`the picker offers several backgrounds (${bgIds.length})`, bgIds.length >= 4);
check('"none" is first and is the default (it sets no attribute at all)', bgIds[0] === 'none');
check('every offered background has a CSS rule',
  bgIds.slice(1).every((i) => cssBgIds.includes(i)));
check('every CSS background rule is offered by the picker', cssBgIds.every((i) => bgIds.includes(i)));
check('the art rules ride in the SHARED region, so game pages get them too',
  cssBgIds.every((i) => new RegExp(`html\\[data-bg="${i}"\\]`).test(theme)));
// a url() that 404s degrades to a plain page and is invisible in review — check the files are really there
for (const m of css.matchAll(/html\[data-bg="([a-z]+)"\][^{]*\{[^}]*url\("([^"]+)"\)/g)) {
  check(`${m[1]}: its artwork exists at ${m[2]}`, existsSync('/srv/nado-home/nado' + m[2]));
}
// the swatch previews the real file, so a picker entry pointing at a missing preview is the same bug
for (const m of js.matchAll(/art:\s*"([^"]+)"/g)) {
  check(`swatch art exists: ${m[1]}`, existsSync('/srv/nado-home/nado' + m[1]));
}
const sdkSrc = read('static/nadodapp.js');
check('the SDK mirrors the background choice onto game pages', /nado_bg/.test(sdkSrc) && /data-bg/.test(sdkSrc));
check('...and i18n.js applies it BEFORE first paint, like the theme',
  /nado_bg/.test(i18) && /data-bg/.test(i18));
// The art layer only renders if BODY is transparent: a negative-z-index child paints before the
// backgrounds of in-flow boxes, so an opaque body background hides it completely and silently.
check('body stays transparent so the art layer is visible at all',
  /body \{ background: transparent; \}/.test(css));
check('...and the page glow moved to <html> to make that possible',
  /^html \{\n\s*background: radial-gradient/m.test(css));

console.log('\n' + (fails ? `${fails} FAILURE(S)` : 'ALL THEME CHECKS PASSED'));
process.exit(fails ? 1 : 0);
