/* The wallet's funded-invite flow keeps the chain's rules (static/interface.js "FUNDED INVITE LINKS + REFERRALS";
 * consensus half: ops/transaction_ops.validate_invite / validate_register_referrer, protocol.py "REFERRALS").
 *
 * Each rule below has a failure a user pays for:
 *   - a register names the referrer ONLY while an invite is pending and confirmed by the chain, and NEVER this wallet
 *     itself — consensus refuses a self-referral outright, so naming self would cost the newcomer their registration;
 *     every register the wallet builds goes through buildRegisterTx, so the rule is pinned there;
 *   - opening #invite=<seed> stores the invite (so it survives wallet creation, a registration and reloads) and takes
 *     the seed out of the address bar;
 *   - the claim is sent only once this identity is registered AND present (anything else is refused by consensus),
 *     and only one at a time: never again while the last one's landing block is still ahead;
 *   - a claim that landed (claimed by me) clears the invite; a permanent refusal clears it, but only once a re-read of
 *     the chain agrees it is not ours (a second tab hears "no OPEN invite" after the first tab's claim landed);
 *     a transient refusal keeps it and retries;
 *   - an invite claimed by someone else, refunded, expired or our own is dropped and never claimed; one not yet on
 *     chain is kept for a grace period (a link opened a minute after it was made is read before its lock lands);
 *   - the invite-creation UI is hidden while the tip is below active_from (protocol.REFERRAL_HEIGHT): the wallet never
 *     offers what the chain refuses.
 *
 * The code is LIFTED from interface.js and run against stubs, not restated — a copy here would keep passing after the
 * real one was edited. The cryptography is real (the vendored bundle), and its agreement with the node is pinned by
 * tests/test_invite_link_js_matches_python.py.
 * Run: node tests/test_wallet_invite_flow.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { webcrypto } from "node:crypto";
import * as nc from "../static/vendor/nado-crypto.js";
// the protocol constants the wallet imports from the relay's /protocol.js, rendered from protocol.py (tests/protocol_hook.mjs)
import { P } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const check = (name, cond, detail = "") => { console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : ": " + detail)); if (!cond) fails++; };

const js = readFileSync(join(ROOT, "static", "interface.js"), "utf8");
const cut = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b, i + 1); return i >= 0 && j > i ? js.slice(i, j) : null; };
const parts = [
  cut("function jsonEscapeAscii(", "function blake2bHashLink("),
  cut("function buildRegisterTx(", "// ON-CHAIN messaging key"),
  cut("function mldsaSignHex(", "function authPop("),
  cut("/* ==== FUNDED INVITE LINKS + REFERRALS", "/* ==== end FUNDED INVITE LINKS + REFERRALS ==== */"),
];
check("the register builder and the invite block are found in interface.js", parts.every(Boolean));
const body = parts.join("\n");

const CHAIN = "betanet-9";
const ME = "ndo" + "a".repeat(46), REF = "ndo" + "b".repeat(46), OTHER = "ndo" + "c".repeat(46);
const SEED = "1f".repeat(32);

function fakeEl(id) {
  const cls = new Set(["hidden"]);
  return { id, textContent: "", innerHTML: "", value: "", open: false, dataset: {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, on) => { if (on === undefined ? !cls.has(c) : on) cls.add(c); else cls.delete(c); }, contains: (c) => cls.has(c) },
    querySelectorAll: () => [], hidden: () => cls.has("hidden") };
}

