# NADO messaging — off-chain, end-to-end-encrypted, free

**Status:** LIVE — implemented and running (message pool + gossip: `ops/message_pool.py`, node endpoints;
E2E crypto: ML-KEM-768 encapsulation + blake2b-CTR AEAD + ML-DSA-44 signatures + hashcash PoW; wallet UI with
local history; tests: `tests/test_message_pool*.py`, `tests/test_msgkey.py`). This document is the design it
was built from; sections read as design language but describe the shipped system.

**Brief (owner).** Address-to-address messaging, **off-chain**. Nodes keep a shared **message pool/stack**
gossiped between them but **never written to a block**. **100% encrypted** (nodes can't read it), **free**
(no fees), **alias-aware**, with **message history kept locally** by the client.

The design goal in one line: *a Signal-grade, post-quantum DM layer that rides NADO's existing P2P gossip
and wallet identity, adds nothing to consensus, and costs nothing to send.*

---

## 1. Why off-chain (and what that buys)

Putting messages in blocks would make them **permanent, public-metadata, fee-bearing, and a bloat
vector** — the opposite of what a DM wants. Off-chain gives us:

- **Free** — no block space consumed, so no fee needed.
- **Ephemeral** — messages live in a TTL pool and disappear; the durable copy is the *recipient's local
  history*, not a global ledger.
- **Private** — content is end-to-end encrypted; the chain records nothing.
- **Zero consensus risk** — a messaging bug can never fork the chain (same firewall as the exec layer).

The trade-off vs on-chain: **no global durability or ordering guarantee**. A message is delivered
best-effort while it lives in the pool; if the recipient never fetches it before TTL, it's gone. That's the
right model for chat (store-and-forward), not for value.

## 2. Identity & keys — the one subtlety

A NADO address is an **ML-DSA-44 signing** key. ML-DSA **cannot encrypt** — it only signs. So to encrypt
*to* an address we need separate **post-quantum KEM** keys. Every KEM key is **ML-KEM-768** (FIPS 203 /
Kyber) and every long-term key is **derived deterministically from the wallet seed** (same HD trick as
accounts), so the one recovery phrase restores your whole messaging identity — no extra backup.

Each user publishes a **prekey bundle** (for the async session handshake, §3.1) as a **signed off-chain
announcement** gossiped in the message pool:

```
bundle = {
  addr,
  ik_pub,          // IDENTITY KEM key   — long-term, seed-derived
  spk_pub, spk_ts, // SIGNED PREKEY      — medium-term, rotated periodically
  opk_pub[],       // ONE-TIME PREKEYS   — a small pool, each used once (optional but recommended)
  sig              // ML-DSA sig over the whole bundle, verifiable via proof_sender + verify
}
```

Anyone can verify the bundle is really from `addr` with the node's **existing** primitives (`proof_sender`
+ `verify`) — no on-chain registration; the signed announcement *is* the directory (newest valid wins,
TOFU-style, with the ML-DSA signature preventing key substitution). Everything is post-quantum: **ML-DSA**
(auth) + **ML-KEM** (confidentiality) + a **hash-based AEAD** — no EC/pairing crypto anywhere.

> **Why not X25519?** Signal's classic X3DH + Double Ratchet lean on X25519 DH, which a quantum computer
> breaks. NADO's rule is *no EC crypto*, so we replace every DH with an **ML-KEM encapsulation** (§3). This
> is the same direction as Signal's PQXDH, taken all the way to a **pure-PQ** ratchet. (A hybrid
> X25519+ML-KEM would be marginally more battle-tested but violates the no-EC principle; pure-KEM is the
> NADO-consistent choice.)

## 3. Encryption — a post-quantum Double Ratchet

