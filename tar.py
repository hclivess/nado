import py7zr


def make_archive(output_filename, source_dirs):
    with py7zr.SevenZipFile(output_filename, 'w') as z:
        for dir in source_dirs:
            print(f"processing {dir}")
            z.writeall(dir)


if __name__ == "__main__":
    source_dirs = ["blocks", "index", "peers", "transactions", "accounts"]
    output_filename = "archive.7z"

    make_archive(output_filename, source_dirs)
