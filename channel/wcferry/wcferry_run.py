import logging
import os
import time
from queue import Empty
from threading import Thread

os.environ['ntchat_LOG'] = "ERROR"

from wcferry import Wcf

wcf = Wcf(debug=False)
LOG = logging.getLogger("wcferry")

def forever():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        wcf.cleanup()  # 退出前清理环境
        exit(0)
        os._exit(0)
        # sys.exit(0)
