import os.path
import os
import shutil
from data_ops import get_home

to_wipeout = ["blocks", "logs", "index", "peers", "transactions"]


def delete(to_wipeout):
    for folder in to_wipeout:
        print(f"Removing {folder}")
        path = f"{get_home()}/{folder}"
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"Removed {path}")

delete(to_wipeout)