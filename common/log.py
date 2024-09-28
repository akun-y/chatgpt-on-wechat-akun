from loguru import logger
import sys
import logging

# 配置日志记录
logger.remove()  # 移除默认的日志记录器

# 添加控制台日志记录器
logger.add(sys.stdout, format="[{level}][{time:HH:mm:ss}]-{message} [{file}:{line}]")

# 添加文件日志记录器，按日期命名
logger.add("logs/run_{time:YYYY-MM-DD}.log", format="[{level}][{time:YYYY-MM-DD HH:mm:ss}] - {message} [{file}:{line}]", rotation="00:00", encoding="utf-8")

# 添加错误日志记录器，按日期命名
logger.add("logs/err_{time:YYYY-MM-DD}.log", level="ERROR", format="[{level}][{time:YYYY-MM-DD HH:mm:ss}] - {message} [{file}:{line}]", rotation="00:00", encoding="utf-8")

# 兼容 Python 自带的 logging 模块的输入参数
class InterceptHandler(logging.Handler):
    def emit(self, record):
        # 获取 loguru 的 logger
        loguru_logger = logger.opt(depth=6, exception=record.exc_info)
        loguru_logger.log(record.levelname, record.getMessage())

logging.basicConfig(handlers=[InterceptHandler()], level=0)

# 示例日志记录
logger.info("这是一个信息日志")
logger.error("这是一个错误日志")

# 正确的用法
logger.warning('This is a warning message')
# 添加 warn 方法作为 warning 方法的别名
logger.warn = logger.warning
logger.warn('This is a warning message2')