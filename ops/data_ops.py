import asyncio
import os
import random
import re
import sys
from pathlib import Path


def get_home():
    return f"{Path.home()}/nado"


def check_traversal(to_check):
    allowed = "^\w+$"
    if not re.search(allowed, to_check):
        raise ValueError(f"Traversal attack attempt with [{to_check}]")


def dict_to_val_list(some_dict) -> list:
    return_list = []
    for value in some_dict.values():
        return_list.append(value)
    return return_list


def sort_occurrence(some_list) -> list:
    """takes list of values, returns list with unique values sorted by occurrence"""
    total = {value: some_list.count(value) for value in some_list}
    sorted_total = sorted(total, key=total.get, reverse=True)
    return sorted_total


def set_and_sort(entries: list) -> list:
    sorted_entries = sorted(list(set(entries)))
    return sorted_entries


def average(list_of_values) -> int:
    total = 0
    for value in list_of_values:
        total = total + value
    return int(total / len(list_of_values))


def sort_list_dict(entries) -> list:
    clean_list = []
    for entry in entries:
        if entry not in clean_list:
            clean_list.append(entry)
    return clean_list


def get_byte_size(size_of) -> int:
    return sys.getsizeof(repr(size_of))


def shuffle_dict(dictionary) -> dict:
    items = list(dictionary.items())
    random.shuffle(items)
    shuffled_dict = {}
    for key, value in items:
        shuffled_dict[key] = value
    return shuffled_dict


def allow_async():
    if sys.platform == "win32" and sys.version_info >= (3, 8, 0):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def make_folder(folder_name: str, strict: bool = True):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        return True
    else:
        if strict:
            raise ValueError(f"{folder_name} folder already exists")
        else:
            return False