function harness(opts = {}) {
  const events = [];
  const ls = new Map(opts.ls || []);
  const els = new Map();
  const relay = { invite: opts.invite === undefined ? null : opts.invite, tip: opts.tip ?? 1000, submit: opts.submit || (() => ({ result: true })) };
  const env = {
    events, ls, els, relay,
    CHAIN_ID: CHAIN, netAdopted: true, P, EPOCH_LENGTH: P.EPOCH_LENGTH,
    INVITE_MIN_TIMELOCK: P.INVITE_MIN_TIMELOCK, INVITE_MAX_TIMELOCK: P.INVITE_MAX_TIMELOCK,
    blake2b: nc.blake2b, bytesToHex: nc.bytesToHex, hexToBytes: nc.hexToBytes, ml_dsa44: nc.ml_dsa44, TextEncoder,
    crypto: webcrypto,
    state: { wallet: { address: ME, publicKey: "pk", privateKey: "sk" }, locked: false, latest: relay.tip, mining: false,
             lastMs: { registered_present: opts.present ?? true }, activeTab: "wallet" },
    localStorage: {
      getItem: (k) => (ls.has(k) ? ls.get(k) : null),
      setItem: (k, v) => { ls.set(k, String(v)); },
      removeItem: (k) => { ls.delete(k); },
    },
    location: { hash: opts.hash || "", pathname: "/wallet", origin: "https://wallet.example" },
    history: { replaceState: (a, b, url) => events.push(["replace", url]) },
    validateAddress: (a) => typeof a === "string" && /^ndo[0-9a-f]{46}$/.test(a),
    randNonce: () => "nonce",
    finalizeTransaction: (draft, priv, fee) => ({ ...draft, fee, txid: "reg" }),
    relayBase: () => "http://relay",
    fetch: async (url) => {
      events.push(["fetch", url]);
      if (url.startsWith("http://relay/invite?id=")) {
        const id = decodeURIComponent(url.split("=")[1]);
        const inv = typeof relay.invite === "function" ? relay.invite() : relay.invite;
        return { ok: true, json: async () => ({ id, invite: inv, tip: relay.tip }) };
      }
      return { ok: false, json: async () => ({}) };
    },
    getAccount: async () => (opts.acc === undefined ? { registered: 1, public_key: "pk" } : opts.acc),
    pubkeyEstablished: (a) => !!(a && a.public_key),
    nowSeconds: () => 1,
    buildTransferTx: (wallet, recipient, amount, fee, maxBlock, data, ts, inclPk) =>
      ({ txid: "t" + events.length, sender: wallet.address, recipient, amount, fee, max_block: maxBlock, data }),
    submitTransaction: async (tx) => { events.push(["submit", tx]); return { data: relay.submit(tx) }; },
    isTransient: () => false,
    log: (kind, msg) => events.push(["log", kind, msg]),
    toast: (msg, kind) => events.push(["toast", kind, msg]),
    i18: (k, fb, vars) => String(fb).replace(/\{(\w+)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m)),
    $: (id) => { if (!els.has(id)) els.set(id, fakeEl(id)); return els.get(id); },
    show: (id, on = true) => { events.push(["show", id, on]); env.$(id).classList.toggle("hidden", !on); },
    rawToNado: (r) => String(r), bnum: (x) => { try { return BigInt(x || 0); } catch { return 0n; } }, num: (x) => (Number.isFinite(+x) ? +x : 0),
    escapeHtml: (s) => String(s), exEsc: (s) => String(s), exShort: (s) => String(s).slice(0, 8), exLink: (k, v, l) => String(l),
    blocksToEta: (b) => b + " blocks", _abAlias: {}, _abShort: (a) => String(a).slice(0, 8), abResolveAliases: async () => {},
    showTab: () => {}, copyToClipboard: async () => true, sdkShare: () => {}, setMsg: () => {},
  };
  const make = new Function("env", `with (env) { ${body}\n return { buildRegisterTx, registerData, consumeInviteRequest,
    maybeInviteClaim, inviteVerdict, inviteUiState, referralStatus, renderInviteCard, inviteKeyOf, inviteIdOf, inviteLink,
    pendingInviteLoad, pendingInviteSave, LS_PENDING_INVITE, INVITE_NULL_GRACE,
    _setInv: (r, l, a) => { _invRef = r; _invList = l; _invAddr = a; } }; }`);
  return { env, events, ls, ...make(env) };
}
const submits = (ev) => ev.filter((e) => e[0] === "submit").map((e) => e[1]);
const open = (extra = {}) => ({ sender: REF, amount: 50_000_000_000, expiry: 5000, status: "open", claimant: "", ...extra });

// ---- 1. the register names the referrer only with a confirmed pending invite, and never this wallet ---------------
{
  const h = harness();
  const reg = () => h.buildRegisterTx(h.env.state.wallet, 1008, null, 1, null);
  check("no pending invite: register data is \"\"", reg().data === "");
  h.pendingInviteSave({ seed: SEED, at: 1 });
  check("a pending invite the chain has not confirmed yet (no sender) names nobody", reg().data === "");
  h.pendingInviteSave({ seed: SEED, at: 1, sender: REF, status: "open" });
  const d = reg().data;
  check("a confirmed pending invite: register data is exactly {referrer: <the invite's sender>}",
    d && typeof d === "object" && Object.keys(d).join() === "referrer" && d.referrer === REF, JSON.stringify(d));
  h.pendingInviteSave({ seed: SEED, at: 1, sender: ME, status: "open" });
  check("NEVER NAMES ITSELF: a pending invite sent by this wallet gives data \"\"", reg().data === "");
  h.pendingInviteSave({ seed: SEED, at: 1, sender: "not-an-address", status: "open" });
  check("a sender that is not a valid address is never named", reg().data === "");
  h.pendingInviteSave(null);
  check("after the invite is cleared the register names nobody again", reg().data === "");
}

