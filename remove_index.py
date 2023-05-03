import sqlite3
from ops.data_ops import get_home

db = sqlite3.connect(f"{get_home()}/index/transactions.db")
c = db.cursor()

c.execute("DELETE FROM tx_index")
db.commit()
c.execute("VACUUM")
db.commit()