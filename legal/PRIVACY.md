# Privacy Notice — NADO software and maintainer-operated nodes

**Last updated: 2026-08-21**

This notice explains what personal data is processed when you (a) run the NADO software,
(b) use the browser page or API of a **maintainer-operated node**, or (c) transact on the
network. It is written for transparency and as a starting point for GDPR/UK-GDPR/CCPA
compliance; it is not legal advice. (For the *cryptographic* privacy design of the shielded
pool see `doc/privacy.md`.)

## 1. Data that is inherent to a public blockchain

A blockchain is a **public, append-only, replicated ledger**. By transacting you publish,
permanently and to every node in the world:

- your address(es), balances, transaction history, timestamps and amounts;
- any **alias** you register and any **on-chain message, forum post or game move** you
  submit (encrypted message *content* is ciphertext, but sender/recipient addresses and
  timing are public);
- validator/miner activity tied to your address.

This data **cannot be deleted, corrected or restricted** by the maintainers or anyone else;
it is held by every node operator independently. Erasure rights under data-protection law
cannot be honoured for on-chain data — please consider this before putting personal data on
chain. Pseudonymous addresses can become identifying if you link them to your identity.

The **shielded pool** hides sender, recipient and amount of shielded transfers; it does not
hide the fact that a shielded transaction occurred, or the fee.

## 2. Data processed by the node software (wherever it runs)

When you run a node it:

- stores the **IP addresses and ports of peers** (`peers.dat`, `peers/`) and exchanges
  them with other peers (peer discovery). Your own public IP is visible to every peer you
  connect to;
- writes **logs** (`logs/`) that may contain peer IPs, request paths and errors;
- keeps **local statistics** (`daily_stats.json`, etc.) about the node itself.

This is processed on **your** machine under **your** control. No data is sent to the
maintainers.

## 3. Data processed by maintainer-operated nodes (e.g. `nadochain.com`)

When you use the browser page or API of a node we run, our server receives and may log:

| Data | Purpose | Legal basis (GDPR) | Retention |
|---|---|---|---|
| IP address, user-agent, request path, timestamp | serving the page/API, rate-limiting, abuse prevention, debugging | legitimate interest (Art. 6(1)(f)) | rotated with server logs, typically ≤ 30 days |
| Transactions you submit | relaying to the network | performance of your request (Art. 6(1)(b)) | permanently, on chain (see §1) |
| Peer IP if you run a node that connects to ours | peer discovery | legitimate interest | while listed as a peer, plus logs |

We do **not**:

- set tracking cookies, use analytics or advertising trackers, or fingerprint browsers;
- create accounts or collect names, emails or phone numbers;
- receive your private keys — they are generated and stored **in your browser's local
  storage** and never leave your device through our page;
- sell or share data with third parties, except hosting providers acting as processors, or
  where required by law.

Browser `localStorage` used by the wallet page (keys, settings, cached state) stays on your
device; clear it from your browser to remove it. **Clearing it destroys your keys if you
have no backup.**

## 4. Third-party services

The project uses GitHub (code, issues), Discord and X/Twitter (community). Those services
have their own privacy policies; we see only what you post there.

## 5. Your rights

For the limited server-side data in §3 you may request access, rectification or erasure by
contacting the maintainers (Discord or GitHub, see `README.md`). Identify the IP and time
window concerned. For on-chain data see §1 — erasure is technically impossible. If you are
in the EU/UK you may also complain to your supervisory authority.

## 6. Children

The service is not directed at children under 18 (or the age of majority where you live),
particularly given the on-chain games of chance.

## 7. Changes

We will update this notice as the software changes and move the date above.

## 8. Controller

*(Maintainers: identify the legal person or individual operating `nadochain.com` and an
address for data-protection requests before mainnet. Under GDPR a controller must be
identifiable.)*
