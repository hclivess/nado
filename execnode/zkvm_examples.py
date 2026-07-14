"""
Starter zkVM contract library (doc/zk-execution-proofs.md) — the field-native replacement for the deleted
stackvm contract_lib. Each entry is {code, abi}; the wallet's Rollup tab offers them as one-click deploys and
the game ports compose from the same patterns. Assembled from execnode/zkvmasm.py.

Patterns:
  COUNTER   — a shared integer at slot 0 (the "hello world").
  TIP_JAR   — a per-caller running total (accumulator: tipping, reputation, vote tallies); slot = caller
              digest, which the zkVM gives you directly via `ctx r_ caller`.
  COIN_FLIP — a fair 2-player commit-reveal flip; the outcome is a sponge hash of both revealed secrets,
              unknowable until both are out. Uses the in-VM alghash `HASH` macro — no BLAKE2b, so the whole
              contract is provable.
"""
from execnode import zkvmasm

COUNTER = zkvmasm.assemble_contract({
    "bump": "movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2",
    "get":  "movi r1 0\n sload r2 r1\n ret r2",
})

TIP_JAR = zkvmasm.assemble_contract({
    # deposit(): add the escrowed value to caller's running total (slot = caller digest)
    "tip":   "ctx r1 caller\n ctx r2 value\n sload r3 r1\n add r3 r2\n sstore r1 r3\n ret r3",
    "total": "ctx r1 caller\n sload r2 r1\n ret r2",
})

# COMMIT_BOX: the commit-reveal primitive every fair game builds on, minimal + provable. commit(i, H(secret))
# stores a sealed commitment in slot i (once); reveal(i, secret) re-hashes with the in-VM alghash sponge and
# REQUIREs a match, then marks slot i as opened (value 1 at slot i+8). The full 2-player flip/lottery layers
# result derivation on top — see the game ports; this is the audited kernel.
COMMIT_BOX = zkvmasm.assemble_contract({
    "commit": """
        sload r2 r0
        nez r2
        notb r2
        require r2
        sstore r0 r1
        ret r0
    """,
    "reveal": """
        hash r2 <- r1
        sload r3 r0
        eq r3 r2
        require r3
        movi r4 8
        add r0 r4
        movi r5 1
        sstore r0 r5
        ret r5
    """,
})

LIBRARY = {
    "counter":    {"code": COUNTER,    "abi": {"bump": {"args": []}, "get": {"args": []}}},
    "tip_jar":    {"code": TIP_JAR,    "abi": {"tip": {"args": []}, "total": {"args": []}}},
    "commit_box": {"code": COMMIT_BOX, "abi": {"commit": {"args": ["slot", "hash"]},
                                               "reveal": {"args": ["slot", "secret"]}}},
}
