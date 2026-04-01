"""日志工具"""
from loguru import logger
import sys

def setup_logger(verbose=False):
    """配置日志"""
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
        logger.add("flight_scraper.log", rotation="10 MB", level="DEBUG")
    else:
        logger.add("flight_scraper.log", rotation="10 MB", level="INFO")
    return logger
