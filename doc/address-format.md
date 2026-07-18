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

Candidate on the table: **`pq`** — describes the chain's post-quantum identity, survives any
rebrand, 2 chars (addresses shorten to 48), no company or token name inside it.
