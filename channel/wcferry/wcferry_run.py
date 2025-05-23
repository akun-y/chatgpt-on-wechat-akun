import json
import logging
import os
import time
from queue import Empty
from threading import Thread
from common.log import logger
from config import conf

os.environ["ntchat_LOG"] = "ERROR"

from wcferry import Wcf

wcf = Wcf(debug=True if conf().get("debug") else False)


def forever():
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 这里可以执行任何清理工作
        print("Cleaning up...")
        wcf.cleanup()  # 退出前清理环境
        # exit(0)
        os._exit(0)
        # sys.exit(0)


# 专用于保存联系人,群聊,群成员信息
def save_json_to_file(directory, contacts, filename):
    try:
        # 检查目录是否存在，如果不存在则创建
        if not os.path.exists(directory):
            os.makedirs(directory)
        # 生成文件路径
        file_path = os.path.join(directory, filename)
        # 打开文件并写入数据
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=4)

        logger.info(f"json saved to {file_path}")

    except Exception as e:
        logger.error(f"Failed to write to file: {e}")


# 专用于读取联系人,群聊,群成员信息
def load_json_from_file(directory, filename):
    try:
        # 生成文件路径
        file_path = os.path.join(directory, filename)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No such file: '{file_path}'")

        # 打开文件并读取数据
        with open(file_path, "r", encoding="utf-8") as f:
            contacts = json.load(f)

        print(f"Successfully loaded from {file_path}")
        return contacts

    except Exception as e:
        print(f"Failed to read from file: {e}")
        return None
    
# 专用于groupx返回的用户信息
def save_wxgroups_to_file(rooms:dict,directory=None,file_name=None):
    if not directory:
        directory = os.path.join(os.getcwd(), "tmp")
    if not directory:
        os.makedirs(directory, exist_ok=True)
    if not file_name:
        file_name = "wcferry_rooms.json"   

    save_json_to_file(directory, rooms, file_name)