Confidentiality is a **KEM-based Double Ratchet** (a fully-PQ analog of Signal's), giving **forward secrecy**
(a stolen key can't decrypt past messages) **and post-compromise security / break-in recovery** (the session
*heals* — a one-time key theft stops decrypting future messages after the next ratchet step). Every DH in the
Signal design is replaced by an **ML-KEM encapsulation**.

### 3.1 Session setup — asynchronous "KEM-X3DH"

Works even when the recipient is offline (it fetches their prekey bundle from the pool). To open a session,
the initiator Alice pulls Bob's bundle (`ik`, `spk`, one `opk`) and does **three encapsulations**:

```
(ss1, ct1) = ML_KEM.encap(bob.ik_pub)          # binds to Bob's long-term identity
(ss2, ct2) = ML_KEM.encap(bob.spk_pub)          # forward secrecy from the rotating signed prekey
(ss3, ct3) = ML_KEM.encap(bob.opk_pub)          # one-time: post-compromise start (optional if pool empty)
SK   = HKDF(blake2b, ss1 ‖ ss2 ‖ ss3)           # the initial shared session secret (root key seed)
```

Alice sends `{ct1, ct2, ct3, her identity + first ratchet public key}` in the first envelope; Bob
decapsulates with his private `ik/spk/opk` to derive the same `SK`. The **signed prekey** is ML-DSA-signed
in the bundle (authenticity), and the whole first message is ML-DSA-signed by Alice (sender auth). One-time
prekeys are consumed once; when the pool is exhausted the session still forms from `ik+spk` (slightly weaker
initial PCS until the first ratchet).

### 3.2 The Double Ratchet (KEM ratchet + symmetric chains) — **BUILT** (`static/messaging.js`, envelope `v: 2`)

Signal's state machine with every DH replaced by an ML-KEM-768 encapsulation. Because a KEM is one-sided, the
party that **starts a new sending chain** encapsulates to the peer's latest ratchet public key and ships the
ciphertext `c` in every header of that chain (where Signal ships its DH pub), together with its **own freshly
generated ratchet public key `k`** for the peer to encapsulate to in turn.

- **Root / asymmetric ratchet.** Receiving a header whose `k` is new = a ratchet step: `ss = decap(c, ourRatchetSec)`,
  `(rk', ckr) = KDF_rk(rk, ss)`, start a new receiving chain, and mark our sending chain stale so our **next send
  generates a fresh keypair** and encapsulates to `k`. That fresh keypair is what delivers **post-compromise
  security**: a leaked state stops decrypting as soon as the leaked party has sent on a fresh chain (one round-trip,
  exactly Signal's healing bound — the test `tests/test_msg_ratchet.mjs` pins both the "not healed yet" and the
  "healed" halves).
- **Symmetric ratchet.** `(ck', mk) = KDF_ck(ck)` per message; `mk` is used once and deleted — **forward secrecy**
  (a session snapshot cannot re-decrypt anything already read, including the pool's stored copy of it).
- **Session setup ("KEM-X3DH", identity key only).** The initiator encapsulates `i` to the recipient's **on-chain
  identity KEM key** (`msgkey` tx) → `ss0 → rk0`; the first chain then encapsulates to the identity key again, so the
  session is normal-ratchet from message #1. `i` rides along on every message **until the peer has replied** (a lost
  first message must not strand the session). There are no one-time prekeys: the PCS start is weaker than with an
  `opk` exactly until the first reply, then identical.
- **Out-of-order / offline.** Headers carry `pn`/`n`; a receiver caches up to `MAX_SKIP = 200` skipped message keys
  per gap (600 per session, FIFO), so late messages from a previous chain still open. Every receive works on a
  copy of the session and commits only on a successful AEAD open — a bogus envelope never corrupts state.
- **Crossed first messages** (both sides initiate before hearing the other) leave two valid sessions per peer; the
  sender uses the one the peer most recently spoke on, and at most 3 are kept.
- **Recipient hiding with a ratchet.** The tag can no longer be `H(ss)` of a per-message decap. Instead
  `tag = H_dk(nonce)` with `dk = KDF(rk0, 'detect')`, a **session-constant detection key**: the receiver hashes every
  fetched nonce under each session's `dk` (cheap, no KEM) and only trial-decapsulates `i` for envelopes no session
  claims. Tags stay unlinkable to the node (fresh nonce per message); a leaked `dk` lets an attacker *detect* a
  conversation's messages but not read them.
- **KDFs.** `KDF_rk(rk, ss) = blake2b(key=rk, 'nado-msg-rk' ‖ ss, 64) → rk' ‖ ck`;
  `KDF_ck(ck) = blake2b(key=ck, 'nado-msg-ck', 32), blake2b(key=ck, 'nado-msg-mk', 32)`. The AEAD is the v1
  blake2b-CTR encrypt-then-MAC under `mk`, with the **header as associated data**.
- **Header** (base64 in `hdr`, opaque to the node): `flags(1) ‖ pn(4) ‖ n(4) ‖ k(1184) ‖ c(1088) ‖ [i(1088)]`.
  Envelope overhead is ~10.8 KB per chain message / ~12.3 KB per session-init against the pool's 16 KiB cap, which
  leaves ~2.5 KB / ~1.9 KB of body; `ratchetSeal` refuses an oversized body **before** advancing the chain, and
  the compose box caps at `MSG_BODY_MAX = 1800` chars.
- **Storage / honest limits.** Sessions persist in the wallet's `localStorage` beside the history (this device
  only, same at-rest model as the history). Wiping it strands live sessions: the peer's messages cannot be read
  until *they* receive something from us on a new session (our next send re-initialises; `sessionsForget(peer)`
  forces it). v1 envelopes are still **received** (legacy wallets), never sent.

