import json
import os
import subprocess

# repo root (this file lives there) — used instead of getcwd() so the stamp resolves regardless of the
# process's working directory (systemd may launch us from /).
_REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def update_version():
    """Release stamp for /status + logs: the git TAG via `git describe` — e.g. 'v1.0.0-beta.1' on a tagged
    release commit, 'v1.0.0-beta.1-45-g6f2a758' a few commits past the last tag (with '-dirty' if the tree
    has uncommitted tracked changes), or the short commit hash when the repo has no tags. Falls back to the
    raw main ref (a .git dir but no git binary), then False (no git at all — read_version() maps that to 'na')."""
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=_REPO_DIR, stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    try:
        with open(f"{_REPO_DIR}/.git/refs/heads/main") as version_file:
            return version_file.read().strip()
    except Exception:
        return False


def set_version(version):
    """Persist the derived stamp into the untracked `version` file (JSON), relative to the process
    CWD — written at node startup so read_version() works even after the .git dir goes away."""
    with open("version", "w") as version_file:
        json.dump(version, version_file)


def read_version():
    """The version string surfaced in /status and logs: the cached `version` file if present, else
    a live git describe via update_version(), else 'na'. Never raises."""
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
