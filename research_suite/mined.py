from ops.sqlite_ops import DbHandler
from ops.data_ops import get_home
import matplotlib.pyplot as plt
import pandas as pd

acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
fetched = acc_handler.db_fetch("SELECT * FROM acc_index")
acc_handler.close()

print(fetched)

pd.set_option("display.max_rows", None)
mined = pd.DataFrame(fetched, columns =['Address', 'Balance', 'Produced', 'Burned'])
print(mined)
#plt.figure()


#mined.plot.bar()


plt.title("Rewards received")
plt.xlabel("Address")
plt.ylabel("Block Reward Count")
plt.locator_params(axis='both', nbins=4)
p = plt.bar(mined.Address, mined.Produced)
plt.xticks(rotation=-90)
plt.show()
