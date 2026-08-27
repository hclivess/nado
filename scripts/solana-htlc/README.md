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
