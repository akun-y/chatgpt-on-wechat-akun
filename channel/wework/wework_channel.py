import io
import os
import random
import sys
import tempfile
import threading

os.environ["ntwork_LOG"] = "ERROR"
import ntwork
import requests
import uuid

from bridge.context import *
from bridge.reply import *
from channel.chat_channel import ChatChannel
from channel.wework.wework_message import *
from channel.wework.wework_message import WeworkMessage
from common.singleton import singleton
from common.log import logger
from common.time_check import time_checker
from config import conf
from channel.wework.run import wework
from channel.wework import run
from PIL import Image
from typing import Optional

import time
import json
import re


def get_wxid_by_name(room_members: [], group_wxid, name) -> Optional[str]:
    for member in room_members.get("member_list", []):
        if member["room_nickname"] == name or member["username"] == name:
            return member["user_id"]
    return None  # 如果没有找到对应的group_wxid或name，则返回None


def download_and_compress_image(url, filename, quality=30):
    # 确定保存图片的目录
    directory = os.path.join(os.getcwd(), "tmp")
    # 如果目录不存在，则创建目录
    if not os.path.exists(directory):
        os.makedirs(directory)

    # 下载图片
    response = requests.get(url)
    image = Image.open(io.BytesIO(response.content))

    # 压缩图片
    image_path = os.path.join(directory, f"{filename}.jpg")
    image.save(image_path, "JPEG", quality=quality)

    return image_path


def download_video(url, filename):
    # 确定保存视频的目录
    directory = os.path.join(os.getcwd(), "tmp")
    # 如果目录不存在，则创建目录
    if not os.path.exists(directory):
        os.makedirs(directory)

    # 下载视频
    response = requests.get(url, stream=True)
    total_size = 0

    video_path = os.path.join(directory, f"{filename}.mp4")

    with open(video_path, "wb") as f:
        for block in response.iter_content(1024):
            total_size += len(block)

            # 如果视频的总大小超过30MB (30 * 1024 * 1024 bytes)，则停止下载并返回
            if total_size > 30 * 1024 * 1024:
                logger.info("[WX] Video is larger than 30MB, skipping...")
                return None

            f.write(block)

    return video_path


def create_message(wework_instance, message, is_group):
    logger.debug(f"正在为{'群聊' if is_group else '单聊'}创建 WeworkMessage")
    cmsg = WeworkMessage(message, wework=wework_instance, is_group=is_group)
    logger.debug(f"cmsg:{cmsg}")
    return cmsg


def handle_message(cmsg, is_group):
    logger.debug(f"准备用 WeworkChannel 处理{'群聊' if is_group else '单聊'}消息")
    if is_group:
        WeworkChannel().handle_group(cmsg)
    else:
        WeworkChannel().handle_single(cmsg)
    logger.debug(f"已用 WeworkChannel 处理完{'群聊' if is_group else '单聊'}消息")


def _check(func):
    def wrapper(self, cmsg: ChatMessage):
        msgId = cmsg.msg_id
        create_time = cmsg.create_time  # 消息时间戳
        if create_time is None:
            return func(self, cmsg)
        if int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[WX]history message {} skipped".format(msgId))
            return
        return func(self, cmsg)

    return wrapper


@wework.msg_register(
    [ntwork.MT_RECV_TEXT_MSG, ntwork.MT_RECV_IMAGE_MSG, 11072, ntwork.MT_RECV_VOICE_MSG]
)
def all_msg_handler(wework_instance: ntwork.WeWork, message):
    logger.debug(f"收到消息: {message}")
    if "data" in message:
        # 首先查找conversation_id，如果没有找到，则查找room_conversation_id
        conversation_id = message["data"].get(
            "conversation_id", message["data"].get("room_conversation_id")
        )
        if conversation_id is not None:
            is_group = "R:" in conversation_id
            try:
                cmsg = create_message(
                    wework_instance=wework_instance, message=message, is_group=is_group
                )
            except NotImplementedError as e:
                logger.error(f"[WX]{message.get('MsgId', 'unknown')} 跳过: {e}")
                return None
            delay = random.randint(1, 2)
            timer = threading.Timer(delay, handle_message, args=(cmsg, is_group))
            timer.start()
        else:
            logger.debug("消息数据中无 conversation_id")
            return None
    return None


