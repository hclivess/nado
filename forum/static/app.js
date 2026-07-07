/* NADO forum SPA (doc/forum.md). Vanilla ES module. Wallet-native login via the interface SSO handoff.
 * All user-supplied content is HTML-escaped before any formatting is applied — the node's verifier is the
 * only trust boundary for identity; the client never renders raw markup. */

const app = document.getElementById("app");
const who = document.getElementById("who");
let ME = null;                     // {address, alias, balance, role, can_post} or null
let INTERFACE = "https://get.nadochain.com";   // wallet/explorer origin (server-provided via /api/me)
let TREASURY = null;               // cached /treasury_status

// ---- helpers -------------------------------------------------------------------------------------
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (a) => (a && a.length > 16) ? a.slice(0, 10) + "…" + a.slice(-4) : (a || "");
// raw units -> "NADO" string (DENOM 1e10). BigInt end-to-end — balances arrive as strings. `dp` caps decimals.
const DENOM = 10n ** 10n;
function fmtNado(raw, dp) {
  let v; try { v = BigInt(raw || 0); } catch (e) { return "?"; }
  let frac = (v % DENOM).toString().padStart(10, "0");
  if (dp != null) frac = frac.slice(0, dp);
  frac = frac.replace(/0+$/, "");
  return (v / DENOM).toString() + (frac ? "." + frac : "");
}
// display name for an author: on-chain alias when the view's authors map has one, else the short address
const uname = (a, authors) => {
  const m = authors && authors[a];
  return m && m.alias ? "@" + m.alias : short(a);
};
// clickable author -> in-forum profile (#/u/<addr>), which links onward to the explorer
const userLink = (a, authors) => {
  const m = authors && authors[a];
  return '<a class="addr ulink" href="#/u/' + esc(a) + '">' + esc(uname(a, authors)) + "</a>" +
    (m && m.role === "mod" ? ' <span class="pill mod">mod</span>' : "");
};
const ago = (ts) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000) - (ts || 0));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
};
// minimal, SAFE markdown: applied to ALREADY-ESCAPED text, so no tag can be injected.
function fmt(bodyRaw) {
  let t = esc(bodyRaw);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<>"']+)/g, (m, p, url) =>
    p + '<a href="' + url + '" rel="noopener nofollow" target="_blank">' + url + "</a>");
  return t;
}
async function getJSON(url) { const r = await fetch(url, { credentials: "same-origin" }); return r.json(); }
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}
// one mod action -> refresh the current view; failures surface as an alert (mod-only path).
async function modAction(payload, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  const res = await postJSON("/api/mod", payload);
  if (!res.ok) alert(res.error || "action failed");
  route();
}
// wire every element carrying data-mod='{"action":...}' (+ optional data-confirm) to modAction.
function bindModButtons() {
  app.querySelectorAll("[data-mod]").forEach((el) => {
    el.onclick = () => modAction(JSON.parse(el.dataset.mod), el.dataset.confirm || null);
  });
}
const modBtn = (payload, label, confirmMsg) =>
  '<button class="btn ghost sm" data-mod="' + esc(JSON.stringify(payload)) + '"' +
  (confirmMsg ? ' data-confirm="' + esc(confirmMsg) + '"' : "") + ">" + esc(label) + "</button>";

// ---- header (who am I) ---------------------------------------------------------------------------
function renderWho() {
  who.textContent = "";
  if (ME) {
    const badge = ME.role === "mod" ? ' <span class="pill mod">mod</span>' : "";
    const gate = ME.can_post ? "" : ' <span class="pill">read-only — register to post</span>';
    const bal = ME.balance != null ? ' <span class="pill bal">' + esc(fmtNado(ME.balance, 2)) + " NADO</span>" : "";
    const name = ME.alias ? "@" + ME.alias : short(ME.address);
    who.innerHTML = '<a class="addr ulink" href="#/u/' + esc(ME.address) + '">' + esc(name) + "</a>" + badge + bal + gate +
      ' <button class="btn ghost sm" id="logout">Sign out</button>';
    document.getElementById("logout").onclick = async () => { await postJSON("/api/logout", {}); ME = null; renderWho(); route(); };
  } else {
    who.innerHTML = '<button class="btn sm" id="login">Sign in with NADO wallet</button>';
    document.getElementById("login").onclick = () => { location.href = "/api/sso_start"; };
  }
}

