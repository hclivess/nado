import sqlite3
import threading
import time
from ops.log_ops import get_logger, logging

sqlite_logger = get_logger(file="sqlite.log", logger_name="sqlite_logger")

# One live connection per (thread, db_file). The old DbHandler opened a NEW connection AND
# re-issued four PRAGMAs (incl. journal_mode=WAL) on EVERY query, then closed it -- the
# connect/teardown dominated the cost of each tiny point lookup and piled onto the write
# lock under load (a real "node gets stuck" contributor). Reusing a per-thread connection
# removes that overhead; WAL still lets the many Tornado reader threads run concurrently
# with the single writer thread. Connections are closed when the thread tears down.
_local = threading.local()


def _is_locked(error) -> bool:
    """transient contention worth retrying (vs. a permanent schema/programming error)"""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _get_connection(db_file, timeout):
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    con = cache.get(db_file)
    if con is None:
        con = sqlite3.connect(db_file, timeout=timeout)
        # PRAGMAs applied ONCE per connection, not per query
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA temp_store=MEMORY")
        cache[db_file] = con
    return con


def close_thread_connections():
    """close every cached connection for the current thread (call on thread teardown)"""
    cache = getattr(_local, "conns", None)
    if not cache:
        return
    for con in cache.values():
        try:
            con.close()
        except Exception:
            pass
    cache.clear()


class DbHandler:
    def __init__(self, db_file, retry_delay=0.05, max_retries=200, timeout=30.0):
        self.db_file = db_file
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.logger = sqlite_logger
        self.con = _get_connection(db_file, timeout)
        self.cur = self.con.cursor()

    def _run(self, runner, query, args):
        """run a cursor operation, retrying only on transient lock contention.
        Permanent errors (bad schema/query) are raised instead of looping forever."""
        attempt = 0
        while True:
            try:
                with self.con:
                    return runner(query, *args)
            except Exception as e:
                if _is_locked(e):
                    attempt += 1
                    if attempt >= self.max_retries:
                        self.logger.error(f"{e} | {query} | giving up after {attempt} locked attempts")
                        raise
                    time.sleep(self.retry_delay)
                    continue
                self.logger.error(f"{e} | {query}")
                raise

    def db_execute(self, query, *args):
        self._run(self.cur.execute, query, args)
        return True

    def db_change(self, query, *args):
        """execute a write and return the number of rows affected (for guarded UPDATEs)"""
        self._run(self.cur.execute, query, args)
        return self.cur.rowcount

    def db_executemany(self, query, *args):
        self._run(self.cur.executemany, query, args)
        return True

    def db_fetch(self, query, *args):
        return self._run(lambda q, *a: self.cur.execute(q, *a).fetchall(), query, args)

    def close(self):
        # The connection is shared per-thread and reused across handlers; closing it here
        # would break other handlers on the same thread. Intentionally a no-op -- use
        # close_thread_connections() on thread teardown. Only the cursor is dropped.
        try:
            self.cur.close()
        except Exception:
            pass


if __name__ == "__main__":
    dbhandler = DbHandler(db_file="../test.db")
    dbhandler.db_execute("CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER)")
    dbhandler.db_execute("INSERT INTO tx_index VALUES (?, ?)", ('a', '1'))
    print(dbhandler.db_fetch("SELECT * FROM tx_index"))
    dbhandler.close()
