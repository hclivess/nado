# NADO units

NADO's sub-units are named after the **people** behind it — the cryptographers whose ideas NADO is built on,
the developers who wrote it, and the community that carried it. Like Bitcoin's `sat` or Ethereum's
`wei`/`gwei`, these are a **display convention**: the ledger only ever stores integer **raw** units. Nothing
here is a consensus rule; it lives in the interface, the CLI's number formatting, and docs.

`1 NADO = 10,000,000,000 raw` — ten decimal places, so **one named unit per decimal place**.

## The ladder

| Symbol | Named for | Who / contribution | Value (NADO) | In raw |
|---|---|---|---:|---:|
| **dag** | **Dagmar** | Jan's wife and cofounder | 10⁻¹ | `1,000,000,000` |
| **jan** | **Jan Kučera** (`hclivess`) | author of NADO — and of Bismuth before it | 10⁻² | `100,000,000` |
| **syl** | **Sylvain** (`EggPool`) | one of Bismuth's principal contributors — ran Eggpool; core mining & infrastructure | 10⁻³ | `10,000,000` |
| **bry** | **Bryan McEachran** | the most important historical community member | 10⁻⁴ | `1,000,000` |
| **kha** | **Khaa Aarl** | friend and early supporter | 10⁻⁵ | `100,000` |
| **geh** | **Geir Hovland** (`geho2`) | co-author of the peer-reviewed control-theory analysis of the PoW difficulty controller | 10⁻⁶ | `10,000` |
| **vit** | **Vitalik Buterin** | the account model and FFG (Casper) finality NADO adopts | 10⁻⁷ | `1,000` |
| **nak** | **Satoshi Nakamoto** | proof-of-work and the no-premine fair-launch ethos | 10⁻⁸ | `100` |
| **dam** | **Damian** (`alias-bitsignal`) | code contributor & infrastructure maintainer | 10⁻⁹ | `10` |
| **eli** | **Eli Ben-Sasson** | co-inventor of zk-STARKs — NADO's private-transfer proofs | 10⁻¹⁰ | `1` |
| **NADO** | the coin | — | 1 | `10,000,000,000` |

```
1 NADO = 10 dag = 100 jan = 1,000 syl = 10,000 bry = 100,000 kha
       = 1,000,000 geh = 10,000,000 vit = 100,000,000 nak = 1,000,000,000 dam = 10,000,000,000 eli
```

### Notes on the anchor tiers

- **eli** is the atomic quantum (10⁻¹⁰) — the cryptographic *foundation* (STARKs), the way `wei`/`satoshi` are
  their chains' atoms.
- **nak** sits at **10⁻⁸ NADO — the exact scale of one Bitcoin satoshi (10⁻⁸ BTC)** — a deliberate homage to
  Nakamoto at the "satoshi tier." Symbol is **`nak`, never `sat`**: reusing `sat` would collide with Bitcoin on
  every chart and listing. Honour the ethos, skip the collision.
- **dag** is the largest sub-unit (10⁻¹, a tenth of a NADO). A neat coincidence: the maximum block reward
  (`BASE_SUBSIDY`, 0.1 NADO) is **exactly 1 dag**.

## Conversions & style

- Symbols are lowercase, three letters, and don't pluralise: `500 vit`, `2 jan`, `12 nak`.
- The coin ticker is **NADO** (uppercase).
- **Accounting stays in raw integers.** Convert to a named unit only for display; never store or compute
  balances as floats.

| From raw | Reads as |
|---|---|
| `1` | `1 eli` |
| `100` | `1 nak` |
| `1_000` | `1 vit` |
| `1_000_000` | `1 bry` |
| `100_000_000` | `1 jan` |
| `1_000_000_000` | `1 dag` |
| `1_500_000_000` | `0.15 NADO` (= `1.5 dag` = `15 jan`) |
| `10_000_000_000` | `1 NADO` |

### Worked examples

- `MIN_TX_FEE = 1000 raw` = **1 vit** (= 10 nak).
- `BASE_SUBSIDY = 1_000_000_000 raw` (max block reward) = **0.1 NADO** = exactly **1 dag**.
- A `2,500,000,000 raw` transfer = **0.25 NADO** = `2.5 dag` = `25 jan`.

## Honorable mentions

The ladder is capped at ten rungs by the ten decimal places, so not everyone who shaped NADO/Bismuth could
get a rung. Still owed a nod: `majordutch`, `Endogen`, `RedDwarf` (`redDwarf03`), `jimtalksdata`, and `raetsch`.
(The repo's #2 committer by volume is the `claude` AI assistant — left off the honorary ladder by design.)

## Scope

These names are cosmetic and additive. Implementation touch-points, when wired up: interface / wallet number
formatting (show the largest unit that renders cleanly), a CLI `--unit` display option, and explorer amount
rendering. The raw-integer values in `protocol.py` (`MIN_TX_FEE`, `BASE_SUBSIDY`, …) and every on-chain amount
are unchanged — a unit is just a label over `raw`.
