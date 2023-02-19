import tarfile
from ops.data_ops import get_home


def make_archive(output_filename, source_dirs):
    with tarfile.open(f"{output_filename}.tar.gz", "w:gz") as tar:
        for file in source_dirs:
            try:
                print("Compressing", file)
                tar.add(file, arcname=file)
            except Exception as e:
                print(f"Error compressing {file}: {e}")

        print("Compression finished for", source_dirs)

if __name__ == "__main__":
    source_dirs = [f"{get_home()}/blocks", f"{get_home()}/index", f"{get_home()}/peers"]
    output_filename = "nado_archive"

    make_archive(output_filename, source_dirs)