// cards.js — shared CARD primitives for NADO card games (blackjack today; baccarat/poker-family later).
// One convention, one renderer, one chain-draw formula, so every card game shows the same deck and can
// never drift from what its contract computes.
//
//   card index c ∈ 0..51 :  rank = c % 13 (0="2" … 8="10", 9=J, 10=Q, 11=K, 12=A)
//                           suit = c // 13 (0=♠ 1=♥ 2=♦ 3=♣) — hearts/diamonds render red
//   chain draw (multi-deck / draws independent, the only sound dealer-less scheme — see hold'em):
//           card_i = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + salt + i ) % 52
//   which is exactly the VM's HASH over ints (blake2bHash of a BigInt canonicalizes to bare digits).
import { blake2bHash } from "./nadotx.js";

export const RANK_NAMES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
export const SUITS = ["♠", "♥", "♦", "♣"];
const H = (v) => BigInt("0x" + blake2bHash(v));

// chainCards(bh0Hex, bh1Hex, salt, n): the i-th card of a bound draw — null until both hashes exist.
// salt disambiguates draws sharing a height (seat id scheme is the game's contract's business).
export function chainCards(bh0, bh1, salt, n) {
  if (!bh0 || !bh1) return null;
  const q = BigInt("0x" + bh0) + BigInt("0x" + bh1) + BigInt(salt);
  return Array.from({ length: n }, (_, i) => Number(H(q + BigInt(i)) % 52n));
}

// cardHTML(c, big): the standard card tile (same classes as poker.js: .card/.red/.big/.back).
// c == null renders a face-down back.
export function cardHTML(c, big) {
  if (c == null) return '<div class="card back' + (big ? " big" : "") + '"></div>';
  const r = RANK_NAMES[c % 13], s = Math.floor(c / 13), red = (s === 1 || s === 2);
  return '<div class="card' + (red ? " red" : "") + (big ? " big" : "") + '">' + r + '<span class="suit">' + SUITS[s] + "</span></div>";
}

// injectCardCSS(): the one shared stylesheet for card tiles (poker.html predates this and keeps its own).
let _cardCssOn = false;
export function injectCardCSS() {
  if (_cardCssOn || typeof document === "undefined") return;
  _cardCssOn = true;
  const s = document.createElement("style");
  s.textContent =
    ".card{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;width:46px;height:64px;border-radius:8px;" +
    "background:#f4f6f8;color:#111826;font-weight:800;font-size:15px;border:1px solid #c9d2dc;box-shadow:0 3px 10px rgba(0,0,0,.35);margin:2px}" +
    ".card .suit{font-size:19px;line-height:1}" +
    ".card.red{color:#c22a3a}" +
    ".card.big{width:56px;height:78px;font-size:18px}.card.big .suit{font-size:24px}" +
    ".card.back{background:repeating-linear-gradient(45deg,#134e42,#134e42 6px,#0d3a31 6px,#0d3a31 12px);border-color:#0a2d26}";
  document.head.appendChild(s);
}

// ---- blackjack values ------------------------------------------------------------------------------
// bjCardValue(c): the HARD value (ace counts 1 — softness is a hand property, not a card property).
export const bjCardValue = (c) => { const r = c % 13; return r === 12 ? 1 : r >= 9 ? 10 : r + 2; };
// bjTotal(cards): best blackjack total — {total, soft, bust, natural}. An ace counts 11 when it fits.
export function bjTotal(cards) {
  let hard = 0, aces = 0;
  for (const c of cards) { hard += bjCardValue(c); if (c % 13 === 12) aces++; }
  const soft = aces > 0 && hard + 10 <= 21;
  const total = soft ? hard + 10 : hard;
  return { total, soft, bust: total > 21, natural: cards.length === 2 && total === 21 };
}
