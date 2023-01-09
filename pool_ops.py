from data_ops import get_byte_size, sort_list_dict
from transaction_ops import max_from_transaction_pool


def merge_buffer(from_buffer, to_buffer, limit, block_max, block_min) -> dict:
    """tool to transition between 3 transaction buffers"""
    from_buffer = sort_list_dict(from_buffer)

    for item in range(len(from_buffer)):
        if get_byte_size(to_buffer) < limit:

            tx_to_merge = max_from_transaction_pool(from_buffer, key="fee")
            if tx_to_merge not in to_buffer and block_min < tx_to_merge["target_block"] <= block_max:
                to_buffer.append(tx_to_merge)
                from_buffer.remove(tx_to_merge)
        else:
            break

    to_buffer = sort_list_dict(to_buffer)

    return {"from_buffer": from_buffer,
            "to_buffer": to_buffer}


def get_from_pool(pool, source, target):
    for item in pool.copy().items():
        target[item[0]] = item[1][source]
