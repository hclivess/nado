import json
import os
from os import getcwd


def update_version():
    try:
        version_path = f"{getcwd()}/.git/refs/heads/main"
        if os.path.exists(version_path):
            with open(version_path) as version_file:
                return version_file.read().strip()
        else:
            return False
    except Exception as e:
        print(f"Unable to obtain version, switching to N/A: {e}")
        return "na"


def set_version(version):
    with open("version", "w") as version_file:
        json.dump(version, version_file)


def read_version():
    # `version` is a runtime-derived build artifact (git HEAD), NOT tracked in git — see .gitignore. Fall
    # back to reading HEAD directly (fresh clone before the first boot writes the file), then "na" (a tarball
    # deploy with neither the file nor a .git dir), so a missing file never crashes startup.
    try:
        with open("version", "r") as version_file:
            return json.load(version_file)
    except Exception:
        return update_version() or "na"


if __name__ == "__main__":
    new_version = update_version()
    if new_version:
        set_version(new_version)
    print(read_version())
