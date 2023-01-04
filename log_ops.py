import logging
import os.path
from logging.handlers import RotatingFileHandler

import coloredlogs

from data_ops import get_home
from dircheck import make_folder


def get_logger(max_detail=False, file="log.log"):
    if not os.path.exists(f"{get_home()}/logs"):
        make_folder(f"{get_home()}/logs", strict=False)

    # Create a logger object.
    format = "%(asctime)s %(levelname)s %(message)s"

    logger = logging.getLogger(__name__)
    logger.propagate = False
    file_handler = RotatingFileHandler(
        f"{get_home()}/logs/{file}", maxBytes=10000000, backupCount=10, mode="a"
    )
    file_handler.setFormatter(logging.Formatter(format))
    logger.addHandler(file_handler)

    if max_detail:
        coloredlogs.install(level="DEBUG")

    coloredlogs.install(level="DEBUG", logger=logger, fmt=format)
    return logger


if __name__ == "__main__":
    # Some examples.
    logger = get_logger(file=f"{get_home()}/logs.log")

    logger.debug("this is a debugging message")
    logger.info("this is an informational message")
    logger.warning("this is a warning message")
    logger.error("this is an error message")
    logger.critical("this is a critical message")
