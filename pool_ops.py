from data_ops import get_byte_size, sort_list_dict
from transaction_ops import max_from_transaction_pool


def merge_buffer(from_buffer, to_buffer, limit, block_max) -> dict:
    """tool to transition between 3 transaction buffers"""

    while get_byte_size(to_buffer) < limit and from_buffer:
        to_buffer = sort_list_dict(to_buffer)

        tx_to_merge = max_from_transaction_pool(from_buffer, key="fee")
        if tx_to_merge not in to_buffer and tx_to_merge["target_block"] < block_max:
            to_buffer.append(tx_to_merge)
            from_buffer.remove(tx_to_merge)

        from_buffer = sort_list_dict(from_buffer)
        break

    return {"from_buffer": from_buffer,
            "to_buffer": to_buffer}


def get_from_pool(pool, source, target):
    for item in pool.copy().items():
        target[item[0]] = item[1][source]
