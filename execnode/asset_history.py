"""NODE-LOCAL ASSET HISTORY — every movement of every exec asset, so an NFT page can show its whole provenance (mint,
plain wallet-to-wallet `asset_transfer`, escrow into a contract and out of it, sales, burns). Served at
GET /exec/asset_history (execnode/execnode.py).

NOT CONSENSUS, AND IT MUST STAY THAT WAY. The chain's state holds only balances (`abal`); who moved what, when, is
history the chain never committed and no proof covers. This index is what one exec node SAW while applying finalized
blocks. Nothing in it enters ExecState._snapshot(), state_root() or any value a block's application computes (the sink
is a class attribute outside the snapshot — see ExecState.asset_sink), and the store never raises into block
application: every failure is logged, the store disables itself, and the chain keeps moving
(tests/test_the_asset_history_index_changes_no_consensus_value.py).

EXACTNESS. The index is a pure function of the block stream the node applied, and stays one across restart and rewind:
  * a block is written in ONE transaction, after it applied (flush_block);
  * rows are keyed UNIQUE (ns, cursor, seq) and written INSERT OR REPLACE, so re-applying a block cannot duplicate;
  * trim(ns, cursor) deletes everything above a cursor — called at start (the loaded state may be behind what was
    flushed) and on every rewind, so a block replayed onto a rewound state replaces exactly what it wrote before;
  * `last` (the newest flushed cursor) makes a GAP visible: a block that does not follow the last one flushed (a pruned
    body, a bootstrap/anchor adoption, a period the store was disabled) restarts the namespace's index from that block,
    so `indexed_from` is always a cursor from which the history is COMPLETE. Never a silent hole.

Stdlib sqlite3 only; one file next to the exec state (exec_state.json.asset_history.sqlite — inside the
`exec_state.json*` .gitignore glob and the reroll purge, both of which are right for a derived file)."""
import json
import sqlite3
import threading

from execnode import dex_trades as DX

LIMIT_DEFAULT = 500
LIMIT_MAX = 2000

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS moves (ns TEXT NOT NULL, cursor INTEGER NOT NULL, seq INTEGER NOT NULL,"
    " txid TEXT, sender TEXT, op TEXT, method TEXT, args TEXT, value TEXT, call_asset TEXT,"
    " aid TEXT NOT NULL, holder TEXT NOT NULL, delta TEXT NOT NULL, UNIQUE (ns, cursor, seq))",
    "CREATE INDEX IF NOT EXISTS moves_by_asset ON moves (ns, aid, cursor, seq)",
    # indexed_from: the first cursor of the complete history; last: the newest cursor flushed (gap detection)
    "CREATE TABLE IF NOT EXISTS meta (ns TEXT PRIMARY KEY, indexed_from INTEGER NOT NULL, last INTEGER NOT NULL)",
) + DX.SCHEMA                    # the DEX trade index (execnode/dex_trades.py) lives in this file and shares its lifecycle
# every table holding rows of a namespace by cursor: a gap, a trim, a reset or a re-application treats them ALL alike
# (INVARIANT: a table added here that is left out of _NS_TABLES would keep an abandoned branch's rows after a rewind)
_NS_TABLES = ("moves",) + DX.TABLES


def _log(msg):
    try:
        print(f"[execnode] asset history: {msg}", flush=True)
    except Exception:
        pass


