# Alphanet reboot — 2026-07-14 (alphanet-5: zkVM-only, provable contracts, games returning)

> **Chain reboot.** Deleting the legacy stack VM (v1.0.0-alpha.9) made the field-native **zkVM the only
> contract runtime**, so alphanet-4 was rebooted to **alphanet-5** with a fresh genesis. Every holder's
> **balance + bonded stake carried forward** (`tools/alphanet5_carryforward.py`): exec-side user balances +
> uncollected dividends folded into L1 balances, contract game-pots refunded to their players, and the folds
> debited from the escrow reserved accounts so total supply is conserved EXACTLY (Δ=0). Nodes rebuild the
> identical genesis from the shared `genesis_data/genesis_alloc.dat`. Bonded validators must update + rejoin
> for full FFG finality (the chain produces + depth-finalizes meanwhile).

Games are being re-shipped as zkVM ports (`execnode/games/`) — the old stackvm game JSONs are gone. Each
port: the contract in zkVM assembly over a composite-integer `slot` model, an `abi._view` schema so the exec
node presents its flat slots as the named maps the frontend already reads (so only the `cid` changes), and
`chainResultAlg` for a client-side beacon preview that byte-matches the contract's in-VM alghash. **Live so
far:** coinflip, dice, roulette, tictactoe. Two techniques the ports drove: **arg-packing** (a many-arg game
like roulette packs its 37-number coverage into one bitmask + bounded in-VM loops — the 8-register arg limit
is a feature, not raised) and a **widened DIVMOD** (48-bit quotient) for financial payout division.

See `doc/zk-execution-proofs.md` and `execnode/README.md`.

---