### 3.3 The wire envelope

```
envelope = {
  v, sender, public_key,   // v=1 legacy / v=2 ratchet; NO `to` (recipient hidden, §9.1); sender gates registration (§6)
  hdr,                // v2: base64 ratchet header (k, c, pn, n, + init ct while unanswered); v1: hex KEM ct
  nonce, ct,          // AEAD (blake2b-AEAD or ChaCha20-Poly1305) of the body under this message's key mk
  ts, pow,            // timestamp + anti-spam proof-of-work (§6)
  sig                 // ML-DSA sig over blake2b(everything above) — sender auth + integrity
}
```

Only Bob can advance the ratchet and derive `mk` to decrypt. Nodes store/forward the envelope as **opaque
bytes** — they verify `sig`, `pow`, and the registered-sender gate, but **never read `hdr`/`ct`**. Session
state (root key, chain keys, ratchet keys, skipped-key cache) lives **locally**, password-encrypted with the
wallet, and is re-derivable per conversation from stored history.

*Complexity note:* ML-KEM keys/ciphertexts are ~1 KB (vs 32 B for X25519), so a ratchet step adds ~1–2 KB —
fine for chat. The ratchet + skipped-key logic is the one genuinely intricate piece; it should be built
against the standard Double-Ratchet test vectors (adapted to ML-KEM) and fuzzed for out-of-order delivery.

## 4. The message pool (off-chain, gossiped, ephemeral)

Mirror the existing `transaction_pool`, but **never drain into a block**:

- Each node keeps a **message pool**: a map `msg_id → envelope` (`msg_id = blake2b(envelope)`), bounded
  **primarily by bytes** — `MSG_POOL_MAX_BYTES` = 5 MiB; when an insert crosses it the oldest-accepted
  envelopes are **rotated out** (ring buffer by arrival order) until it fits. A long **TTL backstop**
  (`MSG_TTL_SECONDS` = 90 days) reaps anything rotation never reached and bounds how old an accepted
  `ts` may be. So an undelivered message lives as long as the node's churn allows: on a quiet network that
  is weeks to months; under a flood the pool degrades to "old messages drop early," never OOM.
- **Gossip:** on receiving a valid new envelope (good `sig`, good `pow`, within size/rate limits), a node
  adds it and relays it to peers — the same anti-loop set-reconciliation the tx mempool uses. So a message
  propagates to the whole network within a few gossip rounds, independent of whether the recipient is
  online.
- **Store-and-forward:** the pool *is* the inbox-in-transit. A phone that was asleep fetches its messages
  from whatever node it reconnects to. Delivery is decoupled from the sender being online.
- **Not consensus:** the pool is never hashed into a block, never affects state_root, never validated by
  consensus. A node with a corrupt/empty message pool is still a fully valid node.

## 5. Delivery, status, and the "not delivered" notification

- **Recipient polls by tag, not by address:** because v1 hides the recipient (§9.1), the client pulls the
  pool's **detection tags** (`GET /tags?since=<cursor>`), matches its own active-session + first-contact
  tags, then fetches only its own bodies (`GET /message?id=<msg_id>`), decrypts, dedups by `msg_id`, and
  advances its cursor.
