/* Wallet accent THEMES (static/interface.css + interface.js + i18n.js).
 *
 * A theme overrides three variables and nothing else — the accent, its lighter partner for the 135deg
 * button gradient, and the same accent in bare RGB channels for the alpha washes. Surfaces, text and
 * borders stay shared with the base theme deliberately: recolouring only the accent means a theme cannot
 * change any contrast ratio the interface was designed against, so no theme can make text unreadable.
 *
 * The failure this pins is subtle. rgba() cannot take a hex custom property, so the page wash, the button
 * shadow and the pill fills were hardcoded to the brand teal — a theme would recolour the buttons and
 * leave the page glow teal. --accent-rgb exists to fix that, which only works if every theme's rgb is the
 * SAME colour as its own hex. That is arithmetic, so it is checked rather than eyeballed. */
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

for (const id of new Set(cssIds)) {
  const blk = css.match(new RegExp(`html\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`))[1];
  const hex = blk.match(/--accent:\s*#([0-9a-f]{6})/)?.[1];
  const rgb = blk.match(/--accent-rgb:\s*([0-9, ]+);/)?.[1].split(',').map(n => +n.trim());
  const want = hex && [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
  check(`${id}: defines accent, accent-2 and accent-rgb`,
    /--accent:/.test(blk) && /--accent-2:/.test(blk) && /--accent-rgb:/.test(blk));
  check(`${id}: accent-rgb is the same colour as accent (else the washes disagree with the buttons)`,
    !!want && JSON.stringify(rgb) === JSON.stringify(want));
}

check('no accent colour is left hardcoded (a theme must reach the glow and shadows too)',
  !/rgba\(\s*0\s*,\s*173\s*,\s*147/.test(css));
check('the alpha washes go through --accent-rgb', (css.match(/rgba\(var\(--accent-rgb\)/g) || []).length >= 4);

check('the theme is applied before first paint, from a NON-module script',
  /nado_theme/.test(i18) && /data-theme/.test(i18));
check('...and validates the stored value rather than trusting it', /\/\^\[a-z\]\{3,10\}\$\//.test(i18));
check('an unknown stored theme falls back to the default', /THEMES\.find\(\(x\) => x\.id === id\) \|\| THEMES\[0\]/.test(js));
check('the choice is persisted', /localStorage\.setItem\(LS_THEME/.test(js));
check('the picker previews each theme as its own gradient', /linear-gradient\(135deg, \$\{t\.a\}, \$\{t\.b\}\)/.test(js));
check('the picker is keyboard-reachable and states which is active',
  /aria-pressed/.test(js) && /:focus-visible/.test(css));

console.log('\n' + (fails ? `${fails} FAILURE(S)` : 'ALL THEME CHECKS PASSED'));
process.exit(fails ? 1 : 0);
