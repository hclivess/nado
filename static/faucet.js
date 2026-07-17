// faucet.js — client SDK for the faucet system contract (doc/faucet.md). One shared implementation:
// reads the on-chain registry (grant / window budget / PoW target per enrolled game), grinds the claim
// PoW in chunked async steps (alghash(callerDigest, gameIdx, nonce) < target — the same hash the VM
// verifies in ONE op), and submits claim() against the fixed-name "faucet" contract. Enrolled game pages
// call faucetAttach(dapp, slug, el) once; the bar renders only when it can actually help: signed in,
// enrolled + granting, budget left, not yet claimed here, and the player is broke (below the grant).
import { blake2bHash } from "./nadotx.js";
import { $, algHashn, ALG_P, base, notify, rawToNado } from "./nadodapp.js";

export const FAUCET_CID = "faucet";
// idx ↔ game registry (mirror of the operator's set_game enrollment — keep in lockstep)
export const FAUCET_GAMES = { dice: 0, scrapline: 1, stormhold: 2, farkle: 3, blackjack: 4, battleship: 5, slots: 6, mines: 7 };

const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("sdk." + k, d, v) : d;
// the VM's address digest (runtimes.zkvm_addr_digest): blake2b(["zkvmaddr", addr]) reduced into the field
export const addrDigest = (addr) => BigInt("0x" + blake2bHash(["zkvmaddr", addr])) % ALG_P();

let _sto = { t: 0, maps: null };
async function faucetMaps() {
  if (Date.now() - _sto.t < 30_000 && _sto.maps) return _sto.maps;
  try {
    const r = await (await fetch(base() + "/exec/contract?ns=default&cid=" + FAUCET_CID + "&provisional=1", { cache: "no-store" })).json();
    _sto = { t: Date.now(), maps: r.storage || {} };
  } catch { _sto = { t: Date.now(), maps: null }; }
  return _sto.maps;
}
async function faucetBalance() {
  try {
    const r = await (await fetch(base() + "/exec/bridge?ns=default&provisional=1", { cache: "no-store" })).json();
    return BigInt((r.balances || {})[FAUCET_CID] || 0);
  } catch { return 0n; }
}

export async function faucetInfo(slug) {
  const idx = FAUCET_GAMES[slug];
  if (idx == null) return null;
  const m = await faucetMaps();
  if (!m) return null;
  const grant = BigInt(Math.round((m.ggrant || {})[idx] || 0));
  if (grant <= 0n) return null;                                  // not enrolled / paused
  const cap = Number((m.gcap || {})[idx] || 0);
  const pow = BigInt(Math.round((m.gpow || {})[idx] || 0));
  return { idx, grant, cap, pow };
}

// grindClaim: chunked main-thread PoW grind (yields every chunk so the UI stays live). Expected work is
// P/target hashes; the operator tunes targets so a browser lands in seconds-to-a-minute.
export async function grindClaim(addr, idx, pow, onProgress) {
  const d = addrDigest(addr), I = BigInt(idx);
  let nonce = BigInt(Math.floor(Math.random() * 2 ** 40));       // random start — restarts don't redo work
  for (let chunk = 0; ; chunk++) {
    for (let i = 0; i < 4000; i++, nonce++) {
      if (algHashn([d, I, nonce]) < pow) return nonce;
    }
    if (onProgress) onProgress(chunk * 4000);
    await new Promise((r) => setTimeout(r, 0));
  }
}

// faucetAttach(dapp, slug): show a claim banner when it can help. SDK-OWNED PLACEMENT — the SDK inserts
// its own banner card at a consistent spot (top of the page, right under the header) in every game, so no
// game hand-places it. IDEMPOTENT + STABLE — the DOM is rebuilt ONLY when the show/hide decision actually
// flips (never every poll), a mid-grind bar is never wiped, a transient balance-fetch failure keeps the
// current state instead of blinking the bar off, and the empty container is display:none (no ghost card).
export function faucetAttach(dapp, slug, elArg) {
  // consistent placement: a dedicated banner card as the first content under <header> inside .wrap.
  let el = elArg || document.getElementById("faucetBar");
  if (!el) {
    el = document.createElement("div");
    el.id = "faucetBar"; el.className = "card";
    const wrap = document.querySelector(".wrap") || document.body;
    const header = wrap.querySelector("header");
    if (header && header.nextSibling) wrap.insertBefore(el, header.nextSibling);
    else wrap.insertBefore(el, wrap.firstChild);
  }
  el.style.display = "none";                                   // hidden until we decide to show it
  const LSK = "nado_faucet_claimed_" + slug;
  let busy = false, shown = false, info = null;
  const build = () => {
    el.innerHTML = '<div class="dp">🚰 ' + T("fctOffer", "New here? Claim {amt} NADO of airdrop play for this game — your browser proves you're human with ~a minute of hashing.", { amt: rawToNado(info.grant) }) + "</div>";
    const b = document.createElement("button"); b.className = "primary";
    b.textContent = T("fctClaim", "🪂 Claim {amt} NADO airdrop play", { amt: rawToNado(info.grant) });
    b.onclick = async () => {
      if (busy) return;
      busy = true; b.disabled = true;
      try {
        const nonce = await grindClaim(dapp.me, info.idx, info.pow,
          (h) => { b.textContent = T("fctGrinding", "⛏ proving… {n}k hashes", { n: Math.round(h / 1000) }); });
        b.textContent = T("fctSubmitting", "✓ proof found — claiming…");
        dapp.call("claim", [info.idx, nonce], null,
          T("fctCallLabel", "claim {amt} NADO airdrop play ({slug})", { amt: rawToNado(info.grant), slug }),
          { phase: "faucet" }, { cid: FAUCET_CID });
        try { localStorage.setItem(LSK, dapp.me); } catch {}
        notify(T("fctSent", "Claim submitted — your airdrop lands with the next block."));
      } finally { busy = false; b.disabled = false; }
    };
    el.appendChild(b);
  };
  async function refresh() {
    if (busy) return;                                          // never disturb a bar the user is grinding
    // decide want=show without touching the DOM
    let want = false;
    if (dapp.me) {
      let claimedHere = null;
      try { claimedHere = localStorage.getItem(LSK); } catch {}
      if (claimedHere !== dapp.me) {
        info = await faucetInfo(slug);
        if (info && dapp.exec < info.grant) {
          const bal = await faucetBalance();
          want = bal >= info.grant;
        }
      }
    }
    if (want === shown) return;                                // NO-OP unless the decision actually flipped
    shown = want;
    if (want) { build(); el.style.display = ""; }
    else { el.innerHTML = ""; el.style.display = "none"; }     // hide the whole card — no empty ghost box
  }
  refresh();
  setInterval(refresh, 20_000);
  return refresh;
}
