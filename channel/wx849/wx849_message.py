import os
import time
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from config import conf

class WX849Message(ChatMessage):
    """
    wx849 消息处理类 - 适配 gewechat 的方式
    """
    def __init__(self, msg: Dict[str, Any], is_group: bool = False):
        super().__init__(msg)
        self.msg = msg
        self.content = ''  # 初始化self.content为空字符串，与gewechat保持一致

        # 提取消息基本信息
        self.msg_id = msg.get("msgid", msg.get("MsgId", msg.get("id", "")))
        if not self.msg_id:
            self.msg_id = f"msg_{int(time.time())}_{hash(str(msg))}"

        self.create_time = msg.get("timestamp", msg.get("CreateTime", msg.get("createTime", int(time.time()))))
        self.is_group = is_group

        # 提取发送者和接收者ID
        self.from_user_id = self._get_string_value(msg.get("fromUserName", msg.get("FromUserName", "")))
        self.to_user_id = self._get_string_value(msg.get("toUserName", msg.get("ToUserName", "")))

        # 提取消息内容
        self.content = self._get_string_value(msg.get("content", msg.get("Content", "")))

        # 获取消息类型
        self.msg_type = msg.get("type", msg.get("Type", msg.get("MsgType", 0)))

        # 初始化其他字段
        self.sender_wxid = ""      # 实际发送者ID
        self.at_list = []          # 被@的用户列表
        self.ctype = ContextType.UNKNOWN
        self.self_display_name = "" # 机器人在群内的昵称
        self.image_info = {}       # 图片信息
        self.image_path = ""       # 图片本地路径

        # 添加与gewechat兼容的字段
        self.actual_user_id = ""    # 实际发送者ID
        self.actual_user_nickname = "" # 实际发送者昵称
        self.other_user_id = self.from_user_id  # 群ID（群聊）或对方ID（私聊），与gewechat保持一致
        self.other_user_nickname = ""  # 群名称（群聊）或对方昵称（私聊），与gewechat保持一致
        self.is_at = False  # 是否被@，与gewechat保持一致
        self.my_msg = False  # 是否是自己发送的消息，与gewechat保持一致

        # 针对引用的内容进行字段处理
        self.quoted_message = {}
        if self.msg_type == 49:
           self.quoted_message = msg.get("QuotedMessage", {})

        # 尝试从MsgSource中提取机器人在群内的昵称
        try:
            msg_source = msg.get("MsgSource", "")
            if msg_source and ("<msgsource>" in msg_source.lower() or msg_source.startswith("<")):
                root = ET.fromstring(msg_source if "<msgsource>" in msg_source.lower() else f"<msgsource>{msg_source}</msgsource>")

                # 查找displayname或其他可能包含群昵称的字段
                for tag in ["selfDisplayName", "displayname", "nickname"]:
                    elem = root.find(f".//{tag}")
                    if elem is not None and elem.text:
                        self.self_display_name = elem.text
                        break

                # 检查是否被@，与gewechat保持一致
                atuserlist_elem = root.find('atuserlist')
                if atuserlist_elem is not None and atuserlist_elem.text:
                    # 提取@列表
                    at_users = atuserlist_elem.text.split(",")
                    for user in at_users:
                        if user.strip():
                            self.at_list.append(user.strip())
                    # 检查是否@了机器人
                    self.is_at = self.to_user_id in self.at_list
        except Exception as e:
            # 解析失败，保持为空字符串
            pass

    def _get_string_value(self, value):
        """确保值为字符串类型"""
        if isinstance(value, dict):
            return value.get("string", "")
        return str(value) if value is not None else ""

    # 以下是公开接口方法，提供给外部使用
    def get_content(self):
        """获取消息内容"""
        return self.content

    def get_type(self):
        """获取消息类型"""
        return self.ctype

    def get_msg_id(self):
        """获取消息ID"""
        return self.msg_id

    def get_create_time(self):
        """获取消息创建时间"""
        return self.create_time

    def get_from_user_id(self):
        """获取原始发送者ID"""
        return self.from_user_id

    def get_sender_id(self):
        """获取处理后的实际发送者ID（群聊中特别有用）"""
        return self.sender_wxid or self.from_user_id

    def get_to_user_id(self):
        """获取接收者ID"""
        return self.to_user_id

    def get_at_list(self):
        """获取被@的用户列表"""
        return self.at_list

    def is_at(self, wxid):
        """检查指定用户是否被@"""
        return wxid in self.at_list

    def is_group_message(self):
        """判断是否为群消息"""
        return self.is_group

    def _prepare_fn(self):
        """准备函数，用于下载图片等资源
        这个函数会被插件调用，用于确保资源已经准备好
        """
        # 对于图片消息，确保图片已下载
        if self.ctype == ContextType.IMAGE and hasattr(self, '_channel'):
            import asyncio
            import threading

            # 如果已经有图片路径且文件存在，直接返回
            if self.image_path and os.path.exists(self.image_path):
                return

            # 否则尝试下载图片
            try:
                # 使用线程运行异步下载函数
                if hasattr(self._channel, '_download_image'):
                    from common.log import logger
                    logger.info(f"[WX849Message] 开始下载图片: {self.msg_id}")

                    # 创建事件循环
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # 直接在当前线程中运行异步函数
                    try:
                        success = loop.run_until_complete(self._channel._download_image(self))
                        loop.close()

                        if success:
                            logger.info(f"[WX849Message] 图片下载成功: {self.image_path}")
                            # 检查图片是否下载成功
                            if self.image_path and os.path.exists(self.image_path):
                                # 更新content为图片路径
                                self.content = self.image_path
                                # 设置_prepared标志
                                self._prepared = True
                                return
                        else:
                            logger.error(f"[WX849Message] 图片下载失败")
                    except Exception as loop_err:
                        logger.error(f"[WX849Message] 运行异步下载函数失败: {loop_err}")

                    # 如果上面的方法失败，尝试使用线程方法
                    logger.info(f"[WX849Message] 尝试使用线程方法下载图片")
                    thread = threading.Thread(
                        target=lambda: asyncio.run(self._channel._download_image(self))
                    )
                    thread.start()
                    thread.join(timeout=15)  # 最多等待15秒

                    # 检查图片是否下载成功
                    if self.image_path and os.path.exists(self.image_path):
                        # 更新content为图片路径
                        self.content = self.image_path
                        # 设置_prepared标志
                        self._prepared = True
            except Exception as e:
                from common.log import logger
                logger.error(f"[WX849Message] 准备图片失败: {e}")
                import traceback
                logger.error(traceback.format_exc())