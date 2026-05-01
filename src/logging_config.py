import os
import sys
from loguru import logger

_log_initialized = False


def setup_logging():
    global _log_initialized
    if _log_initialized:
        return
    _log_initialized = True

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")

    # 移除默认 handler，避免重复输出到 stderr
    logger.remove()

    # 终端输出（INFO 级别以上）
    logger.add(sys.stderr, level="INFO", colorize=True,
               format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

    # 文件输出（每天轮转，保留7天）
    logger.add(log_path, rotation="1 day", retention="7 days", level="INFO", encoding="utf-8")

    logger.info("日志系统初始化完成")
