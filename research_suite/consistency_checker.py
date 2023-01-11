from log_ops import get_logger
from block_ops import load_block_from_hash
import pandas as pd
import matplotlib.pyplot as plt
MIN_BLOCK = 20000

logger = get_logger()
block_hash = "6514c2b2fac0d1e820c1d24dbcf36dd34532b59ed4c268b15c341663ce505b9f"
miners = []
tx_count = []

def check_consistency(block_hash, logger):
    old_block_number = 0
    oks = 0

    try:
        while block_hash:
            block = load_block_from_hash(block_hash, logger=logger)
            block_hash = block["child_hash"]
            block_number = block["block_number"]
            if block_number >= MIN_BLOCK:
                miners.append(block["block_creator"])
                tx_count.append(len(block["block_transactions"]))

            if block_number == old_block_number + 1:
                oks += 1
                old_block_number = block_number
    except Exception as e:
        print(e)
    finally:
        return oks


print(check_consistency(block_hash, logger))

#print(miners)
pd.set_option("display.max_rows", None)
count = pd.Series(miners).value_counts()

p = plt.bar(count.index, count.values)
plt.xticks(rotation=-90)
plt.show()


print("Element Count")
print(count)
print(tx_count)

x_axis = []
y_axis = []

for x in enumerate(tx_count):

    if x[1] != 0:
        print(x[1])
        x_axis.append(x[0])
        y_axis.append(x[1])

plt.scatter(x_axis, y_axis)
plt.draw()

plt.xticks(rotation=-90)
plt.show()

