import tarfile
import argparse
from ops.data_ops import get_home

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
    parser = argparse.ArgumentParser(description="Backup specified folders into a tar.gz archive.")
    parser.add_argument("--backup", nargs="*", help="List of folders to backup. If not provided, all folders will be backed up.")
    parser.add_argument("--output", default="nado_archive", help="Output filename for the archive.")

    args = parser.parse_args()

    if args.backup:
        source_dirs = [
            {"files": f"{get_home()}/{folder}", "dir": folder} for folder in args.backup
        ]
    else:
        source_dirs = [
            {"files": f"{get_home()}/peers", "dir": "peers"},
            {"files": f"{get_home()}/blocks", "dir": "blocks"},
            {"files": f"{get_home()}/index", "dir": "index"},
        ]

    make_archive(args.output, source_dirs)