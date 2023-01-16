import matplotlib.pyplot as plt
import pandas as pd

from ops.block_ops import load_block_from_hash
from ops.log_ops import get_logger
from ops.transaction_ops import to_readable_amount

MIN_BLOCK = 65000

logger = get_logger()
block_hash = "d3996da8cd07efa3c69f37641ea822cd66492a00b50f393a802880d9455a3539"
miners = []
tx_count = []


def check_consistency(block_hash, logger):
    rewards = 0
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
                rewards += block["block_reward"]

            if block_number == old_block_number + 1:
                oks += 1
                old_block_number = block_number
        print(to_readable_amount(rewards))
    except Exception as e:
        print(e)
    finally:

        return oks


print(check_consistency(block_hash, logger))

#print(miners)
pd.set_option("display.max_rows", None)
count = pd.Series(miners).value_counts()

plt.title("Block Rewards")
plt.xlabel("Address")
plt.ylabel("Block Reward Count")
plt.locator_params(axis='both', nbins=4)
p = plt.bar(count.index, count.values)
plt.xticks(rotation=-90)
plt.show()

print("Element Count")
print(count)
print(tx_count)

txs = pd.Series(tx_count)
print(txs)
plt.title("Transactions per Blocks")
plt.xlabel("Block Number")
plt.ylabel("Transaction Count")
plt.scatter(txs.index, txs.values)
plt.xticks(rotation=-90)
plt.show()

