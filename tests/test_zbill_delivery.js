/* Delivering a shielded claim code over NADO's encrypted messaging, instead of copy-pasting it.
 *
 * The user's complaint was ergonomic ("copypasting claims is a bit clunky"), but the obvious fix is a
 * PRIVACY bug, so most of these checks are about what the feature must NOT do:
 *
 *   - it must not make `zaddr` self-addressing. shieldOwner() is alghash.ownerOf(shieldNsk()) — a one-way
 *     hash, not a KEM public key — so nothing can be sealed to it. The two ways round that (embed the
 *     transparent address, or register shieldOwner -> kem_pub on chain) both publish the link between a
 *     shielded identity and a transparent one, which is the entire thing a zaddr exists to avoid.
 *   - it must not send the code in the clear. The code is NOT bearer — doReceiveShielded rebuilds
 *     commit(value, THEIR shieldOwner, rho), so only the recipient can bank it — but a cleartext broadcast
 *     tagged by owner publicly asserts "this zaddr received X NADO", which the on-chain commitment hides.
 *     Safe from theft is not the same as private.
 *   - the zaddr -> contact mapping that makes repeat sends typing-free must stay in the SENDER'S OWN
 *     storage: not on chain, not in the address, not in the envelope.
 *
 * Run: node tests/test_zbill_delivery.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "static", "interface.js"), "utf8");
const HTML = fs.readFileSync(path.join(__dirname, "..", "static", "interface.html"), "utf8");

let fails = 0;
function check(name, fn) {
  try { fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + e.message); }
}
function has(hay, needle, msg) { if (hay.indexOf(needle) === -1) throw new Error(msg || ("missing: " + needle)); }
function hasnt(hay, needle, msg) { if (hay.indexOf(needle) !== -1) throw new Error(msg || ("must not contain: " + needle)); }

const deliver = SRC.slice(SRC.indexOf("async function deliverZbill"), SRC.indexOf("async function doDeliverZbill"));
if (!deliver) { console.error("FAIL  deliverZbill not found"); process.exit(1); }

// ---- the mapping stays local -------------------------------------------------------------------------

check("the zaddr -> contact mapping is sender-local storage only", () => {
  has(SRC, "LS_ZADDR_CONTACTS", "the mapping needs a storage key");
  const decl = SRC.slice(SRC.indexOf("const LS_ZADDR_CONTACTS"), SRC.indexOf("function zaddrContacts"));
  has(decl, "localStorage" in global ? "nado_zaddr_contacts" : "nado_zaddr_contacts", "keyed in localStorage");
  const fn = SRC.slice(SRC.indexOf("function zaddrContactSet"), SRC.indexOf("// Seal a claim code"));
  has(fn, "localStorage.setItem", "the mapping must be written to local storage");
  hasnt(fn, "fetch(", "the mapping must never be published anywhere");
});

check("the shielded address format is unchanged", () => {
  // If this ever becomes anything but owner-in-base36, the privacy argument above has been broken.
  has(SRC, 'function shieldAddr() { return "zaddr" + shieldOwner().toString(36); }',
      "zaddr must stay owner-only — no embedded address, alias or kem_pub");
});

check("no on-chain registration binds a shielded owner to a messaging key", () => {
  // A shieldOwner -> kem_pub registry would be a permanent, public link in consensus state.
  if (/msgkey[\s\S]{0,120}shieldOwner|shieldOwner[\s\S]{0,120}buildMsgkeyTx/.test(SRC))
    throw new Error("shieldOwner must never be registered against a messaging key");
});

// ---- delivery is sealed, and addressed by ACCOUNT ------------------------------------------------------

check("the code is sealed in an envelope, never posted in the clear", () => {
  has(deliver, "msgSeal", "delivery must seal the payload (through the ratchet)");
  has(deliver, "msgFetchKemPub", "delivery must resolve the recipient's ML-KEM public key");
  // the only network write is the sealed envelope
  const posts = deliver.split("fetch(").length - 1;
  if (posts !== 1) throw new Error("expected exactly one network write (the sealed envelope), found " + posts);
  has(deliver, "JSON.stringify(env)", "the POST body must be the envelope");
});

check("delivery refuses when the recipient has no messaging key", () => {
  has(deliver, "if (!kemPub) return", "no key on chain must abort, not fall back to something weaker");
});

check("an alias is resolved to an account before sealing", () => {
  has(deliver, "resolveAlias", "@alias must resolve");
  has(deliver, "if (!owner) return", "an unresolvable alias must abort");
});

check("the payload carries a type AND a human-readable body", () => {
  // A wallet that predates this feature falls through to the plain-message branch of msgPoll; without a
  // body it would render an empty chat bubble and the banknote would look lost.
  has(deliver, 'type: "zbill"', "payload must be typed so the receiver can act on it");
  has(deliver, "body:", "payload must degrade to something openable on older wallets");
  has(deliver, "claimLink(code)", "the fallback body should be the claim link");
});

// ---- the receiving side --------------------------------------------------------------------------------

const poll = SRC.slice(SRC.indexOf("async function msgPoll"), SRC.indexOf("// ---- unread badge"));

check("msgPoll handles zbill BEFORE the generic message branch", () => {
  const iAck = poll.indexOf('pt.type === "ack"');
  const iZ = poll.indexOf('pt.type === "zbill"');
  const iElse = poll.indexOf("} else {");
  if (iZ === -1) throw new Error("msgPoll must recognise a zbill");
  if (!(iAck < iZ && iZ < iElse)) throw new Error("the zbill branch must precede the catch-all message branch");
});

check("a delivered zbill is validated before being banked", () => {
  has(poll, 'pt.code.startsWith("zbill")', "a malformed code must not be fed to the claim path");
  has(poll, 'typeof pt.code === "string"', "the code must be a string before .startsWith");
});

check("banking only runs on an unlocked wallet and is de-duplicated", () => {
  has(poll, "state.wallet && !state.locked", "must not try to bank while locked");
  has(poll, "conv.messages.some(x => x.id === t.id)", "a re-polled envelope must not re-bank");
});

check("the delivery still appears in the conversation", () => {
  // Silent money movement is worse UX than copy-paste, not better.
  has(poll, "dir: \"in\"", "a zbill must land in the thread like any other message");
  has(poll, "msgSendAck", "the sender should still get a delivery receipt");
});

// ---- the UI ---------------------------------------------------------------------------------------------

check("the send screen exposes the delivery field and button", () => {
  has(HTML, 'id="zsendDeliverTo"', "there must be a recipient field");
  has(HTML, 'id="btnZdeliver"', "there must be a send button");
  has(HTML, 'id="zsendDeliverHint"', "delivery must report success or failure");
  has(SRC, '$("btnZdeliver")', "the button must be wired");
});

check("a first-time zaddr is never auto-delivered to a guess", () => {
  // Bound the slice by LENGTH, not by another marker: the obvious end markers ($("shieldStatus")… ) also
  // occur EARLIER in the same function, which silently yields an empty slice and a test that cannot fail.
  const i = SRC.indexOf("state._lastZaddrSent =");
  if (i === -1) throw new Error("the send path must record which zaddr was used");
  const send = SRC.slice(i, i + 600);
  has(send, "if (_known) doDeliverZbill()", "auto-delivery must be gated on a REMEMBERED contact");
  has(send, "zaddrContactGet(", "the contact must come from the remembered mapping");
});

check("the manual paths survive", () => {
  // The DM is an addition. Copy, share-sheet, QR and the manual claim code must all still be there.
  has(HTML, 'id="zsendCode"', "the manual claim code must remain");
  has(HTML, 'id="btnZcodeShare"', "the share sheet must remain");
  has(HTML, 'id="zsendCodeQR"', "the QR must remain");
  has(SRC, "async function doReceiveShielded", "manual receive must remain");
});

console.log();
if (fails) { console.log(fails + " FAILURES"); process.exit(1); }
console.log("ALL PASS");
