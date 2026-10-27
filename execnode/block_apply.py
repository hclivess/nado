"""ONE BLOCK OF THE EXEC TRANSITION, as a pure function of (states, block): what execnode._apply_block_inner does between its
DA pre-resolve and its pin bookkeeping, moved here unchanged (G4, 2026-10-27) so the gen-29 settlement verifier
(execnode/settle_b2.py) replays a span through the SAME code the exec node applies it with. A second implementation of
the dispatch is how a prover and a chain come to disagree (CLAUDE.md, "rollback must be the exact inverse": re-deriving
is a second implementation of the rules, with its own bugs). INVARIANT: execnode.py and settle_b2.py both call these
three functions, in this order, per block; nothing exec-relevant happens in either caller between them.

No I/O, no network, no node state: importing this module opens nothing (L1 imports it to verify a span).
"""
from protocol import chain_clock


def begin(states_map, h):
    """Open block `h` on every namespace's state: the rule height, a fresh step budget, the block's own context."""
    for _st in states_map.values():
        _st._applying = h              # the height every rules_* helper judges by (see ExecState.applying_height)
        _st._block_steps = 0           # F4: the per-block execution budget starts fresh
        _st._block_steps_by = {}       # ...and every sender's share of it (EXEC_BUDGET_V2_HEIGHT)
        if int(h) >= 1:
            # F3: the context a call sees is the block it executes in — what block_calls stamps and the settlement
            # prover replays — not the previous one. `>= 1`: gen 25's EXEC_CTX_CURRENT_HEIGHT, 1 from gen 26
            # (deleted); genesis (h = 0, applied from cursor -1) keeps the order it always had.
            _st.cursor, _st.block_ts = h, chain_clock(h)


