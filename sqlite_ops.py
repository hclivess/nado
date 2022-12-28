import sqlite3


class DbHandler:
    def __init__(self, db_file):
        self.con = sqlite3.connect(db_file)
        self.cur = self.con.cursor()

    def db_execute(self, query):
        try:
            with self.con:
                self.cur.execute(query)
                self.con.commit()
            return True
        except Exception as e:
            return False

    def db_fetch(self, query):
        try:
            with self.con:
                self.cur.execute(query)
                result = self.cur.fetchall()
            return result
        except Exception as e:
            return False

    def close(self):
        self.con.close()


if __name__ == "__main__":
    dbhandler = DbHandler(db_file="test.db")
    dbhandler.db_execute(query="CREATE TABLE IF NOT EXISTS tx_index(tx UNIQUE, account, block)")
    dbhandler.db_execute(query="INSERT INTO tx_index VALUES('a', '1')")
    print(dbhandler.db_fetch(query="SELECT tx,block FROM tx_index"))
    dbhandler.close()
