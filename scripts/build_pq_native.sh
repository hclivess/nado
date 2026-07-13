#!/bin/sh
# Build the optional NATIVE ML-DSA-44 backend (native/mldsa44 -> libnado_mldsa44.so).
# Rust cdylib, same pattern as the Goldilocks prover lib (wasm/goldilocks). Operators:
# run this once (needs `cargo`), then set NADO_PQ_NATIVE_MODULE=nado_pq_native in the node's
# environment (the systemd unit already does). signatures.py adopts it ONLY after the startup
# interop self-test passes — a bad build can never split consensus, it just isn't used.
set -e
cd "$(dirname "$0")/../native/mldsa44"
cargo build --release
cp target/release/libnado_mldsa44.so ./libnado_mldsa44.so
echo "built $(pwd)/libnado_mldsa44.so"