// ---- views ---------------------------------------------------------------------------------------
async function viewBoards() {
  const d = await getJSON("/api/boards");
  if (!d.ok) return app.innerHTML = '<div class="err">Could not load boards.</div>';
  app.innerHTML = "<h1>Boards</h1>" + d.boards.map((b) =>
    '<div class="card board-row"><div><h3><a href="#/b/' + esc(b.slug) + '">' + esc(b.title) + "</a></h3>" +
    "<p>" + esc(b.description || "") + "</p></div>" +
    '<div class="count">' + b.threads + " threads</div></div>").join("");
}

async function viewBoard(slug) {
  const d = await getJSON("/api/threads?board=" + encodeURIComponent(slug));
  if (!d.ok) return app.innerHTML = '<div class="err">' + esc(d.error || "board not found") + "</div>";
  let html = '<div class="crumb"><a href="#/">Boards</a> › ' + esc(d.board.title) + "</div><h1>" + esc(d.board.title) + "</h1>";
  html += '<div class="card">' + (d.threads.length ? d.threads.map((t) =>
    '<div class="thread-row"><div><a href="#/t/' + t.id + '">' + esc(t.title) + "</a>" +
    (t.deleted ? ' <span class="pill del">deleted</span>' : "") +
    (t.pinned ? ' <span class="pill">pinned</span>' : "") + (t.locked ? ' <span class="pill">locked</span>' : "") +
    (t.pid ? ' <span class="pill pid">proposal</span>' : "") +
    '<div class="meta">by ' + userLink(t.author, d.authors) + " · " + ago(t.bumped_at) + "</div></div>" +
    '<div class="count">' + t.replies + " replies</div></div>").join("") : '<div class="empty">No threads yet.</div>') + "</div>";
  // compose
  if (ME && ME.can_post && (d.board.post_min_role !== "mod" || ME.role === "mod")) {
    html += '<div class="card"><h2>New thread</h2>' +
      '<input id="ntTitle" maxlength="200" placeholder="Title">' +
      '<textarea id="ntBody" placeholder="Write your post… (**bold**, `code`, links)"></textarea>' +
      '<div class="row" style="margin-top:8px"><input id="ntPid" placeholder="Treasury proposal id (optional)" style="flex:1">' +
      '<button class="btn" id="ntPost">Post thread</button></div><div class="err" id="ntErr"></div></div>';
  } else if (!ME) {
    html += '<div class="note">Sign in with your NADO wallet to start a thread.</div>';
  } else if (!ME.can_post) {
    html += '<div class="note">Posting requires a <b>registered</b> NADO address — register (one-time) in the wallet, then reload.</div>';
  }
  app.innerHTML = html;
  const btn = document.getElementById("ntPost");
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    const res = await postJSON("/api/thread", { board: slug,
      title: document.getElementById("ntTitle").value, body: document.getElementById("ntBody").value,
      pid: document.getElementById("ntPid").value });
    if (res.ok) location.hash = "#/t/" + res.thread_id;
    else { document.getElementById("ntErr").textContent = res.error || "failed"; btn.disabled = false; }
  };
}

