from data_ops import get_byte_size, sort_list_dict
from transaction_ops import max_from_transaction_pool


def merge_buffer(from_buffer, to_buffer) -> dict:
    while get_byte_size(to_buffer) < 250000 and from_buffer:
        to_buffer = sort_list_dict(to_buffer)

        tx_to_merge = max_from_transaction_pool(from_buffer, key="fee")
        if tx_to_merge not in to_buffer:
            to_buffer.append(tx_to_merge)
            from_buffer.remove(tx_to_merge)

        from_buffer = sort_list_dict(from_buffer)

    return {"from_buffer": from_buffer,
            "to_buffer": to_buffer}
