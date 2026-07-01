/* NADO Explorer — a client-side page (like the light miner) that reads the node's public JSON API.
 * No server-side rendering: it fetches /get_block, /get_account, /get_transaction, /status, etc. from
 * the node that serves it (or a ?node=host:port override) and renders them. Shareable via URL hash. */
"use strict";

const DENOM = 10_000_000_000n;
const $ = (id) => document.getElementById(id);

// Same-origin by default (the node serves this file); ?node=host:port points it at another node.
function apiBase() {
  const q = new URLSearchParams(location.search).get("node");
  if (q) return /^https?:\/\//.test(q) ? q.replace(/\/$/, "") : "http://" + q.replace(/\/$/, "");
  return location.origin;
}
async function getJSON(path) {
  const res = await fetch(apiBase() + path, { cache: "no-store" });
  const text = await res.text();
  let data; try { data = JSON.parse(text); } catch { data = null; }
  if (!res.ok || data == null) throw new Error((data && data.message) || text || ("HTTP " + res.status));
  return data;
}

// ---- formatting ---------------------------------------------------------------------------------
function fmtNado(raw) {
  try {
    const n = BigInt(raw);
    const whole = n / DENOM, frac = (n % DENOM).toString().padStart(10, "0").replace(/0+$/, "");
    return whole.toLocaleString("en-US") + (frac ? "." + frac : "") + " NADO";
  } catch { return String(raw); }
}
function fmtTime(ts) {
  if (!ts && ts !== 0) return "—";
  const d = new Date(ts * 1000);
  return d.toISOString().replace("T", " ").replace(".000Z", " UTC");
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const short = (h, n = 14) => (h && h.length > n * 2 ? h.slice(0, n) + "…" + h.slice(-6) : (h ?? "—"));

// clickable links that drive the hash router
const aBlock = (v, label) => `<a class="link" href="#b/${esc(v)}">${esc(label ?? v)}</a>`;
const aAddr  = (v, label) => `<a class="link" href="#a/${esc(v)}">${esc(label ?? v)}</a>`;
const aTx    = (v, label) => `<a class="link" href="#tx/${esc(v)}">${esc(label ?? v)}</a>`;

function kv(pairs) {
  return `<div class="kv">${pairs.filter(Boolean).map(([k, v]) => `<div class="k">${esc(k)}</div><div class="v">${v}</div>`).join("")}</div>`;
}

// ---- overview -----------------------------------------------------------------------------------
async function loadOverview() {
  try {
    const [st, sup] = await Promise.all([getJSON("/status"), getJSON("/get_supply")]);
    setConn(true);
    $("tipText").textContent = "tip: #" + st.latest_block_weight;
    $("network").innerHTML = [
      ["Tip height", `${aBlock(st.latest_block_hash, "#" + (sup.block_number ?? "?"))}`],
      ["Latest hash", `<span class="mono">${short(st.latest_block_hash)}</span>`],
      ["Finalized", "#" + st.finalized_height + (st.ffg_finalized != null ? `  ·  FFG #${st.ffg_finalized}` : "")],
      ["Total supply", fmtNado(sup.total_supply)],
      ["Circulating", fmtNado(sup.circulating)],
      ["Treasury", fmtNado(sup.treasury)],
      ["Fees burned", fmtNado(sup.fees)],
      ["Protocol", "v" + st.protocol],
    ].map(([k, v]) => `<div class="stat"><span class="k">${k}</span><span class="n">${v}</span></div>`).join("");
  } catch (e) { setConn(false); $("network").innerHTML = `<div class="warnbox danger">Node unreachable: ${esc(e.message)}</div>`; }
  try {
    const ms = await getJSON("/mining_status");
    $("mining").innerHTML = [
      ["Epoch", ms.epoch + `  (len ${ms.epoch_length})`],
      ["Next block", "#" + ms.next_block],
      ["Block time", ms.block_time + "s"],
      ["OPEN lane", `${ms.open_registry_size} miners · weight ${ms.total_open_weight} · ${ms.k_open}/${ms.epoch_length} slots`],
      ["BONDED lane", `${ms.bonded_registry_size} miners · ${ms.total_bonded_shares} shares`],
      ["Beacon", `<span class="mono">${short(ms.beacon)}</span>`],
    ].map(([k, v]) => `<div class="stat"><span class="k">${k}</span><span class="n">${v}</span></div>`).join("");
  } catch (e) { $("mining").innerHTML = `<div class="faint small">mining status unavailable</div>`; }
}

async function loadRecent() {
  try {
    const tip = await getJSON("/get_latest_block");
    const top = tip.block_number, lo = Math.max(0, top - 11);
    const nums = []; for (let n = top; n >= lo; n--) nums.push(n);
    const blocks = await Promise.all(nums.map((n) => getJSON("/get_block_number?number=" + n).catch(() => null)));
    $("recent").innerHTML = blocks.filter(Boolean).map(blockRow).join("") || `<div class="faint small">no blocks</div>`;
  } catch (e) { $("recent").innerHTML = `<div class="faint small">unavailable</div>`; }
}
function blockRow(b) {
  const txs = (b.block_transactions || []).length;
  return `<div class="rowline">
    <div>${aBlock(b.block_hash, "#" + b.block_number)} <span class="faint small">· ${txs} tx${txs === 1 ? "" : "s"}</span>
      <div class="faint small">${fmtTime(b.block_timestamp)}</div></div>
    <div style="text-align:right"><span class="mono faint small">${short(b.block_hash, 8)}</span>
      <div class="small">by ${aAddr(b.block_creator, short(b.block_creator, 8))}</div></div>
  </div>`;
}

// ---- detail views -------------------------------------------------------------------------------
function renderBlock(b) {
  const txs = b.block_transactions || [];
  const txlist = txs.length
    ? `<div class="rows mt">${txs.map(txRow).join("")}</div>`
    : `<div class="faint small mt">no transactions in this block</div>`;
  return `<h2>Block #${b.block_number}</h2>${kv([
    ["Hash", `<span class="mono">${esc(b.block_hash)}</span>`],
    ["Parent", aBlock(b.parent_hash, short(b.parent_hash))],
    ["Producer", aAddr(b.block_creator)],
    ["Time", fmtTime(b.block_timestamp)],
    ["Reward", fmtNado(b.block_reward)],
    ["Cumulative fees", fmtNado(b.cumulative_fees)],
    ["Cumulative weight", String(b.cumulative_weight)],
    ["Transactions", String(txs.length)],
  ])}${txlist}`;
}
function txRow(t) {
  return `<div class="rowline">
    <div>${t.txid ? aTx(t.txid, short(t.txid, 10)) : `<span class="mono">${esc(t.recipient)}</span>`}
      <div class="small">${aAddr(t.sender, short(t.sender, 8))} → ${reservedOrAddr(t.recipient)}</div></div>
    <div style="text-align:right" class="mono">${fmtNado(t.amount)}<div class="faint small">fee ${fmtNado(t.fee || 0)}</div></div>
  </div>`;
}
const RESERVED = new Set(["bond", "unbond", "withdraw", "register", "heartbeat", "slash", "attest", "commit", "reveal"]);
const reservedOrAddr = (r) => RESERVED.has(r) ? `<span class="badge">${esc(r)}</span>` : aAddr(r, short(r, 8));

function renderAccount(a) {
  return `<h2>Account</h2>${kv([
    ["Address", `<span class="mono">${esc(a.address)}</span>`],
    ["Balance", fmtNado(a.balance)],
    ["Bonded", fmtNado(a.bonded) + (a.bonded ? ` <span class="faint small">(stake in the bonded lane)</span>` : "")],
    ["Produced", fmtNado(a.produced)],
    ["Registered", a.registered ? "yes (OPEN-lane miner)" : "no"],
    ["Fidelity", String(a.fidelity ?? 0) + " <span class=\"faint small\">/ 1000 (open-lane diligence)</span>"],
    a.last_hb_epoch ? ["Last heartbeat", "epoch " + a.last_hb_epoch] : null,
  ])}<div class="row mt"><button class="accent" id="loadTxs">Show transactions</button></div>
    <div id="acctTxs" class="rows mt"></div>`;
}
async function loadAccountTxs(addr) {
  const box = $("acctTxs"); if (!box) return;
  box.innerHTML = `<div class="faint small">loading…</div>`;
  try {
    const d = await getJSON("/get_transactions_of_account?address=" + encodeURIComponent(addr) + "&min_block=0");
    const txs = d.transactions || [];
    box.innerHTML = txs.length ? txs.map(txRow).join("") : `<div class="faint small">no transactions</div>`;
  } catch (e) { box.innerHTML = `<div class="warnbox danger">${esc(e.message)}</div>`; }
}

function renderTx(t) {
  return `<h2>Transaction</h2>${kv([
    ["Txid", `<span class="mono">${esc(t.txid || "—")}</span>`],
    ["From", aAddr(t.sender)],
    ["To", reservedOrAddr(t.recipient)],
    ["Amount", fmtNado(t.amount)],
    ["Fee", fmtNado(t.fee || 0)],
    ["Target block", t.target_block != null ? aBlock(String(t.target_block), "#" + t.target_block) : "—"],
    ["Timestamp", fmtTime(t.timestamp)],
    t.data ? ["Data", `<span class="mono">${esc(String(t.data).slice(0, 200))}</span>`] : null,
    ["Nonce", `<span class="mono">${esc(t.nonce || "—")}</span>`],
  ])}`;
}

// ---- router -------------------------------------------------------------------------------------
function showResult(html) { const r = $("result"); r.innerHTML = html; r.classList.remove("hidden"); r.scrollIntoView({ behavior: "smooth", block: "start" }); }
function showErr(msg) { const e = $("searchErr"); e.textContent = msg; e.classList.remove("hidden"); }
function clearErr() { $("searchErr").classList.add("hidden"); }

async function route() {
  clearErr();
  const h = location.hash.slice(1);
  if (!h) { $("result").classList.add("hidden"); return; }
  const [kind, ...rest] = h.split("/");
  const val = decodeURIComponent(rest.join("/"));
  try {
    if (kind === "a") {
      showResult(renderAccount(await getJSON("/get_account?address=" + encodeURIComponent(val))));
      const btn = $("loadTxs"); if (btn) btn.onclick = () => loadAccountTxs(val);
    } else if (kind === "b") {
      const path = /^\d+$/.test(val) ? "/get_block_number?number=" + val : "/get_block?hash=" + encodeURIComponent(val);
      const b = await getJSON(path);
      if (!b || b === false || !b.block_hash) throw new Error("block not found");
      showResult(renderBlock(b));
    } else if (kind === "tx") {
      const t = await getJSON("/get_transaction?txid=" + encodeURIComponent(val));
      if (!t || t === false) throw new Error("transaction not found");
      showResult(renderTx(t));
    }
  } catch (e) { showResult(`<div class="warnbox danger">Not found: ${esc(e.message)}</div>`); }
}

function search() {
  clearErr();
  const q = $("q").value.trim();
  if (!q) return;
  if (/^\d+$/.test(q)) location.hash = "b/" + q;
  else if (/^ndo[0-9a-f]{46}$/i.test(q)) location.hash = "a/" + q;
  else if (/^[0-9a-f]{64}$/i.test(q)) location.hash = "b/" + q;   // 64-hex: try block; route() falls back to tx on miss
  else showErr("Unrecognized — expected an ndo… address, a block number, or a 64-hex hash/txid.");
}

// a 64-hex that isn't a block should resolve as a txid: wrap route() to retry
const _route = route;
route = async function () {
  const h = location.hash.slice(1);
  if (h.startsWith("b/")) {
    const val = decodeURIComponent(h.slice(2));
    if (/^[0-9a-f]{64}$/i.test(val)) {
      try {
        const b = await getJSON("/get_block?hash=" + encodeURIComponent(val));
        if (b && b.block_hash) { showResult(renderBlock(b)); return; }
      } catch {}
      try {
        const t = await getJSON("/get_transaction?txid=" + encodeURIComponent(val));
        if (t && t !== false) { showResult(renderTx(t)); return; }
      } catch {}
      showResult(`<div class="warnbox danger">No block or transaction with hash <span class="mono">${short(val)}</span>.</div>`);
      return;
    }
  }
  return _route();
};

function setConn(ok) {
  $("connDot").className = "dot" + (ok ? " ok" : " bad");
  $("connText").textContent = ok ? "connected" : "node unreachable";
}

// ---- boot ---------------------------------------------------------------------------------------
$("go").onclick = search;
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
window.addEventListener("hashchange", route);
loadOverview();
loadRecent();
route();
setInterval(() => { loadOverview(); loadRecent(); }, 15000);
