# encoding:utf-8

import os
import signal
import sys
from common.log import logger
from channel import channel_factory
from common.log import set_logger
from config import conf, load_config
from plugins.plugin_manager import PluginManager

def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        conf().save_user_datas()
        if callable(old_handler):  # check old_handler
            return old_handler(_signo, _stack_frame)
        os._exit(0)

    signal.signal(_signo, func)


def run_app():
    try:
        # load config
        load_config()
        # set logger
        set_logger()
        # ctrl + c
        sigterm_handler_wrap(signal.SIGINT)
        # kill signal
        sigterm_handler_wrap(signal.SIGTERM)

        # create channel
        channel_name = conf().get("channel_type", "ntchat")

        if "--cmd" in sys.argv:
            channel_name = "terminal"

        channel = channel_factory.create_channel(channel_name)
        if channel_name in ["wcferry","ntchat", "wework", "weworktop",'wechatmp_service','wechatmp']:
            PluginManager().load_plugins()

        # startup channel
        channel.startup()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, exiting...")
        os._exit(0)
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)


if __name__ == "__main__":
    run_app()
