# encoding:utf-8

import os
import signal
import sys
import time
from common.log import logger, set_log_level
# 添加lib目录到Python路径，解决wx849模块导入问题
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(current_dir, "lib")
if os.path.exists(lib_dir) and lib_dir not in sys.path:
    sys.path.append(lib_dir)
    print(f"已添加lib目录到Python路径: {lib_dir}")
    # 特别处理wx849模块路径
    wx849_dir = os.path.join(lib_dir, "wx849")
    if os.path.exists(wx849_dir) and wx849_dir not in sys.path:
        sys.path.append(wx849_dir)
        print(f"已添加wx849目录到Python路径: {wx849_dir}")

from channel import channel_factory
from common import const
from config import load_config
from plugins import *
import threading


def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        conf().save_user_datas()
        if callable(old_handler):  #  check old_handler
            return old_handler(_signo, _stack_frame)
        sys.exit(0)

    signal.signal(_signo, func)


def start_channel(channel_name: str):
    channel = channel_factory.create_channel(channel_name)
    if channel_name in ["wx", "wxy", "terminal", "wechatmp","wechatmp_service", "wechatcom_app", "wework",
                        "wechatcom_service", "gewechat", "web", "wx849"]:

        PluginManager().load_plugins()

    if conf().get("use_linkai"):
        try:
            from common import linkai_client
            threading.Thread(target=linkai_client.start, args=(channel,)).start()
        except Exception as e:
            pass
    channel.startup()


def run():
    try:
        # load config
        load_config()

        # 获取配置的日志级别，默认为 INFO 以减少输出
        set_log_level("DEBUG" if conf().get("debug", False) else "INFO")
        # ctrl + c
        sigterm_handler_wrap(signal.SIGINT)
        # kill signal
        sigterm_handler_wrap(signal.SIGTERM)

        # create channel
        channel_name = conf().get("channel_type", "wx")

        if "--cmd" in sys.argv:
            channel_name = "terminal"

        if channel_name == "wxy":
            os.environ["WECHATY_LOG"] = "warn"

        start_channel(channel_name)

        while True:
            time.sleep(1)
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)


if __name__ == "__main__":
    run()
