import os
import os.path
import shutil

from ops.data_ops import get_home

to_wipeout = ["blocks", "logs", "index"]


def delete(to_wipeout):
    for folder in to_wipeout:
        print(f"Removing {folder}")
        path = f"{get_home()}/{folder}"
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"Removed {path}")

delete(to_wipeout)