// ---- 2. opening the link stores it and clears the fragment -----------------------------------------------------------
{
  const h = harness({ hash: "#invite=" + SEED.toUpperCase(), invite: open() });
  const took = h.consumeInviteRequest();
  check("#invite=<seed> is consumed", took === true);
  check("the seed is stored (lower-case) in localStorage, where it survives wallet setup and reloads",
    JSON.parse(h.ls.get(h.LS_PENDING_INVITE) || "{}").seed === SEED);
  check("the fragment is removed from the address bar", h.events.some((e) => e[0] === "replace" && e[1] === "/wallet"));
  const h2 = harness({ hash: "#invite=1234" });
  check("a malformed invite fragment is ignored and nothing is stored", h2.consumeInviteRequest() === false && !h2.ls.has(h2.LS_PENDING_INVITE));
  check("the link is origin + path + #invite=<seed>", h.inviteLink(SEED) === "https://wallet.example/wallet#invite=" + SEED);
}

// ---- 3. the claim: only registered + present, one at a time --------------------------------------------------------
{
  const h = harness({ invite: open(), acc: { registered: 0, public_key: "pk" } });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("NOT REGISTERED: no claim is sent", submits(h.events).length === 0);
  check("...but the chain's answer is kept, so the coming registration names the referrer",
    JSON.stringify(h.registerData(ME)) === JSON.stringify({ referrer: REF }));
}
{
  const h = harness({ invite: open(), present: false });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("REGISTERED BUT NOT PRESENT: no claim is sent", submits(h.events).length === 0);
}
{
  const h = harness({ invite: open() });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await Promise.all([h.maybeInviteClaim(), h.maybeInviteClaim()]);
  const s = submits(h.events);
  check("registered + present: the claim is sent, once even when two polls overlap", s.length === 1, String(s.length));
  const tx = s[0];
  const key = h.inviteKeyOf(SEED), id = h.inviteIdOf(key);
  check("the claim is invite_claim, zero amount, zero fee, data exactly {id, key, sig}",
    tx && tx.recipient === "invite_claim" && tx.amount === 0n && tx.fee === 0 && Object.keys(tx.data).sort().join() === "id,key,sig"
    && tx.data.id === id && tx.data.key === key);
  const claimMsg = nc.hexToBytes(new Function("env", `with (env) { ${parts[0]}\n return blake2bHash; }`)({ blake2b: nc.blake2b, bytesToHex: nc.bytesToHex, TextEncoder })(["invite-claim-v1", CHAIN, id, ME]));
  check("the signature is the LINK key's, over (chain, id, THIS claimant)", tx && nc.ml_dsa44.verify(nc.hexToBytes(key), claimMsg, nc.hexToBytes(tx.data.sig)));
  check("the claim is not signed with the wallet's key (the link key is a throwaway, never the wallet's)", tx && tx.data.key !== h.env.state.wallet.publicKey);
  h.events.length = 0;
  h.env.relay.tip = 1005; h.env.state.latest = 1005;
  await h.maybeInviteClaim();
  check("IN FLIGHT: no second claim while the first one's landing block is ahead", submits(h.events).length === 0);
  h.env.relay.tip = 1009; h.env.state.latest = 1009;
  await h.maybeInviteClaim();
  check("its landing block passed and the invite is still open: the claim is sent again", submits(h.events).length === 1);
  h.events.length = 0;
  h.env.relay.invite = open({ status: "claimed", claimant: ME });
  await h.maybeInviteClaim();
  check("LANDED (claimed by me): the pending invite is cleared and nothing is sent",
    h.pendingInviteLoad() === null && submits(h.events).length === 0);
  check("...and the arrival is reported", h.events.some((e) => e[0] === "log" && e[1] === "ok" && /has arrived/.test(e[2])));
}

// ---- 4. refusals: permanent clears (after the chain agrees), transient retries ------------------------------------
{
  const h = harness({ invite: open(), submit: () => ({ result: false, message: "Could not merge remote transaction: no OPEN invite with that id" }) });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("PERMANENT REFUSAL, and a re-read does not show it as ours: the pending invite is cleared",
    h.pendingInviteLoad() === null);
  check("...and the reason is logged", h.events.some((e) => e[0] === "log" && e[1] === "err" && /cannot be claimed/.test(e[2])));
}
{
  let reads = 0;
  const h = harness({ invite: () => (++reads === 1 ? open() : open({ status: "claimed", claimant: ME })),
                      submit: () => ({ result: false, message: "no OPEN invite with that id" }) });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("\"no OPEN invite\" after ANOTHER TAB's claim landed: re-read, reported as arrived, not as an error",
    h.pendingInviteLoad() === null && h.events.some((e) => e[0] === "log" && e[1] === "ok") && !h.events.some((e) => e[0] === "log" && e[1] === "err"));
}
{
  const h = harness({ invite: open(), submit: () => ({ result: false, message: "only a registered device identity can claim an invite — register this wallet first" }) });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("TRANSIENT REFUSAL: the pending invite is kept", h.pendingInviteLoad() !== null);
  h.events.length = 0;
  await h.maybeInviteClaim();
  check("...and the claim is retried on the next pass", submits(h.events).length === 1);
  check("...the refusal is logged once, not once per poll", h.events.filter((e) => e[0] === "log").length === 0);
}