- **Delivery ACK:** when the recipient fetches + decrypts a message, its client returns a tiny **signed,
  encrypted delivery ACK** — itself an ordinary detection-tag-routed envelope back to the original sender
  (so confirming delivery adds **no** metadata channel). On ACK a node may also drop the original early
  (TTL reaps it otherwise).

### 5.1 Sender-visible delivery status

Every sent message carries a status the **sender** sees, ending in ✓ delivered or a **"not delivered"**
notification:

| status | meaning |
|---|---|
| **Sending** | being submitted to a node |
| **Sent** | accepted into the pool (gossiping; waiting for the recipient to come online) |
| **Delivered ✓** | the recipient fetched + decrypted it and returned a delivery ACK |
| **Not delivered ✕** | terminal failure (below), surfaced to the sender |

**"Not delivered" fires in two cases:**

1. **Immediate (at send time):** a node rejects submission (sender **not registered**, rate-limited, or
   oversize), **or** the recipient has **no published prekey bundle** (no messaging key to encrypt to). The
   client shows "not delivered" instantly, with the reason.
2. **Timeout:** the message reached the pool but **no delivery ACK arrived** before it was rotated out
   (or hit the 90-day TTL backstop) — the recipient never came online to fetch it. The client has no view
   of a remote pool's churn, so it uses a fixed client-side patience window (7 days) to flip the message
   to "not delivered."

