// nft.js — NADO NFT: mint, collect and trade NFTs on the execution layer (execnode/games/nft.py), on the shared SDK.
//
// AN NFT HERE IS A NATIVE ASSET (dec 0, supply = editions, not mintable, uri = its media), so it is in every wallet's
// Assets tab and survives a reroll with the asset ledger. Minting is TWO signatures: `asset_create` (the wallet's
// own blob — the asset now exists) and `register` (the contract checks hash(you, seed) == the asset, so only its
// issuer can attach the royalty and the collection). The page finds the new asset by its seed through
// /exec/assets?issuer= — no address digest is computed in the browser.
//
// Every trade escrows on the contract and settles in ONE call: royalty to the creator, the rest to the seller. The
// page never holds anything; every signature is the NADO wallet's, and an asset-valued call always asks for a confirm.
//
// UNTRUSTED TEXT: names, descriptions, bios, avatar and media links come from the chain, i.e. from anyone. Every one
// goes through esc() before it reaches innerHTML, and a media link is used only if it is ipfs:// or https://.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, gate, canPay, notify, confirmingLabel, wireWallet, financeLabels,
         renderWallet, alertBar, loadQR, disp, esc, base, BLOCK_TIME, enhanceFile } from "./nadodapp.js";
import { blake2s, personOf, bytesWord, hashWords } from "./blake2s.js";

const CID = "b0162edacd9f4c6c6a27391c692d90c5";      // set by execnode/games/redeploy.py wire() at deploy
const dapp = new NadoDapp({ cid: CID, app: "NFT" });
const T = (k, en, v) => window.t("nft." + k, en, v);

const OPEN = 1, DONE = 2, CANCELLED = 3, EXPIRED = 4;
const MAX_UPLOAD = 5 * 1024 * 1024;   // scripts/operator/nft_upload.py MAX_BYTES (it enforces it; this only saves a round trip)
const MAX_ROYALTY_PCT = 25, MIN_DUR = 60, MAX_DUR = 201600, EXTEND = 50, MIN_RAISE_PCT = 5;
const SALE_KIND = { 1: "listing", 2: "offer", 3: "auction", 4: "dutch" };

let sto = null, assets = {}, mine = {}, cursor = 0;

// ---- small helpers ----------------------------------------------------------------------------------------------
const big = (v) => { try { return BigInt(v || 0); } catch (e) { return 0n; } };
const ids = (map) => Object.keys(_m(sto, map)).map(Number).sort((a, b) => b - a);
const field = (map, id) => _m(sto, map)[String(id)];
const pct = (bps) => (Number(bps || 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 }) + " %";
const blocksLeft = (h) => Math.max(0, Number(h || 0) - cursor);
const fmtBlocks = (b) => {
  const s = b * BLOCK_TIME;
  if (s >= 86400) return T("days", "{n} d", { n: Math.floor(s / 86400) });
  if (s >= 3600) return T("hours", "{n} h", { n: Math.floor(s / 3600) });
  return T("mins", "{n} min", { n: Math.max(1, Math.round(s / 60)) });
};

