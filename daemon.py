import os
import sys
import time
print("Daemon started...")
time.sleep(1)
os.execv(sys.executable, ['python'] + sys.argv)