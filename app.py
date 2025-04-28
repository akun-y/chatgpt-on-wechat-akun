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
    """Wrap the signal handler to handle program termination and daily restart
    Args:
        _signo: Signal number
    """
    from datetime import datetime, time
    import schedule
    
    def check_restart_time():
        restart_time = conf().get("restart_time", "01:00")  # Default restart at 1 AM
        try:
            hour, minute = map(int, restart_time.split(":"))
            if datetime.now().time() >= time(hour, minute):
                logger.info("Daily restart time reached, performing graceful shutdown...")
                conf().save_user_datas()
                os._exit(0)  # Program will be restarted by external process manager
        except ValueError:
            logger.error(f"Invalid restart_time format: {restart_time}, should be HH:MM")
    
    # Schedule daily restart check
    schedule.every(1).minutes.do(check_restart_time)


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

        # Add scheduler runner
        import schedule
        import time
        def run_scheduler():
            while True:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
                
        import threading
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
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
