import sqlite3
import time
from ops.log_ops import get_logger, logging

sqlite_logger = get_logger(file="sqlite.log", logger_name="sqlite_logger")


class DbHandler:
    def __init__(self, db_file, retry_delay=1):
        self.con = sqlite3.connect(db_file)
        self.cur = self.con.cursor()
        self.retry_delay = retry_delay
        self.logger = sqlite_logger

    def db_execute(self, query, *args):
        while True:
            try:
                with self.con:
                    self.cur.execute(query, *args)
                    self.con.commit()
                return True
            except Exception as e:
                self.logger.info(e, query, *args)
                time.sleep(self.retry_delay)

    def db_executemany(self, query, *args):
        while True:
            try:
                with self.con:
                    self.cur.executemany(query, *args)
                    self.con.commit()
                return True
            except Exception as e:
                self.logger.info(e, query, *args)
                time.sleep(self.retry_delay)

    def db_fetch(self, query, *args):
        while True:
            try:
                with self.con:
                    self.cur.execute(query, *args)
                    result = self.cur.fetchall()
                return result
            except Exception as e:
                self.logger.info(e, query, *args)
                time.sleep(self.retry_delay)

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