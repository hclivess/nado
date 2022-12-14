import json
import os
from os import getcwd


def update_version():
    version_path = f"{getcwd()}/.git/refs/heads/main"
    if os.path.exists(version_path):
        with open(version_path) as version_file:
            return version_file.read().strip()
    else:
        return False


def set_version(version):
    with open("version", "w") as version_file:
        json.dump(version, version_file)


def read_version():
    with open("version", "r") as version_file:
        return json.load(version_file)


if __name__ == "__main__":
    new_version = update_version()
    if new_version:
        set_version(new_version)
    print(read_version())
