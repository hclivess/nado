import sqlite3
import time
from ops.log_ops import get_logger, logging

sqlite_logger = get_logger(file="sqlite.log", logger_name="sqlite_logger")


def _is_locked(error) -> bool:
    """transient contention that is worth retrying (vs. a permanent schema/programming error)"""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "locked" in message or "busy" in message


class DbHandler:
    def __init__(self, db_file, retry_delay=1, max_retries=20, timeout=30.0):
        # timeout lets SQLite itself wait for a lock instead of raising instantly
        self.con = sqlite3.connect(db_file, timeout=timeout)
        self.cur = self.con.cursor()
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.logger = sqlite_logger
        self._configure()

    def _configure(self):
        """WAL lets readers (e.g. tx-history queries) run concurrently with the writer
        (block production) without blocking each other, and is faster for our workload."""
        try:
            self.cur.execute("PRAGMA journal_mode=WAL")
            self.cur.execute("PRAGMA synchronous=NORMAL")
            self.cur.execute("PRAGMA busy_timeout=30000")
            self.cur.execute("PRAGMA temp_store=MEMORY")
        except Exception as e:
            self.logger.info(f"Failed to apply pragmas: {e}")

    def _run(self, runner, query, args):
        """run a cursor operation, retrying only on transient lock contention.
        Permanent errors (bad schema/query) are raised instead of looping forever."""
        attempt = 0
        while True:
            try:
                with self.con:
                    result = runner(query, *args)
                return result
            except Exception as e:
                if _is_locked(e):
                    attempt += 1
                    self.logger.info(f"{e} | {query} | locked, attempt {attempt}")
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(self.retry_delay)
                    continue
                # permanent error: surface it rather than hang the caller forever
                self.logger.error(f"{e} | {query}")
                raise

    def db_execute(self, query, *args):
        self._run(self.cur.execute, query, args)
        return True

    def db_executemany(self, query, *args):
        self._run(self.cur.executemany, query, args)
        return True

    def db_fetch(self, query, *args):
        return self._run(lambda q, *a: self.cur.execute(q, *a).fetchall(), query, args)

    def close(self):
        self.con.close()


if __name__ == "__main__":
    dbhandler = DbHandler(db_file="../test.db")
    dbhandler.db_execute("CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER)")
    dbhandler.db_execute("INSERT INTO tx_index VALUES (?, ?)", ('a', '1'))
    dbhandler.db_execute("INSERT INTO tx_index VALUES (?, ?)", ('b', '2'))
    dbhandler.db_execute("DELETE FROM tx_index WHERE block_number = ?", '1')

    rows = [('d', '3'), ('e', '4')]
    query = "INSERT INTO tx_index VALUES (?, ?)"
    dbhandler.db_executemany(query, rows)

    rows = ['1', '2']
    query = "DELETE FROM tx_index WHERE block_number = ?"
    dbhandler.db_executemany(query, rows)

    print(dbhandler.db_fetch("SELECT * FROM tx_index WHERE block_number = ?", '2'))
    dbhandler.close()
