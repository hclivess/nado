import os


def make_folder(folder_name: str, strict: bool = True):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        return True
    else:
        if strict:
            raise ValueError(f"{folder_name} folder already exists")
        else:
            return False