def accept_friend_with_retries(wework_instance, user_id, corp_id):
    result = wework_instance.accept_friend(user_id, corp_id)
    logger.debug(f"result:{result}")


# @wework.msg_register(ntwork.MT_RECV_FRIEND_MSG)
# def friend(wework_instance: ntwork.WeWork, message):
#     data = message["data"]
#     user_id = data["user_id"]
#     corp_id = data["corp_id"]
#     logger.info(f"接收到好友请求，消息内容：{data}")
#     delay = random.randint(1, 180)
#     threading.Timer(delay, accept_friend_with_retries, args=(wework_instance, user_id, corp_id)).start()
#
#     return None


def get_with_retry(get_func, max_retries=5, delay=5):
    retries = 0
    result = None
    while retries < max_retries:
        result = get_func()
        if result:
            break
        logger.warning(f"获取数据失败，重试第{retries + 1}次······")
        retries += 1
        time.sleep(delay)  # 等待一段时间后重试
    return result


@singleton
class WeworkChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()

    def startup(self):
        smart = conf().get("wework_smart", True)
        wework.open(smart)
        logger.info("等待登录······")

        wework.wait_login()
        login_info = wework.get_login_info()
        self.user_id = login_info["user_id"]
        self.name = (
            login_info["nickname"] if login_info["nickname"] else login_info["username"]
        )
        logger.info(f"登录信息:>>>user_id:{self.user_id}>>>>>>>>name:{self.name}")
        logger.info("静默延迟60s，等待客户端刷新数据，请勿进行任何操作······")
        time.sleep(60)
        contacts = get_with_retry(wework.get_external_contacts)
        rooms = get_with_retry(wework.get_rooms)
        directory = os.path.join(os.getcwd(), "tmp")
        if not contacts or not rooms:
            logger.error("获取contacts或rooms失败，程序退出")
            ntwork.exit_()
            sys.exit(0)
        if not os.path.exists(directory):
            os.makedirs(directory)
        # 将contacts保存到json文件中
        with open(
            os.path.join(directory, "wework_contacts.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(contacts, f, ensure_ascii=False, indent=4)
        with open(
            os.path.join(directory, "wework_rooms.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(rooms, f, ensure_ascii=False, indent=4)
        # 创建一个空字典来保存结果
        result = {}

        # 遍历列表中的每个字典
        for room in rooms["room_list"]:
            # 获取聊天室ID
            room_wxid = room["conversation_id"]
            room_nickname = room.get("nickname", "")
            # 获取聊天室成员
            room_members = wework.get_room_members(room_wxid)
            if room_members:
                room_members['nickname'] = room_nickname
                # 将聊天室成员保存到结果字典中
                result[room_wxid] = room_members
        # 将结果保存到json文件中
        with open(os.path.join(directory, "wework_room_members.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=4)

        logger.info("wework程序初始化完成········")
        run.forever()

    @time_checker
    @_check
    def handle_single(self, cmsg: ChatMessage):
        if cmsg.ctype == ContextType.VOICE:
            if not conf().get("speech_recognition"):
                return
            logger.debug("[WX]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[WX]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug(
                "[WX]receive text msg: {}, cmsg={}".format(
                    json.dumps(cmsg._rawmsg, ensure_ascii=False), cmsg
                )
            )
        else:
            logger.debug("[WX]receive msg: {}, cmsg={}".format(cmsg.content, cmsg))
        context = self._compose_context(
            cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg
        )
        if context:
            self.produce(context)

    @time_checker
    @_check
    def handle_group(self, cmsg: ChatMessage):
        if cmsg.ctype == ContextType.VOICE:
            if not conf().get("speech_recognition"):
                return
            logger.debug("[WX]receive voice for group msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image for group msg: {}".format(cmsg.content))
        elif cmsg.ctype in [ContextType.JOIN_GROUP, ContextType.PATPAT]:
            logger.debug("[WX]receive note msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            pass
        else:
            logger.debug("[WX]receive group msg: {}".format(cmsg.content))
        context = self._compose_context(
            cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg
        )
        if context:
            self.produce(context)

    # 统一的发送函数，每个Channel自行实现，根据reply的type字段发送不同类型的消息
    def send(self, reply: Reply, context: Context):
        ret = False
        receiver = context["receiver"]
        
        if reply.type == ReplyType.TEXT or reply.type == ReplyType.TEXT_:
            match = re.search(r"^@(.*?)\n", reply.content)
            if match:
                # 提取@的用户名
                name = match.group(1)  # 获取第一个组的内容，即名字

                cmsg = context.get("msg", None)
                room_wxid = cmsg.other_user_id or context.get("session_id", "")
                room_members = wework.get_room_members(room_wxid)
                wxid = get_wxid_by_name(room_members, receiver, name)
                if wxid:
                    new_content = reply.content.replace(f"@{name}", "")
                    # wxid_list = [actual_user_id for actual_user_id in match.group(1).split()]
                    wxid_list = [wxid]
                    ret = wework.send_room_at_msg(receiver, new_content, wxid_list)
                else:
                    ret = wework.send_text(receiver, reply.content)
                # wxid_list = [actual_user_id for actual_user_id in match.group(1).split()]
                # wework.send_room_at_msg(receiver, new_content, wxid_list)
                # wework.send_room_at_msg(receiver, new_content,[self.user_id])
            else:
                wework.send_text(receiver, reply.content)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))
        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            ret = wework.send_text(receiver, reply.content)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))
        elif reply.type == ReplyType.IMAGE:  # 从文件读取图片
            image_storage = reply.content
            # 检查 reply.content 是字符串还是文件句柄
            if isinstance(image_storage, str):
                # 如果是字符串，假设它是文件路径或内容
                logger.info(
                    "[WX] reply.content is a string, treating as file path or content"
                )
                # 发送图片
                wework.send_image(receiver, image_storage)
                logger.info("[WX] sendImage, receiver={}".format(receiver))
                return
            elif isinstance(image_storage, (io.IOBase, io.BufferedReader, io.BytesIO)):
                # 如果是文件句柄，seek 到开头并读取
                image_storage.seek(0)
                data = image_storage.read()
            else:
                raise ValueError(
                    f"Unsupported reply.content type: {type(image_storage)}"
                )

            # 创建临时文件
            with tempfile.NamedTemporaryFile(delete=False) as temp:
                temp_path = temp.name
                temp.write(data)

            # 发送图片
            ret = wework.send_image(receiver, temp_path)
            logger.info("[WX] sendImage, receiver={}".format(receiver))

            # 删除临时文件
            os.remove(temp_path)
        elif reply.type == ReplyType.IMAGE_URL:  # 从网络下载图片
            img_url = reply.content
            filename = str(uuid.uuid4())

            # 调用你的函数，下载图片并保存为本地文件
            image_path = download_and_compress_image(img_url, filename)

            ret = wework.send_image(receiver, file_path=image_path)
            logger.info("[WX] sendImage url={}, receiver={}".format(img_url, receiver))
        elif reply.type == ReplyType.VIDEO_URL:
            video_url = reply.content
            filename = str(uuid.uuid4())
            video_path = download_video(video_url, filename)

            if video_path is None:
                # 如果视频太大，下载可能会被跳过，此时 video_path 将为 None
                ret = wework.send_text(receiver, "抱歉，视频太大了！！！")
            else:
                ret = wework.send_video(receiver, video_path)
            logger.info("[WX] sendVideo, receiver={}".format(receiver))
        elif reply.type == ReplyType.VIDEO:
            video_path = reply.content
            if exists := os.path.exists(video_path):
                if not exists:
                    logger.error("[WX] Video file does not exist: {}".format(video_path))                    
                    return
            ret = wework.send_video(receiver, video_path)
            logger.info("[WX] sendVideo, receiver={}".format(receiver))
        elif reply.type == ReplyType.VOICE:
            ret = wework.send_file(receiver, reply.content)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))
        else:
            logger.error(
                "[WX] Unsupported reply type: {}, content: {}".format(
                    reply.type, reply.content
                )
            )
            raise NotImplementedError(
                f"Unsupported reply type: {reply.type}, content: {reply.content}"
            )
        return ret
