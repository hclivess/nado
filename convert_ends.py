from ops.data_ops import get_home
import json

genesis = "6514c2b2fac0d1e820c1d24dbcf36dd34532b59ed4c268b15c341663ce505b9f"

with open(f"{get_home()}/index/latest_block.dat", "r") as old:
    old_format = json.load(old)

new_dict = {"earliest_block": genesis,
            "latest_block": old_format}

with open(f"{get_home()}/index/block_ends.dat", "w") as new:
    json.dump(new_dict, new)
