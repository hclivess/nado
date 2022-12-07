from block_ops import get_latest_block_info, load_block_from_hash
from config import get_timestamp_seconds
from log_ops import get_logger


#  not used


def find_block(parameter, value, logger):
    latest_block_info = get_latest_block_info(logger=logger)

    current_block_message = load_block_from_hash(
        block_hash=latest_block_info["latest_block_hash"], logger=logger
    )
    current_parameter = current_block_message[parameter]

    while current_parameter != value:
        """if the desired is not the latest one"""
        current_block_message = load_block_from_hash(
            block_hash=current_block_message["parent_hash"], logger=logger
        )
        current_parameter = current_block_message[parameter]

    return current_block_message


if __name__ == "__main__":
    logger = get_logger(file="seek.log")
    start = get_timestamp_seconds()
    print(find_block(parameter="block_timestamp", value=1655912367, logger=logger))
    passed = get_timestamp_seconds() - start
    print(passed)