// a media link is usable only as ipfs:// (through a public gateway) or https://; anything else (javascript:, data:,
// http:) is dropped, never rendered
// ipfs:// is served by THIS site's own IPFS node (nginx /ipfs/ -> nado-ipfs.service gateway, sandboxed): the uploads
// are pinned there, so they load fast and never depend on a public gateway's mood
function mediaUrl(uri) {
  uri = String(uri || "").trim();
  if (uri.startsWith("ipfs://")) {
    const cid = uri.slice(7).replace(/^ipfs\//, "");
    return /^[A-Za-z0-9]+(\/[^\s"'<>]*)?$/.test(cid) ? base() + "/ipfs/" + encodeURI(cid) : "";
  }
  if (/^https:\/\/[^\s"'<>]+$/.test(uri)) return uri;
  return "";
}
function mediaTag(uri, cls) {
  const u = mediaUrl(uri);
  if (!u) return `<div class="${cls} nomedia">${T("noMedia", "no media")}</div>`;
  // an image first; if it is not one (a video, an audio file), the error handler swaps in a <video>
  return `<img class="${cls}" loading="lazy" src="${esc(u)}" alt="" data-media="${esc(u)}">`;
}
// LAND TITLES (#125, "the land plot should have a screenshot attached like in a realtor ad, also plot size etc"): a plot
// of the Land planet is sold here as a title whose uri is its place in the game (https://land.nadochain.com/?plot=N).
// Its picture is the world server's aerial photo and its facts are the planet's own (/land/api/card) — shown ONLY once
// the world server names THIS asset as that plot's title. Anyone can mint an asset whose uri points at a plot; a copy
// must never borrow the real plot's photo and facts, so a mismatch says plainly that it is not that plot's title.
const LAND = "https://land.nadochain.com";
const landPlotOf = (a) => {
  const m = a && a.sym === "PLOT" && /^https:\/\/land\.nadochain\.com\/\?plot=(\d{1,10})$/.exec(String(a.uri || ""));
  return m ? Number(m[1]) : null;
};
const landCards = {};          // aid -> the verified card | false (the world knows another title for that plot) | null (asking)
let landRedraw = 0;
function landCard(aid) {
  const p = landPlotOf(assets[aid]);
  if (p === null) return null;
  if (landCards[aid] === undefined) {
    landCards[aid] = null;
    fetch(`${LAND}/land/api/card?plot=${p}`, { cache: "no-cache" }).then((r) => r.json()).then((c) => {
      landCards[aid] = c && c.plot === p && String(c.aid) === String(aid) ? c : false;
      clearTimeout(landRedraw);                                  // a grid of titles answers at once: one redraw for them
      landRedraw = setTimeout(() => { lastRoute = ""; render(); }, 250);
    }).catch(() => { setTimeout(() => { delete landCards[aid]; }, 30000); });
  }
  return landCards[aid];
}
function media(aid, uri, cls) {
  if (landPlotOf(assets[aid]) === null) return mediaTag(uri, cls);
  const c = landCard(aid);
  return c && c.shot ? `<img class="${cls}" loading="lazy" src="${esc(LAND + c.shot)}" alt="">`
    : `<div class="${cls} nomedia">${c ? T("landNoShot", "Its photo is being taken") : T("landPlot", "Land plot")}</div>`;
}
const BIOME = { grass: () => T("bGrass", "Meadow"), forest: () => T("bForest", "Forest"), desert: () => T("bDesert", "Desert"),
                rock: () => T("bRock", "Rocky highland"), snow: () => T("bSnow", "Snowfield"), beach: () => T("bBeach", "Beach") };
const kv = (k, v) => `<div class="kv"><span class="k">${k}</span><span>${v}</span></div>`;
function landFacts(aid) {
  const p = landPlotOf(assets[aid]);
  if (p === null) return "";
  const c = landCard(aid);
  if (c === false) return `<p class="small warnline">${T("landFake", "⚠ Not a Land title: the Land world knows another asset as plot {p}.", { p })}</p>`;
  if (!c) return `<p class="small dim">${T("landAsking", "Asking the Land world about this plot…")}</p>`;
  return kv(T("landSize", "Size"), T("landSizeV", "{s} × {s} m · {a} m²", { s: c.size_m, a: c.area_m2 }))
    + kv(T("landWhere", "Where"), T("landWhereV", "planet {pl} · face {f} · row {r} · column {c}", { pl: c.planet, f: c.face, r: c.row, c: c.col }))
    + kv(T("landBiome", "Landscape"), esc((BIOME[c.biome] || (() => c.biome))()))
    + kv(T("landElev", "Elevation"), T("landElevV", "{m} m above the sea ({lo} to {hi} m)", { m: c.mean, lo: c.low, hi: c.high }))
    + (c.under_sea ? kv(T("landWater", "Under water"), T("landWaterV", "{n} of 256 m²", { n: c.under_sea })) : "")
    + kv(T("landGrows", "Growing"), T("landTrees", "{n} {n|one:tree|other:trees}", { n: c.trees })
      + (c.flax ? " · " + T("landFlax", "{n} {n|one:flax plant|other:flax plants}", { n: c.flax }) : ""))
    + (c.town_hall_m != null ? kv(T("landTown", "Town hall"), c.town_hall_m ? T("landTownV", "{m} m away", { m: c.town_hall_m }) : T("landTownHere", "on this plot")) : "")
    + (c.built || c.pieces ? kv(T("landBuilt", "Built"), T("landBuiltV", "{b} {b|one:block changed|other:blocks changed} · {p} {p|one:piece|other:pieces}", { b: c.built, p: c.pieces })) : "")
    + `<a class="small" href="${esc(LAND)}/?plot=${p}" target="_blank" rel="noopener noreferrer">${T("landVisit", "Walk it in Land")}</a>`;
}
document.addEventListener("error", (ev) => {
  const el = ev.target;
  if (!el.dataset || !el.dataset.media) return;
  if (el instanceof HTMLImageElement) {
    const v = document.createElement("video");
    v.className = el.className; v.src = el.dataset.media; v.dataset.media = el.dataset.media;
    v.controls = true; v.loop = true; v.muted = true; v.playsInline = true;
    el.replaceWith(v);
  } else if (el instanceof HTMLVideoElement) {
    // neither an image nor a playable video (or the gateway is down): a placeholder, never a broken player
    const d = document.createElement("div");
    d.className = el.className + " nomedia"; d.textContent = T("noMedia", "no media");
    el.replaceWith(d);
  }
}, true);

// ---- reads ------------------------------------------------------------------------------------------------------
function tokenByAsset(aid) {
  aid = String(aid);
  for (const t of ids("t_mk")) if (String(field("t_asset", t)) === aid) return t;
  return 0;
}
function tokenInfo(aid) {
  aid = String(aid);
  const t = tokenByAsset(aid), a = assets[aid] || {};
  return {
    aid, t, name: a.name || T("untitled", "Untitled"), uri: a.uri || "", supply: big(a.supply), holders: a.holders || 0,
    mintable: !!a.mintable, dec: a.dec || 0,
    creator: t ? field("t_creator", t) : (a.issuer || ""), bps: t ? Number(field("t_bps", t) || 0) : 0,
    coll: t ? Number(field("t_coll", t) || 0) : 0, registered: !!t,
  };
}
const listingsOf = (aid) => ids("l_mk").filter((l) => String(field("l_asset", l)) === String(aid) && field("l_st", l) === OPEN);
const auctionsOf = (aid) => ids("a_mk").filter((a) => String(field("a_asset", a)) === String(aid) && field("a_st", a) === OPEN);
const dutchOf = (aid) => ids("d_mk").filter((d) => String(field("d_asset", d)) === String(aid) && field("d_st", d) === OPEN);
function offersFor(aid) {
  const coll = tokenInfo(aid).coll;
  return ids("o_mk").filter((o) => field("o_st", o) === OPEN && !expiredOffer(o)
    && (String(field("o_asset", o)) === String(aid) || (coll && Number(field("o_coll", o)) === coll && !big(field("o_asset", o)))));
}
const expiredOffer = (o) => { const e = Number(field("o_exp", o) || 0); return e > 0 && cursor >= e; };
function dutchPrice(d) {
  const sp = big(field("d_sp", d)), ep = big(field("d_ep", d)), dur = big(field("d_dur", d)), h0 = big(field("d_h0", d));
  let el = BigInt(cursor) - h0; if (el < 0n) el = 0n; if (el > dur) el = dur;
  return sp - (sp - ep) * el / dur;
}
function floorOf(aid) {
  const ps = listingsOf(aid).map((l) => big(field("l_price", l)));
  return ps.length ? ps.reduce((a, b) => (b < a ? b : a)) : null;
}
const held = (aid) => big((mine[String(aid)] || {}).balance);
function profileOf(addr) {
  for (const p of ids("p_mk")) if (field("p_addr", p) === addr) return {
    id: p, name: field("p_name", p) || "", bio: field("p_bio", p) || "", av: field("p_av", p) || "" };
  return null;
}
const who = (addr) => { const p = profileOf(addr); return p && p.name ? esc(p.name) : esc(disp(addr)); };
const userLink = (addr) => addr ? `<a href="#user/${encodeURIComponent(addr)}">${who(addr)}</a>` : "—";
const myCollections = () => ids("c_mk").filter((c) => field("c_owner", c) === dapp.me);

// ---- actions ----------------------------------------------------------------------------------------------------
const busy = (phase, id) => dapp.busy(phase, "id", id) && (notify(confirmingLabel()), true);
const units = (s) => { const n = parseInt(String(s || "").trim(), 10); return Number.isFinite(n) && n > 0 ? n : 0; };
function priceRaw(id) { try { return nadoToRaw($(id).value || "0"); } catch (e) { return 0n; } }

function mint() {
  if (!dapp.me) return notify(T("signInFirst", "Sign in with your NADO wallet first."));
  const name = $("mName").value.trim(), uri = $("mUri").value.trim(), ed = units($("mEditions").value);
  const roy = Number($("mRoyalty").value || 0), coll = Number($("mColl").value || 0);
  if (!name) return notify(T("needName", "Give it a title."));
  if (name.length > 64) return notify(T("nameLong", "A title is at most 64 characters."));
  if (!mediaUrl(uri) || uri.length > 128) return notify(T("needUri", "Paste an ipfs:// or https:// link to the media (at most 128 characters)."));
  if (!ed) return notify(T("needEditions", "Editions must be a whole number of at least 1."));
  if (!(roy >= 0 && roy <= MAX_ROYALTY_PCT)) return notify(T("needRoyalty", "Royalty is between 0 and 25 %."));
  // ONE APPROVAL (objkt / fxhash: everything is configured before the mint). The royalty registration rides the mint's
  // own confirm as its `then` step (nadodapp signBlob opts.then), so there is no second popup minutes later — the
  // creator who missed that popup got an NFT with no royalty and no listing (2026-11-04). `register` needs only the
  // asset's id, which is hash(issuer, seed) and known before the asset exists (assetId), so the two may land in
  // either order. If the step fails, the NFT's page offers Register to its creator (registerLater).
  const seed = randId(), bps = Math.round(roy * 100);
  dapp.signBlob({ op: "asset_create", seed, name, sym: "NFT", dec: 0, supply: ed, mintable: false, uri },
    T("callMint1", "create NFT “{n}” · {e} editions · {r} royalty", { n: name, e: ed, r: pct(bps) }), { phase: "mint", id: seed },
    { confirm: true, then: { op: "call", contract: CID, method: "register", args: [randId(), assetId(dapp.me, seed), seed, bps, coll] } });
}

// execnode/state.asset_id: the VM hash over (the issuer's address digest, seed); the digest is
// execnode/runtimes.zkvm_addr_digest — BLAKE2s, person "NADOvmA1", over canonical_bytes(["zkvmaddr", addr]). Pinned
// against the Python by tests/test_an_nft_mints_with_its_royalty_in_one_approval.py.
const ADDR_PERSON = personOf("NADOvmA1");
function assetId(addr, seed) {
  const digest = bytesWord(blake2s(new TextEncoder().encode(JSON.stringify(["zkvmaddr", String(addr)])), ADDR_PERSON));
  return hashWords([digest, BigInt(seed)]);
}

// register from the NFT's own page, any time after the mint (the creator's way back when step 2 never ran: nftAssets)
function registerLater(aid) {
  const a = assets[String(aid)];
  if (!a || a.issuer !== dapp.me) return;
  const roy = Number($("rRoyalty").value || 0), coll = Number($("rColl").value || 0);
  if (!(roy >= 0 && roy <= MAX_ROYALTY_PCT)) return notify(T("needRoyalty", "Royalty is between 0 and 25 %."));
  const bps = Math.round(roy * 100);
  dapp.call("register", [randId(), big(a.id), Number(a.seed), bps, coll], null,
    T("callRegister", "register “{n}” · {r} royalty", { n: a.name, r: pct(bps) }), { phase: "register", id: Number(a.seed) });
}

// objkt-style upload: the file goes to this site's IPFS node (pinned there — the local copy that keeps it alive) and its
// ipfs:// link fills the media field. The service re-checks everything; these checks only save a pointless upload.
// The drop zone is the SDK's enhanceFile — never the operating-system file button (operator 2026-11-01).
// The preview is the user's OWN file (a blob: URL) the moment it is chosen; the IPFS copy replaces nothing visible.
function localPreview(file) {
  const u = URL.createObjectURL(file), t = file.type || "";
  if (t.startsWith("video/")) return `<video src="${u}" controls loop muted playsinline></video>`;
  if (t.startsWith("audio/")) return `<audio src="${u}" controls></audio>`;
  if (t.startsWith("image/")) return `<img src="${u}" alt="">`;
  return `<div class="nomedia thumb prev">${esc(file.name)}</div>`;   // a GLB: no in-page viewer
}
function postFile(file, onPct) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest(), fd = new FormData();
    fd.append("file", file, "media");
    x.open("POST", base() + "/upload");
    x.upload.onprogress = (e) => { if (e.lengthComputable) onPct(100 * e.loaded / e.total); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {}
      x.status >= 200 && x.status < 300 && j.cid ? resolve(j) : reject(new Error(j.error || ("HTTP " + x.status))); };
    x.onerror = () => reject(new Error(T("netErr", "network error")));
    x.send(fd);
  });
}
const sizeTxt = (n) => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
async function upload(file, zone) {
  if (!file) return;
  if (file.size > MAX_UPLOAD) return notify(T("tooBig", "The file is larger than 5 MB."));
  const up = (pct) => zone.busy(pct, T("uploading", "Uploading {n}…", { n: file.name }) + (pct == null ? "" : " " + Math.round(pct) + " %"));
  up(0);
  $("btnMint").disabled = true;
  try {
    const j = await postFile(file, up);
    $("mUri").value = "ipfs://" + j.cid;
    if (!$("mName").value.trim()) $("mName").value = file.name.replace(/\.[^.]+$/, "").slice(0, 64);
    zone.done(localPreview(file), `${file.name} · ${sizeTxt(file.size)} · ${T("uploaded", "Stored on IPFS · {c}", { c: j.cid })}`);
  } catch (e) {
    zone.reset();
    notify(T("uploadFail", "Upload failed: {e}", { e: String(e.message || e) }));
  } finally { $("btnMint").disabled = false; }
}

function createCollection() {
  const n = $("cName").value.trim(), d = $("cDesc").value.trim();
  if (!n) return notify(T("needCollName", "Name the collection."));
  dapp.call("create_collection", [randId(), n, d || "-"], null, T("callColl", "create collection “{n}”", { n }), { phase: "coll" });
}

function saveProfile() {
  const p = profileOf(dapp.me);
  const name = $("pName").value.trim(), bio = $("pBio").value.trim(), av = $("pAv").value.trim();
  if (av && !mediaUrl(av)) return notify(T("needAvatar", "An avatar must be an ipfs:// or https:// link."));
  dapp.call("set_profile", [p ? p.id : randId(), name || "-", bio || "-", av || "-"], null,
    T("callProfile", "save your profile"), { phase: "profile" });
}

function list(aid) {
  const n = units($("sUnits").value), price = priceRaw("sPrice");
  if (!n || BigInt(n) > held(aid)) return notify(T("needUnits", "You hold {h} — choose how many to sell.", { h: held(aid) }));
  if (price <= 0n) return notify(T("needPrice", "Set a price."));
  dapp.call("list", [randId(), big(aid), price], BigInt(n), T("callList", "list {n} × “{t}” at {p} NADO", {
    n, t: tokenInfo(aid).name, p: rawToNado(price) }), { phase: "list" }, { asset: String(aid) });
}

function auction(aid) {
  const n = units($("sUnits").value), reserve = priceRaw("sPrice"), hrs = Number($("sHours").value || 0);
  const dur = Math.round(hrs * 3600 / BLOCK_TIME);
  if (!n || BigInt(n) > held(aid)) return notify(T("needUnits", "You hold {h} — choose how many to sell.", { h: held(aid) }));
  if (reserve <= 0n) return notify(T("needReserve", "Set a reserve price."));
  if (dur < MIN_DUR || dur > MAX_DUR) return notify(T("needDur", "An auction runs from 6 minutes to 2 weeks."));
  dapp.call("auction", [randId(), big(aid), reserve, dur], BigInt(n), T("callAuction", "auction {n} × “{t}” · reserve {p} NADO", {
    n, t: tokenInfo(aid).name, p: rawToNado(reserve) }), { phase: "auction" }, { asset: String(aid) });
}

function dutch(aid) {
  const n = units($("sUnits").value), sp = priceRaw("sPrice"), ep = priceRaw("sEnd"), hrs = Number($("sHours").value || 0);
  const dur = Math.round(hrs * 3600 / BLOCK_TIME);
  if (!n || BigInt(n) > held(aid)) return notify(T("needUnits", "You hold {h} — choose how many to sell.", { h: held(aid) }));
  if (!(ep > 0n && ep < sp)) return notify(T("needDutch", "A Dutch auction starts above its end price, and the end price is above 0."));
  if (dur < MIN_DUR || dur > MAX_DUR) return notify(T("needDur", "An auction runs from 6 minutes to 2 weeks."));
  dapp.call("dutch", [randId(), big(aid), sp, ep, dur], BigInt(n), T("callDutch", "Dutch auction {n} × “{t}” · {a} → {b} NADO", {
    n, t: tokenInfo(aid).name, a: rawToNado(sp), b: rawToNado(ep) }), { phase: "dutch" }, { asset: String(aid) });
}

function buy(l) {
  if (busy("buy", l)) return;
  const price = big(field("l_price", l)), n = units(($("buyN" + l) || {}).value || "1") || 1;
  const cost = price * BigInt(n);
  if (!canPay(dapp, cost, T("whatBuy", "Buying"))) return;
  dapp.call("buy", [l, n], cost, T("callBuy", "buy {n} × “{t}” for {p} NADO", {
    n, t: tokenInfo(field("l_asset", l)).name, p: rawToNado(cost) }), { phase: "buy", id: l });
}

function bid(a) {
  if (busy("bid", a)) return;
  const cur = big(field("a_bid", a)), reserve = big(field("a_reserve", a));
  const min = cur ? cur + (cur * BigInt(MIN_RAISE_PCT) + 99n) / 100n : reserve;
  const v = priceRaw("bidAmt" + a);
  if (v < min) return notify(T("bidLow", "The minimum bid is {m} NADO.", { m: rawToNado(min) }));
  if (!canPay(dapp, v, T("whatBid", "Bidding"))) return;
  dapp.call("bid", [a], v, T("callBid", "bid {p} NADO on “{t}”", { p: rawToNado(v), t: tokenInfo(field("a_asset", a)).name }), { phase: "bid", id: a });
}

function dbuy(d) {
  if (busy("dbuy", d)) return;
  // the price falls every block and the call lands a few blocks after you sign, so the ceiling is today's price; any
  // difference comes straight back to you in the same call
  const n = units(($("dN" + d) || {}).value || "1") || 1, p = dutchPrice(d), cost = p * BigInt(n);
  if (!canPay(dapp, cost, T("whatBuy", "Buying"))) return;
  dapp.call("dbuy", [d, n, p], cost, T("callDbuy", "buy {n} × “{t}” at {p} NADO or less", {
    n, t: tokenInfo(field("d_asset", d)).name, p: rawToNado(p) }), { phase: "dbuy", id: d });
}

function makeOffer(aid, coll) {
  const n = units($("oUnits").value) || 1, price = priceRaw("oPrice"), days = Number($("oDays").value || 0);
  if (price <= 0n) return notify(T("needPrice", "Set a price."));
  const exp = days > 0 ? cursor + Math.round(days * 86400 / BLOCK_TIME) : 0;
  const cost = price * BigInt(n);
  if (!canPay(dapp, cost, T("whatOffer", "An offer"))) return;
  dapp.call("offer", [randId(), coll ? 0n : big(aid), coll || 0, n, price, exp], cost,
    coll ? T("callCollOffer", "offer {p} NADO each for {n} from the collection", { p: rawToNado(price), n })
         : T("callOffer", "offer {p} NADO each for {n} × “{t}”", { p: rawToNado(price), n, t: tokenInfo(aid).name }),
    { phase: "offer" });
}

function accept(o, aid) {
  if (busy("accept", o)) return;
  const left = big(field("o_left", o)), have = held(aid), n = have < left ? have : left;
  if (n <= 0n) return notify(T("holdNone", "You hold none of this NFT."));
  dapp.call("accept", [o], n, T("callAccept", "sell {n} × “{t}” into the offer at {p} NADO each", {
    n, t: tokenInfo(aid).name, p: rawToNado(field("o_price", o)) }), { phase: "accept", id: o }, { asset: String(aid) });
}

const simple = (method, phase, label) => (id) => {
  if (busy(phase, id)) return;
  dapp.call(method, [id], null, label(id), { phase, id });
};
const unlist = simple("unlist", "unlist", (l) => T("callUnlist", "take listing #{id} down", { id: l }));
const settle = simple("settle_auction", "settle", (a) => T("callSettle", "settle auction #{id}", { id: a }));
const cancelAuction = simple("cancel_auction", "cancelA", (a) => T("callCancelA", "cancel auction #{id}", { id: a }));
const dcancel = simple("dcancel", "dcancel", (d) => T("callDcancel", "end Dutch auction #{id}", { id: d }));
const cancelOffer = simple("cancel_offer", "cancelO", (o) => T("callCancelO", "withdraw offer #{id}", { id: o }));
const expireOffer = simple("expire_offer", "expireO", (o) => T("callExpireO", "close expired offer #{id}", { id: o }));

// ---- rendering --------------------------------------------------------------------------------------------------
function card(aid) {
  const k = tokenInfo(aid), fl = floorOf(aid), au = auctionsOf(aid).length, du = dutchOf(aid).length;
  const tag = au ? `<span class="pill hot">${T("onAuction", "on auction")}</span>`
    : fl != null ? `<span class="pill">${rawToNado(fl)} NADO</span>` : du ? `<span class="pill">${T("dutchTag", "Dutch")}</span>` : "";
  return `<a class="nft" href="#token/${esc(aid)}">${media(aid, k.uri, "thumb")}
    <div class="nftmeta"><div class="nftname">${esc(k.name)}</div>
    <div class="dim small">${who(k.creator)} · ${k.supply === 1n ? "1/1" : T("eds", "{n} editions", { n: k.supply })}</div>${tag}</div></a>`;
}
const grid = (aids, empty) => aids.length ? `<div class="grid">${aids.map(card).join("")}</div>` : `<div class="dim">${empty}</div>`;
const registeredAssets = () => ids("t_mk").map((t) => String(field("t_asset", t))).filter((a) => assets[a]);
// EVERY NFT MINTED HERE IS SHOWN, REGISTERED OR NOT. A mint is two signatures and the second (register) lived only in
// the minting tab: a creator who closed it, came back in another tab or dismissed the prompt got an NFT that existed
// on chain (in their wallet, its media pinned) but appeared nowhere on this site — Nacho1 and a Korachi1, 2026-11-04.
// An unregistered one is listed (its page says no royalty is paid yet) and its creator can register it from there.
const isNft = (a) => !!a && !a.dec && !a.mintable && a.sym === "NFT" && !!mediaUrl(a.uri);
const nftAssets = () => {
  const reg = registeredAssets(), seen = new Set(reg);
  return reg.concat(Object.keys(assets).filter((a) => !seen.has(a) && isNft(assets[a])));
};

function viewExplore() {
  const all = nftAssets();                 // not registeredAssets(): an unregistered mint is still an NFT (nftAssets)
  const forSale = all.filter((a) => listingsOf(a).length || auctionsOf(a).length || dutchOf(a).length);
  return `<h2>${T("forSale", "For sale")}</h2>${grid(forSale, T("noneForSale", "Nothing is for sale yet."))}
    <h2 class="mt2">${T("allNfts", "All NFTs")}</h2>${grid(all, T("noneYet", "No NFTs yet — mint the first one."))}`;
}

function viewAuctions() {
  const live = registeredAssets().filter((a) => auctionsOf(a).length || dutchOf(a).length);
  const done = ids("a_mk").filter((a) => field("a_st", a) === OPEN && blocksLeft(field("a_end", a)) === 0);
  return `<h2>${T("liveAuctions", "Live auctions")}</h2>${grid(live, T("noAuctions", "No auctions running."))}
    ${done.length ? `<h2 class="mt2">${T("toSettle", "Ended — waiting to be settled")}</h2>` + done.map((a) =>
      `<div class="line">${esc(tokenInfo(field("a_asset", a)).name)} · ${rawToNado(field("a_bid", a))} NADO
       <button class="ghost sm" data-act="settle" data-id="${a}">${T("settleBtn", "Settle")}</button></div>`).join("") : ""}`;
}

function viewActivity() {
  const rows = ids("s_kind").slice(0, 200).map((s) => {
    const aid = String(field("s_asset", s));
    return `<div class="line"><a href="#token/${esc(aid)}">${esc(tokenInfo(aid).name)}</a> ·
      ${T("sold", "{n} sold for {p} NADO", { n: field("s_n", s), p: rawToNado(field("s_amt", s)) })}
      <span class="dim small">(${T("kind_" + SALE_KIND[field("s_kind", s)], SALE_KIND[field("s_kind", s)] || "")}) ${userLink(field("s_seller", s))} → ${userLink(field("s_buyer", s))}</span></div>`;
  });
  return `<h2>${T("activity", "Activity")}</h2>${rows.join("") || `<div class="dim">${T("noSales", "No sales yet.")}</div>`}`;
}

function viewToken(aid) {
  const k = tokenInfo(aid);
  if (!assets[aid]) return `<div class="dim">${T("unknown", "No such NFT.")}</div>`;
  const me = dapp.me, h = held(aid);
  const warn = [];
  if (k.mintable) warn.push(T("warnMintable", "⚠ Its issuer can still mint more — the edition count is not final."));
  if (k.dec) warn.push(T("warnDec", "⚠ This asset has decimals — it is a token, not an NFT."));
  if (!k.registered) warn.push(T("warnUnreg", "Not registered here: no royalty is paid on its sales."));
  const coll = k.coll ? `<a href="#coll/${k.coll}">${esc(field("c_name", k.coll) || "")}</a>` : "";
  const ls = listingsOf(aid).map((l) => {
    const mineL = field("l_seller", l) === me;
    return `<div class="line">${T("listingLine", "{n} left at {p} NADO", { n: field("l_left", l), p: rawToNado(field("l_price", l)) })} · ${userLink(field("l_seller", l))}
      ${mineL ? `<button class="ghost sm" data-act="unlist" data-id="${l}">${T("unlistBtn", "Take down")}</button>`
              : `<input class="qty" id="buyN${l}" value="1" inputmode="numeric"><button class="primary sm" data-act="buy" data-id="${l}">${T("buyBtn", "Buy")}</button>`}</div>`;
  }).join("");
  const as = auctionsOf(aid).map((a) => {
    const left = blocksLeft(field("a_end", a)), cur = big(field("a_bid", a)), mineA = field("a_seller", a) === me;
    const status = cur ? T("topBid", "top bid {p} NADO by {w}", { p: rawToNado(cur), w: userLink(field("a_bidder", a)) })
                       : T("reserveIs", "reserve {p} NADO, no bids", { p: rawToNado(field("a_reserve", a)) });
    const act = left === 0 ? `<button class="primary sm" data-act="settle" data-id="${a}">${T("settleBtn", "Settle")}</button>`
      : mineA ? (cur ? "" : `<button class="ghost sm" data-act="cancelA" data-id="${a}">${T("cancelBtn", "Cancel")}</button>`)
      : `<input class="amt" id="bidAmt${a}" placeholder="NADO" inputmode="decimal"><button class="primary sm" data-act="bid" data-id="${a}">${T("bidBtn", "Bid")}</button>`;
    return `<div class="line">${T("auctionLine", "{q} × in auction · {s}", { q: field("a_qty", a), s: status })} ·
      <span class="dim">${left ? T("endsIn", "ends in {t}", { t: fmtBlocks(left) }) : T("ended", "ended")}</span> ${act}</div>`;
  }).join("");
  const ds = dutchOf(aid).map((d) => {
    const mineD = field("d_seller", d) === me;
    return `<div class="line">${T("dutchLine", "{n} left at {p} NADO, falling to {e}", { n: field("d_left", d), p: rawToNado(dutchPrice(d)), e: rawToNado(field("d_ep", d)) })}
      ${mineD ? `<button class="ghost sm" data-act="dcancel" data-id="${d}">${T("cancelBtn", "Cancel")}</button>`
              : `<input class="qty" id="dN${d}" value="1" inputmode="numeric"><button class="primary sm" data-act="dbuy" data-id="${d}">${T("buyBtn", "Buy")}</button>`}</div>`;
  }).join("");
  const os = offersFor(aid).map((o) => {
    const mineO = field("o_bidder", o) === me, isColl = !big(field("o_asset", o));
    return `<div class="line">${T("offerLine", "{p} NADO each for {n}", { p: rawToNado(field("o_price", o)), n: field("o_left", o) })}${isColl ? " · " + T("collWide", "collection offer") : ""} · ${userLink(field("o_bidder", o))}
      ${mineO ? `<button class="ghost sm" data-act="cancelO" data-id="${o}">${T("withdrawBtn", "Withdraw")}</button>`
              : h > 0n ? `<button class="primary sm" data-act="accept" data-id="${o}" data-aid="${esc(aid)}">${T("acceptBtn", "Accept")}</button>` : ""}</div>`;
  }).join("");
  const history = historyHtml(aid);
  // the issuer can register at any time (the contract proves hash(issuer, seed) == asset, once): the way back for a
  // mint whose second signature never happened (nftAssets)
  const copts = myCollections().map((c) => `<option value="${c}">${esc(field("c_name", c) || "")}</option>`).join("");
  const regForm = !k.registered && me && me === k.creator && isNft(assets[aid]) ? `<div class="card"><h3>${T("regTitle", "Register the royalty")}</h3>
      <p class="small dim">${T("regLater", "Its royalty is not recorded yet. Only you, its creator, can register it — once.")}</p>
      <div class="row"><div><label>${T("fRoyalty", "Royalty (%)")}</label><input id="rRoyalty" value="10" inputmode="decimal"></div>
      <div><label>${T("fColl", "Collection")}</label><select id="rColl"><option value="0">${T("noCollOpt", "— none —")}</option>${copts}</select></div></div>
      <div class="row mt"><button class="primary" data-act="register" data-aid="${esc(aid)}">${T("regOk", "Register")}</button></div></div>` : "";
  const sell = h > 0n ? `<div class="card"><h3>${T("sellH", "Sell yours")} <span class="dim small">(${T("youHold", "you hold {h}", { h })})</span></h3>
      <div class="row"><div><label>${T("fUnits", "Editions")}</label><input id="sUnits" value="1" inputmode="numeric"></div>
      <div><label>${T("fPrice", "Price / reserve / start (NADO each)")}</label><input id="sPrice" inputmode="decimal"></div></div>
      <div class="row mt"><div><label>${T("fEnd", "Dutch end price (NADO)")}</label><input id="sEnd" inputmode="decimal"></div>
      <div><label>${T("fHours", "Auction length (hours)")}</label><input id="sHours" value="24" inputmode="decimal"></div></div>
      <div class="row mt"><button class="primary" data-act="list" data-aid="${esc(aid)}">${T("listBtn", "List at fixed price")}</button>
      <button data-act="auction" data-aid="${esc(aid)}">${T("auctionBtn", "English auction")}</button>
      <button data-act="dutch" data-aid="${esc(aid)}">${T("dutchBtn", "Dutch auction")}</button></div>
      <p class="small dim">${T("sellNote", "Your editions are held by the contract until they sell or you take them back. Auctions extend by 5 minutes when someone bids at the end.")}</p></div>` : "";
  const offerForm = me ? `<div class="card"><h3>${T("offerH", "Make an offer")}</h3>
      <div class="row"><div><label>${T("fPriceEach", "NADO each")}</label><input id="oPrice" inputmode="decimal"></div>
      <div><label>${T("fUnits", "Editions")}</label><input id="oUnits" value="1" inputmode="numeric"></div>
      <div><label>${T("fDays", "Expires in (days, 0 = never)")}</label><input id="oDays" value="7" inputmode="decimal"></div></div>
      <div class="row mt"><button class="primary" data-act="offer" data-aid="${esc(aid)}">${T("offerBtn", "Offer")}</button>
      ${k.coll ? `<button data-act="collOffer" data-coll="${k.coll}">${T("collOfferBtn", "Offer on the whole collection")}</button>` : ""}</div>
      <p class="small dim">${T("offerNote", "Your NADO is held by the contract until a holder accepts or you withdraw it.")}</p></div>` : "";
  const land = landPlotOf(assets[aid]) !== null;
  return `<div class="detail">${media(aid, k.uri, "big")}<div class="info">
      <h1>${esc(k.name)}</h1>
      ${landFacts(aid)}
      <div class="kv"><span class="k">${T("creator", "Creator")}</span><span>${userLink(k.creator)}</span></div>
      ${coll ? `<div class="kv"><span class="k">${T("collection", "Collection")}</span><span>${coll}</span></div>` : ""}
      <div class="kv"><span class="k">${T("editions", "Editions")}</span><span>${k.supply} · ${T("owners", "{n} owners", { n: k.holders })}</span></div>
      <div class="kv"><span class="k">${T("royalty", "Royalty")}</span><span>${pct(k.bps)}</span></div>
      <div class="kv"><span class="k">${T("assetId", "Asset id")}</span><span class="mono small trunc">${esc(aid)}</span></div>
      ${warn.map((w) => `<p class="small warnline">${w}</p>`).join("")}
      ${mediaUrl(k.uri) && !land ? `<a class="small" href="${esc(mediaUrl(k.uri))}" target="_blank" rel="noopener noreferrer">${T("openMedia", "Open the original")}</a>` : ""}
    </div></div>
    ${regForm}
    ${ls || as || ds ? `<div class="card"><h3>${T("onSale", "On sale")}</h3>${ls}${as}${ds}</div>` : ""}
    ${sell}
    <div class="card"><h3>${T("offers", "Offers")}</h3>${os || `<div class="dim small">${T("noOffers", "No offers yet.")}</div>`}</div>
    ${offerForm}
    <div class="card"><h3>${T("history", "History")}</h3>${history || `<div class="dim small">${T("noSales", "No sales yet.")}</div>`}</div>`;
}

// ---- provenance (the exec node's node-local asset history, /exec/asset_history) ----------------------------------
// Every movement of the asset — mint, wallet-to-wallet transfers, escrow into and out of this marketplace, burns — as
// the exec node applied it. The contract's own storage cannot see a plain asset_transfer, which is why this comes from
// the node and not from the sales log.
const hist = {};                     // aid -> {events, from, at}
async function loadHistory(aid) {
  const h = hist[aid];
  if (h && Date.now() - h.at < 15000) return;
  hist[aid] = Object.assign(h || { events: null, from: null }, { at: Date.now() });
  try {
    const j = await (await fetch(base() + "/exec/asset_history?ns=" + dapp.ns + "&id=" + encodeURIComponent(aid) + "&limit=500", { cache: "no-store" })).json();
    hist[aid] = { events: Array.isArray(j.events) ? j.events : [], from: j.indexed_from, enabled: j.enabled !== false, at: Date.now() };
  } catch (e) { /* keep what we had */ }
  if (location.hash === "#token/" + aid) { lastRoute = ""; render(); }
}
const holderLink = (h) => h === CID ? T("marketplace", "the marketplace") : userLink(h);
function describe(ev, aid) {
  const mv = (ev.moves || []).map((m) => ({ h: m.holder, d: big(m.delta) }));
  // the PARTIES are everyone but the marketplace: a sale into an offer passes through its escrow in one call (seller ->
  // marketplace -> bidder), and counting those transit moves would read 2 editions for 1; the marketplace is named only
  // when it IS one side (a listing, a take-down)
  const ext = mv.filter((m) => m.h !== CID);
  const gain = mv.filter((m) => m.d > 0n), loss = mv.filter((m) => m.d < 0n);
  const gx = ext.filter((m) => m.d > 0n), lx = ext.filter((m) => m.d < 0n);
  const n = gx.reduce((a, m) => a + m.d, 0n) || lx.reduce((a, m) => a - m.d, 0n) || gain.reduce((a, m) => a + m.d, 0n);
  const to = (gx.length ? gx[gx.length - 1] : gain[gain.length - 1] || {}).h || "";
  const from = (lx.length ? lx[0] : loss[0] || {}).h || "";
  const a0 = Number(ev.args && ev.args[0] || 0), ours = mv.some((m) => m.h === CID);
  const saleAmt = (kind) => { for (const sId of ids("s_kind")) if (String(field("s_asset", sId)) === aid && Number(field("s_h", sId)) === ev.cursor && Number(field("s_kind", sId)) === kind) return field("s_amt", sId); return null; };
  switch (ev.op) {
    case "asset_create": return T("hMinted", "Minted · {n}", { n }) + " · " + holderLink(to);
    case "asset_mint": return T("hMintedMore", "{n} more minted", { n }) + " · " + holderLink(to);
    case "asset_burn": return T("hBurned", "{n} burned", { n }) + " · " + holderLink(from);
    case "asset_transfer": case "asset_transfer_from":
      return T("hTransfer", "Transferred {n}", { n }) + " · " + holderLink(from) + " → " + holderLink(to);
  }
  if (ev.op === "call" && ours) {
    const nado = (raw) => raw == null ? "?" : rawToNado(raw);
    switch (ev.method) {
      case "list": return T("hListed", "Listed {n} at {p} NADO each", { n, p: nado(ev.args[2]) }) + " · " + holderLink(from);
      case "unlist": case "dcancel": case "cancel_auction": return T("hDelisted", "Taken down") + " · " + holderLink(to);
      case "buy": return T("hBought", "{n} bought for {p} NADO", { n, p: nado(ev.value) }) + " · " + holderLink(to);
      case "accept": return T("hOfferSold", "{n} sold into an offer for {p} NADO", { n, p: nado(saleAmt(2)) }) + " · " + holderLink(from) + " → " + holderLink(to);
      case "auction": return T("hAuction", "Put up for auction · reserve {p} NADO", { p: nado(ev.args[2]) }) + " · " + holderLink(from);
      case "settle_auction": {
        const amt = saleAmt(3);
        return amt == null ? T("hDelisted", "Taken down") + " · " + holderLink(to) : T("hWon", "Won at auction for {p} NADO", { p: nado(amt) }) + " · " + holderLink(to);
      }
      case "dutch": return T("hDutch", "Dutch auction · {a} → {b} NADO", { a: nado(ev.args[2]), b: nado(ev.args[3]) }) + " · " + holderLink(from);
      case "dbuy": return T("hDutchBuy", "{n} bought in a Dutch auction for {p} NADO", { n, p: nado(saleAmt(4)) }) + " · " + holderLink(to);
    }
  }
  return T("hCall", "contract call: {m}", { m: esc(ev.method || ev.op || "?") }) + " · " + (from ? holderLink(from) + " → " : "") + holderLink(to);
}
function historyHtml(aid) {
  loadHistory(aid);
  const h = hist[aid];
  if (!h || h.events == null) return `<div class="dim small">${T("histLoading", "Loading history…")}</div>`;
  const rows = h.events.map((ev) => `<div class="line small">${describe(ev, aid)}
    <span class="dim">· ${T("ago", "{t} ago", { t: fmtBlocks(Math.max(0, cursor - Number(ev.cursor || 0))) })}</span></div>`).join("");
  const minted = h.events.some((ev) => ev.op === "asset_create");
  const note = !minted && h.from != null ? `<div class="dim small mt">${T("histFrom", "History on this node starts at block {b}.", { b: h.from })}</div>` : "";
  return (rows || `<div class="dim small">${T("noHistory", "No history yet.")}</div>`) + note;
}

function viewCollection(c) {
  if (!field("c_mk", c)) return `<div class="dim">${T("noColl", "No such collection.")}</div>`;
  const aids = registeredAssets().filter((a) => tokenInfo(a).coll === c);
  const offers = ids("o_mk").filter((o) => field("o_st", o) === OPEN && Number(field("o_coll", o)) === c && !expiredOffer(o));
  const desc = field("c_desc", c);
  return `<h1>${esc(field("c_name", c) || "")}</h1>
    <p class="dim">${desc && desc !== "-" ? esc(desc) : ""}</p>
    <div class="small">${T("by", "by {w}", { w: userLink(field("c_owner", c)) })} · ${T("nItems", "{n} items", { n: aids.length })}</div>
    ${offers.length ? `<div class="card"><h3>${T("collOffers", "Collection offers")}</h3>${offers.map((o) =>
      `<div class="line">${T("offerLine", "{p} NADO each for {n}", { p: rawToNado(field("o_price", o)), n: field("o_left", o) })} · ${userLink(field("o_bidder", o))}</div>`).join("")}</div>` : ""}
    ${grid(aids, T("emptyColl", "Nothing in this collection yet."))}`;
}

function viewUser(addr) {
  const p = profileOf(addr);
  const created = nftAssets().filter((a) => tokenInfo(a).creator === addr);   // incl. unregistered (nftAssets)
  const av = p && p.av !== "-" ? mediaUrl(p.av) : "";
  const isMe = addr === dapp.me;
  const owned = isMe ? Object.keys(mine).filter((a) => assets[a] && !assets[a].dec && (tokenInfo(a).registered || isNft(assets[a]))) : [];
  const myOffers = isMe ? ids("o_mk").filter((o) => field("o_bidder", o) === addr && field("o_st", o) === OPEN) : [];
  return `<div class="profile">${av ? `<img class="avatar" src="${esc(av)}" alt="">` : ""}
      <div><h1>${p && p.name && p.name !== "-" ? esc(p.name) : esc(disp(addr))}</h1>
      <div class="mono small trunc dim">${esc(addr)}</div>
      ${p && p.bio && p.bio !== "-" ? `<p>${esc(p.bio)}</p>` : ""}</div></div>
    ${isMe ? `<h2>${T("owned", "Owned")}</h2>${grid(owned, T("ownNone", "You hold no NFTs yet."))}` : ""}
    ${myOffers.length ? `<div class="card"><h3>${T("yourOffers", "Your open offers")}</h3>${myOffers.map((o) =>
      `<div class="line">${T("offerLine", "{p} NADO each for {n}", { p: rawToNado(field("o_price", o)), n: field("o_left", o) })}
       ${expiredOffer(o) ? `<button class="ghost sm" data-act="expireO" data-id="${o}">${T("closeBtn", "Close (expired)")}</button>`
                         : `<button class="ghost sm" data-act="cancelO" data-id="${o}">${T("withdrawBtn", "Withdraw")}</button>`}</div>`).join("")}</div>` : ""}
    <h2 class="mt2">${T("created", "Created")}</h2>${grid(created, T("createdNone", "Nothing created yet."))}`;
}

function viewCreate() {
  if (!dapp.me) return `<div class="dim">${T("signInFirst", "Sign in with your NADO wallet first.")}</div>`;
  const p = profileOf(dapp.me) || {};
  const opts = myCollections().map((c) => `<option value="${c}">${esc(field("c_name", c) || "")}</option>`).join("");
  const v = (s) => (s && s !== "-" ? esc(s) : "");
  return `<div class="card"><h3>${T("mintH", "Mint an NFT")}</h3>
      <p class="small dim">${T("mintIntro3", "Choose your file — it is stored on IPFS and pinned by this site. Set the royalty and collection here: one approval in your wallet creates the NFT and records its royalty.")}</p>
      <label>${T("fTitle", "Title")}</label><input id="mName" maxlength="64">
      <label class="mt">${T("fFile", "File")}</label>
      <input id="mFile" type="file" accept="image/png,image/jpeg,image/gif,image/webp,image/avif,video/mp4,video/webm,audio/mpeg,audio/ogg,audio/wav,audio/flac,audio/mp4,model/gltf-binary,.glb">
      <label class="mt">${T("fUri", "Media link (ipfs:// or https://)")}</label><input id="mUri" maxlength="128" placeholder="ipfs://…">
      <div class="row mt"><div><label>${T("fEditions", "Editions")}</label><input id="mEditions" value="1" inputmode="numeric"></div>
      <div><label>${T("fRoyalty", "Royalty (%)")}</label><input id="mRoyalty" value="10" inputmode="decimal"></div></div>
      <label class="mt">${T("fColl", "Collection")}</label><select id="mColl"><option value="0">${T("noCollOpt", "— none —")}</option>${opts}</select>
      <div class="row mt"><button class="primary" id="btnMint">${T("mintBtn", "Mint")}</button></div></div>
    <div class="card"><h3>${T("newCollH", "New collection")}</h3>
      <label>${T("fName", "Name")}</label><input id="cName"><label class="mt">${T("fDesc", "Description")}</label><input id="cDesc">
      <div class="row mt"><button id="btnColl">${T("collBtn", "Create collection")}</button></div></div>
    <div class="card"><h3>${T("profileH", "Your profile")}</h3>
      <label>${T("fName", "Name")}</label><input id="pName" value="${v(p.name)}"><label class="mt">${T("fBio", "Bio")}</label><input id="pBio" value="${v(p.bio)}">
      <label class="mt">${T("fAvatar", "Avatar link (ipfs:// or https://)")}</label><input id="pAv" value="${v(p.av)}">
      <div class="row mt"><button id="btnProfile">${T("profileBtn", "Save profile")}</button></div></div>`;
}

const ROUTES = { explore: viewExplore, auctions: viewAuctions, activity: viewActivity, create: viewCreate };
let lastRoute = "";
function render() {
  renderWallet(dapp);
  gate({ navMe: !!dapp.me });
  if (!sto) { $("view").innerHTML = `<div class="dim">${T("loading", "Loading…")}</div>`; return; }
  const [route, arg] = decodeURIComponent((location.hash || "#explore").slice(1)).split("/");
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("on", a.dataset.r === route);
  // the Create forms re-render only when what they show changes: your collections, your profile, who is signed in
  const key = location.hash + (route === "create"
    ? "|" + dapp.me + "|" + myCollections().join(",") + "|" + JSON.stringify(profileOf(dapp.me)) : "");
  // forms keep what you typed: a route only re-renders its form when you navigate to it, not on every poll
  // the Create forms need no live data: they render when you navigate there, never on a poll (a re-render would close
  // the collection picker mid-choice); a token page re-renders live but not while you are typing into it
  if (route === "create" && key === lastRoute) return;
  if (route === "token" && key === lastRoute && document.activeElement && document.activeElement.tagName === "INPUT") return;
  lastRoute = key;
  const html = route === "token" ? viewToken(arg) : route === "coll" ? viewCollection(Number(arg))
    : route === "user" ? viewUser(arg) : (ROUTES[route] || viewExplore)();
  const keep = {};
  for (const el of document.querySelectorAll("#view input, #view select")) if (el.id && el.type !== "file") keep[el.id] = el.value;
  $("view").innerHTML = html;
  for (const id in keep) if ($(id) && keep[id] !== "") $(id).value = keep[id];
  if (route === "create") { $("btnMint").onclick = mint; $("btnColl").onclick = createCollection; $("btnProfile").onclick = saveProfile;
    wireDrop(); }
}

// the Create form re-renders when your collections change; a file already uploaded stays shown (from its link)
function wireDrop() {
  const zone = enhanceFile($("mFile"), {
    hint: T("fileHint", "PNG, JPG, GIF, WEBP, AVIF, MP4, WEBM, MP3, OGG, WAV, FLAC or GLB · at most 5 MB"),
    onFile: (f, z) => upload(f, z),
    onRemove: () => { if ($("mUri").value.startsWith("ipfs://")) $("mUri").value = ""; },
  });
  const u = $("mUri").value.trim();
  if (zone && u.startsWith("ipfs://")) zone.done(mediaTag(u, "thumb prev"), u);
}

async function refresh() {
  try {
    const [s, all, mineR] = await Promise.all([
      dapp.storage(),
      (await fetch(base() + "/exec/assets?ns=" + dapp.ns, { cache: "no-store" })).json(),
      dapp.me ? (await fetch(base() + "/exec/assets?ns=" + dapp.ns + "&holder=" + encodeURIComponent(dapp.me), { cache: "no-store" })).json() : null,
    ]);
    if (s) sto = s;
    if (all && all.assets) { assets = {}; for (const a of all.assets) assets[String(a.id)] = a; cursor = Number(all.cursor || cursor); }
    mine = {};
    if (mineR && mineR.assets) for (const a of mineR.assets) mine[String(a.id)] = a;
  } catch (e) { /* a relay blip keeps the last good view */ }
  render();
}

function wireUI() {
  dapp.walletLabels = financeLabels();   // a marketplace, not a game: deposit / withdraw a usable balance
  wireWallet(dapp, render);
  window.addEventListener("hashchange", () => { lastRoute = ""; render(); });
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-act]");
    if (!b) return;
    const id = Number(b.dataset.id || 0), aid = b.dataset.aid;
    const acts = { buy: () => buy(id), unlist: () => unlist(id), bid: () => bid(id), settle: () => settle(id),
      cancelA: () => cancelAuction(id), dbuy: () => dbuy(id), dcancel: () => dcancel(id), cancelO: () => cancelOffer(id),
      expireO: () => expireOffer(id), accept: () => accept(id, aid), list: () => list(aid), auction: () => auction(aid),
      dutch: () => dutch(aid), register: () => registerLater(aid), offer: () => makeOffer(aid, 0), collOffer: () => makeOffer(0, Number(b.dataset.coll)) };
    if (!dapp.me && b.dataset.act !== "settle") return notify(T("signInFirst", "Sign in with your NADO wallet first."));
    (acts[b.dataset.act] || (() => {}))();
  });
  $("navMe").onclick = (ev) => { ev.preventDefault(); location.hash = "#user/" + encodeURIComponent(dapp.me || ""); };
}

dapp.onReturn((pend, ok, err, err2) => {
  // the mint landed but its royalty step was not submitted: say so, and where to finish it (registerLater)
  if (ok && err2 && pend && pend.phase === "mint") notify(T("regFailed", "Your NFT is being created, but its royalty was not recorded ({e}). Open the NFT and press Register.", { e: err2 }));
  dapp.showReturn(pend, ok, err, {
    mint: T("mintSent2", "Creating your NFT with its royalty — confirming…"),
    register: T("regSent", "Royalty registered — confirming…"),
    buy: T("buySent", "Buying — confirming…"), bid: T("bidSent", "Bid placed — confirming…"),
    list: T("listSent", "Listing — confirming…"), offer: T("offerSent", "Offer posted — confirming…"),
  });
  refresh();
});

async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  refresh();
  setInterval(refresh, 4000);
}
boot();
