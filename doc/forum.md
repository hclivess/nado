# NADO forum — design draft (`quorum.nadochain.com`)

**Status:** LIVE. Built and running — `forum/server.py` (aiohttp) serves it as `forum.service`, with wallet-signature login (`proof_sender` + ML-DSA `verify`).

**Brief (owner):** NADO needs its own forum — **written from scratch** (no phpBB/bbPress, no PHP), hosted at
**quorum.nadochain.com**. It should feel modern and be a natural home for community + governance discussion.

The differentiator, and the reason to build rather than adopt: **your identity is your NADO wallet.** No
passwords, no email, no CAPTCHA farms — you sign a challenge with your post-quantum ML-DSA key and your
`ndo…` address *is* your account. That ties the forum to the chain, gives it real Sybil resistance for free,
and is something no off-the-shelf forum can do.

---

## 1. Principles

- **From scratch, modern, no PHP.** Match the existing NADO stack so it reuses code and skills: a small
  **Python `aiohttp`** backend (same framework the node's API already uses) + a **vanilla-JS SPA** frontend
  (same style as `static/interface.js`, no framework, no build step). One dependency-light service.
- **Wallet-native identity (post-quantum).** Login = sign a server nonce with your ML-DSA key. Reuses
  `signatures.verify` server-side and the `nado-crypto.js` bundle client-side — the same crypto the wallet
  already ships. No secondary account system to breach.
- **Sybil-resistant by construction.** Optional posting gates keyed to *on-chain* status (registered miner /
  bonded staker), queried live from the node API — the same anti-Sybil the chain already enforces, so spam
  costs real work or stake, not a throwaway email.
- **Governance-first.** The subdomain is `quorum.*` for a reason: threads can bind to on-chain treasury
  proposals (`pid`), and bonded stakers get a verified badge — the forum is where a proposal is *debated*
  before the Quorum tab *votes* it.
- **Boring where it should be.** Content is off-chain in a normal DB (SQLite → Postgres at scale). A forum
  is infra, not consensus; don't over-decentralize it. (Optional integrity anchoring in §7.)

## 2. Stack (recommended)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3 + `aiohttp` | Same as the node API; reuses `signatures.verify`, `hashing`, `ops.address_ops`. |
| Storage | SQLite (WAL) → Postgres later | Zero-ops start; the schema (§5) ports cleanly. |
| Frontend | Vanilla ES-module SPA | Matches `interface.js`; no build pipeline; CSP-friendly. |
| Auth | ML-DSA challenge-response (§4) | Post-quantum, wallet-native, no passwords. |
| Sessions | HttpOnly signed cookie (server HMAC) | Simple, revocable; no JWT libon. |
| Deploy | systemd service behind nginx on `quorum.nadochain.com` | Same pattern as `nado.service` + the existing nginx. |

*(If the owner prefers a different language/runtime, the only NADO-specific dependency is ML-DSA
verification — trivially reproducible via `@noble/post-quantum` in Node/TS. The Python-native choice just
maximizes reuse.)*

## 3. Cross-origin note (important)

The wallet keys live in the interface's `localStorage` on **get.nadochain.com**; the forum on
**quorum.nadochain.com** is a *different origin* and cannot read them. Two clean options:

1. **Forum-local wallet (MVP).** The forum imports/generates its own NADO key (paste `keys.dat` / mnemonic,
   or "use a burner identity"), stored password-encrypted in the forum origin's `localStorage` — mirrors how
   the interface handles keys. Simplest; ship this first.
2. **Interface SSO (phase 2).** A "Sign in to forum" button *in the interface* signs the forum's challenge
   and redirects back with the signature (an OAuth-like handoff over a one-time code). Best UX; no key
   re-entry. Build after the MVP proves out.

## 4. Wallet-native auth — **prototyped and proven**

Flow (already validated end-to-end against the real ML-DSA stack — see `scratchpad/forum_auth_poc.py`):

1. `GET /api/nonce?address=ndo…` → server stores `{address, nonce, issued}` (TTL ~5 min) and returns it.
2. Client computes `msg = blake2b_hash(["nado-forum-login", address, nonce, issued])` and signs
   `unhex(msg)` with its ML-DSA private key.
3. `POST /api/login {address, public_key, signature}` → server:
   - re-derives `msg` from the stored challenge (rejects if expired),
   - `proof_sender(public_key, address)` — the pubkey must hash to the claimed address,
   - `verify(signature, unhex(msg), public_key)` — the ML-DSA signature must check out,
   - on success, issues a session cookie bound to `address`.

Verified rejections: **imposter address**, **wrong pubkey**, **tampered nonce**, **expired challenge** —
all correctly denied. The domain tag `"nado-forum-login"` makes a login signature unusable as a transaction
signature and vice-versa (no cross-protocol replay).

## 5. Data model (SQLite, first cut)

```
users     (address PK, public_key, handle, created_at, last_seen, role)         -- role: user|mod, mods bootstrapped by address list
boards    (id PK, slug, title, description, position, post_min_role)            -- post_min_role gates who can post
threads   (id PK, board_id FK, author, title, created_at, bumped_at, locked, pinned, pid)  -- pid: optional treasury proposal link
posts     (id PK, thread_id FK, author, body_md, created_at, edited_at, deleted)
reactions (post_id FK, address, kind, PRIMARY KEY(post_id,address,kind))
sessions  (token PK, address, created_at, expires_at)                           -- or stateless signed cookie
reports   (id PK, post_id FK, reporter, reason, created_at, resolved)           -- community moderation queue
```

Content is **Markdown, rendered server- or client-side with strict escaping** (reuse the interface's
`escapeHtml` discipline; the CSP already blocks inline script). No HTML passthrough, no image hotlinking
beyond `data:`/same-origin (keeps the H-5-style XSS surface closed).

## 6. Anti-spam / Sybil (the wallet-identity payoff)

- **Posting gates per board** (`post_min_role` / on-chain check): e.g. an "Announcements" board is
  mod-only; "Governance" requires a **bonded** address; "General" requires a **registered** address (has
  done the one-time registration PoW). Read is public. The node API already exposes account state to check.
- **Rate limits** keyed to `address` (not IP): N posts / minute, cooldown on new accounts.
- **No email, no CAPTCHA** — a spammer needs a registered/bonded on-chain identity, which costs sequential
  PoW or stake. That is the whole point of a wallet-native forum.

## 7. Moderation (minimal-intervention, on-brand)

- **Bootstrapped mods** (an address allow-list in config) can lock/pin/delete + resolve reports.
- **Community reports** queue posts for review; a threshold of distinct bonded reporters can auto-hide
  pending review (stake-weighted, echoing the chain's quorum ethos).
- **Transparency:** deletions are soft (tombstoned), and (optional, phase 2) each post's
  `blake2b(body, author, ts)` can be periodically Merkle-anchored via a `blob` tx so the record is
  tamper-evident without putting content on-chain. Nice-to-have, not MVP.

## 8. Governance integration (why it's `quorum.*`)

- A thread may carry a `pid` (treasury proposal id). The forum shows the **live tally** (pulled from the
  node's `/treasury_status`) inline, and a **"Discuss"** link from the Quorum tab deep-links to the thread —
  debate off-chain, vote on-chain, one identity across both.
- Bonded stakers render with a **verified badge + weight**, so governance threads show *who actually has
  skin in the game*.

## 9. Deployment

- New nginx server block for `quorum.nadochain.com` (mirrors the `get.nadochain.com` proxy): TLS via the
  existing Let's Encrypt/Cloudflare setup, reverse-proxy to the forum `aiohttp` service on a local port,
  static assets served directly.
- `forum.service` systemd unit (Restart=always), same pattern as `nado.service`.
- Certbot: add `-d quorum.nadochain.com` to the cert.

## 10. MVP scope (what I'll build first)

1. `aiohttp` service: nonce/login (§4), boards/threads/posts CRUD, session cookies, address rate-limits.
2. SQLite schema (§5) + a seed of a few boards.
3. Vanilla-JS SPA: board list → thread list → thread view, wallet login (forum-local wallet, §3-1), compose
   + reply with escaped Markdown.
4. nginx block + `forum.service` + README.
5. On-chain badge (registered/bonded) via the node API.

Deferred to phase 2: interface SSO, reactions, community-report auto-hide, Merkle anchoring, Postgres,
search, notifications.

## 11. Open decisions for the owner

1. **Stack confirm:** Python `aiohttp` + vanilla JS (recommended, max reuse) vs a different runtime.
2. **Login model:** forum-local wallet first (fast) vs wait for interface SSO (nicer, slower).
3. **Default posting gate:** open-to-any-registered vs bonded-only for launch (spam vs inclusivity).
4. **Moderation seed:** which addresses are the initial mods.
5. **Governance coupling depth:** just `pid` links, or full inline tally + vote deep-links from day one.

### Bottom line

Build it from scratch as a small `aiohttp` + vanilla-JS service on `quorum.nadochain.com`, with **NADO
wallet login** as the headline feature — already proven to work with the real post-quantum crypto. It reuses
the node's stack end-to-end, gets Sybil resistance from on-chain identity, and doubles as the debate layer
for treasury governance. Give me the go-ahead on §11 and I'll stand up the MVP (§10).
