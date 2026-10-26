# Address format — and the one-constant rebrand

```
address = ADDRESS_PREFIX + ADDRESS_BODY hex of blake2b([nado-address-v2, pubkey]) + 4-byte blake2b checksum
          ""  (removed)    42 chars                                                 8 hex, over prefix+body
          → 50 chars total today (format 2, gen 28); a multisig address is "msig" + body + checksum = 54
```

`validate_address` is **checksum-based** — it verifies the trailing 8 hex (`ADDRESS_CHECKSUM` = 4
bytes) against blake2b of everything before them, and requires the exact length (50, or 54 for an
`msig` address), so a 46-char format-1 address is rejected by shape. The prefix only exists in **derivation** and in
UI/consensus string checks, and all of those now read a single constant per language:

| where | constant |
|---|---|
| `protocol.py` | `ADDRESS_PREFIX` / `ADDRESS_BODY` / `ADDRESS_CHECKSUM` / `ADDRESS_LENGTH` |
| `static/nadotx.js` (games SDK) | `ADDR_PREFIX` / `ADDR_BODY` / `ADDR_LEN` / `ADDR_RE` / `isAddress` |
| `static/interface.js` (wallet) | `ADDR_PREFIX` / `ADDR_BODY` / `ADDR_LEN` / `ADDR_RE*` |

Nothing else in the codebase spells the prefix. (Verified by grep at the time of the refactor;
keep it that way — new code imports the constants.)

## Why this exists

(History: the prefix was `ndo` until it was removed; `ADDRESS_PREFIX` is now `""`.) The `ndo` prefix coupled every address string to the brand. A rebrand (possible: nadohq
exists, and "nado" ⊂ "tornado" invites tornadocash association) must not orphan the format — so
the prefix is a deliberate ONE-CONSTANT decision point, changeable in three lines.

## The switch procedure (whenever the operator pulls the trigger)

This procedure was written for format 1, where the body was the pubkey itself. Under format 2
(gen 28) the body is a hash of the key (`protocol.py`, ADDRESS FORMAT 2), so a re-key must re-derive
each address from its public key, not re-prefix the old string. Changing any field orphans every
existing address **string** while every **key** still owns its account, so the switch ships as one
commit + one reroll:

1. Flip `ADDRESS_PREFIX` in `protocol.py` and `ADDR_PREFIX` in `static/nadotx.js` +
   `static/interface.js` (three lines).
2. `sed -i 's/ndo…/<new>…/g' static/i18n/*.json static/i18n_games/*.json static/*.html`, then
   `python3 tools/build_i18n.py` — the human-readable "ndo…" hints in translations and input
   placeholders (language-invariant, one mechanical pass; i18n.js is generated from those JSON files).
3. Re-derive the wallet self-test vectors in `static/interface.js` (`make_address_out`,
   `pow_address`, `register_tx` fixtures) — the self-test pins the format on purpose.
4. Re-key the genesis allocation so every balance carries to the same owners:
   `python3 scripts/rekey_alloc.py genesis_data/genesis_alloc.dat ndo <new> > …` (same body,
   recomputed checksum — deterministic, keys unchanged).
5. Bump `CHAIN_GENERATION` (+ the protocol number), commit, `/update` wave — the standard reroll.

Prefix constraints for a future value: must not contain a line-ambiguous hex boundary — chars
outside `[0-9a-f]` at the START guarantee the prefix/body boundary is visually and mechanically
unambiguous (e.g. "pq" qualifies; "beef" would not). Keep it lowercase, short, and — the whole
point — **brand-free**.

Candidate selected in discussion: **`mldsa44`** — the prefix as a KEY-TYPE DISCRIMINATOR (the
address literally names the FIPS-204 scheme whose pubkey it hashes). A rebrand never touches it;
a future scheme migration mints new keys — and therefore new addresses — under its own prefix
(`mldsa65…`, `slh…`), coexisting like Bitcoin's `1`/`3`/`bc1q`/`bc1p` script discriminators.

## Multisig (and future policy accounts)

A multisig account is P2SH-style: the "pubkey" slot holds the domain-tagged hash of the policy
(`blake2b(DOMAIN_MSIG, M, members)`, `ops/multisig_ops.py`), and it carries its OWN prefix,
**`msig`** (`protocol.MSIG_PREFIX` — starts non-hex ✓), exactly the `1`-vs-`3` split: a keyed address = hash of one pubkey,
`msig…` = hash of an M-of-N policy whose members are themselves keyed addresses. Wallets
and explorers can then label them, refuse identity ops (bond/mine/vote) client-side before the
consensus rule even fires, and — critically — future migrations can IDENTIFY them (see below).

**⚠ Cutover caveat (found the hard way, before it bit):** multisig addresses do NOT survive a
prefix switch by re-keying. The member address STRINGS live inside the descriptor hash, so
re-prefixing the members changes the multisig address BODY, not just its prefix — and because
nothing marks a policy account on-chain, `rekey_alloc.py` cannot even tell which alloc entries
are multisig. A naive re-key would land those balances on addresses no descriptor derives —
bricked. Therefore the switch procedure includes: **announce a pre-snapshot window in which
multisig balances must be moved to keyed accounts** (on betanet today that is ~zero accounts);
the new generation launches multisig as v2 — own `msig` prefix, new domain tag, new-format
members. This is precisely why the discriminator prefix is worth having: with `msig…` visible,
any FUTURE format migration can enumerate policy accounts and define their carry-over.

## Domain-separation tags (rename free at the same reroll)

Most consensus domain tags have already been renamed brand-free (`protocol.py`: `msig-v2`, `register-v1`,
`randao-commit-v1`, `randao-beacon-v1`, `blocksig-v2`, `genesis-beacon-v1`; the forum's non-consensus
`forum-login-v1`). Some still carry the brand — invisible to users, but they exist: `nado-address-v2`
(`DOMAIN_ADDRESS_V2`), `nado-auth-v1`, `nado-air-v1`, `nado-epoch-statement-v1` (in `execnode/stark/`), plus
non-consensus ones (the `nado-lang` event, localStorage keys). The chain_id is already brand-free
(`protocol.CHAIN_ID`, and it changes every reroll). Outside a reroll, renaming any consensus tag is a fork for zero
value. AT the reroll everything re-derives from genesis anyway, so renaming them to brand-free
tags (`chain-stark`, `msig-v2`, …) is free — fold it into the same cutover commit.
