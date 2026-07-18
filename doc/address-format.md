# Address format — and the one-constant rebrand

```
address = ADDRESS_PREFIX + first ADDRESS_BODY hex chars of the pubkey + 4-hex blake2b checksum
          "ndo"           42 chars                                      over prefix+body
          → 49 chars total today
```

`validate_address` is **checksum-based and prefix-agnostic** — it verifies the trailing 4 hex
against blake2b of everything before them. The prefix only exists in **derivation** and in
UI/consensus string checks, and all of those now read a single constant per language:

| where | constant |
|---|---|
| `protocol.py` | `ADDRESS_PREFIX` / `ADDRESS_BODY` / `ADDRESS_CHECKSUM` / `ADDRESS_LENGTH` |
| `static/nadotx.js` (games SDK) | `ADDR_PREFIX` / `ADDR_BODY` / `ADDR_LEN` / `ADDR_RE` / `isAddress` |
| `static/interface.js` (wallet) | `ADDR_PREFIX` / `ADDR_BODY` / `ADDR_LEN` / `ADDR_RE*` |

Nothing else in the codebase spells the prefix. (Verified by grep at the time of the refactor;
keep it that way — new code imports the constants.)

## Why this exists

The `ndo` prefix couples every address string to the current brand. A rebrand (possible: nadohq
exists, and "nado" ⊂ "tornado" invites tornadocash association) must not orphan the format — so
the prefix is a deliberate ONE-CONSTANT decision point, changeable in three lines.

## The switch procedure (whenever the operator pulls the trigger)

Changing any field orphans every existing address **string** while every **key** still owns its
account (the body is the pubkey), so the switch ships as one commit + one reroll:

1. Flip `ADDRESS_PREFIX` in `protocol.py` and `ADDR_PREFIX` in `static/nadotx.js` +
   `static/interface.js` (three lines).
2. `sed -i 's/ndo…/<new>…/g' static/i18n.js static/*.html` — the human-readable "ndo…" hints in
   translations and input placeholders (language-invariant, one mechanical pass).
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

Today a multisig account is P2SH-style: the SAME prefix, with the "pubkey" slot holding the
domain-tagged hash of the policy (`blake2b("nado-msig-v1", M, members)`). Nothing marks it
on-chain until it spends — a keyed account and a policy account are indistinguishable by string.

Under the discriminator model, policy accounts get their OWN prefix (candidate: **`msig`** —
starts non-hex ✓), exactly the `1`-vs-`3` split: `mldsa44…` = hash of one ML-DSA-44 pubkey,
`msig…` = hash of an M-of-N policy whose members are themselves `mldsa44…` addresses. Wallets
and explorers can then label them, refuse identity ops (bond/mine/vote) client-side before the
consensus rule even fires, and — critically — future migrations can IDENTIFY them (see below).

**⚠ Cutover caveat (found the hard way, before it bit):** multisig addresses do NOT survive a
prefix switch by re-keying. The member address STRINGS live inside the descriptor hash, so
re-prefixing the members changes the multisig address BODY, not just its prefix — and because
nothing marks a policy account on-chain, `rekey_alloc.py` cannot even tell which alloc entries
are multisig. A naive re-key would land those balances on addresses no descriptor derives —
bricked. Therefore the switch procedure includes: **announce a pre-snapshot window in which
multisig balances must be moved to keyed accounts** (on alphanet today that is ~zero accounts);
the new generation launches multisig as v2 — own `msig` prefix, new domain tag, new-format
members. This is precisely why the discriminator prefix is worth having: with `msig…` visible,
any FUTURE format migration can enumerate policy accounts and define their carry-over.

## Domain-separation tags (rename free at the same reroll)

Consensus domain tags also carry the brand — invisible to users, but they exist:
`nado-stark`, `nado-msig-v1`, `nado-register`, `nado-randao-commit`/`-secret`, `nado-fx`,
`nado-rec-digest`, the chain_id `nado-relaunch-1`, plus non-consensus ones (`nado-forum-login`,
`nado-lang`, localStorage keys). Outside a reroll, renaming any consensus tag is a fork for zero
value. AT the reroll everything re-derives from genesis anyway, so renaming them to brand-free
tags (`chain-stark`, `msig-v2`, …) is free — fold it into the same cutover commit.
