import logging
import os.path
import sys
from logging.handlers import RotatingFileHandler

import coloredlogs

from .data_ops import get_home, make_folder

# WINDOWS FIX: the console defaults to a legacy code page (cp1252) there, so logging any message that
# contains a non-cp1252 character — e.g. a localized OS error string like the Czech "Vzdálený počítač
# odmítl…" from a refused connection — raised UnicodeEncodeError inside the log handler and spammed a
# giant traceback (or killed the log thread). Force UTF-8 with errors="replace" on the std streams so a
# stray character can never crash logging. No-op where already UTF-8 (Linux/macOS) or unsupported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def get_logger(logger_name, max_detail=False, file="log.log"):
    """Build a named logger writing to a rotating file under ~/logs (3 MB x 10 backups) plus a
    coloredlogs console. Both sinks use UTF-8 with errors='replace' so a localized OS error string
    can never crash logging (see the Windows fix above); propagate=False keeps root handlers from
    double-printing. max_detail additionally installs DEBUG-level console logging globally."""
    if not os.path.exists(f"{get_home()}/logs"):
        make_folder(f"{get_home()}/logs", strict=False)

    # Create a logger object with the specified name.
    format = "%(asctime)s %(levelname)s %(message)s"

    logger = logging.getLogger(logger_name)
    logger.propagate = False
    file_handler = RotatingFileHandler(
        f"{get_home()}/logs/{file}", maxBytes=3000000, backupCount=10, mode="a",
        encoding="utf-8", errors="replace",   # never let a non-ASCII OS error string crash the log file
    )
    file_handler.setFormatter(logging.Formatter(format))
    logger.addHandler(file_handler)

    if max_detail:
        coloredlogs.install(level="DEBUG")

    coloredlogs.DEFAULT_LEVEL_STYLES = dict(
        spam=dict(color='green', faint=True),
        debug=dict(color='green', bright=True),
        verbose=dict(color='blue'),
        info=dict(color='white', bright=True),
        notice=dict(color='magenta'),
        warning=dict(color='yellow', bright=True),
        success=dict(color='green', bold=True),
        error=dict(color='red'),
        critical=dict(color='red', bold=True),
    )

    coloredlogs.install(level="DEBUG", logger=logger, fmt=format)
    return logger


if __name__ == "__main__":
    # Some examples.
    logger = get_logger(logger_name="demo_logger", file=f"demo.log")

    logger.debug("this is a debugging message")
    logger.info("this is an informational message")
    logger.warning("this is a warning message")
    logger.error("this is an error message")
    logger.critical("this is a critical message")