Implementation: the sender's client keeps a local **pending table** `{msg_id → sent_ts, status}`, watches
its own inbox for the matching delivery ACK, and on each open/poll expires any still-pending message older
than its patience window to **not delivered**. Because the layer is store-and-forward and best-effort, "not delivered"
means precisely **"no delivery confirmation within 7 days"** — the UI should word it that way (e.g. *"Not
delivered — hasn't come online in 7 days"*) and offer **Resend** (a fresh ratchet message). Read receipts /
typing indicators are further encrypted control-message types — out of scope for v1.

## 6. Free — but not costless (anti-spam)

"Free" means **no protocol fee**, not **no cost to spam**. Since anyone can flood a free pool, layer the
same cheap-identity defenses the chain already uses:

1. **Registered-sender gate (REQUIRED).** A node accepts an envelope only from an on-chain **registered**
   address (it checks `from` via `get_account`, exactly like the forum's posting gate) — so `from` cannot be
   sealed/blank in v1 (that rules out sealed-sender until Phase-2). This ties every sender to the one-time
   registration **sequential PoSW** + the registration-rate difficulty + IP caps: free to *use*, expensive
   to *Sybil*. This is the primary spam wall; the PoW and rate limits below are secondary.
2. **Per-message proof-of-work (`pow`):** a small hashcash bound to `(from, to, ct, ts)` — negligible for a
   human sending a few messages, painful for a spammer sending millions. Tunable difficulty; raise it
   adaptively if the pool floods.
3. **Rate limits:** per-`from` and per-source-IP caps (reuse the forum's limiter); per-`to` inbox caps so
   one victim can't be buried.
4. **Size + pool caps:** max envelope size (16 KiB), max pool bytes (5 MiB, oldest rotated out first),
   TTL backstop — a hard memory bound so a flood degrades to "old messages drop early," never OOM.

None of these charge a fee; together they make spam **rate-limited and PoW-priced**, consistent with
NADO's "cost identities, not usage" philosophy.

## 7. Aliases

The sender addresses a message to a **raw address or an alias**. The client resolves the alias to its owner
address (the wallet's existing `resolveAlias` / on-chain alias registry) **before** encrypting — so the
envelope always carries the resolved `to` address, and encryption targets the owner's KEM key. The UI can
show the alias; the wire carries the address.

## 8. History (local)

The pool is ephemeral; **the durable record is the recipient's (and sender's) local store**:

- Decrypted messages are kept in the client's **IndexedDB/localStorage**, organized by conversation
  (peer address/alias), with the wallet's existing password-encryption applied at rest.
- Because history is local, it's **private by default** and **portable with the seed** (you can re-derive
  your KEM key on a new device and re-fetch anything still in the pool, but old delivered history lives on
  the device that received it — like Signal without a cloud backup). An optional **encrypted export/import**
  (a signed, self-encrypted blob) lets a user move history between devices.

## 9. What a node can see (honest limits)

- **Content:** never — end-to-end encrypted (Double Ratchet).
- **Recipient:** **hidden in v1 via detection tags** (§9.1). The envelope carries **no cleartext `to`** — a
  node can't tell who a message is for.
- **Sender:** the `from` address **is** visible — the required registered-sender gate (§6) needs it. So v1
  hides *what* you say **and who you're talking to**, but the node still sees that *a* registered address
  sent *a* message (not to whom).
- **Timing/size:** visible; correlation attacks over timing are out of scope for v1 (a mixnet/cover-traffic
  layer is Phase-2).

### 9.1 Recipient detection tags (how the recipient is hidden without breaking delivery)

Dropping the cleartext `to` means a node can't route by recipient — so each envelope carries a compact
**detection tag** that only the recipient recognizes and the node cannot link to an identity:

- **Established sessions (common case):** the ratchet handshake also derives a shared **detection key**;
  each message is stamped `T = blake2b(["nado-msg-detect", detect_key, msg_#])`. The recipient computes the
  next-expected tags for its **active sessions** and matches — cheap symmetric lookups, no decryption. The
  node sees only an opaque, unlinkable `T`.
- **First contact (no session yet):** the initial message uses either a **trial-decapsulation** against the
  recipient's identity KEM key (~1 KEM op per candidate — first-contacts are rare) or a **fuzzy message
  detection (FMD)** tag against a published detection key, which lets a node pre-filter to a *tunable
  anonymity set* without learning the exact recipient.
- **Delivery:** `GET /tags?since=<cursor>` returns the (tiny) tags in the pool; the client matches its own
  and `GET /message?id=<msg_id>` fetches **only its own bodies**. Bandwidth scales with total message
  *count* (tag scan), not your traffic, and is bounded by the TTL pool. Nodes gossip envelopes keyed by
  `msg_id`, indexed by tag prefix — never by recipient identity.

### 9.2 Scaling recipient-hiding (the honest tradeoff)

The **encryption** side scales trivially (ML-KEM is per-message and fast). The cost of hiding the recipient
is on **retrieval**: with no cleartext recipient, a client must **scan tags** to find its own, and that scan
grows with **total network traffic, not the client's own**. Pool ≈ (msgs/day network-wide) × 7-day TTL; at
~24 B/tag a 1M-msg/day network is ~24 MB/day of tag-pulls per client, a 10M/day network ~240 MB/day — too
heavy for a phone at high volume. **Full recipient-unlinkability (one global scan) does not scale.**

The knob is **FMD bucketing**: partition the pool into **K buckets** by a coarse recipient-derived prefix;
a client scans only its bucket → bandwidth **/K**, leaking `log₂K` bits (the node learns you're one of ~N
possible recipients — a **tunable anonymity set**). This slides between the extremes:

| mode | node learns | client bandwidth | scales |
|---|---|---|---|
| cleartext `to` | exact recipient | one message | ✅ perfectly |
| **FMD bucket (tunable)** | 1-of-N anonymity set | pool / K | ✅ (choose K) |
| full-scan tags | nothing | whole pool | ❌ at high volume |
| OMR / PIR | nothing | one message | ✅ but heavy server crypto (future) |

**Plan:** v1 ships **full-scan detection tags** (fine at betanet volume). As traffic grows, enable **FMD
bucketing** with K auto-sized to the pool, keeping client bandwidth bounded against a real recipient
anonymity set; keep **cleartext-`to` as an opt-out** for users who don't want the scan cost. **OMR/PIR**
(private *and* O(1) bandwidth) is the eventual upgrade, deferred as too compute-heavy today.

**Sender-sealing (hiding `from` too) is Phase-2:** it conflicts with the registration gate, so it needs an
**anonymous credential** — the sender proves "I am *some* registered identity" (ring signature / credential
over the registered set) without revealing which — plus a mixnet for timing. Deferred.

## 10. What to build (deltas)

1. **Browser crypto:** add **ML-KEM-768** to the vendor bundle (`@noble/post-quantum` already exports
   `ml_kem768`; the current `nado-crypto.js` bundles only ML-DSA + blake2b). Derive the KEM key from the
   seed; implement encapsulate/decapsulate + the AEAD seal/open.
2. **Node message pool** (`ops/message_pool.py` + memserver): store/gossip/TTL/anti-spam, mirroring
   `transaction_pool` but never block-bound. Endpoints: `POST /message`, `GET /messages?to=`,
   `GET /msg_key?addr=` (announcement lookup), `POST /msg_key` (publish announcement), gossip wiring.
   **No new node crypto** — reuse `signatures.verify` (ML-DSA-44, via `proof_sender`) for `sig` and the PoW check.
3. **Client "Messages" tab** in the interface (like Quorum/Shield): conversation list, compose (alias-aware),
   local history, poll loop, key-announcement on first use. 16-lang like the rest.
4. **Anti-spam** (§6) wired to the existing registered-check + a small hashcash + the forum's rate limiter.

## 11. Security summary

- **Confidentiality + PQ:** a **KEM-based Double Ratchet** (ML-KEM-768) + AEAD; ML-DSA sender auth; all
  post-quantum, no EC. A future quantum adversary can't read messages or forge senders.
- **Forward secrecy + post-compromise security:** per-message keys are deleted after use (a later
  compromise can't read earlier messages), and the KEM ratchet **heals** the session after one clean
  round-trip (a one-time key theft can't read future messages) — full Double-Ratchet guarantees, in v1.
- **Sender auth + integrity:** every envelope is ML-DSA-signed and address-bound (`proof_sender`), and the
  sender **must be a registered on-chain identity** (the primary spam wall).
- **Replay:** `msg_id` dedup + ratchet counters + `ts`/TTL windows; the recipient ignores duplicates.
- **Spam/DoS:** required registered-sender + per-message PoW + rate + size + pool caps → bounded memory,
  priced flood.
- **No consensus surface:** off-chain, never in a block, can't fork the chain.
- **Honest gaps:** metadata (who↔who) is visible to nodes in v1 — the required registered-sender gate needs
  a cleartext `from`, so **sealed-sender + mixnet is explicitly Phase-2** (and would trade the registration
  gate for PoW-only anti-spam). No global durability (TTL pool + local history, not a ledger).

## 12. Decisions

**Locked in (owner):**
- **Registered-sender: REQUIRED** — every sender must be a registered on-chain identity (§6). Primary spam
  wall; keeps `from` cleartext, so **sender-sealing is Phase-2** (§9.1).
- **Full post-quantum Double Ratchet in v1** (§3) — KEM-based, **pure ML-KEM, no EC / no hybrid**: forward
  secrecy **and** post-compromise security.
- **Recipient hidden in v1** via detection tags (§9.1) — the node sees the sender, not the recipient.
- **TTL = 7 days** — how long an undelivered message lives in the pool; also the "not delivered" timeout (§5.1).
- **"Not delivered" sender notification** (§5.1) — immediate on reject/no-key, or on the 7-day timeout.

**Still open:**
1. **One-time-prekey pool size** per user (`opk` count + replenish cadence): more = stronger
   post-compromise security at session start, at the cost of more announcement traffic.
2. **Group messaging** — out of v1; a later fan-out-of-1:1 or a sender-key scheme.

### Bottom line

It fits NADO cleanly: reuse the wallet seed (derive the identity/prekey **ML-KEM** keys), the P2P gossip (a
second, block-free pool), and the existing ML-DSA verify + **required** registered-gate + rate-limiter for
anti-spam. The genuinely new crypto is **ML-KEM-768 in the browser bundle** plus the **KEM Double-Ratchet**
state machine (the one intricate piece — build against adapted Double-Ratchet test vectors + fuzz
out-of-order delivery); the node stays a dumb, blind store-and-forward relay. Result: a **free,
post-quantum, end-to-end-encrypted, forward-secret, self-healing, alias-aware DM layer** with local history
and zero consensus footprint. v1 = required-registered-sender + KEM Double Ratchet + ephemeral pool + local
history; sealed-sender / mixnet / groups are Phase-2.
