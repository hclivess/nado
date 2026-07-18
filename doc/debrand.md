# Debrand inventory — every "nado"/"ndo" in the system, classified

The brand appears in five very different risk classes. Everything below is **centralized behind a
constant** (nothing else spells it), so each class renames by flipping its constants — but the
classes rename at different times, and one of them must **never** rename at all.

## Class 1 — Address prefix (`ndo`) → reroll

See `doc/address-format.md`. Three constants total (`protocol.py ADDRESS_PREFIX`,
`nadotx.js ADDR_PREFIX`, `interface.js ADDR_PREFIX`). Candidate: **`mldsa44`** (key-type
discriminator; multisig gets `msig`). Switch = constants + `rekey_alloc.py` + the multisig
pre-snapshot window + `CHAIN_GENERATION` reroll.

## Class 2 — Consensus domain tags (chain-derived) → rename FREE at the same reroll

Everything here re-derives from genesis at a reroll; renaming outside one is a fork for zero value.

| tag (today) | constant | home (py / js mirror) | candidate |
|---|---|---|---|
| `nado-stark` | `DOMAIN_STARK` | `execnode/stark/transcript.py` / `static/stark/transcript.js` | `stark-v1` |
| `nado-msig-v1` | `DOMAIN_MSIG` | `protocol.py` / `interface.js` | `msig-v2` |
| `nado-register` | `DOMAIN_REGISTER` | `protocol.py` / `interface.js` | `register-v1` |
| `nado-randao-commit` | `DOMAIN_RANDAO_COMMIT` | `protocol.py` / `interface.js` | `randao-commit-v1` |
| `nado-genesis-beacon` | `DOMAIN_GENESIS_BEACON` | `protocol.py` | `genesis-beacon-v1` |
| `nado-rec-digest` | `DOMAIN_REC_DIGEST` | `execnode/exec_root.py` | `rec-digest-v1` |
| `nado.shield` | `DOMAIN_SHIELD` | `execnode/shielded.py` / `static/shielded.js` | `shield-v1` |
| `nado-empty-merkle` | `DOMAIN_EMPTY_MERKLE` | `hashing.py` | `empty-merkle-v1` |

`chain_id` is already brand-free (`alphanet-6`) and changes at every reroll anyway.
`_GENESIS_BODY` in `protocol.py` is an address literal — re-derived at the reroll (flagged inline).

## Class 3 — ⚠ KEY-DERIVED tags (special rules — read both paragraphs)

These derive from the **user's seed**, not from the chain: a reroll does NOT reset them, and
renaming them silently changes the derived keys — derived accounts and shielded notes become
unreachable with no error anywhere.

**Operator decision (2026-07-18): they flip WITH the alphanet cutover anyway** — this is alphanet;
nothing here is worth preserving beyond main-account balances. Consequences, folded into the
pre-snapshot notice: move DERIVED-account and MULTISIG balances to your MAIN account and unshield
any shielded notes before the snapshot — only main keyed-account balances carry (via
`rekey_alloc.py`); everything seed-derived re-derives fresh under the new tags on alphanet-7.
**After mainnet, the frozen-forever rule applies**: renaming any of these post-launch requires
explicit migration code, never a sed.

| tag | constant | derives |
|---|---|---|
| `nado-hd-account` | `interface.js DOMAIN_HD_ACCOUNT` | child-account private keys from the master seed |
| `nado.shield.nsk` | `interface.js DOMAIN_SHIELD_NSK` | the shielded nullifier secret from the private key |
| `nado-randao-secret` | `interface.js DOMAIN_RANDAO_SECRET` | per-epoch RANDAO secrets from the seed (in-flight commits break if renamed mid-epoch) |

Same class, same rule: **localStorage keys that hold secrets** — `nado_hexholm_secret_*` (game
commit-reveal secrets: renaming mid-game forfeits stakes), wallet storage keys, `nado_msg_v1_*`
(messaging identity). Preference keys (`nado_lang`, `nado_bg_sign`, …) merely lose a setting.

## Class 4 — Client/server pairs (non-consensus, rename in lockstep, anytime)

- `nado-forum-login` — `forum/server.py DOMAIN_FORUM_LOGIN` / `interface.js DOMAIN_FORUM_LOGIN`.
- `nado-pq-backend-interop-selftest` (`signatures.py`) — a local self-test message; rename freely.
- Frozen wallet self-test vectors (`interface.js` — `chain_id: "nado-relaunch-1"`, `ndo…`
  fixtures): they pin historical derivation ON PURPOSE; re-derive them at the address switch,
  never sed them blindly.

## Class 5 — Pure cosmetics / infra (rename whenever the rebrand happens; no chain impact)

- **UI text**: "NADO" as currency/product name across `i18n.js` (16 languages), game pages, hub,
  whitepaper/README/doc — a text sweep.
- **Domains**: `nadochain.com` + `get.` + `forum.` + ~20 game subdomains (nginx vhosts, DNS,
  Cloudflare, certs, `og:` tags, canonical URLs, `share()` strings).
- **Code names**: `nado.py`, `nadotx.js`, `nadodapp.js`, `nado_venv`, systemd units
  (`nado`, `nado-exec`), the `nado-fx` CSS class, repo paths.
- **The autoupdater pin**: `ops/self_update.py _OFFICIAL_REPO_RE` pins `github.com/hclivess/nado` —
  a repo rename MUST update this or the fleet stops updating (GitHub redirects help git, not the
  regex). Same for the daily-check URL.
- Explorer/bitcointalk/announcement docs.

## Rename timeline summary

| when | what |
|---|---|
| anytime, no coordination | Class 5 cosmetics (except the autoupdater pin — coordinate with a wave), Class 4 pairs |
| at the alphanet-7 cutover reroll | Class 1 prefix + ALL of Class 2 **and Class 3** in the same commit (operator decision: everything flips while it's still alphanet) |
| never after mainnet (without migration code) | Class 3 key-derived tags + secret-bearing localStorage keys |
