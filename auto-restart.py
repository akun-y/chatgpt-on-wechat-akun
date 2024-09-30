from datetime import datetime, timedelta
import sys
import threading
from loguru import logger
import os
import signal

from app import run_app

def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        if callable(old_handler):  # check old_handler
            return old_handler(_signo, _stack_frame)
        sys.exit(0)

    signal.signal(_signo, func)

def calc_delay():
    # 计算当前时间到明天2:01:01的时间差
    now = datetime.now()
    run_time = now.replace(hour=1, minute=2, second=25, microsecond=0)
    if now >= run_time:  # 如果当前时间已经超过了今天的2:01:01，则设置为明天
        run_time += timedelta(days=1)

    # 计算延迟时间
    delay = (run_time - now).total_seconds()
    return delay


def restart_app():
    global running
    while True:  # 添加循环以每20秒重启一次
        # ctrl + c
        sigterm_handler_wrap(signal.SIGINT)
        # kill signal
        sigterm_handler_wrap(signal.SIGTERM)
        # 启动 run_app 的线程
        app_thread = threading.Thread(target=run_app)
        app_thread.start()

        delay = calc_delay()

        app_thread.join(timeout=delay)

        if app_thread.is_alive():
            logger.info(
                "App did not finish in {} seconds. Terminating...".format(delay)
            )
            running = False

        logger.info("App finished running. Restarting...")
        running = True  # 重置 running 为 True 以便重新启动


if __name__ == "__main__":
    logger.info("Starting the app with periodic restarts...")
    try:
        restart_app()
    except KeyboardInterrupt:
        logger.info("App interrupted by user. Exiting...")
        os._exit(0)
