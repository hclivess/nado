import py7zr

from ops.data_ops import get_home


def make_archive(output_filename, source_dirs):
    with py7zr.SevenZipFile(output_filename, 'w') as z:
        for dir in source_dirs:
            print(f"processing {dir}")
            z.writeall(dir, arcname="nado")


if __name__ == "__main__":
    source_dirs = [f"{get_home()}/blocks", f"{get_home()}/index", f"{get_home()}/peers"]
    output_filename = "nado_archive.7z"

    make_archive(output_filename, source_dirs)