async function viewThread(id) {
  const d = await getJSON("/api/thread?id=" + encodeURIComponent(id));
  if (!d.ok) return app.innerHTML = '<div class="err">' + esc(d.error || "thread not found") + "</div>";
  const isMod = ME && ME.role === "mod";
  let html = '<div class="crumb"><a href="#/">Boards</a> › <a href="#/b/' + esc(d.board.slug) + '">' + esc(d.board.title) +
    "</a></div><h1>" + esc(d.thread.title) +
    (d.thread.deleted ? ' <span class="pill del">deleted</span>' : "") +
    (d.thread.locked ? ' <span class="pill">locked</span>' : "") + "</h1>";
  if (isMod) {
    const t = d.thread;
    html += '<div class="modbar">' +
      modBtn({ action: t.locked ? "unlock" : "lock", thread_id: t.id }, t.locked ? "Unlock" : "Lock") +
      modBtn({ action: t.pinned ? "unpin" : "pin", thread_id: t.id }, t.pinned ? "Unpin" : "Pin") +
      (t.deleted
        ? modBtn({ action: "restore_thread", thread_id: t.id }, "Restore thread")
        : modBtn({ action: "delete_thread", thread_id: t.id }, "Delete thread", "Delete this whole thread? (soft — restorable)")) +
      '<button class="btn ghost sm" id="modMove">Move…</button>' +
      "</div>";
  }
  if (d.thread.pid) html += '<div class="card" id="pidBox"><span class="pill pid">treasury proposal</span> ' +
    '<span class="addr">' + esc(d.thread.pid.slice(0, 18)) + '…</span><div class="tally" id="tally">loading tally…</div></div>';
  html += d.posts.map((p) => {
    let mod = "";
    if (isMod) {
      mod = '<span class="pmod">' +
        (p.deleted
          ? modBtn({ action: "restore_post", post_id: p.id }, "Restore")
          : modBtn({ action: "delete_post", post_id: p.id }, "Delete", "Delete this post? (soft — restorable)")) +
        (ME.address !== p.author
          ? modBtn({ action: "ban_user", address: p.author }, "Ban author",
                   "Ban " + short(p.author) + " from posting and kill their sessions? (unban via any of their posts)") +
            modBtn({ action: "unban_user", address: p.author }, "Unban")
          : "") +
        "</span>";
    }
    return '<div class="post' + (p.deleted ? " deleted" : "") + '"><div class="phead"><span>' +
      userLink(p.author, d.authors) + "</span>" + (p.deleted ? '<span class="pill del">deleted</span>' : "") +
      "<span>" + ago(p.created_at) + "</span>" + mod +
      "</div><div class=\"body\">" + fmt(p.body_md) + "</div></div>";
  }).join("");
  if (ME && ME.can_post && !d.thread.locked) {
    html += '<div class="card"><h2>Reply</h2><textarea id="rBody" placeholder="Write a reply…"></textarea>' +
      '<div class="row" style="margin-top:8px"><button class="btn" id="rPost">Reply</button></div><div class="err" id="rErr"></div></div>';
  } else if (d.thread.locked) {
    html += '<div class="note locked">This thread is locked.</div>';
  } else if (!ME) {
    html += '<div class="note">Sign in with your NADO wallet to reply.</div>';
  }
  app.innerHTML = html;
  bindModButtons();
  const mv = document.getElementById("modMove");
  if (mv) mv.onclick = async () => {
    const bl = await getJSON("/api/boards");
    const slugs = (bl.boards || []).map((b) => b.slug).join(", ");
    const slug = prompt("Move thread to board (" + slugs + "):");
    if (slug) modAction({ action: "move_thread", thread_id: d.thread.id, board: slug.trim() });
  };
  if (d.thread.pid) renderTally(d.thread.pid);
  const rb = document.getElementById("rPost");
  if (rb) rb.onclick = async () => {
    rb.disabled = true;
    const res = await postJSON("/api/reply", { thread_id: id, body: document.getElementById("rBody").value });
    if (res.ok) route();
    else { document.getElementById("rErr").textContent = res.error || "failed"; rb.disabled = false; }
  };
}

async function renderTally(pid) {
  try {
    if (!TREASURY) TREASURY = await getJSON("/api/treasury");
    const p = (TREASURY.proposals || []).find((x) => x.pid === pid);
    const el = document.getElementById("tally");
    if (!el) return;
    if (!p) { el.textContent = "proposal not currently open (executed, expired, or not yet seen)"; return; }
    el.textContent = `${p.approving_shares} approving share(s) · ${p.voters} voter(s) · status: ${p.status}` +
      ` — vote in the wallet's Quorum tab`;
  } catch (e) { /* non-fatal */ }
}

