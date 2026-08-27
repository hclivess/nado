# Solana leg — nado-htlc

The on-chain half of the Solana leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5). Bitcoin needs
nothing deployed because its HTLC is a script; Solana has no such script, so the conditions live here and
the escrow lives in a PDA this program owns.

    seeds = ["htlc", hashlock, claimant, funder, deadline_le, amount_le]

Every term of the agreement is in the address, which is what makes an underfunded lock land somewhere
else entirely instead of buying the claimant's secret for dust.

## Build and test

    export PATH="$PATH:/root/.local/share/solana/install/active_release/bin"
    cd scripts/solana-htlc && cargo-build-sbf --arch v3      # v0/v1/v2 deployment is disabled (SIMD-0500)
    solana-test-validator --reset --quiet --ledger /tmp/svl/test-ledger \
        --rpc-port 8999 --faucet-port 9901 --dynamic-port-range 9910-9950 &
    solana --url http://127.0.0.1:8999 program deploy target/deploy/nado_htlc.so -k <payer.json>
    /root/tools/secvenv/bin/python ../../tests/test_solana_htlc.py <program_id>

## The client side

`static/solsign.js` is the whole client: base58, ed25519 (vendored @noble), the PDA derivation including
the off-curve rule, legacy transaction assembly, JSON-RPC, and the wallet bridge. It runs unchanged in the
browser (the dex dApp's Solana rows) and in node (`scripts/otc_sol_leg.mjs`, the headless leg).

    node tests/test_solsign.mjs <program_id> [rpc]      # 16/16 against a live validator

That suite includes a BYTE-PARITY check: the same swap, keys and blockhash must serialise to exactly the
transaction `solders` produces (sha256 `5e4b0c3e…`). A signer that merely "works" can still order accounts
differently, and only some chains would reject it. To regenerate the vector after an intentional change,
build the same transaction with `solders` (fixed seeds `aa…`/`bb…`, blockhash `1111…1112`, deadline
1900000000, amount 50000000) and take the sha256 of `bytes(tx)`.

Two traps worth remembering, both cost real debugging:

* **Commitment.** `getSignaturesForAddress` and `getBalance` default to `finalized`. Reading them right
  after a transaction that was only waited to `confirmed` reports a balance of zero or no transaction at
  all — not an error, just a wrong answer. Every read here passes `commitment: "confirmed"` explicitly.
* **The fee payer.** Solana is an account model, so the submitter pays. A freshly generated swap address
  holds nothing and cannot claim its own payout. The program therefore lets ANYONE submit a claim or
  refund while the money still moves only to the recorded party — so the answer is to submit from a funded
  key (the counterparty's, or the watchtower's), which is what the CLI says when it sees an empty payer.

## Deploying to a cluster

The program keypair is `private/sol_program.json` (gitignored), so the program id is fixed at
`C4WceD67WW9c5LS4Qu3NSCcfmPfdy5KLidhsRA18waNC` on every cluster. Deploying needs about 1.1 SOL of rent for
a 74 KB program plus fees; the deployer is `private/sol_deployer.json`.

    solana --url https://api.devnet.solana.com program deploy target/deploy/nado_htlc.so \
        -k private/sol_deployer.json --program-id private/sol_program.json

Then fill the id into `NETS.sold.program` in `static/dex.js` and pass `--sol-program` to the watchtower.
