# -*- coding: utf-8 -*-

import logging
import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread

from wcferry import Wcf, WxMsg

from config import conf, load_config
from common.log import logger


__version__ = "39.0.10.1"


class Robot:
    """个性化自己的机器人"""

    def __init__(self, wcf: Wcf, all_msg_handler) -> None:
        self.wcf = wcf
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts()
       # self.chatrooms = self.getAllrooms()
        self.msgHandler = all_msg_handler

        logger.warning("未配置模型")
        self.chat = None   
        logger.info(f"AI模型已选择: {self.chat}")
        

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(
                value is not None for key, value in args.items() if key != "proxy"
            )
        return False

    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        return self.toChitchat(msg)

    def toChengyu(self, msg: WxMsg) -> bool:
        pass

    def toChitchat(self, msg: WxMsg) -> bool:
        """闲聊，接入 ChatGPT"""
        if not self.chat:  # 没接 ChatGPT，固定回复
            rsp = "你好啊,找我有事吗？"
        else:  # 接了 ChatGPT，智能回复
            q = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
            rsp = self.chat.get_answer(
                q, (msg.roomid if msg.from_group() else msg.sender)
            )

        if rsp:
            if msg.from_group():
                self.sendTextMsg(rsp, msg.roomid, msg.sender)
            else:
                pass
                # self.sendTextMsg(rsp, msg.sender)

            return True
        else:
            logger.error(f"无法从 ChatGPT 获得答案")
            return False
    def shorten_text(self,text, max_length=20):
        if len(text) <= max_length:
            return text
        else:
            return text[:max_length-3] + "..."
    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """

        # 群聊消息
        if msg.from_group():         
            if msg.from_self():
                logger.info(f"===>自己发出(群聊):{msg.roomid}-{msg.content}")  
            # 进入消息处理函数
            self.msgHandler(self.wcf, msg)
            return  # 处理完群聊信息，后面就不需要处理了

        # 非群聊信息，按消息类型进行处理
        if msg.type == 37:  # 好友请求
            self.autoAcceptFriendRequest(msg)

        elif msg.type == 10000:  # 系统信息
            self.sayHiToNewFriend(msg)

        elif msg.type == 0x01:  # 私聊文本消息
            # 让配置加载更灵活，自己可以更新配置。也可以利用定时任务更新。
            if msg.from_self():
                logger.info(f"===>自己发出(私聊): {msg.content}")
                if msg.content == "^更新$":
                    #  self.config.reload()
                    load_config()
                    logger.info("已更新配置文件")
                    self.sendTextMsg("已经重新载入配置文件", msg.sender)
            else:  # 进入消息处理函数
                self.msgHandler(self.wcf, msg)
        elif msg.type == 0x03:  # 私聊图片消息
            self.msgHandler(self.wcf, msg)
        elif msg.type == 49:  # 共享实时位置、文件、转账、链接
            logger.warning(f"收到消息类型：{msg.type}")
        else:
            logger.warn(f"收到消息类型：{msg.type}")

    def onMsg(self, msg: WxMsg) -> int:
        try:
            # logger.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            logger.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    logger.debug(msg)
                    self.processMsg(msg)
                except Empty:
                    continue  # Empty message
                except Exception as e:
                    logger.error(f"Receiving message error: {e}")
                    logger.error(traceback.format_exc())

        self.wcf.enable_receiving_msg()
        Thread(
            target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True
        ).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            if at_list == "notify@all":  # @所有人
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid in wxids:
                    # 根据 wxid 查找群昵称
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid, receiver)}"

        # {msg}{ats} 表示要发送的消息内容后面紧跟@，例如 北京天气情况为：xxx @张三
        if ats == "":
            #logger.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            logger.info(f"To {receiver}: {ats}\r{msg}")
            self.wcf.send_text(f"{ats}\n\n{msg}", receiver, at_list)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql(
            "MicroMsg.db", "SELECT UserName, NickName FROM Contact;"
        )
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)
            logger.warn(f"同意好友请求：{v3}，{v4}，{scene}")

        except Exception as e:
            logger.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(
                f"Hi {nickName[0]}，我自动通过了你的好友请求。", msg.sender
            )
