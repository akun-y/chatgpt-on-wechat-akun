import os
from loguru import logger as logger_instance
import sys

from config import conf

# 确保 Python 环境使用 UTF-8 编码
os.environ["PYTHONIOENCODING"] = "utf-8"


# 为警告级别的日志添加别名
def warn(*args, **kwargs):
    logger.warning(*args, **kwargs)


# 将 warn 函数添加到 logger 对象中
logger_instance.warn = warn

# 示例日志记录
# logger.info("这是一个信息日志")
# logger.error("这是一个错误日志")
# logger.warning('This is a warning message')
# logger.warn('This is another warning message')  # 使用别名记录告日志

logger = logger_instance

def set_logger():
    level = "DEBUG" if conf().get("debug") == True else "INFO"
    print(f"set_logger level: {level}")
    # 配置日志记录器
    logger.remove()  # 移除默认的日志记录器
    # 添加控制台日志记录器，设置为 info 级别
    logger.add(
        sink=sys.stdout,
        format="<level>{level:.4} <blue>{time:HH:mm:ss}</blue> {message} </level><blue>[{file}:{line}]</blue>",
        level=level,
        colorize=True,  # 控制台日志彩色输出
    )

    # 添加文件日志记录器，按日期命名，设置为 info 级别
    logger.add(
        "logs/run_{time:YYYY-MM-DD}.log",
        format="[{level}][{time:YYYY-MM-DD HH:mm:ss}] {message} [{file}:{line}]",
        rotation="1 day",  # 每天午夜轮换日志文件
        encoding="utf-8",
        level=level,
    )

    # 添加错误日志记录器，按日期命名，设置为 error 级别
    logger.add(
        "logs/err_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="[{level}][{time:YYYY-MM-DD HH:mm:ss}] {message} [{file}:{line}]",
        rotation="1 day",  # 每天午夜轮换日志文件
        encoding="utf-8",
    )


def _reset_logger(logger_instance):
    """重置logger配置"""
    set_logger()
    return logger_instance
