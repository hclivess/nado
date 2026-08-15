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
  const blk = css.match(new RegExp(`html\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`))[1];

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

console.log('\n' + (fails ? `${fails} FAILURE(S)` : 'ALL THEME CHECKS PASSED'));
process.exit(fails ? 1 : 0);
