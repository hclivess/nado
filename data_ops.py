import random
import sys
import os
import re
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


def sort_occurence(some_list) -> list:
    """takes list of values, returns list with unique values sorted by occurrence"""
    total = {value: some_list.count(value) for value in some_list}
    sorted_total = sorted(total, key=total.get, reverse=True)
    return sorted_total


def set_and_sort(entries: list) -> list:
    sorted_entries = sorted(list(set(entries)))
    return sorted_entries


def average(list) -> int:
    sum = 0
    for value in list:
        sum = sum + value
    return int(sum / len(list))


def sort_list_dict(entries) -> list:
    clean_list = []
    for entry in entries:
        if entry not in clean_list:
            clean_list.append(entry)
    return clean_list


def get_byte_size(object) -> int:
    return sys.getsizeof(repr(object))


def shuffle_dict(dictionary) -> dict:
    items = list(dictionary.items())
    random.shuffle(items)
    shuffled_dict = {}
    for key, value in items:
        shuffled_dict[key] = value
    return shuffled_dict