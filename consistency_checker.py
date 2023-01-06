from log_ops import get_logger
from block_ops import load_block_from_hash
import pandas as pd


logger = get_logger()
block_hash = "6514c2b2fac0d1e820c1d24dbcf36dd34532b59ed4c268b15c341663ce505b9f"
miners = []

def check_consistency(block_hash, logger):
    old_block_number = 0
    oks = 0

    try:
        while block_hash:
            block = load_block_from_hash(block_hash, logger=logger)
            block_hash = block["child_hash"]
            block_number = block["block_number"]
            if block_number > 11000:
                miners.append(block["block_creator"])

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
print("Element Count")
print(count)
