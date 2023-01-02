from log_ops import get_logger
from block_ops import load_block_from_hash

logger = get_logger()
block_hash = "6514c2b2fac0d1e820c1d24dbcf36dd34532b59ed4c268b15c341663ce505b9f"
old_block_number = 0
oks = 0

while block_hash:
    try:
        block = load_block_from_hash(block_hash, logger=logger)
        block_hash = block["child_hash"]
        block_number = block["block_number"]

        if block_number == old_block_number + 1:
            oks += 1
            old_block_number = block_number
    except Exception as e:
        print(e)
        print(block_number)
        break

print(f"consistent blocks: {oks}")