// ---- 5. invites that must be dropped and never claimed -------------------------------------------------------------
for (const [name, inv, tip] of [
  ["claimed by someone else", open({ status: "claimed", claimant: OTHER }), 1000],
  ["taken back by its sender", open({ status: "refunded" }), 1000],
  ["past its expiry", open({ expiry: 1000 }), 1000],
  ["sent by this wallet itself", open({ sender: ME }), 1000],
]) {
  const h = harness({ invite: inv, tip });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check(`an invite ${name} is dropped, never claimed, and the user is told`,
    h.pendingInviteLoad() === null && submits(h.events).length === 0 && h.events.some((e) => e[0] === "toast" && e[1] === "err"));
}
{
  const h = harness({ invite: null, tip: 1000 });
  h.pendingInviteSave({ seed: SEED, at: 1 });
  await h.maybeInviteClaim();
  check("NOT ON CHAIN YET (a link opened before its lock landed): kept, nothing sent",
    h.pendingInviteLoad() !== null && submits(h.events).length === 0);
  h.env.relay.tip = 1000 + h.INVITE_NULL_GRACE; h.env.state.latest = h.env.relay.tip;
  await h.maybeInviteClaim();
  check("...still kept within the grace period", h.pendingInviteLoad() !== null);
  h.env.relay.tip = 1001 + h.INVITE_NULL_GRACE; h.env.state.latest = h.env.relay.tip;
  await h.maybeInviteClaim();
  check("...dropped once it stays absent past the grace period", h.pendingInviteLoad() === null);
}

// ---- 6. the creation UI is hidden before active_from -----------------------------------------------------------------
{
  const h = harness();
  const PLACEHOLDER = JSON.parse('{"active_from": 4611686018427387904, "tip": 300000}');   // 1 << 62 through JSON
  let ui = h.inviteUiState({ ...PLACEHOLDER, referrer: null, referred: [] }, null);
  check("BEFORE active_from (placeholder 2^62): creation is not offered and the card is hidden", !ui.canCreate && !ui.showCard);
  ui = h.inviteUiState({ active_from: 300000, tip: 300000, referrer: null, referred: [] }, {});
  check("FROM active_from: creation is offered, and an empty list stays hidden", ui.canCreate && ui.showCard && !ui.showList);
  ui = h.inviteUiState(null, null);
  check("a relay without /referrals: nothing is offered", !ui.canCreate && !ui.showCard);
  ui = h.inviteUiState({ active_from: 10, tip: 20, referrer: { address: REF }, referred: [] }, null);
  check("someone referred me: the list is shown", ui.showList && ui.showCard);

  h._setInv({ ...PLACEHOLDER, referrer: null, referred: [] }, null, ME);
  h.renderInviteCard();
  check("rendered before active_from: the invite card and the creation form stay hidden",
    h.env.els.get("inviteCard").hidden() && h.env.els.get("inviteCreate").hidden());
  h._setInv({ active_from: 300000, tip: 300001, referrer: null, referred: [], share: [1, 10], window_epochs: 7200 }, {}, ME);
  h.renderInviteCard();
  check("rendered from active_from: the card and the creation form are shown",
    !h.env.els.get("inviteCard").hidden() && !h.env.els.get("inviteCreate").hidden());
  check("the deal line states 10 % for 30 days, 90 % kept (from the chain's share and window)",
    /10 %/.test(h.env.els.get("inviteDeal").textContent) && /30 days/.test(h.env.els.get("inviteDeal").textContent) && /90 %/.test(h.env.els.get("inviteDeal").textContent),
    h.env.els.get("inviteDeal").textContent);
}

// ---- 7. why a referral is (not) earning -------------------------------------------------------------------------------
{
  const h = harness();
  check("in window, friend present, me present: earning", h.referralStatus({ in_window: true, present: true }, true) === "earning");
  check("window over: says so", h.referralStatus({ in_window: false, present: true }, true) === "window");
  check("friend absent: says so", h.referralStatus({ in_window: true, present: false }, true) === "absent");
  check("I am absent: says so", h.referralStatus({ in_window: true, present: true }, false) === "selfAbsent");
  check("verdict: an open, unexpired invite from someone else is claimable", h.inviteVerdict(open(), 1000, ME, {}) === "open");
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
