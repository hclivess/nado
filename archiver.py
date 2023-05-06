import tarfile
from ops.data_ops import get_home
from pathlib import Path


def make_archive(output_filename, source_dirs):
    with tarfile.open(f"{output_filename}.tar.gz", "w:gz") as tar:
        for path in source_dirs:
            try:
                print("Compressing", path["files"])
                tar.add(path["files"], arcname=path["dir"])
            except Exception as e:
                print(f"Error compressing {path}: {e}")

        print("Compression finished for", source_dirs)


if __name__ == "__main__":
    source_dirs = [
        {"files": f"{get_home()}/peers", "dir": "peers"},
        {"files": f"{get_home()}/blocks", "dir": "blocks"},
        {"files": f"{get_home()}/index", "dir": "index"},
        {"files": f"{get_home()}/peers", "dir": "peers"}
    ]

    output_filename = "nado_archive"

    make_archive(output_filename, source_dirs)
