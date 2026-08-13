/* A dead RANDAO reveal must not take the rest of the epoch duty with it (static/interface.js maybeRandao).
 *
 * OBSERVED LIVE (2026-08-13, betanet-3), once a minute, forever:
 *
 *     20:52:28 Epoch duty rejected: Could not merge remote transaction: No matching commit for this reveal
 *     20:53:28 Epoch duty rejected: Could not merge remote transaction: No matching commit for this reveal
 *
 * A bonded validator's FFG attest (epoch X), RANDAO commit (X+2) and reveal (X+1) ride in ONE `duty` tx.
 * So a reveal the chain can never accept fails the WHOLE tx, and the attest and the next commit — both
 * perfectly valid — are lost with it. The validator silently stops attesting for FFG and stops committing
 * for future epochs. Then it retries: the rejection does not match the "nothing left to post" pattern, so
 * _dutyDone[X] is never set and every poll pass resubmits the identical doomed transaction.
 *
 * THE REJECTION IS PERMANENT, which is exactly what _randaoDead was declared for ("a resubmit can never
 * succeed; never send one twice") — and nothing ever added to it. A commit for epoch E must be posted in
 * epoch E-2, while its reveal lands in E-1's finalized window, so by the time a reveal is refused for a
 * missing commit that window shut a whole epoch earlier and commit_get(sender, E) stays empty for good.
 *
 * WHAT THIS PINS: that each of the node's three deterministic reveal rejections is recognised, that
 * ordinary/transient failures are NOT (retrying those is correct), and — the part that actually rots —
 * that the classifier still matches the assertion text ops/transaction_ops.py raises today. That coupling
 * is to a string in another language; if it silently stops matching, the duty tx retries forever again.
 *
 * Run: node tests/test_duty_dead_reveal.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let fails = 0;
const check = (name, cond) => { console.log((cond ? 'PASS  ' : 'FAIL  ') + name); if (!cond) fails++; };

const js = readFileSync(join(ROOT, 'static', 'interface.js'), 'utf8');

// Lift the classifier out of the wallet source rather than restating it — a copy here would keep passing
// after the real one was edited, which is the failure mode this file exists to prevent.
const m = js.match(/const DEAD_REVEAL_RE = (\/.*?\/i);/);
check('DEAD_REVEAL_RE is defined in interface.js', !!m);
const DEAD_REVEAL_RE = m ? eval(m[1]) : /$^/;

// ---- the three PERMANENT rejections, exactly as the node words them ------------------------------
// verbatim from the live log, mempool prefix and all
check('the observed live rejection is recognised',
  DEAD_REVEAL_RE.test('Could not merge remote transaction: No matching commit for this reveal'));
check('bare "No matching commit for this reveal"',
  DEAD_REVEAL_RE.test('No matching commit for this reveal'));
check('"Reveal does not open the commitment"',
  DEAD_REVEAL_RE.test('Reveal does not open the commitment'));
check('"This secret is already revealed for the epoch"',
  DEAD_REVEAL_RE.test('This secret is already revealed for the epoch'));

// ---- and the ones that must stay RETRYABLE -------------------------------------------------------
// Marking a transient failure dead would forfeit a reveal the chain would have taken.
for (const msg of [
  'Reveal must land in epoch E-1s finalized window',      // wrong landing block: next pass can be right
  'Commit/reveal sender is not a bonded validator',        // fix the stake and it works
  'Target block too low',
  'Could not merge remote transaction: transaction pool is full',
  'Executor shutdown has been called',                     // a node restart — the exact cause here
  'Duty tx carries no sections',
]) check(`retryable, not dead: "${msg.slice(0, 46)}"`, !DEAD_REVEAL_RE.test(msg));

// ---- THE COUPLING: does it still match what the node actually raises? ------------------------------
// The classifier reads assertion text from a Python file. Nothing but this check ties the two together.
const py = readFileSync(join(ROOT, 'ops', 'transaction_ops.py'), 'utf8');
const validator = py.slice(py.indexOf('def _validate_reveal_fields'),
                           py.indexOf('def construct_duty_tx'));
check('_validate_reveal_fields was found in transaction_ops.py', validator.length > 200);

// every assertion message in the validator, as the node would send it
const asserts = [...validator.matchAll(/assert [^,]+(?:,[^"']*)?,\s*["']([^"']+)["']/g)].map(x => x[1]);
check('the validator raises several distinct messages', asserts.length >= 4);

// the three we treat as permanent must each still exist verbatim on the node side
for (const needle of ['No matching commit for this reveal',
                      'Reveal does not open the commitment',
                      'already revealed for the epoch']) {
  check(`node still raises: "${needle}"`, validator.includes(needle));
}

// and nothing the node raises should be classified dead unless it is one of those three
const permanent = asserts.filter(a => DEAD_REVEAL_RE.test(a));
check(`exactly the 3 permanent rejections are classified dead (got ${permanent.length}: ${permanent.join(' | ')})`,
  permanent.length === 3);

// ---- the recovery path is actually wired -----------------------------------------------------------
check('a dead reveal is recorded in _randaoDead', /_randaoDead\.add\(X \+ 1\)/.test(js));
check('...the reveal section is dropped', /delete data\.reveal;/.test(js));
check('...and the duty is RESUBMITTED so attest + commit still land',
  /delete data\.reveal;[\s\S]{0,600}?res = await submitTransaction\(tx\)/.test(js));
check('_randaoDead is pruned as epochs pass (it would otherwise grow forever)',
  /for \(const e of _randaoDead\)[\s\S]{0,80}_randaoDead\.delete\(e\)/.test(js));
check('the reveal is still gated on _randaoDead before being built',
  /!_randaoDead\.has\(X \+ 1\)/.test(js));

console.log();
console.log(fails === 0 ? 'ALL DEAD-REVEAL CHECKS PASSED' : `${fails} FAILURE(S)`);
process.exit(fails ? 1 : 0);
