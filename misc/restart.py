import os
import sys
from os.path import getmtime

WATCHED_FILES = [__file__]
WATCHED_FILES_MTIMES = [(f, getmtime(f)) for f in WATCHED_FILES]

ux = ["Linux", "posix"]
wins = ["nt"]

while True:
    for f, mtime in WATCHED_FILES_MTIMES:
        if getmtime(f) != mtime:
            print('--> restarting')
            if os.name in ux:
                os.execv(__file__, sys.argv)
            elif os.name in wins:
                os.execv(sys.executable, ['python'] + sys.argv)