// ---- profile -------------------------------------------------------------------------------------
async function viewProfile(addr) {
  const d = await getJSON("/api/profile?address=" + encodeURIComponent(addr));
  if (!d.ok) return app.innerHTML = '<div class="err">' + esc(d.error || "profile not found") + "</div>";
  const p = d.profile;
  if (d.interface) INTERFACE = d.interface;
  const name = p.alias ? "@" + p.alias : short(p.address);
  const exUrl = INTERFACE + "/explore?q=" + encodeURIComponent(p.address);
  let html = '<div class="crumb"><a href="#/">Boards</a> › profile</div>' +
    "<h1>" + esc(name) +
    (p.role === "mod" ? ' <span class="pill mod">mod</span>' : "") +
    (p.role === "banned" ? ' <span class="pill del">banned</span>' : "") +
    (p.registered ? ' <span class="pill">registered</span>' : ' <span class="pill del">unregistered</span>') + "</h1>";
  html += '<div class="card profile">' +
    '<div class="prow"><span class="plabel">Address</span><span class="addr full">' + esc(p.address) + "</span></div>" +
    (p.aliases && p.aliases.length
      ? '<div class="prow"><span class="plabel">On-chain alias' + (p.aliases.length > 1 ? "es" : "") + "</span><span>" +
        p.aliases.map((n) => "@" + esc(n)).join(", ") + "</span></div>"
      : '<div class="prow"><span class="plabel">On-chain alias</span><span class="faint">none — register one in the wallet’s Aliases tab</span></div>') +
    '<div class="prow"><span class="plabel">Balance</span><span class="balnum">' + esc(fmtNado(p.balance)) + " NADO</span></div>" +
    '<div class="prow"><span class="plabel">Bonded</span><span class="balnum">' + esc(fmtNado(p.bonded)) + " NADO</span></div>" +
    '<div class="prow"><span class="plabel">Forum activity</span><span>' + p.threads + " thread(s) · " + p.posts + " post(s)</span></div>" +
    (p.first_seen
      ? '<div class="prow"><span class="plabel">Joined</span><span>' + ago(p.first_seen) + " · last seen " + ago(p.last_seen) + "</span></div>"
      : '<div class="prow"><span class="plabel">Joined</span><span class="faint">never signed in to the forum</span></div>') +
    '<div class="row mt"><a class="btn sm" href="' + esc(exUrl) + '" target="_blank" rel="noopener">Open in explorer ↗</a></div>' +
    "</div>";
  // own profile: pick which owned on-chain alias the forum displays (or force the plain address)
  if (ME && ME.address === p.address) {
    if (p.aliases && p.aliases.length) {
      const opts = ['<option value=""' + (!p.alias_pref ? " selected" : "") + ">auto — first alias</option>"]
        .concat(p.aliases.map((n) =>
          '<option value="' + esc(n) + '"' + (p.alias_pref === n ? " selected" : "") + ">@" + esc(n) + "</option>"))
        .concat(['<option value="-"' + (p.alias_pref === "-" ? " selected" : "") + ">show my address</option>"]);
      html += '<div class="card"><h2>Display name</h2>' +
        '<div class="row"><select id="aliasPick">' + opts.join("") + "</select>" +
        '<button class="btn sm" id="aliasSave">Save</button></div><div class="err" id="aliasErr"></div></div>';
    } else {
      html += '<div class="card"><h2>Display name</h2><div class="note">You own no on-chain aliases yet — ' +
        'register one in the wallet’s <a href="' + esc(INTERFACE + "/aliases") + '" target="_blank" rel="noopener">Aliases tab</a> ' +
        "(an ordinary signed tx), then come back and pick it here.</div></div>";
    }
  }
  // mod tools live here too — profile is the natural place to manage a user
  if (ME && ME.role === "mod" && ME.address !== p.address && !p.admin) {
    html += '<div class="modbar">' +
      (p.role === "banned"
        ? modBtn({ action: "unban_user", address: p.address }, "Unban")
        : modBtn({ action: "ban_user", address: p.address }, "Ban user",
                 "Ban " + name + " from posting and kill their sessions?")) +
      (ME.admin
        ? (p.role === "mod"
            ? modBtn({ action: "remove_mod", address: p.address }, "Remove mod")
            : modBtn({ action: "add_mod", address: p.address }, "Make mod", "Grant " + name + " the moderator role?"))
        : "") +
      "</div>";
  }
  app.innerHTML = html;
  bindModButtons();
  const asv = document.getElementById("aliasSave");
  if (asv) asv.onclick = async () => {
    asv.disabled = true;
    const res = await postJSON("/api/set_alias", { alias: document.getElementById("aliasPick").value });
    if (res.ok) {
      try { const m = await getJSON("/api/me"); ME = m.user; } catch (e) {}   // header shows the new name
      renderWho(); route();
    } else {
      document.getElementById("aliasErr").textContent = res.error || "failed";
      asv.disabled = false;
    }
  };
}

// ---- router --------------------------------------------------------------------------------------
function route() {
  const h = location.hash || "#/";
  app.innerHTML = '<div class="loading">Loading…</div>';
  if (h.startsWith("#/b/")) return viewBoard(decodeURIComponent(h.slice(4)));
  if (h.startsWith("#/t/")) return viewThread(decodeURIComponent(h.slice(4)));
  if (h.startsWith("#/u/")) return viewProfile(decodeURIComponent(h.slice(4)));
  return viewBoards();
}

async function init() {
  try { const m = await getJSON("/api/me"); ME = m.user; if (m.interface) INTERFACE = m.interface; } catch (e) { ME = null; }
  renderWho();
  window.addEventListener("hashchange", route);
  route();
}
init();