def dispatch(states_map, default_state, block, resolved, refused, verbose=True):
    """Apply every exec-relevant tx of `block` in order. `resolved` maps a txid to (field, bytes) fetched from DA by the
    caller; `refused` holds the positions refused at the exec DA deadline. A tx that raises is skipped (logged); an
    exception that is not an Exception (settle_b2.Unprovable) passes through untouched, by design."""
    h = block["block_number"]
    for _pos, tx in enumerate(block.get("block_transactions", [])):
      # PER-TX GUARD (halt-class, audit 2026-07): this DISPATCH code — not apply_blob, which is already
      # fully guarded — used a payload field (`ns`) as a dict key with no type check, so a blob carrying an
      # unhashable ns raised TypeError HERE and aborted the whole block before the cursor advance below. The
      # tail loop then refetched the same block forever: a permanent, fleet-wide exec halt for one
      # MIN_TX_FEE tx. L1 admission now refuses such a payload; this ensures ONE bad tx can never freeze the
      # cursor regardless (a block from history, or any future field this loop reads without checking).
      try:
        if _pos in refused:
            # REFUSED AT THE EXEC DA DEADLINE (see the pre-resolve): not dispatched at all — not even to apply_blob
            # without its bytes, where an inline `bundle` riding beside the proof_da would apply in its place.
            continue
        if tx.get("txid") in resolved and isinstance(tx.get("data"), dict):
            _field, _bytes = resolved[tx["txid"]]
            tx = {**tx, "data": {**tx["data"], _field: _bytes}}
        r = tx.get("recipient")
        if r == "blob":
            d = tx.get("data")
            bns = d.get("ns", "default") if isinstance(d, dict) else "default"
            tgt = states_map.get(bns) if isinstance(bns, str) else None
            if tgt is not None:
                res = tgt.apply_blob(d, tx.get("sender"), tx.get("txid"))
                if verbose:
                    print(f"[execnode] block {h} ns={bns}: {res}", flush=True)
        elif r == "xmsg":
            d = tx.get("data") or {}
            tgt = states_map.get(d.get("to_ns"))
            if tgt is not None:
                res = tgt.apply_xmsg(d.get("from_ns", "default"), d.get("message") or {})
                if verbose:
                    print(f"[execnode] block {h} ns={d.get('to_ns')}: {res}", flush=True)
            # the delivery burned the (from_ns, seq) L1 nullifier — GC the SOURCE outbox record too
            src = states_map.get(d.get("from_ns", "default"))
            if src is not None:
                src.drop_consumed_outbox((d.get("message") or {}).get("seq"))
        elif r in ("bridge_withdraw", "dividend_withdraw", "unshield"):
            # a FINALIZED claim burned its L1 nullifier — the exec-side exit record is dead weight
            # in state_root now; GC it (state.drop_claimed). ns-aware for bridge_withdraw.
            d = tx.get("data") or {}
            ns = d.get("ns", "default") if r == "bridge_withdraw" else "default"
            tgt = states_map.get(ns)
            if tgt is not None:
                tgt.drop_claimed(r, d.get("nonce"))
        elif r == "bridge":
            default_state.credit_deposit(tx.get("sender"), tx.get("amount", 0))
            if verbose:
                print(f"[execnode] block {h}: bridge deposit {tx.get('amount')} by {(tx.get('sender') or '')[:12]}…", flush=True)
        elif r == "faucet":
            # FAUCET DONATION (doc/faucet.md): an L1 tx to the reserved name locked `amount` in the L1
            # faucet escrow; mirror it as spendable balance of the FIXED-NAME faucet CONTRACT ("faucet"
            # is its literal cid — see state.FIXED_CIDS), whose claim() method PAYs grants to players.
            default_state.credit_deposit("faucet", tx.get("amount", 0))
            # an L1 donation FROM THE OPERATOR counts toward what defund() may take back (faucet.py slot 7)
            try:
                from execnode.games.faucet import OPERATOR as _FAUCET_OP
                if tx.get("sender") == _FAUCET_OP:
                    default_state.bump_contract_slot("faucet", 7, int(tx.get("amount", 0)))
            except Exception:
                pass
            if verbose:
                print(f"[execnode] block {h}: faucet donation {tx.get('amount')} by {(tx.get('sender') or '')[:12]}…", flush=True)
        elif r == "treasury_execute":
            # TREASURY -> FAUCET payout: a MINED treasury_execute is a completed payout (L1 validation gated
            # the 2/3 quorum, funding and the one-shot pid nullifier, and apply credited the L1 faucet
            # escrow). When the approved spend targets the reserved faucet name, mirror it into the faucet
            # CONTRACT's spendable balance exactly like a donation, so game grants/prizes can pay from it.
            spend = (tx.get("data") or {}).get("spend") or {}
            if spend.get("recipient") == "faucet":
                default_state.credit_deposit("faucet", int(spend.get("amount") or 0))
                if verbose:
                    print(f"[execnode] block {h}: treasury->faucet payout {spend.get('amount')}", flush=True)
        elif r == "shield":
            d = tx.get("data") or {}
            from protocol import LEGACY_SHIELD_CLOSE_HEIGHT as _LCLOSE
            if d.get("field"):
                res = default_state.apply_field_shield(tx.get("amount", 0), d.get("owner"), d.get("rho"))
            elif int(h) >= _LCLOSE:
                # the legacy pool is closed (protocol.LEGACY_SHIELD_CLOSE_HEIGHT; L1 refuses these too): nothing moves
                res = "skip shield: the legacy shielded pool takes no new deposits"
            else:
                res = default_state.apply_shield(tx.get("amount", 0), d.get("out_commitments", []), d.get("openings", []))
            if verbose:
                print(f"[execnode] block {h}: {res}", flush=True)
        elif r == "reveal":
            # RANDAO reveal (#randao): accumulate the secret into every namespace's beacon accumulator, so the
            # BEACON opcode can read the same grind-resistant chain randomness consensus derives.
            d = tx.get("data") or {}
            for _st in states_map.values():
                _st.record_reveal(d.get("target_epoch"), d.get("secret"))
        elif r == "duty":
            # The live path emits attest/commit/reveal MERGED into one `duty` tx (core_loop), and L1 records
            # its carried reveal via reveal_put — but this loop only saw STANDALONE `reveal` txs, so every exec
            # BEACON was computed reveal-free (predictable + grind-able) AND mismatched L1's with-reveals value,
            # so a settle-with-proof over a BEACON contract could never pass the chain-read cross-check. Feed
            # the duty-carried reveal in exactly like a standalone one so the exec beacon == L1's.
            rv = (tx.get("data") or {}).get("reveal")
            if rv:
                for _st in states_map.values():
                    _st.record_reveal(rv.get("target_epoch"), rv.get("secret"))
      except Exception as e:
        # A single malformed tx must never abort the block — that is the permanent-wedge bug. Skip it and
        # go on; the cursor still advances below. Deterministic: every node hits the same exception on the
        # same tx and skips identically, so no fork. (apply_blob's own effects are already guarded upstream.)
        if verbose:
            print(f"[execnode] block {h}: skipped tx {(tx.get('txid') or '')[:12]}… ({type(e).__name__}: {e})", flush=True)


def close(states_map, h, block_hash):
    """Close block `h`: the cursor, the TIME clock, the beacons now final, and the block's hash for BHASH."""
    for _st in states_map.values():
        _st.cursor = h
        _st._applying = None
        # TIME opcode: the DETERMINISTIC chain clock, NOT block_timestamp. block_timestamp sits outside the
        # block-hash preimage (so honest clock skew cannot fork the chain) and therefore differs between
        # honest nodes for the SAME block — measured live at 1 s apart. Feeding it to the VM made any
        # contract that reads TIME able to diverge exec state, and with it exec_root and the settle quorum.
        # chain_clock(h) is a pure function of block height, so every node runs the contract identically.
        _st.block_ts = chain_clock(h)
        _st.advance_beacons(h)      # cache every epoch beacon now finalized at this height
        _st.record_block_hash(h, block_hash)   # BLOCKHASH randomness for this finalized height
