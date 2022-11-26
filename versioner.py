import glob
import hashlib


def get_version():
    base = glob.glob("*.py")
    loops = glob.glob("loops/*.py")
    htmls = glob.glob("templates/*.html")

    joint = base + loops + htmls

    hashes = []
    for file in joint:
        with open(file, "r") as infile:
            file_contents = infile.read()

            file_hash = hashlib.blake2b(repr((infile, file_contents)).encode()).hexdigest()
            hashes.append(file_hash)

    joint_hash = hashlib.blake2b(repr(hashes).encode(), digest_size=6).hexdigest()
    return joint_hash


if __name__ == "__main__":
    print(get_version())