class AssetHistoryStore:
    """The sqlite store. Every public method is failure-proof: an exception is logged, the store is DISABLED (every
    later call is a no-op) and the caller gets a neutral answer. `disabled` is what the endpoint reports."""

    def __init__(self, path):
        self.path = path
        self.disabled = False
        self._lock = threading.RLock()
        self._pending = {}             # ns -> [record, ...] buffered by the sinks until the block is flushed
        self._pending_dex = {}         # ns -> [DEX record, ...] (execnode/dex_trades.DexCallSink), likewise
        self._meta = {}                # ns -> (indexed_from, last), mirror of the meta table
        self._dex_start = {}           # ns -> the first block the DEX capture flushed (mirror of dex_meta)
        self._db = None
        try:
            self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            # WAL + NORMAL: a commit per block without an fsync per block (cold replay applies thousands a minute).
            # A crash can lose the newest flushes — trim() at start removes anything above the saved state anyway.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            for q in _SCHEMA:
                self._db.execute(q)
            self._meta = {ns: (int(f), int(la)) for ns, f, la in self._db.execute("SELECT ns, indexed_from, last FROM meta")}
            self._dex_start = {ns: int(st) for ns, st in self._db.execute("SELECT ns, start FROM dex_meta")}
        except Exception as e:
            self._fail("open", e)

    # ---- failure handling ---------------------------------------------------------------------------------------
    def _fail(self, what, e):
        """Disable for good (until the process restarts): a store that failed once is not trusted to be contiguous."""
        _log(f"{what} failed ({type(e).__name__}: {e}) — index DISABLED, block application unaffected")
        self.disabled = True
        self._pending = {}
        self._pending_dex = {}
        try:
            if self._db is not None:
                self._db.close()
        except Exception:
            pass
        self._db = None

    def close(self):
        with self._lock:
            try:
                if self._db is not None:
                    self._db.close()
            except Exception:
                pass
            self._db = None
            self.disabled = True

    # ---- capture --------------------------------------------------------------------------------------------------
    def sink(self, ns):
        """The callable ExecState.asset_sink takes for namespace `ns`: buffer one blob's records until flush_block."""
        def _sink(records):
            if self.disabled:
                return
            with self._lock:
                self._pending.setdefault(ns, []).extend(records)
        return _sink

    def dex_sink(self, ns, records):
        """Buffer one call's DEX records (execnode/dex_trades.DexCallSink) until flush_block."""
        if self.disabled:
            return
        with self._lock:
            self._pending_dex.setdefault(ns, []).extend(records)

    def flush_block(self, h, namespaces, ts=0):
        """Write block `h` for every namespace in ONE transaction: its buffered records (seq = order within the block),
        and `last = h`. A namespace whose last flushed block is not h-1 restarts its index at h (see the module note).
        `ts`: the block's timestamp (seconds) — the DEX index's time axis; display only, never consensus."""
        if self.disabled:
            return
        h = int(h)
        try:
            ts = int(ts or 0)
        except (TypeError, ValueError):
            ts = 0
        with self._lock:
            pending, self._pending = self._pending, {}
            pending_dex, self._pending_dex = self._pending_dex, {}
            try:
                db = self._db
                db.execute("BEGIN")
                new_meta, new_dex = dict(self._meta), dict(self._dex_start)
                for ns in namespaces:
                    recs = [r for r in pending.get(ns, ()) if int(r.get("cursor", -2)) == h]
                    stray = len(pending.get(ns, ())) - len(recs)
                    if stray:
                        _log(f"ns={ns}: dropped {stray} record(s) not of block {h}")
                    m = new_meta.get(ns)
                    if m is None:
                        frm = h
                    elif h <= m[1]:
                        frm = m[0]                     # re-application without a trim: replace what h.. held
                        for t in _NS_TABLES:
                            db.execute(f"DELETE FROM {t} WHERE ns=? AND cursor>=?", (ns, h))  # nosec B608 # t is one of _NS_TABLES (constant names); ns and h are bound
                        if h < frm:
                            frm = h
                    elif h == m[1] + 1:
                        frm = m[0]
                    else:
                        _log(f"ns={ns}: gap {m[1] + 1}..{h - 1} — history restarts at {h}")
                        for t in _NS_TABLES:
                            db.execute(f"DELETE FROM {t} WHERE ns=?", (ns,))  # nosec B608 # t is one of _NS_TABLES (constant names); the values are bound
                        new_dex.pop(ns, None)              # the DEX history restarts here too
                        frm = h
                    if recs:
                        db.executemany(
                            "INSERT OR REPLACE INTO moves (ns, cursor, seq, txid, sender, op, method, args, value,"
                            " call_asset, aid, holder, delta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(ns, h, i, r.get("txid", ""), r.get("sender", ""), r.get("op", ""), r.get("method", ""),
                              json.dumps(r.get("args") or []), r.get("value", "0"), r.get("call_asset", ""),
                              str(r["aid"]), str(r["holder"]), str(r["delta"])) for i, r in enumerate(recs)])
                    # the DEX capture's start: this block if it has none, or lower if this block is a re-application
                    if new_dex.get(ns) is None or h < new_dex[ns]:
                        new_dex[ns] = h
                        db.execute("INSERT OR REPLACE INTO dex_meta (ns, start) VALUES (?,?)", (ns, h))
                    drecs = [r for r in pending_dex.get(ns, ()) if int(r.get("cursor", -2)) == h]
                    if drecs:
                        DX.write_block(db, ns, h, ts, drecs)
                    db.execute("INSERT OR REPLACE INTO meta (ns, indexed_from, last) VALUES (?,?,?)", (ns, frm, h))
                    new_meta[ns] = (frm, h)
                db.execute("COMMIT")
                self._meta, self._dex_start = new_meta, new_dex
            except Exception as e:
                try:
                    self._db.execute("ROLLBACK")
                except Exception:
                    pass
                self._fail(f"flush of block {h}", e)

    def discard_pending(self):
        """Forget records of a block that did not complete (nothing of it is flushed)."""
        with self._lock:
            self._pending = {}
            self._pending_dex = {}

    # ---- exactness across restart and rewind ----------------------------------------------------------------------
    def trim(self, ns, cursor):
        """Delete everything ABOVE `cursor` for `ns`: the state is (back) at `cursor`, and the blocks after it will be
        applied again — onto an empty slot, so they can never duplicate or mix with an abandoned branch."""
        if self.disabled:
            return
        cursor = int(cursor)
        with self._lock:
            self._pending.pop(ns, None)
            self._pending_dex.pop(ns, None)
            try:
                db = self._db
                db.execute("BEGIN")
                for t in _NS_TABLES:
                    db.execute(f"DELETE FROM {t} WHERE ns=? AND cursor>?", (ns, cursor))  # nosec B608 # t is one of _NS_TABLES (constant names); the values are bound
                ds = self._dex_start.get(ns)
                if ds is not None and ds > cursor + 1:
                    db.execute("UPDATE dex_meta SET start=? WHERE ns=?", (cursor + 1, ns))
                m = self._meta.get(ns)
                nm = m
                if m is not None:
                    if m[0] > cursor:
                        db.execute("DELETE FROM meta WHERE ns=?", (ns,))
                        nm = None
                    elif m[1] > cursor:
                        db.execute("UPDATE meta SET last=? WHERE ns=?", (cursor, ns))
                        nm = (m[0], cursor)
                db.execute("COMMIT")
                if ds is not None and ds > cursor + 1:
                    self._dex_start[ns] = cursor + 1
                if nm is None:
                    self._meta.pop(ns, None)
                else:
                    self._meta[ns] = nm
            except Exception as e:
                try:
                    self._db.execute("ROLLBACK")
                except Exception:
                    pass
                self._fail(f"trim ns={ns} to {cursor}", e)

    def reset(self, ns):
        """Drop the namespace's whole index: its state was REPLACED (a donor snapshot), so what was indexed below the
        new cursor belongs to a lineage this node no longer holds. The next flushed block restarts it."""
        if self.disabled:
            return
        with self._lock:
            self._pending.pop(ns, None)
            self._pending_dex.pop(ns, None)
            if ns not in self._meta:
                try:
                    if all(self._db.execute(f"SELECT 1 FROM {t} WHERE ns=? LIMIT 1", (ns,)).fetchone() is None  # nosec B608 # t is one of _NS_TABLES (constant names); the values are bound
                           for t in _NS_TABLES):
                        return             # nothing indexed: the common case on a pruned cold start, kept cheap
                except Exception as e:
                    self._fail(f"reset ns={ns}", e)
                    return
            try:
                db = self._db
                db.execute("BEGIN")
                for t in _NS_TABLES:
                    db.execute(f"DELETE FROM {t} WHERE ns=?", (ns,))  # nosec B608 # t is one of _NS_TABLES (constant names); the values are bound
                db.execute("DELETE FROM meta WHERE ns=?", (ns,))
                db.execute("DELETE FROM dex_meta WHERE ns=?", (ns,))
                db.execute("COMMIT")
                self._meta.pop(ns, None)
                self._dex_start.pop(ns, None)
            except Exception as e:
                try:
                    self._db.execute("ROLLBACK")
                except Exception:
                    pass
                self._fail(f"reset ns={ns}", e)

    # ---- reads ----------------------------------------------------------------------------------------------------
    def indexed_from(self, ns):
        m = self._meta.get(ns)
        return None if m is None else m[0]

    def dex_indexed_from(self, ns):
        """The first cursor from which the DEX trade index is COMPLETE: the later of the asset history's start (gaps and
        resets move it) and the DEX capture's own start (the file may predate the capture)."""
        m, d = self._meta.get(ns), self._dex_start.get(ns)
        return None if m is None or d is None else max(m[0], d)

    def events(self, ns, aid, limit=LIMIT_DEFAULT, before=None):
        """The asset's history newest first, one event per (cursor, txid): {cursor, txid, sender, op, method, args,
        value, call_asset, moves: [{holder, delta}]}. `limit` counts events but never splits a cursor — every event of
        the oldest cursor returned is included — so `before=<that cursor>` pages exactly. Two indexed queries on
        (ns, aid, cursor, seq); never scans the chain. Returns (events, next_before or None)."""
        if self.disabled:
            return [], None
        limit = max(1, min(int(limit), LIMIT_MAX))
        top = (1 << 62) if before is None else int(before)
        with self._lock:
            try:
                db = self._db
                groups = db.execute(
                    "SELECT cursor, MIN(seq) AS s FROM moves WHERE ns=? AND aid=? AND cursor<? "
                    "GROUP BY cursor, txid ORDER BY cursor DESC, s DESC LIMIT ?", (ns, str(aid), top, limit)).fetchall()
                if not groups:
                    return [], None
                lo, hi = groups[-1][0], groups[0][0]
                rows = db.execute(
                    "SELECT cursor, seq, txid, sender, op, method, args, value, call_asset, holder, delta FROM moves "
                    "WHERE ns=? AND aid=? AND cursor>=? AND cursor<=? ORDER BY cursor, seq",
                    (ns, str(aid), lo, hi)).fetchall()
            except Exception as e:
                self._fail("query", e)
                return [], None
        out, at = [], {}
        for cur, _seq, txid, sender, op, method, args, value, call_asset, holder, delta in rows:
            key = (cur, txid)
            ev = at.get(key)
            if ev is None:
                try:
                    a = json.loads(args or "[]")
                except Exception:
                    a = []
                ev = at[key] = {"cursor": cur, "txid": txid, "sender": sender, "op": op, "method": method, "args": a,
                                "value": value, "call_asset": call_asset, "moves": []}
                out.append(ev)
            ev["moves"].append({"holder": holder, "delta": delta})
        out.reverse()                         # rows ran oldest first; events go out newest first
        return out, (lo if len(groups) >= limit else None)


    # ---- DEX reads (execnode/dex_trades.py) — the same failure rule: a broken query disables the store ----------------
    def _dex(self, fn, empty, *a):
        if self.disabled:
            return empty
        with self._lock:
            try:
                return fn(self._db, *a)
            except Exception as e:
                self._fail("dex query", e)
                return empty

    def dex_trades(self, ns, cid, pid=None, limit=DX.LIMIT_DEFAULT, before=None, trader=None):
        return self._dex(DX.trades, ([], None), ns, cid, pid, limit, before, trader)

    def dex_candles(self, ns, cid, pid, tf, limit=500):
        return self._dex(DX.candles, [], ns, cid, pid, tf, limit)

    def dex_stats(self, ns, cid, now=None):
        return self._dex(DX.stats, {}, ns, cid, now)


def open_store(path):
    """The store at `path`, or None if it cannot be opened (logged). Never raises."""
    try:
        s = AssetHistoryStore(path)
        return None if s.disabled else s
    except Exception as e:
        _log(f"open {path} failed ({type(e).__name__}: {e})")
        return None
