/* The registration banner must not outlive the condition it describes (static/interface.js).
 *
 * REPORTED: "Relay momentarily unreachable — reconnecting…" stays on screen after the relay is plainly
 * back — the height is ticking, blocks are landing, and the wallet is still warning about a blip that
 * ended minutes ago.
 *
 * CAUSE. #regBanner carries two DIFFERENT kinds of message. Narration ("computing your proof",
 * "submitting", "waiting for confirmation") is a sequence: each stage overwrites the last, so it cannot
 * go stale. Problems ("relay unreachable", "didn't confirm") have NO next stage — the condition simply
 * stops being true, with nothing running to say so. The only place the healthy path touched the banner
 * was:
 *
 *     if (wasStarting) { setRegBanner("Registered ✓ — mining now.", "ok"); hideRegBannerSoon(); }
 *
 * and `wasStarting` is state.starting || btnMine.disabled — both FALSE during steady mining. So the two
 * ways to see a problem banner are exactly the two ways to get stuck with one:
 *
 *   1. a relay blip mid-session (lease renewal or a presence re-register hits a transient error) — the
 *      poll loop recovers on the next tick, reaches the healthy branch with wasStarting false, and
 *      leaves the warning up;
 *   2. failStart()'s own self-heal — it re-checks the chain, finds the registration DID land, sets
 *      state.mining = true and resumes... straight into the same branch, so "Registration didn't
 *      confirm — tap Start to retry." stays on screen while the wallet mines happily behind it.
 *
 * Both cleared only on stop-mining or a page reload, which is precisely "it goes stale".
 *
 * THE FIX, and what this pins: problem banners are TAGGED, and the healthy branch retracts them by tag
 * every poll. The tag is the load-bearing part — an untagged "hide the banner" here would erase live
 * narration whenever a poll landed mid-registration, turning a stale-banner bug into a blank-banner one.
 */
import { readFileSync } from 'node:fs';
const js = readFileSync('/srv/nado-home/nado/static/interface.js', 'utf8');
let fails = 0;
const check = (n, c) => { console.log((c ? 'PASS  ' : 'FAIL  ') + n); if (!c) fails++; };

// ---- BEHAVIOURAL: run the real setRegBanner/clearRegBanner against a DOM shim ------------------------
const src = js.match(/let _regBannerTag = null;[\s\S]*?\nfunction clearRegBanner\(tag\) \{[\s\S]*?\n\}/);
check('the banner helpers are present to exercise', !!src);

const dom = { visible: false, html: '', cls: '' };
const harness = new Function(`
  const el = {};
  const $ = (id) => (id === "regBanner" ? el : { set innerHTML(v) { arguments; } });
  return (function (dom) {
    const $ = (id) => id === "regBanner" ? el : { set innerHTML(v) { dom.html = v; } };
    const show = (id, v) => { if (id === "regBanner") dom.visible = v; };
    ${src[0]}
    return { setRegBanner, clearRegBanner, tag: () => _regBannerTag };
  });
`)()(dom);

const { setRegBanner, clearRegBanner, tag } = harness;

setRegBanner('Relay momentarily unreachable — reconnecting…', 'warn', 'unreachable');
check('a problem banner shows and remembers its tag', dom.visible && tag() === 'unreachable');
clearRegBanner('failed');
check('a DIFFERENT tag does not retract it (the other problem is not this one)', dom.visible === true);
clearRegBanner('unreachable');
check('its own tag retracts it', dom.visible === false && tag() === null);
clearRegBanner('unreachable');
check('retracting again is a harmless no-op (it runs on EVERY poll)', dom.visible === false);

// the case an untagged blanket hide would break
setRegBanner('Relay momentarily unreachable — reconnecting…', 'warn', 'unreachable');
setRegBanner('Waiting for on-chain confirmation — this can take a few blocks…');   // narration, no tag
check('live narration replaces a problem banner and drops its tag', dom.visible && tag() === null);
clearRegBanner('unreachable');
check('...and retracting the OLD problem cannot erase that live narration', dom.visible === true);
clearRegBanner(null);
check('a null tag does not blanket-hide narration either', dom.visible === true);

// ---- STATIC: the call sites, which the harness above cannot see --------------------------------------
check('the unreachable banner is tagged',
  /reg\.reconnecting[\s\S]{0,120}"warn",\s*"unreachable"\)/.test(js));
check('the failed-registration banner is tagged',
  /reg\.retry[\s\S]{0,220}"warn",\s*"failed"\)/.test(js));
check('the healthy poll branch retracts BOTH problem banners',
  /clearRegBanner\("unreachable"\);\s*\n\s*clearRegBanner\("failed"\);/.test(js));

// The regression itself: retraction must sit OUTSIDE `if (wasStarting)`. Inside it, both reported
// symptoms come straight back — steady-state mining and the failStart self-heal both arrive here false.
const healthy = js.match(/markMiningActive\(\);[\s\S]*?if \(wasStarting\) \{/);
check('retraction happens BEFORE the wasStarting gate, not inside it',
  !!healthy && /clearRegBanner\("unreachable"\)/.test(healthy[0]));
check('...and the narration banners stay untagged, so nothing can retract them',
  !/reg\.(waiting|computingEta|submitting|pending)[\s\S]{0,300}?,\s*"(unreachable|failed)"\)/.test(js));

console.log('\n' + (fails ? `${fails} FAILURE(S)` : 'ALL REG-BANNER CHECKS PASSED'));
process.exit(fails ? 1 : 0);
