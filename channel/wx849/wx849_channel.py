import asyncio
import os
import json
import time
import threading
import io
import sys
import traceback  # 添加traceback模块导入
import xml.etree.ElementTree as ET  # 在顶部添加ET导入
import aiohttp  # 添加aiohttp模块导入
import re  # 添加re模块导入
from typing import Dict, Any, Optional, List, Tuple
import urllib.parse  # 添加urllib.parse模块导入
import requests
from bridge.context import Context, ContextType  # 确保导入Context类
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.chat_message import ChatMessage
from channel.wx849.wx849_message import WX849Message  # 改为从wx849_message导入WX849Message
from common.expired_dict import ExpiredDict
from common.log import logger, set_log_level
from common.singleton import singleton
from common.time_check import time_checker
from common.utils import remove_markdown_symbol
from config import conf, get_appdata_dir
# 新增HTTP服务器相关导入
from aiohttp import web
import uuid
import re
import base64
import subprocess
import math
from io import BytesIO
from PIL import Image

# 增大日志行长度限制，以便完整显示XML内容
try:
    import logging
    # 尝试设置日志格式化器的最大长度限制
    for handler in logging.getLogger().handlers:
        if hasattr(handler, 'formatter'):
            handler.formatter._fmt = handler.formatter._fmt.replace('%(message)s', '%(message).10000s')
    logger.info("[WX849] 已增大日志输出长度限制")
except Exception as e:
    logger.warning(f"[WX849] 设置日志长度限制失败: {e}")

# 添加 wx849 目录到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
# 修改路径查找逻辑，确保能找到正确的 lib/wx849 目录
# 尝试多种可能的路径
lib_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))), "lib", "wx849")
if not os.path.exists(lib_dir):
    # 如果路径不存在，尝试项目根目录下的 lib/wx849
    lib_dir = os.path.join(os.path.dirname(os.path.dirname(current_dir)), "..", "lib", "wx849")
    if not os.path.exists(lib_dir):
        # 如果还是不存在，尝试使用相对路径
        lib_dir = os.path.join(os.path.dirname(os.path.dirname(current_dir)), "lib", "wx849")
        if not os.path.exists(lib_dir):
            # 最后尝试使用绝对路径 /root/dow-849/lib/wx849
            lib_dir = os.path.join("/root", "dow-849", "lib", "wx849")

# 打印路径信息以便调试
logger.info(f"WechatAPI 模块搜索路径: {lib_dir}")

if os.path.exists(lib_dir):
    if lib_dir not in sys.path:
        sys.path.append(lib_dir)
    # 直接添加 WechatAPI 目录到路径
    wechat_api_dir = os.path.join(lib_dir, "WechatAPI")
    if os.path.exists(wechat_api_dir) and wechat_api_dir not in sys.path:
        sys.path.append(wechat_api_dir)
    # 添加上级目录到路径以便可以通过 wx849.WechatAPI 方式导入
    parent_dir = os.path.dirname(lib_dir)
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    logger.info(f"已添加 WechatAPI 模块路径: {lib_dir}")
    logger.info(f"Python 搜索路径: {sys.path}")
else:
    logger.error(f"WechatAPI 模块路径不存在: {lib_dir}")

# 导入 WechatAPI 客户端
try:
    # 使用不同的导入方式尝试
    try:
        # 尝试方式1：直接导入
        import WechatAPI
        from WechatAPI import WechatAPIClient
        logger.info("成功导入 WechatAPI 模块（方式1）")
    except ImportError:
        try:
            # 尝试方式2：从相对路径导入
            from lib.wx849.WechatAPI import WechatAPIClient
            import lib.wx849.WechatAPI as WechatAPI
            logger.info("成功导入 WechatAPI 模块（方式2）")
        except ImportError:
            try:
                # 尝试方式3：从项目根目录导入
                sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
                from lib.wx849.WechatAPI import WechatAPIClient
                import lib.wx849.WechatAPI as WechatAPI
                logger.info("成功导入 WechatAPI 模块（方式3）")
            except ImportError:
                # 尝试方式4：从wx849包导入
                sys.path.append(os.path.dirname(lib_dir))
                from WechatAPI import WechatAPIClient
                import WechatAPI
                logger.info("成功导入 WechatAPI 模块（方式4）")

    # 设置 WechatAPI 的 loguru 日志级别（关键修改）
    try:
        from loguru import logger as api_logger
        import logging

        # 移除所有现有处理器
        #api_logger.remove()

        # 获取配置的日志级别，默认为 ERROR 以减少输出
        log_level = conf().get("debug", False) 
        if log_level:
            log_level = "DEBUG"
        else:
            log_level = "INFO"
        set_log_level(log_level)

        # 添加新的处理器，仅输出 ERROR 级别以上的日志
       # api_logger.add(sys.stderr, level=log_level)
        logger.info(f"已设置 WechatAPI 日志级别为: {log_level}")
    except Exception as e:
        logger.error(f"设置 WechatAPI 日志级别时出错: {e}")
except Exception as e:
    logger.error(f"导入 WechatAPI 模块失败: {e}")
    # 打印更详细的调试信息
    logger.error(f"当前Python路径: {sys.path}")

    # 检查目录内容
    if os.path.exists(lib_dir):
        logger.info(f"lib_dir 目录内容: {os.listdir(lib_dir)}")
        wechat_api_dir = os.path.join(lib_dir, "WechatAPI")
        if os.path.exists(wechat_api_dir):
            logger.info(f"WechatAPI 目录内容: {os.listdir(wechat_api_dir)}")

    raise ImportError(f"无法导入 WechatAPI 模块，请确保 wx849 目录已正确配置: {e}")

# 添加 ContextType.PAT 类型（如果不存在）
if not hasattr(ContextType, 'PAT'):
    setattr(ContextType, 'PAT', 'PAT')
if not hasattr(ContextType, 'QUOTE'):
    setattr(ContextType, 'QUOTE', 'QUOTE')
# 添加 ContextType.UNKNOWN 类型（如果不存在）
if not hasattr(ContextType, 'UNKNOWN'):
    setattr(ContextType, 'UNKNOWN', 'UNKNOWN')
# 添加 ContextType.XML 类型（如果不存在）
if not hasattr(ContextType, 'XML'):
    setattr(ContextType, 'XML', 'XML')
    logger.info("[WX849] 已添加 ContextType.XML 类型")
# 添加其他可能使用的ContextType类型
if not hasattr(ContextType, 'LINK'):
    setattr(ContextType, 'LINK', 'LINK')
    logger.info("[WX849] 已添加 ContextType.LINK 类型")
if not hasattr(ContextType, 'FILE'):
    setattr(ContextType, 'FILE', 'FILE')
    logger.info("[WX849] 已添加 ContextType.FILE 类型")
if not hasattr(ContextType, 'MINIAPP'):
    setattr(ContextType, 'MINIAPP', 'MINIAPP')
    logger.info("[WX849] 已添加 ContextType.MINIAPP 类型")
if not hasattr(ContextType, 'SYSTEM'):
    setattr(ContextType, 'SYSTEM', 'SYSTEM')
    logger.info("[WX849] 已添加 ContextType.SYSTEM 类型")
if not hasattr(ContextType, 'VIDEO'):
    setattr(ContextType, 'VIDEO', 'VIDEO')
    logger.info("[WX849] 已添加 ContextType.VIDEO 类型")

def _check(func):
    def wrapper(self, cmsg: ChatMessage):
        msgId = cmsg.msg_id

        # 如果消息ID为空，生成一个唯一ID
        if not msgId:
            msgId = f"msg_{int(time.time())}_{hash(str(cmsg.msg))}"
            logger.debug(f"[WX849] _check: 为空消息ID生成唯一ID: {msgId}")

        # 检查消息时间是否过期
        create_time = cmsg.create_time  # 消息时间戳
        current_time = int(time.time())

        # 设置超时时间为60秒
        timeout = 60
        if int(create_time) < current_time - timeout:
            logger.debug(f"[WX849] 历史消息 {msgId} 已跳过，时间差: {current_time - int(create_time)}秒")
            return

        # 直接调用原始处理函数，不再使用独立线程
        # 因为消息已经在独立线程中处理了
        return func(self, cmsg)
    return wrapper

@singleton
class WX849Channel(ChatChannel):
    """
    wx849 channel - 独立通道实现
    """
    NOT_SUPPORT_REPLYTYPE = []

    # 创建一个全局锁，用于线程安全的消息去重
    _message_lock = threading.Lock()

    # 创建一个全局集合，用于记录已处理的消息ID
    _processed_message_ids = set()

    # 不再使用单独的图片消息ID集合，所有消息ID都记录在_processed_message_ids中

    def _process_single_message_independently(self, msg_id: str, msg: dict):
        """在独立线程中处理单条消息"""
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 记录处理信息
            thread_id = threading.get_ident()
            logger.debug(f"[WX849] 独立消息处理线程 {thread_id} 开始处理 - 消息ID: {msg_id}")

            try:
                # 构建标准的消息对象
                is_group = False

                # 判断是否是群消息
                from_user_id = msg.get("fromUserName", msg.get("FromUserName", ""))
                to_user_id = msg.get("toUserName", msg.get("ToUserName", ""))

                if isinstance(from_user_id, dict) and "string" in from_user_id:
                    from_user_id = from_user_id["string"]
                if isinstance(to_user_id, dict) and "string" in to_user_id:
                    to_user_id = to_user_id["string"]

                if from_user_id and from_user_id.endswith("@chatroom"):
                    is_group = True
                elif to_user_id and to_user_id.endswith("@chatroom"):
                    is_group = True
                    # 交换发送者和接收者，确保from_user_id是群ID
                    from_user_id, to_user_id = to_user_id, from_user_id

                # 创建消息对象
                cmsg = WX849Message(msg, is_group)

                # 注释掉从回调消息中获取发送者昵称的部分，改用API接口获取
                # if "SenderNickName" in msg and msg["SenderNickName"]:
                #     cmsg.sender_nickname = msg["SenderNickName"]
                #     logger.debug(f"[WX849] 使用回调中的发送者昵称: {cmsg.sender_nickname}")

                # 处理被@消息
                if is_group and "@" in str(msg.get("Content", "")):
                    # 检查是否有@列表
                    at_list = []

                    # 方法1: 从RawLogLine中提取@列表
                    raw_log_line = msg.get("RawLogLine", "")

                    # 检查是否是被@消息
                    if raw_log_line and "收到被@消息" in raw_log_line:
                        logger.debug(f"[WX849] 检测到被@消息: {raw_log_line}")
                        # 设置is_at标志
                        cmsg.is_at = True
                    # 检查是否有IsAtMessage标志
                    elif "IsAtMessage" in msg and msg["IsAtMessage"]:
                        logger.debug(f"[WX849] 检测到IsAtMessage标志")
                        # 设置is_at标志
                        cmsg.is_at = True

                        # 尝试从日志行中提取@列表
                        if "@:" in raw_log_line:
                            try:
                                at_part = raw_log_line.split("@:", 1)[1].split(" ", 1)[0]
                                if at_part.startswith("[") and at_part.endswith("]"):
                                    # 解析@列表
                                    at_list_str = at_part[1:-1]  # 去除[]
                                    if at_list_str:
                                        at_items = at_list_str.split(",")
                                        for item in at_items:
                                            item = item.strip().strip("'\"")
                                            if item:
                                                at_list.append(item)
                                        logger.debug(f"[WX849] 从被@消息中提取到@列表: {at_list}")
                            except Exception as e:
                                logger.debug(f"[WX849] 从被@消息中提取@列表失败: {e}")
                    # 普通消息中的@列表提取
                    elif raw_log_line and "@:" in raw_log_line:
                        try:
                            # 尝试从日志行中提取@列表
                            at_part = raw_log_line.split("@:", 1)[1].split(" ", 1)[0]
                            if at_part.startswith("[") and at_part.endswith("]"):
                                # 解析@列表
                                at_list_str = at_part[1:-1]  # 去除[]
                                if at_list_str:
                                    at_items = at_list_str.split(",")
                                    for item in at_items:
                                        item = item.strip().strip("'\"")
                                        if item:
                                            at_list.append(item)
                                    logger.debug(f"[WX849] 从RawLogLine提取到@列表: {at_list}")
                        except Exception as e:
                            logger.debug(f"[WX849] 从RawLogLine提取@列表失败: {e}")

                    # 方法2: 从MsgSource中提取@列表
                    if not at_list and "MsgSource" in msg:
                        try:
                            msg_source = msg.get("MsgSource", "")
                            if msg_source:
                                root = ET.fromstring(msg_source)
                                atuserlist_elem = root.find('atuserlist')
                                if atuserlist_elem is not None and atuserlist_elem.text:
                                    at_users = atuserlist_elem.text.split(",")
                                    for user in at_users:
                                        if user.strip():
                                            at_list.append(user.strip())
                                    logger.debug(f"[WX849] 从MsgSource提取到@列表: {at_list}")
                        except Exception as e:
                            logger.debug(f"[WX849] 从MsgSource提取@列表失败: {e}")

                    # 设置@列表到消息对象
                    if at_list:
                        cmsg.at_list = at_list
                        # 设置is_at标志
                        cmsg.is_at = self.wxid in at_list
                        logger.debug(f"[WX849] 设置@列表: {at_list}, is_at: {cmsg.is_at}")

                # 处理消息
                logger.debug(f"[WX849] 处理回调消息: ID:{cmsg.msg_id} 类型:{cmsg.msg_type}")

                # 使用线程安全的方式检查和标记消息
                with self.__class__._message_lock:
                    # 检查消息是否已经处理过 - 使用全局集合
                    if cmsg.msg_id in self.__class__._processed_message_ids:
                        logger.debug(f"[WX849] 消息 {cmsg.msg_id} 已在全局集合中标记为处理过，忽略")
                        return

                    # 检查本地字典中是否有这个消息ID（兼容旧代码）
                    if cmsg.msg_id in self.received_msgs:
                        logger.debug(f"[WX849] 消息 {cmsg.msg_id} 已在本地字典中标记为处理过，忽略")
                        return

                    # 标记消息为已处理 - 在全局集合和本地字典中标记
                    # 所有消息都在这里标记，包括图片消息
                    self.__class__._processed_message_ids.add(cmsg.msg_id)
                    self.received_msgs[cmsg.msg_id] = True

                    # 如果集合太大，清理一下
                    if len(self.__class__._processed_message_ids) > 1000:
                        # 只保留最近的500条
                        self.__class__._processed_message_ids = set(list(self.__class__._processed_message_ids)[-500:])

                    # 不再使用_processed_image_ids集合

                # 检查消息时间是否过期
                create_time = cmsg.create_time  # 消息时间戳
                current_time = int(time.time())

                # 设置超时时间为60秒
                timeout = 60
                if int(create_time) < current_time - timeout:
                    logger.debug(f"[WX849] 历史消息 {cmsg.msg_id} 已跳过，时间差: {current_time - int(create_time)}秒")
                    return

                # 创建一个全新的消息对象，避免共享引用
                new_msg = WX849Message(msg, is_group)

                # 复制原始消息对象的属性
                for attr_name in dir(cmsg):
                    if not attr_name.startswith('_') and not callable(getattr(cmsg, attr_name)):
                        try:
                            setattr(new_msg, attr_name, getattr(cmsg, attr_name))
                        except Exception:
                            pass

                # 设置正确的接收者和会话ID
                if is_group:
                    # 如果是群聊，接收者应该是群ID
                    new_msg.to_user_id = from_user_id  # 群ID
                    new_msg.session_id = from_user_id  # 使用群ID作为会话ID
                    new_msg.other_user_id = from_user_id  # 群ID
                    new_msg.is_group = True

                    # 确保群聊消息的其他字段也是正确的
                    new_msg.group_id = from_user_id

                    # 清除可能从其他消息继承的私聊相关字段
                    if hasattr(new_msg, 'other_user_nickname'):
                        delattr(new_msg, 'other_user_nickname')
                else:
                    # 如果是私聊，接收者应该是发送者ID
                    sender_wxid = msg.get("SenderWxid", "")
                    if not sender_wxid:
                        sender_wxid = from_user_id

                    new_msg.to_user_id = sender_wxid
                    new_msg.session_id = sender_wxid  # 使用发送者ID作为会话ID
                    new_msg.other_user_id = sender_wxid
                    new_msg.is_group = False

                    # 清除可能从其他消息继承的群聊相关字段
                    if hasattr(new_msg, 'group_name'):
                        delattr(new_msg, 'group_name')
                    if hasattr(new_msg, 'group_id'):
                        delattr(new_msg, 'group_id')
                    if hasattr(new_msg, 'is_at'):
                        new_msg.is_at = False
                    if hasattr(new_msg, 'at_list'):
                        new_msg.at_list = []

                # 使用新的消息对象替换原始消息对象
                cmsg = new_msg

                # 创建一个新的线程来处理消息，确保每个消息都有完全独立的处理环境
                def process_message_in_new_thread():
                    try:
                        # 创建新的事件循环
                        msg_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(msg_loop)

                        try:
                            # 调用原有的消息处理逻辑
                            if is_group:
                                self.handle_group(cmsg)
                            else:
                                self.handle_single(cmsg)
                        finally:
                            # 关闭事件循环
                            msg_loop.close()
                    except Exception as e:
                        logger.error(f"[WX849] 消息处理线程执行异常: {e}")
                        logger.error(traceback.format_exc())

                # 启动新线程处理消息
                msg_thread = threading.Thread(target=process_message_in_new_thread)
                msg_thread.daemon = True
                msg_thread.start()

                # 等待消息处理线程完成
                msg_thread.join()
            finally:
                # 关闭事件循环
                loop.close()

            logger.debug(f"[WX849] 独立消息处理线程 {thread_id} 处理完成 - 消息ID: {msg_id}")
        except Exception as e:
            logger.error(f"[WX849] 独立消息处理线程 {thread_id} 执行异常: {e}")
            logger.error(traceback.format_exc())



    def __init__(self):
        super().__init__()
        self.received_msgs = ExpiredDict(conf().get("expires_in_seconds", 3600))
        self.bot = None
        self.user_id = None
        self.name = None
        self.wxid = None
        self.is_running = False
        self.is_logged_in = False
        self.group_name_cache = {}
        # 新增属性，用于标记是否使用原始框架的会话
        self.using_original_session = True  # 默认使用原始框架会话
        # 新增属性，用于保存Synckey
        self.synckey = ""
        # 新增属性，用于控制同步频率
        self.sync_interval = 0.5  # 默认0.5秒同步一次
        # 新增属性，用于记录上次同步时间
        self.last_sync_time = 0
        # 新增属性，用于记录连续成功/失败的次数
        self.consecutive_success = 0
        self.consecutive_failures = 0
        # 新增属性，用于HTTP服务器
        self.http_server = None
        self.http_runner = None
        self.http_site = None
        # 新增属性，监听的IP和端口
        self.listen_host = conf().get("wx849_callback_host", "127.0.0.1")
        self.listen_port = conf().get("wx849_callback_port", 8088)
        # 设置API密钥，如果配置中没有则不使用密钥
        self.api_key = conf().get("wx849_callback_key", "")
        if self.api_key:
            logger.info(f"[WX849] 消息回调API密钥: {self.api_key}")
        else:
            logger.info("[WX849] 未设置API密钥，将不进行授权验证")
        # 新增属性，用于记录正在等待图片的会话
        self.waiting_for_image = ExpiredDict(300)  # 设置5分钟过期，固定值
        # 新增属性，用于记录会话最近图片消息
        self.recent_image_msgs = ExpiredDict(600)  # 设置10分钟过期，固定值

    async def _initialize_bot(self):
        """初始化 bot"""
        logger.info("[WX849] 正在初始化 bot...")

        # 读取协议版本设置
        protocol_version = conf().get("wx849_protocol_version", "849")
        logger.info(f"使用协议版本: {protocol_version}")

        # 使用9011端口作为默认端口，与原始框架保持一致
        api_host = conf().get("wx849_api_host", "127.0.0.1")
        api_port = conf().get("wx849_api_port", 9011)  # 默认使用9011端口
        logger.info(f"使用API地址: {api_host}:{api_port}")

        # 设置API路径前缀，根据协议版本区分
        if protocol_version == "855" or protocol_version == "ipad":
            api_path_prefix = "/api"
            logger.info(f"使用API路径前缀: {api_path_prefix} (适用于{protocol_version}协议)")
        else:
            api_path_prefix = "/VXAPI"
            logger.info(f"使用API路径前缀: {api_path_prefix} (适用于849协议)")

        # 实例化 WechatAPI 客户端
        if protocol_version == "855":
            # 855版本使用Client2
            try:
                from WechatAPI.Client2 import WechatAPIClient as WechatAPIClient2
                self.bot = WechatAPIClient2(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
                logger.info("成功加载855协议客户端")
            except Exception as e:
                logger.error(f"加载855协议客户端失败: {e}")
                logger.warning("回退使用默认客户端")
                self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
        elif protocol_version == "ipad":
            # iPad版本使用Client3
            try:
                from WechatAPI.Client3 import WechatAPIClient as WechatAPIClient3
                self.bot = WechatAPIClient3(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
                logger.info("成功加载iPad协议客户端")
            except Exception as e:
                logger.error(f"加载iPad协议客户端失败: {e}")
                logger.warning("回退使用默认客户端")
                self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
                # 设置API路径前缀
                if hasattr(self.bot, "set_api_path_prefix"):
                    self.bot.set_api_path_prefix(api_path_prefix)
        else:
            # 849版本使用默认Client
            self.bot = WechatAPI.WechatAPIClient(api_host, api_port)
            # 设置API路径前缀
            if hasattr(self.bot, "set_api_path_prefix"):
                self.bot.set_api_path_prefix(api_path_prefix)
            logger.info("使用849协议客户端")

        # 设置bot的ignore_protection属性为True，强制忽略所有风控保护
        if hasattr(self.bot, "ignore_protection"):
            self.bot.ignore_protection = True
            logger.info("[WX849] 已设置忽略风控保护")

        # 等待 WechatAPI 服务启动
        time_out = 30

        # 使用不同的方法检查服务是否可用，包括尝试直接访问API端点
        logger.info(f"尝试连接到 WechatAPI 服务 (地址: {api_host}:{api_port}{api_path_prefix})")

        is_connected = False
        while not is_connected and time_out > 0:
            try:
                # 直接使用HTTP请求检查服务是否可用
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    try:
                        # 尝试访问登录接口
                        url = f"http://{api_host}:{api_port}{api_path_prefix}/Login/GetQR"
                        logger.debug(f"尝试连接: {url}")
                        async with session.get(url, timeout=5) as response:
                            if response.status in [200, 401, 403, 404]:  # 任何HTTP响应都表示服务在运行
                                is_connected = True
                                logger.info("通过HTTP请求确认服务可用")
                                break
                    except:
                        # 如果特定路径失败，尝试访问根路径
                        url = f"http://{api_host}:{api_port}/"
                        logger.debug(f"尝试连接: {url}")
                        async with session.get(url, timeout=5) as response:
                            if response.status in [200, 401, 403, 404]:
                                is_connected = True
                                logger.info("通过根路径确认服务可用")
                                break
            except Exception as e:
                logger.debug(f"连接尝试失败: {e}")

            logger.info("等待 WechatAPI 启动中")
            await asyncio.sleep(2)
            time_out -= 2

        if not is_connected:
            logger.error("WechatAPI 服务启动超时")
            return False

        # 直接从原始框架的配置文件读取wxid，不进行任何登录操作
        try:
            # 先找到项目根目录
            current_dir = os.path.dirname(os.path.abspath(__file__))   # wx849_channel.py所在目录
            channel_dir = os.path.dirname(current_dir)                  # channel目录
            dow_dir = os.path.dirname(channel_dir)                      # dow目录
            root_dir = os.path.dirname(dow_dir)                         # 项目根目录

            # 构建robot_stat.json的路径
            robot_stat_file = os.path.join(root_dir, "resource", "robot_stat.json")

            if os.path.exists(robot_stat_file):
                logger.info(f"[WX849] 检测到原始框架配置文件: {robot_stat_file}")
                try:
                    with open(robot_stat_file, "r", encoding="utf-8") as f:
                        robot_stat = json.load(f)
                        stored_wxid = robot_stat.get("wxid", "")

                        if stored_wxid:
                            logger.info(f"[WX849] 检测到原始框架已登录，wxid: {stored_wxid}")

                            # 尝试检查连接是否有效
                            import aiohttp
                            async with aiohttp.ClientSession() as session:
                                try:
                                    # 构建检查连接状态的URL
                                    check_url = f"http://{api_host}:{api_port}{api_path_prefix}/Login/HeartBeat"

                                    # 准备参数
                                    form_data = {"wxid": stored_wxid}
                                    encoded_data = urllib.parse.urlencode(form_data)

                                    # 设置请求头
                                    headers = {
                                        'Content-Type': 'application/x-www-form-urlencoded'
                                    }

                                    async with session.post(check_url, data=encoded_data, headers=headers) as response:
                                        if response.status == 200:
                                            json_resp = await response.json()

                                            if json_resp.get("Success", False):
                                                # 连接有效，直接使用这个会话
                                                self.wxid = stored_wxid
                                                self.user_id = stored_wxid
                                                self.using_original_session = True

                                                # 获取个人信息设置昵称
                                                try:
                                                    # 直接使用wxid作为默认昵称
                                                    self.name = stored_wxid

                                                    # 尝试获取更准确的昵称
                                                    my_info = await self.bot.get_self_info()
                                                    if my_info and isinstance(my_info, dict):
                                                        self.name = my_info.get("NickName", stored_wxid)
                                                except Exception as e:
                                                    logger.error(f"[WX849] 获取用户昵称失败: {e}")

                                                self.is_logged_in = True
                                                logger.info(f"[WX849] 成功复用原始框架会话: user_id: {self.user_id}, nickname: {self.name}")

                                                # 启动HTTP服务器接收消息
                                                await self._start_http_server()
                                                return True
                                            else:
                                                logger.error(f"[WX849] 原始框架会话无效: {json_resp.get('Message', '未知错误')}")
                                                logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                                                return False
                                        else:
                                            logger.error(f"[WX849] 检查原始框架会话失败，状态码: {response.status}")
                                            logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                                            return False
                                except Exception as e:
                                    logger.error(f"[WX849] 检查原始框架会话时出错: {e}")
                                    logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                                    return False
                        else:
                            logger.error("[WX849] 未找到原始框架的wxid信息")
                            logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                            return False
                except Exception as e:
                    logger.error(f"[WX849] 读取原始框架配置失败: {e}")
                    logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                    return False
            else:
                logger.error(f"[WX849] 未找到原始框架配置文件: {robot_stat_file}")

                # 尝试其他可能的路径
                alt_robot_stat_file = os.path.join("resource", "robot_stat.json")
                if os.path.exists(alt_robot_stat_file):
                    logger.info(f"[WX849] 在备选路径找到原始框架配置: {alt_robot_stat_file}")
                    try:
                        with open(alt_robot_stat_file, "r", encoding="utf-8") as f:
                            robot_stat = json.load(f)
                            stored_wxid = robot_stat.get("wxid", "")

                            if stored_wxid:
                                # 设置wxid和用户信息
                                self.wxid = stored_wxid
                                self.user_id = stored_wxid
                                self.name = stored_wxid  # 默认使用wxid作为昵称
                                self.using_original_session = True
                                self.is_logged_in = True

                                logger.info(f"[WX849] 使用备选路径成功获取原始框架会话: {stored_wxid}")

                                # 启动HTTP服务器接收消息
                                await self._start_http_server()
                                return True
                    except Exception as e:
                        logger.error(f"[WX849] 读取备选路径配置失败: {e}")

                logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
                return False
        except Exception as e:
            logger.error(f"[WX849] 检查原始框架会话时发生异常: {e}")
            logger.error(traceback.format_exc())
            logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
            return False

        # 如果执行到这里，表示未能找到有效的原始框架会话
        logger.error("[WX849] 未能检测到有效的原始框架会话")
        logger.error("[WX849] DOW框架只支持使用原始框架的会话，请确保原始框架已登录")
        return False

    # 添加HTTP服务器启动方法
    async def _start_http_server(self):
        """启动HTTP服务器接收消息回调"""
        logger.info(f"[WX849] 正在启动HTTP服务器接收消息回调，监听地址: {self.listen_host}:{self.listen_port}")

        # 创建应用和路由
        app = web.Application()
        app.add_routes([
            web.post('/wx849/callback', self._handle_callback),
            web.get('/wx849/status', self._handle_status)
        ])

        # 启动服务器
        try:
            self.http_runner = web.AppRunner(app)
            await self.http_runner.setup()
            self.http_site = web.TCPSite(self.http_runner, self.listen_host, self.listen_port)
            await self.http_site.start()
            logger.info(f"[WX849] HTTP服务器已启动，回调URL: http://{self.listen_host}:{self.listen_port}/wx849/callback")

            # 显示回调配置说明
            logger.info("[WX849] 请在原始框架配置文件中添加以下回调设置:")
            logger.info(f"  \"callback_url\": \"http://{self.listen_host}:{self.listen_port}/wx849/callback\",")
            if self.api_key:
                logger.info(f"  \"callback_key\": \"{self.api_key}\"")
            else:
                logger.info(f"  \"callback_key\": \"\"")
                logger.info("[WX849] 未设置API密钥，将不进行授权验证")

            return True
        except Exception as e:
            logger.error(f"[WX849] 启动HTTP服务器失败: {e}")
            logger.error(traceback.format_exc())
            return False

    # 添加回调处理方法
    async def _handle_callback(self, request):
        """处理原始框架的消息回调"""
        try:
            # 验证API密钥（仅当设置了API密钥时才验证）
            if self.api_key:
                auth_header = request.headers.get('Authorization', '')
                if not auth_header or auth_header != f"Bearer {self.api_key}":
                    logger.warning(f"[WX849] 收到未授权的回调请求，IP: {request.remote}")
                    return web.json_response({"success": False, "message": "Unauthorized"}, status=401)
            # 如果没有设置API密钥，则不进行验证

            # 读取消息内容
            data = await request.json()
            logger.info(f"[WX849] 收到回调消息: {json.dumps(data, ensure_ascii=False)}")

            # 处理消息
            await self._process_callback_message(data)

            return web.json_response({"success": True})
        except Exception as e:
            logger.error(f"[WX849] 处理回调消息失败: {e}")
            logger.error(traceback.format_exc())
            return web.json_response({"success": False, "message": str(e)}, status=500)

    # 添加状态检查方法
    async def _handle_status(self, request):
        """返回服务器状态"""
        return web.json_response({
            "status": "running",
            "wxid": self.wxid,
            "nickname": self.name,
            "is_logged_in": self.is_logged_in,
            "version": "DOW-WX849-1.0"
        })

    # 添加回调消息处理方法
    async def _process_callback_message(self, data):
        """处理从回调接收到的消息"""
        try:
            # 检查消息格式
            if not isinstance(data, dict):
                logger.warning(f"[WX849] 收到无效的回调消息格式: {type(data)}")
                return

            # 提取消息数据
            messages = data.get("messages", [])
            if not messages:
                messages = [data]  # 如果没有messages字段，则把整个data当作单个消息处理

            # 记录最近收到的媒体消息，用于识图等功能的关联
            for msg in messages:
                try:
                    # 检查是否是图片消息
                    msg_type = msg.get('MsgType', 0)
                    raw_log_line = msg.get("RawLogLine", "")

                    # 注释掉这部分代码，让wx849_callback_daemon.py处理图片消息
                    # 两种情况：1. MsgType=3表示图片消息 2. 日志行包含"收到图片消息"
                    if False:
                        # 获取消息ID
                        msg_id = msg.get("MsgId", "")
                        if not msg_id and raw_log_line:
                            # 尝试从日志行提取
                            msg_id_match = re.search(r'消息ID:(\d+)', raw_log_line)
                            if msg_id_match:
                                msg_id = msg_id_match.group(1)

                        # 检查是否已经处理过这条图片消息
                        # 使用一个简单的缓存来跟踪已处理的图片消息ID
                        if not hasattr(self, '_processed_image_msgs'):
                            self._processed_image_msgs = set()

                        if msg_id in self._processed_image_msgs:
                            logger.info(f"[WX849] 图片消息 {msg_id} 已经处理过，跳过重复处理")
                            continue

                        # 标记为已处理
                        self._processed_image_msgs.add(msg_id)

                        # 如果缓存太大，清理一下
                        if len(self._processed_image_msgs) > 1000:
                            # 只保留最近的500条
                            self._processed_image_msgs = set(list(self._processed_image_msgs)[-500:])

                        logger.info(f"[WX849] 检测到图片消息: MsgType={msg_type}, RawLogLine={raw_log_line[:100] if raw_log_line else 'None'}")

                        # 尝试解析图片消息
                        try:
                            # 获取发送者ID
                            from_user_id = msg.get("FromWxid", "")
                            if not from_user_id and raw_log_line:
                                # 尝试从日志行提取
                                from_user_match = re.search(r'来自:([^\s]+)', raw_log_line)
                                from_user_id = from_user_match.group(1) if from_user_match else ""

                            # 获取发送人ID
                            sender_wxid = msg.get("SenderWxid", "")
                            if not sender_wxid and raw_log_line:
                                # 尝试从日志行提取
                                sender_match = re.search(r'发送人:([^\s]+)', raw_log_line)
                                sender_wxid = sender_match.group(1) if sender_match else ""

                            # 获取XML内容
                            xml_content = msg.get("Content", "")
                            if not xml_content.startswith("<") and raw_log_line:
                                # 尝试从日志行提取XML内容
                                xml_match = re.search(r'XML:(.*)', raw_log_line, re.DOTALL)
                                if xml_match:
                                    xml_content = xml_match.group(1).strip()
                                    logger.info(f"[WX849] 从日志行提取到XML内容: {xml_content[:100]}...")

                            # 如果仍然没有有效的XML内容，创建一个基本的XML结构
                            if not xml_content or not xml_content.startswith("<"):
                                xml_content = f'<msg><img aeskey="" cdnmidimgurl="" length="0" md5="" /></msg>'
                                logger.warning(f"[WX849] 无法获取有效的XML内容，使用默认XML结构")
                            else:
                                logger.info(f"[WX849] 成功获取XML内容: {xml_content[:100]}...")

                            # 只要有消息ID和发送者ID，就尝试处理图片消息
                            if msg_id and from_user_id:
                                # 创建一个新的消息对象
                                is_group = from_user_id.endswith("@chatroom")

                                # 构建消息对象
                                image_msg = {
                                    "MsgId": msg_id,
                                    "FromUserName": from_user_id,
                                    "ToUserName": self.wxid,
                                    "MsgType": 3,  # 图片类型
                                    "Content": xml_content,
                                    "SenderWxid": sender_wxid
                                }

                                # 创建消息对象
                                cmsg = WX849Message(image_msg, is_group)

                                # 设置发送者信息
                                cmsg.sender_wxid = sender_wxid

                                # 设置_channel属性，以便_prepare_fn方法可以调用_download_image
                                cmsg._channel = self

                                # 设置消息类型为IMAGE
                                cmsg.ctype = ContextType.IMAGE

                                # 生成会话ID
                                session_id = from_user_id if is_group else sender_wxid

                                # 记录接收到媒体消息的时间和信息
                                logger.info(f"[WX849] 成功解析图片消息，关联到会话: {session_id}")

                                # 将图片消息保存到recent_image_msgs中
                                self.recent_image_msgs[session_id] = cmsg

                                # 处理图片消息 - 这里只进行初步处理
                                self._process_image_message(cmsg)

                                # 直接生成上下文并发送到DOW框架
                                context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=is_group, msg=cmsg)
                                if context:
                                    logger.info(f"[WX849] 图片消息解析完成，生成上下文并发送到DOW框架: {session_id}")
                                    self.produce(context)
                                else:
                                    logger.error(f"[WX849] 图片消息解析完成，但生成上下文失败")

                                # 完全禁用这部分代码，图片消息只在_process_single_message_independently中处理
                                # 标记图片消息为已处理，避免在后续的循环中重复处理
                                if not hasattr(self.__class__, '_processed_image_ids'):
                                    self.__class__._processed_image_ids = set()
                                self.__class__._processed_image_ids.add(msg_id)
                                logger.debug(f"[WX849] 已标记图片消息 {msg_id} 为已处理，避免重复处理")
                            else:
                                logger.error(f"[WX849] 无法获取图片消息的关键信息: MsgId={msg_id}, FromWxid={from_user_id}")
                        except Exception as e:
                            logger.error(f"[WX849] 解析图片消息回调失败: {e}")
                            logger.error(traceback.format_exc())

                    # 处理常规多媒体消息
                    if msg_type in [3, 43, 47, 49]:  # 图片(3)、视频(43)、表情(47)、文件(49)
                        # 获取消息的目标接收者和发送者
                        from_user_id = msg.get("fromUserName", msg.get("FromUserName", ""))
                        to_user_id = msg.get("toUserName", msg.get("ToUserName", ""))
                        sender_wxid = msg.get("SenderWxid", "")

                        if isinstance(from_user_id, dict) and "string" in from_user_id:
                            from_user_id = from_user_id["string"]
                        if isinstance(to_user_id, dict) and "string" in to_user_id:
                            to_user_id = to_user_id["string"]

                        # 确定是群消息还是私聊消息
                        is_group = False
                        if from_user_id and from_user_id.endswith("@chatroom"):
                            is_group = True
                        elif to_user_id and to_user_id.endswith("@chatroom"):
                            is_group = True
                            # 交换发送者和接收者，确保from_user_id是群ID
                            from_user_id, to_user_id = to_user_id, from_user_id

                        # 生成会话ID，用于关联消息
                        session_id = from_user_id if is_group else (sender_wxid or from_user_id)

                        # 记录接收到媒体消息的时间和信息
                        logger.info(f"[WX849] 收到媒体消息(类型:{msg_type})，立即处理并关联到会话: {session_id}")

                        # 保存最近的图片消息，供后续命令使用
                        if msg_type == 3:  # 图片类型
                            logger.info(f"[WX849] 保存图片消息到会话 {session_id} 的最近消息列表")
                            # 创建消息对象
                            cmsg = WX849Message(msg, is_group)
                            # 将图片消息保存到recent_image_msgs中
                            self.recent_image_msgs[session_id] = cmsg

                            # 保存图片消息信息，不需要标记
                            # 图片消息只在_process_image_message方法中处理
                            msg_id = msg.get("MsgId", "")

                        # 注释掉这部分代码，避免重复处理
                        # 媒体消息会在后面的循环中处理，不需要在这里单独处理
                        # 创建消息对象
                        # cmsg = WX849Message(msg, is_group)

                        # 立即处理这条消息，不等待下一次回调
                        # if is_group:
                        #     self.handle_group(cmsg)
                        # else:
                        #     self.handle_single(cmsg)
                        pass
                except Exception as e:
                    logger.error(f"[WX849] 处理媒体消息失败: {e}")
                    logger.error(traceback.format_exc())

            # 处理所有消息 - 为每条消息创建独立的处理流程
            for msg in messages:
                try:
                    # 确保消息类型正确设置
                    if 'MsgType' not in msg or msg['MsgType'] == 0:
                        # 如果消息类型缺失或为0，默认设置为文本消息(1)
                        msg['MsgType'] = 1
                        logger.debug(f"[WX849] 消息类型缺失或为0，设置为默认文本类型(1)")

                    # 获取消息ID，用于跟踪处理流程
                    msg_id = msg.get("MsgId", "")
                    if not msg_id:
                        # 如果消息ID为空，生成一个唯一ID
                        msg_id = f"msg_{int(time.time())}_{hash(str(msg)[:100])}"
                        logger.debug(f"[WX849] 为空消息ID生成唯一ID: {msg_id}")

                    # 不再在这里检查图片消息是否已经处理过
                    msg_type = msg.get('MsgType', 0)
                    # 让图片消息正常处理

                    # 创建独立的处理线程
                    process = threading.Thread(
                        target=self._process_single_message_independently,
                        args=(msg_id, msg),
                        daemon=True  # 设置为守护线程，主线程退出时自动结束
                    )
                    process.start()
                    logger.debug(f"[WX849] 已启动独立处理流程 - 消息ID: {msg_id}")

                except Exception as e:
                    logger.error(f"[WX849] 创建消息处理线程失败: {e}")
                    logger.error(traceback.format_exc())

            return True
        except Exception as e:
            logger.error(f"[WX849] 处理回调消息过程中出错: {e}")
            logger.error(traceback.format_exc())
            return False

    # 修改启动方法，不再启动消息监听器
    def startup(self):
        """启动函数"""
        logger.info("[WX849] 正在启动...")
        logger.info("[WX849] 注意: DOW框架将使用原始框架的登录会话，请确保原始框架已正常登录运行")
        logger.info("[WX849] 消息将通过回调方式从原始框架传递给DOW框架")

        # 创建事件循环
        loop = asyncio.new_event_loop()

        # 定义启动任务
        async def startup_task():
            # 初始化机器人（获取原始框架会话并启动HTTP服务器）
            login_success = await self._initialize_bot()
            if login_success:
                logger.info("[WX849] 成功获取原始框架会话，已启动HTTP服务器接收消息")
                self.is_running = True

                # 保持服务器运行
                while self.is_running:
                    await asyncio.sleep(60)
                    # 定期发送心跳检测原始框架状态
                    if not await self._check_original_framework_status():
                        logger.error("[WX849] 检测到原始框架会话已失效，DOW框架将停止运行")
                        self.is_running = False
                        break
            else:
                logger.error("[WX849] 初始化失败")
                logger.error("[WX849] 请确保原始框架已经登录并正常运行")

        # 在新线程中运行事件循环
        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(startup_task())

            # 启动失败时的提示
            if not self.is_running:
                logger.error("[WX849] DOW框架启动失败，请按照以下步骤排查问题:")
                logger.error("  1. 确保原始框架已经启动并成功登录微信")
                logger.error("  2. 确保原始框架的配置文件'resource/robot_stat.json'存在且包含wxid信息")
                logger.error("  3. 确保DOW框架和原始框架使用相同的API端口(默认9011)")
                logger.error("  4. 检查网络连接是否正常")
                logger.error("  5. 查看日志中的详细错误信息")

        thread = threading.Thread(target=run_loop)
        thread.daemon = True
        thread.start()

    # 添加关闭方法，确保HTTP服务器正确关闭
    async def shutdown(self):
        """关闭HTTP服务器和清理资源"""
        logger.info("[WX849] 正在关闭HTTP服务器...")
        self.is_running = False

        # 关闭HTTP服务器
        if self.http_site:
            await self.http_site.stop()
        if self.http_runner:
            await self.http_runner.cleanup()

        logger.info("[WX849] HTTP服务器已关闭")

    @_check
    def handle_single(self, cmsg: ChatMessage):
        """处理私聊消息"""
        try:
            # 设置_channel属性，以便_prepare_fn方法可以调用_download_image
            if not hasattr(cmsg, '_channel'):
                cmsg._channel = self

            # 处理消息内容和类型
            self._process_message(cmsg)

            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 私聊消息 - 类型: {cmsg.ctype}, ID: {cmsg.msg_id}, 内容: {cmsg.content[:20]}...")

            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("speech_recognition") != True:
                logger.debug("[WX849] 语音识别功能未启用，跳过处理")
                return

            # 检查前缀匹配
            if cmsg.ctype == ContextType.TEXT:
                single_chat_prefix = conf().get("single_chat_prefix", [""])
                # 日志记录前缀配置，方便调试
                logger.debug(f"[WX849] 单聊前缀配置: {single_chat_prefix}")
                match_prefix = None
                for prefix in single_chat_prefix:
                    if prefix and cmsg.content.startswith(prefix):
                        logger.debug(f"[WX849] 匹配到前缀: {prefix}")
                        match_prefix = prefix
                        # 去除前缀
                        cmsg.content = cmsg.content[len(prefix):].strip()
                        logger.debug(f"[WX849] 去除前缀后的内容: {cmsg.content}")
                        break

                # 记录是否匹配
                if not match_prefix and single_chat_prefix and "" not in single_chat_prefix:
                    logger.debug(f"[WX849] 未匹配到前缀，消息被过滤: {cmsg.content}")
                    # 如果没有匹配到前缀且配置中没有空前缀，则直接返回，不处理该消息
                    return

            # 生成上下文
            context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
            if context:
                self.produce(context)
            else:
                logger.debug(f"[WX849] 生成上下文失败，跳过处理")
        except Exception as e:
            logger.error(f"[WX849] 处理私聊消息异常: {e}")
            if conf().get("log_level", "INFO") == "DEBUG":
                import traceback
                logger.debug(f"[WX849] 异常堆栈: {traceback.format_exc()}")

    @_check
    def handle_group(self, cmsg: ChatMessage):
        """处理群聊消息"""
        try:
            # 添加日志，记录处理前的消息基本信息
            logger.debug(f"[WX849] 开始处理群聊消息 - ID:{cmsg.msg_id} 类型:{cmsg.msg_type} 从:{cmsg.from_user_id}")

            # 设置_channel属性，以便_prepare_fn方法可以调用_download_image
            if not hasattr(cmsg, '_channel'):
                cmsg._channel = self

            # 处理消息内容和类型
            self._process_message(cmsg)

            # 只记录关键消息信息，减少日志输出
            if conf().get("log_level", "INFO") != "ERROR":
                logger.debug(f"[WX849] 群聊消息 - 类型: {cmsg.ctype}, 群ID: {cmsg.other_user_id}")

            # 根据消息类型处理
            if cmsg.ctype == ContextType.VOICE and conf().get("group_speech_recognition") != True:
                logger.debug("[WX849] 群聊语音识别功能未启用，跳过处理")
                return

            # 检查白名单
            if cmsg.from_user_id and hasattr(cmsg, 'from_user_id'):
                group_white_list = conf().get("group_name_white_list", ["ALL_GROUP"])
                # 检查是否启用了白名单
                if "ALL_GROUP" not in group_white_list:
                    # 获取群名
                    group_name = None
                    try:
                        # 使用同步方式获取群名，避免事件循环嵌套
                        chatrooms_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", 'wx849_rooms.json')

                        if os.path.exists(chatrooms_file):
                            try:
                                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                                    chatrooms_info = json.load(f)

                                if cmsg.from_user_id in chatrooms_info:
                                    group_name = chatrooms_info[cmsg.from_user_id].get("nickName")
                                    if group_name:
                                        logger.debug(f"[WX849] 从缓存获取到群名: {group_name}")
                            except Exception as e:
                                logger.error(f"[WX849] 读取群聊缓存失败: {e}")

                        # 如果没有从缓存获取到群名，使用群ID作为备用
                        if not group_name:
                            group_name = cmsg.from_user_id
                            logger.debug(f"[WX849] 没有找到群名，使用群ID: {group_name}")

                        logger.debug(f"[WX849] 群聊白名单检查 - 群名: {group_name}")
                    except Exception as e:
                        logger.error(f"[WX849] 获取群名称失败: {e}")
                        group_name = cmsg.from_user_id

                    # 检查群名是否在白名单中
                    if group_name and group_name not in group_white_list:
                        # 使用群ID再次检查
                        if cmsg.from_user_id not in group_white_list:
                            logger.info(f"[WX849] 群聊不在白名单中，跳过处理: {group_name}")
                            return

                    logger.debug(f"[WX849] 群聊通过白名单检查: {group_name or cmsg.from_user_id}")

            # 检查前缀匹配
            trigger_proceed = False
            if cmsg.ctype == ContextType.TEXT:
                group_chat_prefix = conf().get("group_chat_prefix", [])
                group_chat_keyword = conf().get("group_chat_keyword", [])

                # 日志记录前缀配置，方便调试
                logger.debug(f"[WX849] 群聊前缀配置: {group_chat_prefix}")
                logger.debug(f"[WX849] 群聊关键词配置: {group_chat_keyword}")

                # 检查前缀匹配
                for prefix in group_chat_prefix:
                    if prefix and cmsg.content.startswith(prefix):
                        logger.debug(f"[WX849] 群聊匹配到前缀: {prefix}")
                        # 去除前缀
                        cmsg.content = cmsg.content[len(prefix):].strip()
                        logger.debug(f"[WX849] 去除前缀后的内容: {cmsg.content}")
                        trigger_proceed = True
                        break

                # 检查关键词匹配
                if not trigger_proceed and group_chat_keyword:
                    for keyword in group_chat_keyword:
                        if keyword and keyword in cmsg.content:
                            logger.debug(f"[WX849] 群聊匹配到关键词: {keyword}")
                            trigger_proceed = True
                            break

                # 检查是否@了机器人（增强版）
                if not trigger_proceed and (cmsg.at_list or cmsg.content.find("@") >= 0 or getattr(cmsg, 'is_at', False)):
                    logger.debug(f"[WX849] @列表: {cmsg.at_list}, 机器人wxid: {self.wxid}, is_at标志: {getattr(cmsg, 'is_at', False)}")

                    # 首先检查是否已经设置了is_at标志（可能在_process_xml_message中设置）
                    at_matched = getattr(cmsg, 'is_at', False)

                    # 如果没有设置is_at标志，检查at_list中是否包含机器人wxid
                    if not at_matched and cmsg.at_list and self.wxid in cmsg.at_list:
                        at_matched = True
                        # 设置is_at标志
                        cmsg.is_at = True
                        logger.debug(f"[WX849] 在at_list中匹配到机器人wxid: {self.wxid}, 设置is_at=True")

                    # 如果at_list为空，或者at_list中没有找到机器人wxid，则检查消息内容中是否直接包含@机器人的文本
                    if not at_matched and cmsg.content:
                        # 获取可能的机器人名称
                        robot_names = []
                        if self.name:
                            robot_names.append(self.name)
                        if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name:
                            robot_names.append(cmsg.self_display_name)

                        # 检查消息中是否包含@机器人名称
                        for name in robot_names:
                            at_text = f"@{name}"
                            if at_text in cmsg.content:
                                at_matched = True
                                logger.debug(f"[WX849] 在消息内容中直接匹配到@机器人: {at_text}")
                                break

                    # 处理多种可能的@格式
                    if at_matched:
                        # 尝试移除不同格式的@文本
                        original_content = cmsg.content
                        at_patterns = []

                        # 添加可能的@格式
                        if self.name:
                            at_patterns.extend([
                                f"@{self.name} ",  # 带空格
                                f"@{self.name}\u2005",  # 带特殊空格
                                f"@{self.name}",  # 不带空格
                            ])

                        # 检查是否存在自定义的群内昵称
                        if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name:
                            at_patterns.extend([
                                f"@{cmsg.self_display_name} ",  # 带空格
                                f"@{cmsg.self_display_name}\u2005",  # 带特殊空格
                                f"@{cmsg.self_display_name}",  # 不带空格
                            ])

                        # 按照优先级尝试移除@文本
                        for pattern in at_patterns:
                            if pattern in cmsg.content:
                                cmsg.content = cmsg.content.replace(pattern, "", 1).strip()
                                logger.debug(f"[WX849] 匹配到@模式: {pattern}")
                                logger.debug(f"[WX849] 去除@后的内容: {cmsg.content}")
                                break

                        # 如果没有匹配到任何@模式，但确实在at_list中找到了机器人或内容中包含@
                        # 尝试使用正则表达式移除通用@格式
                        if cmsg.content == original_content and at_matched:
                            import re
                            # 匹配形如"@任何内容 "的模式
                            at_pattern = re.compile(r'@[^\s]+[\s\u2005]+')
                            cmsg.content = at_pattern.sub("", cmsg.content, 1).strip()
                            logger.debug(f"[WX849] 使用正则表达式去除@后的内容: {cmsg.content}")

                        trigger_proceed = True

                # 记录是否需要处理
                if not trigger_proceed:
                    logger.debug(f"[WX849] 群聊消息未匹配触发条件，但仍会转发给插件: {cmsg.content}")
                    # 不再直接返回，而是继续处理，但标记为不触发AI
                    # return

            # 生成上下文
            context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
            if context:
                # 添加前缀匹配标志到上下文，用于决定是否触发AI对话
                context["trigger_prefix"] = trigger_proceed
                self.produce(context)
            else:
                logger.debug(f"[WX849] 生成群聊上下文失败，跳过处理")
        except Exception as e:
            error_msg = str(e)
            # 添加更详细的错误日志信息
            logger.error(f"[WX849] 处理群聊消息异常: {error_msg}")
            logger.error(f"[WX849] 消息内容: {getattr(cmsg, 'content', '未知')[:100]}")
            logger.error(f"[WX849] 消息类型: {getattr(cmsg, 'msg_type', '未知')}")
            logger.error(f"[WX849] 上下文类型: {getattr(cmsg, 'ctype', '未知')}")

            # 记录完整的异常堆栈
            import traceback
            logger.error(f"[WX849] 异常堆栈: {traceback.format_exc()}")

    def _process_message(self, cmsg):
        """处理消息内容和类型"""
        # 添加辅助函数来处理可能是字典的字段
        def get_string_value(field):
            """从可能是字典的字段中提取字符串值"""
            if isinstance(field, dict) and "string" in field:
                return field["string"]
            return field

        # 处理消息类型
        msg_type = cmsg.msg_type
        if not msg_type and "Type" in cmsg.msg:
            msg_type = get_string_value(cmsg.msg["Type"])

        # 尝试获取机器人在群内的昵称
        if cmsg.is_group and not cmsg.self_display_name:
            try:
                # 从缓存中查询群成员详情
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)

                        if cmsg.from_user_id in chatrooms_info:
                            room_info = chatrooms_info[cmsg.from_user_id]

                            # 在成员中查找机器人的信息
                            if "members" in room_info and isinstance(room_info["members"], list):
                                for member in room_info["members"]:
                                    if member.get("UserName") == self.wxid:
                                        # 优先使用群内显示名称
                                        if member.get("DisplayName"):
                                            cmsg.self_display_name = member.get("DisplayName")
                                            logger.debug(f"[WX849] 从群成员缓存中获取到机器人群内昵称: {cmsg.self_display_name}")
                                            break
                                        # 其次使用昵称
                                        elif member.get("NickName"):
                                            cmsg.self_display_name = member.get("NickName")
                                            logger.debug(f"[WX849] 从群成员缓存中获取到机器人昵称: {cmsg.self_display_name}")
                                            break
                    except Exception as e:
                        logger.error(f"[WX849] 读取群成员缓存失败: {e}")

                # 如果缓存中没有找到，使用机器人名称
                if not cmsg.self_display_name:
                    cmsg.self_display_name = self.name
                    logger.debug(f"[WX849] 使用机器人名称作为群内昵称: {cmsg.self_display_name}")
            except Exception as e:
                logger.error(f"[WX849] 获取机器人群内昵称失败: {e}")

        # 根据消息类型进行处理
        if msg_type in [1, "1", "Text"]:
            self._process_text_message(cmsg)
        elif msg_type in [3, "3", "Image"]:
            self._process_image_message(cmsg)
        elif msg_type in [6, "6", "Sharing"]:
            self._process_sharing_message(cmsg)
        elif msg_type in [34, "34", "Voice"]:
            self._process_voice_message(cmsg)
        elif msg_type in [43, "43", "Video"]:
            self._process_video_message(cmsg)
        elif msg_type in [47, "47", "Emoji"]:
            self._process_emoji_message(cmsg)
        elif msg_type in [49, "49", "App"]:
            self._process_xml_message(cmsg)
        elif msg_type in [10000, "10000", "System"]:
            self._process_system_message(cmsg)
        else:
            # 默认类型处理
            cmsg.ctype = ContextType.UNKNOWN
            logger.warning(f"[WX849] 未知消息类型: {msg_type}, 内容: {cmsg.content[:100]}")

        # 检查消息是否来自群聊
        if cmsg.is_group or (hasattr(cmsg, 'from_user_id') and isinstance(cmsg.from_user_id, str) and cmsg.from_user_id.endswith("@chatroom")):
            # 增强的群消息发送者提取逻辑
            cmsg.is_group = True

            # 首先检查是否已从回调中获取了发送者昵称
            if hasattr(cmsg, 'sender_nickname') and cmsg.sender_nickname:
                cmsg.actual_user_nickname = cmsg.sender_nickname
                if hasattr(cmsg, 'sender_wxid') and cmsg.sender_wxid:
                    cmsg.actual_user_id = cmsg.sender_wxid
                logger.debug(f"[WX849] 使用回调提供的发送者昵称: {cmsg.actual_user_nickname}")
            else:
                # 方法1: 尝试解析完整的格式 "wxid:\n消息内容"
                split_content = cmsg.content.split(":\n", 1)
                if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                    sender_extracted = True
                    logger.debug(f"[WX849] 群聊发送者提取(方法1): {cmsg.sender_wxid}")
                else:
                    # 方法2: 尝试解析简单的格式 "wxid:消息内容"
                    # split_content = cmsg.content.split(":", 1)
                    # if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                    #     cmsg.sender_wxid = split_content[0]
                    #     cmsg.content = split_content[1]
                    #     sender_extracted = True
                    #     logger.debug(f"[WX849] 群聊发送者提取(方法2): {cmsg.sender_wxid}")
                    # else:
                        sender_extracted = False

                # 方法3: 尝试从回复XML中提取
                if not sender_extracted and cmsg.content and cmsg.content.startswith("<"):
                    try:
                        # 解析XML内容
                        root = ET.fromstring(cmsg.content)

                        # 查找不同类型的XML中可能存在的发送者信息
                        if root.tag == "msg":
                            # 常见的XML消息格式
                            sender_node = root.find(".//username")
                            if sender_node is not None and sender_node.text:
                                cmsg.sender_wxid = sender_node.text
                                sender_extracted = True
                                logger.debug(f"[WX849] 群聊发送者从XML提取: {cmsg.sender_wxid}")

                            # 尝试其他可能的标签
                            if not sender_extracted:
                                for tag in ["fromusername", "sender", "from"]:
                                    sender_node = root.find(f".//{tag}")
                                    if sender_node is not None and sender_node.text:
                                        cmsg.sender_wxid = sender_node.text
                                        sender_extracted = True
                                        logger.debug(f"[WX849] 群聊发送者从XML({tag})提取: {cmsg.sender_wxid}")
                                        break
                    except Exception as e:
                        logger.error(f"[WX849] 从XML提取群聊发送者失败: {e}")

                # 方法4: 尝试从其它字段提取
                if not sender_extracted:
                    for key in ["SenderUserName", "sender", "senderId", "fromUser"]:
                        if key in cmsg.msg and cmsg.msg[key]:
                            cmsg.sender_wxid = str(cmsg.msg[key])
                            sender_extracted = True
                            logger.debug(f"[WX849] 群聊发送者从字段提取({key}): {cmsg.sender_wxid}")
                            break

                # 方法5: 尝试从SenderWxid字段提取
                if not sender_extracted and "SenderWxid" in cmsg.msg and cmsg.msg["SenderWxid"]:
                    cmsg.sender_wxid = str(cmsg.msg["SenderWxid"])
                    sender_extracted = True
                    logger.debug(f"[WX849] 群聊发送者从SenderWxid提取: {cmsg.sender_wxid}")

                # 如果仍然无法提取，设置为默认值但不要留空
                if not sender_extracted or not cmsg.sender_wxid:
                    # 检查原始消息中是否有SenderWxid字段
                    if hasattr(cmsg, 'raw_msg') and isinstance(cmsg.raw_msg, dict) and "SenderWxid" in cmsg.raw_msg:
                        cmsg.sender_wxid = str(cmsg.raw_msg["SenderWxid"])
                        logger.debug(f"[WX849] 从原始消息中提取SenderWxid: {cmsg.sender_wxid}")
                    else:
                        cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                        logger.debug(f"[WX849] 无法提取群聊发送者，使用默认值: {cmsg.sender_wxid}")

                # 设置other_user_id为群ID，确保它不为None
                cmsg.other_user_id = cmsg.from_user_id

                # 设置actual_user_id为发送者wxid
                cmsg.actual_user_id = cmsg.sender_wxid

                # 异步获取发送者昵称并设置actual_user_nickname
                # 但现在我们无法在同步方法中直接调用异步方法，所以先使用wxid
                cmsg.actual_user_nickname = cmsg.sender_wxid

                # 启动异步任务获取昵称并更新actual_user_nickname
                threading.Thread(target=lambda: asyncio.run(self._update_nickname_async(cmsg))).start()

            # 确保other_user_id设置为群ID
            cmsg.other_user_id = cmsg.from_user_id

            # 设置other_user_nickname为群名称，与gewechat保持一致
            # 启动异步任务获取群名称并更新other_user_nickname
            threading.Thread(target=lambda: asyncio.run(self._update_group_nickname_async(cmsg))).start()

            # 处理@消息，与gewechat保持一致
            # 优先从MsgSource的XML中解析是否被at
            msg_source = cmsg.msg.get('MsgSource', '')
            cmsg.is_at = False
            xml_parsed = False
            if msg_source:
                try:
                    root = ET.fromstring(msg_source)
                    atuserlist_elem = root.find('atuserlist')
                    if atuserlist_elem is not None and atuserlist_elem.text:
                        cmsg.is_at = self.wxid in atuserlist_elem.text
                        xml_parsed = True
                        logger.debug(f"[WX849] 从XML解析是否被at: {cmsg.is_at}")
                except ET.ParseError:
                    pass

            # 只有在XML解析失败时才从PushContent中判断
            if not xml_parsed:
                cmsg.is_at = '在群聊中@了你' in cmsg.msg.get('PushContent', '')
                logger.debug(f"[WX849] 从PushContent解析是否被at: {cmsg.is_at}")

            logger.debug(f"[WX849] 设置实际发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.other_user_id = cmsg.from_user_id

            # 检查是否有发送者昵称
            if hasattr(cmsg, 'sender_nickname') and cmsg.sender_nickname:
                cmsg.actual_user_nickname = cmsg.sender_nickname
            else:
                cmsg.actual_user_nickname = cmsg.from_user_id

            # 设置other_user_nickname为联系人昵称，与gewechat保持一致
            # 启动异步任务获取联系人昵称并更新other_user_nickname
            threading.Thread(target=lambda: asyncio.run(self._update_contact_nickname_async(cmsg))).start()

            logger.debug(f"[WX849] 设置私聊发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")

    async def _update_nickname_async(self, cmsg):
        """异步更新消息中的昵称信息"""
        if cmsg.is_group and cmsg.from_user_id.endswith("@chatroom"):
            nickname = await self._get_chatroom_member_nickname(cmsg.from_user_id, cmsg.sender_wxid)
            if nickname and nickname != cmsg.actual_user_nickname:
                cmsg.actual_user_nickname = nickname
                logger.debug(f"[WX849] 异步更新了发送者昵称: {nickname}")

    async def _update_group_nickname_async(self, cmsg):
        """异步更新群名称信息，与gewechat保持一致"""
        if cmsg.is_group and cmsg.from_user_id.endswith("@chatroom"):
            group_name = await self._get_group_name(cmsg.from_user_id)
            if group_name and group_name != cmsg.other_user_nickname:
                cmsg.other_user_nickname = group_name
                logger.debug(f"[WX849] 异步更新了群名称: {group_name}")

    async def _update_contact_nickname_async(self, cmsg):
        """异步更新联系人昵称信息，与gewechat保持一致"""
        if not cmsg.is_group:
            contact_name = await self._get_contact_name(cmsg.from_user_id)
            if contact_name and contact_name != cmsg.other_user_nickname:
                cmsg.other_user_nickname = contact_name
                logger.debug(f"[WX849] 异步更新了联系人昵称: {contact_name}")

    def _process_text_message(self, cmsg):
        """处理文本消息"""
        import xml.etree.ElementTree as ET

        cmsg.ctype = ContextType.TEXT

        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True

            # 只有在sender_wxid尚未设置或是默认值时才进行提取
            # 避免重复提取导致覆盖先前成功提取的值
            if not hasattr(cmsg, 'sender_wxid') or not cmsg.sender_wxid or cmsg.sender_wxid.startswith("未知用户_"):
                # 增强的群消息发送者提取逻辑
                # 尝试多种可能的格式解析发送者信息
                sender_extracted = False

                # 方法1: 尝试解析完整的格式 "wxid:\n消息内容"
                split_content = cmsg.content.split(":\n", 1)
                if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                    sender_extracted = True
                    logger.debug(f"[WX849] 群聊发送者提取(方法1): {cmsg.sender_wxid}")

                # 方法2: 尝试解析简单的格式 "wxid:消息内容"
                # if not sender_extracted:
                #     split_content = cmsg.content.split(":", 1)
                #     if len(split_content) > 1 and split_content[0] and not split_content[0].startswith("<"):
                #         cmsg.sender_wxid = split_content[0]
                #         cmsg.content = split_content[1]
                #         sender_extracted = True
                #         logger.debug(f"[WX849] 群聊发送者提取(方法2): {cmsg.sender_wxid}")

                # 尝试从XML回复或引用中提取
                if not sender_extracted and cmsg.content and cmsg.content.startswith("<"):
                    try:
                        root = ET.fromstring(cmsg.content)
                        for tag in ["username", "fromusername", "sender", "from"]:
                            node = root.find(f".//{tag}")
                            if node is not None and node.text:
                                cmsg.sender_wxid = node.text
                                sender_extracted = True
                                logger.debug(f"[WX849] 群聊发送者从XML提取: {cmsg.sender_wxid}")
                                break
                    except Exception as e:
                        logger.debug(f"[WX849] 从XML提取发送者失败: {e}")

                # 如果仍然无法提取，设置为默认值
                if not sender_extracted or not cmsg.sender_wxid:
                    cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                    logger.debug(f"[WX849] 无法提取群聊发送者，使用默认值: {cmsg.sender_wxid}")

                # 确保其他字段同步更新
                cmsg.actual_user_id = cmsg.sender_wxid
                cmsg.actual_user_nickname = cmsg.sender_wxid

                logger.debug(f"[WX849] 设置实际发送者信息: actual_user_id={cmsg.actual_user_id}, actual_user_nickname={cmsg.actual_user_nickname}")

            # 检测被@用户
            at_list = []
            try:
                # 首先检查消息对象中是否已经有at_list和is_at标志
                if hasattr(cmsg, 'at_list') and cmsg.at_list:
                    at_list = cmsg.at_list
                    logger.debug(f"[WX849] 使用已有的at_list: {at_list}")

                    # 检查是否已经设置了is_at标志
                    if hasattr(cmsg, 'is_at') and cmsg.is_at:
                        logger.debug(f"[WX849] 消息已被标记为@机器人")
                # 如果没有，尝试从消息内容中提取
                elif cmsg.content:
                    # 检查是否是被@消息
                    if hasattr(cmsg, 'msg') and "RawLogLine" in cmsg.msg:
                        raw_log_line = cmsg.msg.get("RawLogLine", "")
                        if raw_log_line and "收到被@消息" in raw_log_line:
                            logger.debug(f"[WX849] 检测到被@消息: {raw_log_line}")
                            # 设置is_at标志
                            cmsg.is_at = True
                    # 检查是否有IsAtMessage标志
                    if hasattr(cmsg, 'msg') and "IsAtMessage" in cmsg.msg and cmsg.msg["IsAtMessage"]:
                        logger.debug(f"[WX849] 检测到IsAtMessage标志")
                        # 设置is_at标志
                        cmsg.is_at = True
                    import re
                    # 匹配@后跟随的非空白字符
                    at_pattern = re.compile(r'@([^\s]+)')
                    matches = at_pattern.findall(cmsg.content)

                    for match in matches:
                        # 先检查是否以常见结束符结尾
                        for suffix in ['\u2005', '\u0020']:
                            if match.endswith(suffix):
                                match = match[:-1]

                        # 将匹配到的用户添加到at_list
                        match = match.strip()
                        if match and match not in at_list:
                            at_list.append(match)

                    # 检查是否@了机器人
                    if hasattr(self, 'name') and self.name:
                        for at_name in at_list:
                            if at_name == self.name or at_name == "所有人" or at_name == "全体成员":
                                logger.debug(f"[WX849] 检测到@机器人: {at_name}")
                                # 确保at_list中包含wxid
                                if self.wxid not in at_list:
                                    at_list.append(self.wxid)

                    # 检查文本中直接包含@机器人昵称的情况
                    if hasattr(self, 'name') and self.name and f"@{self.name}" in cmsg.content:
                        logger.debug(f"[WX849] 文本中直接包含@机器人: @{self.name}")
                        if self.wxid not in at_list:
                            at_list.append(self.wxid)

                    # 如果有自定义群内昵称，也检查是否@了这个昵称
                    if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name and f"@{cmsg.self_display_name}" in cmsg.content:
                        logger.debug(f"[WX849] 文本中直接包含@机器人群内昵称: @{cmsg.self_display_name}")
                        if self.wxid not in at_list:
                            at_list.append(self.wxid)

                # 尝试从RawLogLine中提取@列表
                if not at_list and hasattr(cmsg, 'msg') and "RawLogLine" in cmsg.msg:
                    raw_log_line = cmsg.msg.get("RawLogLine", "")
                    if raw_log_line and "@:" in raw_log_line:
                        try:
                            # 尝试从日志行中提取@列表
                            at_part = raw_log_line.split("@:", 1)[1].split(" ", 1)[0]
                            if at_part.startswith("[") and at_part.endswith("]"):
                                # 解析@列表
                                at_list_str = at_part[1:-1]  # 去除[]
                                if at_list_str:
                                    at_items = at_list_str.split(",")
                                    for item in at_items:
                                        item = item.strip().strip("'\"")
                                        if item and item not in at_list:
                                            at_list.append(item)
                                    logger.debug(f"[WX849] 从RawLogLine提取到@列表: {at_list}")
                        except Exception as e:
                            logger.debug(f"[WX849] 从RawLogLine提取@列表失败: {e}")

                # 尝试从MsgSource中提取@列表
                if not at_list and hasattr(cmsg, 'msg') and "MsgSource" in cmsg.msg:
                    try:
                        msg_source = cmsg.msg.get("MsgSource", "")
                        if msg_source:
                            root = ET.fromstring(msg_source)
                            atuserlist_elem = root.find('atuserlist')
                            if atuserlist_elem is not None and atuserlist_elem.text:
                                at_users = atuserlist_elem.text.split(",")
                                for user in at_users:
                                    if user.strip() and user.strip() not in at_list:
                                        at_list.append(user.strip())
                                logger.debug(f"[WX849] 从MsgSource提取到@列表: {at_list}")
                    except Exception as e:
                        logger.debug(f"[WX849] 从MsgSource提取@列表失败: {e}")
            except Exception as e:
                logger.error(f"[WX849] 提取@信息失败: {e}")

            # 设置at_list
            cmsg.at_list = at_list
            if at_list:
                logger.debug(f"[WX849] 提取到at_list: {at_list}")
                # 设置is_at标志
                cmsg.is_at = self.wxid in at_list
                logger.debug(f"[WX849] 设置is_at: {cmsg.is_at}")
        else:
            # 处理私聊消息发送者
            cmsg.at_list = []
            if not hasattr(cmsg, 'sender_wxid') or not cmsg.sender_wxid:
                cmsg.sender_wxid = cmsg.from_user_id
                cmsg.actual_user_id = cmsg.from_user_id
                cmsg.actual_user_nickname = cmsg.from_user_id

    def _process_image_message(self, cmsg):
        """处理图片消息"""
        import xml.etree.ElementTree as ET
        import os
        import base64
        import asyncio
        import aiohttp
        import time
        import threading

        # 在这里不检查和标记图片消息，而是在图片下载完成后再标记
        # 这样可以确保图片消息被正确处理为IMAGE类型，而不是UNKNOWN类型

        cmsg.ctype = ContextType.IMAGE

        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            split_content = cmsg.content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                cmsg.content = split_content[1]
            else:
                # 处理没有换行的情况
                split_content = cmsg.content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                else:
                    cmsg.content = split_content[0]
                    cmsg.sender_wxid = ""

            # 设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.actual_user_nickname = cmsg.from_user_id

        # 解析图片信息
        try:
            # 检查内容是否是XML
            if cmsg.content and (cmsg.content.startswith('<?xml') or cmsg.content.startswith('<msg>')):
                try:
                    root = ET.fromstring(cmsg.content)
                    img_element = root.find('img')
                    if img_element is not None:
                        cmsg.image_info = {
                            'aeskey': img_element.get('aeskey', ''),
                            'cdnmidimgurl': img_element.get('cdnmidimgurl', ''),
                            'length': img_element.get('length', '0'),
                            'md5': img_element.get('md5', '')
                        }
                        logger.debug(f"解析图片XML成功: aeskey={cmsg.image_info.get('aeskey', '')}, length={cmsg.image_info.get('length', '0')}, md5={cmsg.image_info.get('md5', '')}")
                    else:
                        # 如果找不到img元素，创建一个默认的image_info
                        cmsg.image_info = {
                            'aeskey': '',
                            'cdnmidimgurl': '',
                            'length': '0',
                            'md5': ''
                        }
                        logger.warning(f"[WX849] XML中未找到img元素，使用默认图片信息")
                except ET.ParseError as xml_err:
                    # XML解析失败，创建一个默认的image_info
                    logger.warning(f"[WX849] XML解析失败: {xml_err}, 使用默认图片信息")
                    cmsg.image_info = {
                        'aeskey': '',
                        'cdnmidimgurl': '',
                        'length': '0',
                        'md5': ''
                    }

                # 检查是否已经有图片路径
                if hasattr(cmsg, 'image_path') and cmsg.image_path and os.path.exists(cmsg.image_path):
                    logger.info(f"[WX849] 图片已存在，路径: {cmsg.image_path}")
                else:
                    # 创建一个锁文件，防止重复下载
                    tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")
                    os.makedirs(tmp_dir, exist_ok=True)
                    lock_file = os.path.join(tmp_dir, f"img_{cmsg.msg_id}.lock")

                    # 检查锁文件是否存在
                    if os.path.exists(lock_file):
                        logger.info(f"[WX849] 图片 {cmsg.msg_id} 正在被其他线程下载，跳过")
                        return

                    # 创建锁文件
                    try:
                        with open(lock_file, "w") as f:
                            f.write(str(time.time()))
                    except Exception as e:
                        logger.error(f"[WX849] 创建锁文件失败: {e}")

                    # 尝试下载图片
                    try:
                        # 使用同步方式下载图片，避免多线程问题
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(self._download_image(cmsg))
                        loop.close()
                    except Exception as e:
                        logger.error(f"[WX849] 下载图片失败: {e}")
                        logger.error(traceback.format_exc())
                    finally:
                        # 删除锁文件
                        try:
                            if os.path.exists(lock_file):
                                os.remove(lock_file)
                        except Exception as e:
                            logger.error(f"[WX849] 删除锁文件失败: {e}")
            else:
                # 如果内容不是XML，可能是已经下载好的图片路径
                if os.path.exists(cmsg.content):
                    cmsg.image_path = cmsg.content
                    logger.info(f"[WX849] 图片已存在，路径: {cmsg.image_path}")
                else:
                    logger.warning(f"[WX849] 图片内容既不是XML也不是有效路径: {cmsg.content[:100]}")
                    # 即使内容不是XML也不是有效路径，也创建一个默认的image_info
                    cmsg.image_info = {
                        'aeskey': '',
                        'cdnmidimgurl': '',
                        'length': '0',
                        'md5': ''
                    }
                    # 检查是否已经有图片路径
                    if hasattr(cmsg, 'image_path') and cmsg.image_path and os.path.exists(cmsg.image_path):
                        logger.info(f"[WX849] 图片已存在，路径: {cmsg.image_path}")
                    else:
                        # 创建一个锁文件，防止重复下载
                        tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")
                        os.makedirs(tmp_dir, exist_ok=True)
                        lock_file = os.path.join(tmp_dir, f"img_{cmsg.msg_id}.lock")

                        # 检查锁文件是否存在
                        if os.path.exists(lock_file):
                            logger.info(f"[WX849] 图片 {cmsg.msg_id} 正在被其他线程下载，跳过")
                            return

                        # 创建锁文件
                        try:
                            with open(lock_file, "w") as f:
                                f.write(str(time.time()))
                        except Exception as e:
                            logger.error(f"[WX849] 创建锁文件失败: {e}")

                        # 尝试下载图片
                        try:
                            # 使用同步方式下载图片，避免多线程问题
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            result = loop.run_until_complete(self._download_image(cmsg))
                            loop.close()
                        except Exception as e:
                            logger.error(f"[WX849] 下载图片失败: {e}")
                            logger.error(traceback.format_exc())
                        finally:
                            # 删除锁文件
                            try:
                                if os.path.exists(lock_file):
                                    os.remove(lock_file)
                            except Exception as e:
                                logger.error(f"[WX849] 删除锁文件失败: {e}")
        except Exception as e:
            logger.debug(f"解析图片消息失败: {e}, 内容: {cmsg.content[:100]}")
            logger.debug(f"详细错误: {traceback.format_exc()}")
            # 创建一个默认的image_info
            cmsg.image_info = {
                'aeskey': '',
                'cdnmidimgurl': '',
                'length': '0',
                'md5': ''
            }
            # 检查是否已经有图片路径
            if hasattr(cmsg, 'image_path') and cmsg.image_path and os.path.exists(cmsg.image_path):
                logger.info(f"[WX849] 图片已存在，路径: {cmsg.image_path}")
            else:
                # 创建一个锁文件，防止重复下载
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")
                os.makedirs(tmp_dir, exist_ok=True)
                lock_file = os.path.join(tmp_dir, f"img_{cmsg.msg_id}.lock")

                # 检查锁文件是否存在
                if os.path.exists(lock_file):
                    logger.info(f"[WX849] 图片 {cmsg.msg_id} 正在被其他线程下载，跳过")
                    return

                # 创建锁文件
                try:
                    with open(lock_file, "w") as f:
                        f.write(str(time.time()))
                except Exception as e:
                    logger.error(f"[WX849] 创建锁文件失败: {e}")

                # 尝试下载图片
                try:
                    # 使用同步方式下载图片，避免多线程问题
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(self._download_image(cmsg))
                    loop.close()
                except Exception as e:
                    logger.error(f"[WX849] 下载图片失败: {e}")
                    logger.error(traceback.format_exc())
                finally:
                    # 删除锁文件
                    try:
                        if os.path.exists(lock_file):
                            os.remove(lock_file)
                    except Exception as e:
                        logger.error(f"[WX849] 删除锁文件失败: {e}")

        # 输出日志 - 修改为显示完整XML内容
        logger.info(f"收到图片消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}")

        # 记录最近收到的图片消息，用于识图等功能的关联
        session_id = cmsg.from_user_id if cmsg.is_group else cmsg.sender_wxid
        self.recent_image_msgs[session_id] = cmsg
        logger.info(f"[WX849] 已记录会话 {session_id} 的图片消息，可用于识图关联")

        # 如果已经有图片路径，更新消息内容为图片路径
        if hasattr(cmsg, 'image_path') and cmsg.image_path and os.path.exists(cmsg.image_path):
            # 更新消息内容为图片路径
            cmsg.content = cmsg.image_path
            # 确保消息类型为IMAGE
            cmsg.ctype = ContextType.IMAGE
            # 图片已下载完成，记录日志
            logger.info(f"[WX849] 图片下载完成，保存到: {cmsg.image_path}")

            # 不再在这里生成上下文并发送到DOW框架
            # 图片消息只在_process_single_message_independently方法中处理一次

    async def _download_image(self, cmsg):
        """下载图片并设置本地路径"""
        try:
            # 检查是否已经有图片路径
            if hasattr(cmsg, 'image_path') and cmsg.image_path and os.path.exists(cmsg.image_path):
                logger.info(f"[WX849] 图片已存在，路径: {cmsg.image_path}")
                return True

            # 创建临时目录
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")
            os.makedirs(tmp_dir, exist_ok=True)

            # 检查是否已经存在相同的图片文件
            msg_id = cmsg.msg_id
            existing_files = [f for f in os.listdir(tmp_dir) if f.startswith(f"img_{msg_id}_")]

            if existing_files:
                # 找到最新的文件
                latest_file = sorted(existing_files, key=lambda x: os.path.getmtime(os.path.join(tmp_dir, x)), reverse=True)[0]
                existing_path = os.path.join(tmp_dir, latest_file)

                # 检查文件是否有效
                if os.path.exists(existing_path) and os.path.getsize(existing_path) > 0:
                    try:
                        from PIL import Image
                        try:
                            # 尝试打开图片文件
                            with Image.open(existing_path) as img:
                                # 获取图片格式和大小
                                img_format = img.format
                                img_size = img.size
                                logger.info(f"[WX849] 图片已存在且有效: 格式={img_format}, 大小={img_size}")

                                # 设置图片本地路径
                                cmsg.image_path = existing_path
                                cmsg.content = existing_path
                                cmsg.ctype = ContextType.IMAGE
                                cmsg._prepared = True

                                logger.info(f"[WX849] 使用已存在的图片文件: {existing_path}")
                                return True
                        except Exception as img_err:
                            logger.warning(f"[WX849] 已存在的图片文件无效，重新下载: {img_err}")
                    except ImportError:
                        # 如果PIL库未安装，假设文件有效
                        if os.path.getsize(existing_path) > 10000:  # 至少10KB
                            cmsg.image_path = existing_path
                            cmsg.content = existing_path
                            cmsg.ctype = ContextType.IMAGE
                            cmsg._prepared = True

                            logger.info(f"[WX849] 使用已存在的图片文件: {existing_path}")
                            return True

            # 生成图片文件名
            image_filename = f"img_{cmsg.msg_id}_{int(time.time())}.jpg"
            image_path = os.path.join(tmp_dir, image_filename)

            # 直接使用分段下载方法，不再尝试使用GetMsgImage
            logger.info(f"[WX849] 使用分段下载方法获取图片")
            result = await self._download_image_by_chunks(cmsg, image_path)
            return result

        except Exception as e:
            logger.error(f"[WX849] 下载图片过程中出错: {e}")
            logger.error(traceback.format_exc())
            return False

    async def _download_image_by_chunks(self, cmsg, image_path):
        """使用分段下载方法获取图片"""
        try:
            # 创建临时目录
            tmp_dir = os.path.dirname(image_path)
            os.makedirs(tmp_dir, exist_ok=True)

            # 检查是否已经存在相同的图片文件
            msg_id = cmsg.msg_id
            existing_files = [f for f in os.listdir(tmp_dir) if f.startswith(f"img_{msg_id}_")]

            if existing_files:
                # 找到最新的文件
                latest_file = sorted(existing_files, key=lambda x: os.path.getmtime(os.path.join(tmp_dir, x)), reverse=True)[0]
                existing_path = os.path.join(tmp_dir, latest_file)

                # 检查文件是否有效
                if os.path.exists(existing_path) and os.path.getsize(existing_path) > 0:
                    try:
                        from PIL import Image
                        try:
                            # 尝试打开图片文件
                            with Image.open(existing_path) as img:
                                # 获取图片格式和大小
                                img_format = img.format
                                img_size = img.size
                                logger.info(f"[WX849] 图片已存在且有效: 格式={img_format}, 大小={img_size}")

                                # 设置图片本地路径
                                cmsg.image_path = existing_path
                                cmsg.content = existing_path
                                cmsg.ctype = ContextType.IMAGE
                                cmsg._prepared = True

                                logger.info(f"[WX849] 使用已存在的图片文件: {existing_path}")
                                return True
                        except Exception as img_err:
                            logger.warning(f"[WX849] 已存在的图片文件无效，重新下载: {img_err}")
                    except ImportError:
                        # 如果PIL库未安装，假设文件有效
                        if os.path.getsize(existing_path) > 10000:  # 至少10KB
                            cmsg.image_path = existing_path
                            cmsg.content = existing_path
                            cmsg.ctype = ContextType.IMAGE
                            cmsg._prepared = True

                            logger.info(f"[WX849] 使用已存在的图片文件: {existing_path}")
                            return True

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 估计图片大小
            data_len = int(cmsg.image_info.get('length', '0'))
            if data_len <= 0:
                data_len = 229920  # 默认大小

            # 分段大小
            chunk_size = 65536  # 64KB - 必须使用这个大小，API限制每次最多下载64KB

            # 计算分段数
            num_chunks = (data_len + chunk_size - 1) // chunk_size
            if num_chunks <= 0:
                num_chunks = 1  # 至少分1段

            # 不限制最大分段数，确保完整下载图片
            # 但记录一个警告，如果分段数过多
            if num_chunks > 20:
                logger.warning(f"[WX849] 图片分段数较多 ({num_chunks})，下载可能需要较长时间")

            logger.info(f"[WX849] 开始分段下载图片，总大小: {data_len} 字节，分 {num_chunks} 段下载")

            # 创建一个空文件
            with open(image_path, "wb") as f:
                pass

            # 分段下载
            all_chunks_success = True
            for i in range(num_chunks):
                start_pos = i * chunk_size
                current_chunk_size = min(chunk_size, data_len - start_pos)
                if current_chunk_size <= 0:
                    current_chunk_size = chunk_size

                # 构建API请求参数 - 使用与原始框架相同的格式
                params = {
                    "MsgId": cmsg.msg_id,
                    "ToWxid": cmsg.from_user_id,
                    "Wxid": self.wxid,
                    "DataLen": data_len,
                    "CompressType": 0,
                    "Section": {
                        "StartPos": start_pos,
                        "DataLen": current_chunk_size
                    }
                }

                logger.debug(f"[WX849] 尝试下载图片分段: MsgId={cmsg.msg_id}, ToWxid={cmsg.from_user_id}, DataLen={data_len}, StartPos={start_pos}, ChunkSize={current_chunk_size}")

                # 构建完整的API URL - 尝试不同的API路径
                # 首先尝试 /VXAPI/Tools/DownloadImg
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Tools/DownloadImg"

                # 记录完整的请求URL和参数
                logger.debug(f"[WX849] 图片下载API URL: {api_url}")
                logger.debug(f"[WX849] 图片下载API参数: {params}")

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(api_url, json=params) as response:
                            if response.status != 200:
                                logger.error(f"[WX849] 下载图片分段失败, 状态码: {response.status}")
                                all_chunks_success = False
                                break

                            # 获取响应内容
                            result = await response.json()

                            # 检查响应是否成功
                            if not result.get("Success", False):
                                logger.error(f"[WX849] 下载图片分段失败: {result.get('Message', '未知错误')}")
                                all_chunks_success = False
                                break

                            # 提取图片数据 - 适应原始框架的响应格式
                            data = result.get("Data", {})

                            # 记录响应结构以便调试
                            if isinstance(data, dict):
                                logger.debug(f"[WX849] 响应Data字段包含键: {list(data.keys())}")

                            # 尝试不同的响应格式
                            chunk_base64 = None

                            # 参考 WechatAPI/Client/tool_extension.py 中的处理方式
                            if isinstance(data, dict):
                                # 如果是字典，尝试获取buffer字段
                                if "buffer" in data:
                                    logger.debug(f"[WX849] 从data.buffer字段获取图片数据")
                                    chunk_base64 = data.get("buffer")
                                elif "data" in data and isinstance(data["data"], dict) and "buffer" in data["data"]:
                                    logger.debug(f"[WX849] 从data.data.buffer字段获取图片数据")
                                    chunk_base64 = data["data"]["buffer"]
                                else:
                                    # 尝试其他可能的字段名
                                    for field in ["Chunk", "Image", "Data", "FileData", "data"]:
                                        if field in data:
                                            logger.debug(f"[WX849] 从data.{field}字段获取图片数据")
                                            chunk_base64 = data.get(field)
                                            break
                            elif isinstance(data, str):
                                # 如果直接返回字符串，可能就是base64数据
                                logger.debug(f"[WX849] Data字段是字符串，直接使用")
                                chunk_base64 = data

                            # 如果在data中没有找到，尝试在整个响应中查找
                            if not chunk_base64 and isinstance(result, dict):
                                for field in ["data", "Data", "FileData", "Image"]:
                                    if field in result:
                                        logger.debug(f"[WX849] 从result.{field}字段获取图片数据")
                                        chunk_base64 = result.get(field)
                                        break

                            if not chunk_base64:
                                logger.error(f"[WX849] 下载图片分段失败: 响应中无图片数据")
                                # 避免记录大量数据，只记录数据类型和长度
                                if isinstance(data, dict):
                                    logger.debug(f"[WX849] 响应数据类型: 字典, 键: {list(data.keys())}")
                                elif isinstance(data, str):
                                    logger.debug(f"[WX849] 响应数据类型: 字符串, 长度: {len(data)}")
                                else:
                                    logger.debug(f"[WX849] 响应数据类型: {type(data)}")
                                all_chunks_success = False
                                break

                            # 解码数据并保存图片分段
                            try:
                                # 尝试确定数据类型并正确处理
                                if isinstance(chunk_base64, str):
                                    # 尝试作为Base64解码
                                    try:
                                        # 修复：确保字符串是有效的Base64
                                        # 移除可能的非Base64字符
                                        clean_base64 = chunk_base64.strip()
                                        # 确保长度是4的倍数，如果不是，添加填充
                                        padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                                        clean_base64 = clean_base64 + ('=' * padding)

                                        chunk_data = base64.b64decode(clean_base64)
                                        logger.debug(f"[WX849] 成功解码Base64数据，大小: {len(chunk_data)} 字节")
                                    except Exception as decode_err:
                                        logger.error(f"[WX849] Base64解码失败: {decode_err}")
                                        # 如果解码失败，记录错误并跳过这个分段
                                        logger.error(f"[WX849] 无法解码的数据: {chunk_base64[:100]}...")
                                        raise decode_err
                                elif isinstance(chunk_base64, bytes):
                                    # 已经是二进制数据，直接使用
                                    logger.debug(f"[WX849] 使用二进制数据，大小: {len(chunk_base64)} 字节")
                                    chunk_data = chunk_base64
                                elif isinstance(chunk_base64, dict):
                                    # 如果是字典，尝试从字典中提取数据
                                    logger.debug(f"[WX849] 数据是字典类型，键: {list(chunk_base64.keys())}")
                                    # 尝试从常见的键中获取数据
                                    found_data = False
                                    for key in ['data', 'Data', 'content', 'Content', 'image', 'Image']:
                                        if key in chunk_base64:
                                            data_value = chunk_base64[key]
                                            if isinstance(data_value, str):
                                                try:
                                                    # 清理和填充Base64字符串
                                                    clean_base64 = data_value.strip()
                                                    padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                                                    clean_base64 = clean_base64 + ('=' * padding)

                                                    chunk_data = base64.b64decode(clean_base64)
                                                    logger.debug(f"[WX849] 从字典键 {key} 成功解码Base64数据，大小: {len(chunk_data)} 字节")
                                                    found_data = True
                                                    break
                                                except Exception as e:
                                                    logger.debug(f"[WX849] 从字典键 {key} 解码Base64失败: {e}")
                                                    continue
                                            elif isinstance(data_value, bytes):
                                                chunk_data = data_value
                                                logger.debug(f"[WX849] 从字典键 {key} 获取到二进制数据，大小: {len(data_value)} 字节")
                                                found_data = True
                                                break

                                    # 如果常见键中没有找到，尝试遍历所有键
                                    if not found_data:
                                        logger.debug(f"[WX849] 在常见键中未找到数据，尝试遍历所有键")
                                        for key, value in chunk_base64.items():
                                            if isinstance(value, str) and len(value) > 10:  # 只处理可能是Base64的长字符串
                                                try:
                                                    # 清理和填充Base64字符串
                                                    clean_base64 = value.strip()
                                                    padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                                                    clean_base64 = clean_base64 + ('=' * padding)

                                                    chunk_data = base64.b64decode(clean_base64)
                                                    logger.debug(f"[WX849] 从字典键 {key} 成功解码Base64数据，大小: {len(chunk_data)} 字节")
                                                    found_data = True
                                                    break
                                                except Exception:
                                                    continue
                                            elif isinstance(value, bytes) and len(value) > 10:
                                                chunk_data = value
                                                logger.debug(f"[WX849] 从字典键 {key} 获取到二进制数据，大小: {len(value)} 字节")
                                                found_data = True
                                                break
                                            elif isinstance(value, dict) and len(value) > 0:
                                                # 递归处理嵌套字典
                                                logger.debug(f"[WX849] 发现嵌套字典，键: {key}，尝试递归处理")
                                                for subkey, subvalue in value.items():
                                                    if isinstance(subvalue, str) and len(subvalue) > 10:
                                                        try:
                                                            # 清理和填充Base64字符串
                                                            clean_base64 = subvalue.strip()
                                                            padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                                                            clean_base64 = clean_base64 + ('=' * padding)

                                                            chunk_data = base64.b64decode(clean_base64)
                                                            logger.debug(f"[WX849] 从嵌套字典键 {key}.{subkey} 成功解码Base64数据，大小: {len(chunk_data)} 字节")
                                                            found_data = True
                                                            break
                                                        except Exception:
                                                            continue
                                                    elif isinstance(subvalue, bytes) and len(subvalue) > 10:
                                                        chunk_data = subvalue
                                                        logger.debug(f"[WX849] 从嵌套字典键 {key}.{subkey} 获取到二进制数据，大小: {len(subvalue)} 字节")
                                                        found_data = True
                                                        break
                                                if found_data:
                                                    break

                                    # 如果仍然没有找到有效数据，尝试使用整个字典的字符串表示
                                    if not found_data:
                                        logger.warning(f"[WX849] 无法从字典中提取有效的图片数据，尝试使用默认空数据")
                                        # 创建一个空的JPEG图片数据（最小的有效JPEG文件）
                                        chunk_data = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xff\xd9'
                                        logger.debug(f"[WX849] 使用默认空JPEG数据，大小: {len(chunk_data)} 字节")
                                else:
                                    # 其他类型，尝试转换为字符串后处理
                                    logger.warning(f"[WX849] 未知数据类型: {type(chunk_base64)}，尝试转换为字符串")
                                    try:
                                        # 尝试转换为字符串
                                        str_value = str(chunk_base64)
                                        if len(str_value) > 10:  # 只处理可能有意义的字符串
                                            try:
                                                # 清理和填充Base64字符串
                                                clean_base64 = str_value.strip()
                                                padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                                                clean_base64 = clean_base64 + ('=' * padding)

                                                chunk_data = base64.b64decode(clean_base64)
                                                logger.debug(f"[WX849] 成功将未知类型转换为Base64并解码，大小: {len(chunk_data)} 字节")
                                            except Exception as e:
                                                logger.warning(f"[WX849] 无法将未知类型转换为Base64: {e}")
                                                # 使用默认空JPEG数据
                                                chunk_data = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xff\xd9'
                                                logger.debug(f"[WX849] 使用默认空JPEG数据，大小: {len(chunk_data)} 字节")
                                        else:
                                            # 字符串太短，使用默认空JPEG数据
                                            chunk_data = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xff\xd9'
                                            logger.debug(f"[WX849] 使用默认空JPEG数据，大小: {len(chunk_data)} 字节")
                                    except Exception as e:
                                        logger.error(f"[WX849] 处理未知数据类型失败: {e}")
                                        # 使用默认空JPEG数据
                                        chunk_data = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xff\xd9'
                                        logger.debug(f"[WX849] 使用默认空JPEG数据，大小: {len(chunk_data)} 字节")

                                # 验证数据是否为有效的图片数据
                                if 'chunk_data' in locals() and chunk_data:
                                    # 追加到文件
                                    with open(image_path, "ab") as f:
                                        f.write(chunk_data)
                                    logger.debug(f"[WX849] 第 {i+1}/{num_chunks} 段下载成功，大小: {len(chunk_data)} 字节")
                                else:
                                    logger.error(f"[WX849] 第 {i+1}/{num_chunks} 段下载失败: 无有效数据")
                                    all_chunks_success = False
                                    break
                            except Exception as decode_err:
                                logger.error(f"[WX849] 解码Base64图片分段数据失败: {decode_err}")
                                all_chunks_success = False
                                break
                except Exception as api_err:
                    logger.error(f"[WX849] 调用图片分段API失败: {api_err}")
                    all_chunks_success = False
                    break

            if all_chunks_success:
                # 检查文件大小
                file_size = os.path.getsize(image_path)
                logger.info(f"[WX849] 分段下载图片成功，总大小: {file_size} 字节")

                # 如果文件大小与预期不符，记录警告
                if file_size < data_len * 0.8:  # 如果实际大小小于预期的80%
                    logger.warning(f"[WX849] 图片文件大小 ({file_size} 字节) 小于预期 ({data_len} 字节)，可能下载不完整")

                    # 如果文件太小，尝试再次下载缺失的部分
                    if file_size > 0 and file_size < data_len:
                        logger.info(f"[WX849] 尝试下载缺失的图片部分，从位置 {file_size} 开始")

                        # 计算剩余部分的分段数
                        remaining_size = data_len - file_size
                        remaining_chunks = (remaining_size + chunk_size - 1) // chunk_size

                        # 下载剩余部分
                        remaining_success = True
                        for i in range(remaining_chunks):
                            start_pos = file_size + i * chunk_size
                            current_chunk_size = min(chunk_size, data_len - start_pos)

                            if current_chunk_size <= 0:
                                break

                            # 构建API请求参数
                            params = {
                                "MsgId": cmsg.msg_id,
                                "ToWxid": cmsg.from_user_id,
                                "Wxid": self.wxid,
                                "DataLen": data_len,
                                "CompressType": 0,
                                "Section": {
                                    "StartPos": start_pos,
                                    "DataLen": current_chunk_size
                                }
                            }

                            logger.debug(f"[WX849] 尝试下载缺失的图片分段: MsgId={cmsg.msg_id}, StartPos={start_pos}, ChunkSize={current_chunk_size}")

                            try:
                                async with aiohttp.ClientSession() as session:
                                    async with session.post(api_url, json=params) as response:
                                        if response.status != 200:
                                            logger.error(f"[WX849] 下载缺失的图片分段失败, 状态码: {response.status}")
                                            remaining_success = False
                                            break

                                        result = await response.json()

                                        if not result.get("Success", False):
                                            logger.error(f"[WX849] 下载缺失的图片分段失败: {result.get('Message', '未知错误')}")
                                            remaining_success = False
                                            break

                                        # 提取图片数据
                                        data = result.get("Data", {})
                                        chunk_base64 = None

                                        # 参考 WechatAPI/Client/tool_extension.py 中的处理方式
                                        if isinstance(data, dict):
                                            if "buffer" in data:
                                                chunk_base64 = data.get("buffer")
                                            elif "data" in data and isinstance(data["data"], dict) and "buffer" in data["data"]:
                                                chunk_base64 = data["data"]["buffer"]

                                        if chunk_base64:
                                            try:
                                                chunk_data = base64.b64decode(chunk_base64)
                                                with open(image_path, "ab") as f:
                                                    f.write(chunk_data)
                                                logger.debug(f"[WX849] 缺失的图片分段下载成功，大小: {len(chunk_data)} 字节")
                                            except Exception as e:
                                                logger.error(f"[WX849] 解码缺失的图片分段数据失败: {e}")
                                                remaining_success = False
                                                break
                                        else:
                                            logger.error(f"[WX849] 下载缺失的图片分段失败: 响应中无图片数据")
                                            remaining_success = False
                                            break
                            except Exception as e:
                                logger.error(f"[WX849] 下载缺失的图片分段失败: {e}")
                                remaining_success = False
                                break

                        if remaining_success:
                            file_size = os.path.getsize(image_path)
                            logger.info(f"[WX849] 成功下载缺失的图片部分，最终大小: {file_size} 字节")

                # 检查文件是否存在且有效
                if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                    # 验证图片文件是否为有效的图片格式
                    try:
                        from PIL import Image
                        try:
                            # 尝试打开图片文件
                            with Image.open(image_path) as img:
                                # 获取图片格式和大小
                                img_format = img.format
                                img_size = img.size
                                logger.info(f"[WX849] 图片验证成功: 格式={img_format}, 大小={img_size}")
                        except Exception as img_err:
                            logger.error(f"[WX849] 图片验证失败，可能不是有效的图片文件: {img_err}")
                            # 尝试修复图片文件
                            try:
                                # 读取文件内容
                                with open(image_path, "rb") as f:
                                    img_data = f.read()

                                # 尝试查找JPEG文件头和尾部标记
                                jpg_header = b'\xff\xd8'
                                jpg_footer = b'\xff\xd9'

                                if img_data.startswith(jpg_header) and img_data.endswith(jpg_footer):
                                    logger.info(f"[WX849] 图片文件有效的JPEG头尾标记，但内部可能有损坏")
                                else:
                                    # 查找JPEG头部标记的位置
                                    header_pos = img_data.find(jpg_header)
                                    if header_pos >= 0:
                                        # 查找JPEG尾部标记的位置
                                        footer_pos = img_data.rfind(jpg_footer)
                                        if footer_pos > header_pos:
                                            # 提取有效的JPEG数据
                                            valid_data = img_data[header_pos:footer_pos+2]
                                            # 重写文件
                                            with open(image_path, "wb") as f:
                                                f.write(valid_data)
                                            logger.info(f"[WX849] 尝试修复图片文件，提取了 {len(valid_data)} 字节的有效JPEG数据")
                            except Exception as fix_err:
                                logger.error(f"[WX849] 尝试修复图片文件失败: {fix_err}")
                    except ImportError:
                        logger.warning(f"[WX849] PIL库未安装，无法验证图片有效性")

                    # 设置图片本地路径
                    cmsg.image_path = image_path

                    # 更新消息内容为图片路径，以便DOW框架处理
                    cmsg.content = image_path

                    # 确保消息类型为IMAGE
                    cmsg.ctype = ContextType.IMAGE

                    # 设置_prepared标志，表示图片已准备好
                    cmsg._prepared = True

                    # 图片已经在回调处理时发送到DOW框架，这里只记录日志
                    logger.info(f"[WX849] 图片下载完成，保存到: {cmsg.image_path}")

                    # 返回True表示下载成功
                    return True
                else:
                    logger.error(f"[WX849] 图片文件不存在或为空: {image_path}")
                    return False
        except Exception as e:
            logger.error(f"[WX849] 下载图片失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")

    def _get_image(self, msg_id):
        """获取图片数据"""
        # 查找图片文件
        tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")

        # 查找匹配的图片文件
        if os.path.exists(tmp_dir):
            for filename in os.listdir(tmp_dir):
                if filename.startswith(f"img_{msg_id}_"):
                    image_path = os.path.join(tmp_dir, filename)
                    try:
                        # 验证图片文件是否为有效的图片格式
                        try:
                            from PIL import Image
                            try:
                                # 尝试打开图片文件
                                with Image.open(image_path) as img:
                                    # 获取图片格式和大小
                                    img_format = img.format
                                    img_size = img.size
                                    logger.info(f"[WX849] 图片验证成功: 格式={img_format}, 大小={img_size}")
                            except Exception as img_err:
                                logger.error(f"[WX849] 图片验证失败，可能不是有效的图片文件: {img_err}")
                                # 尝试修复图片文件
                                try:
                                    # 读取文件内容
                                    with open(image_path, "rb") as f:
                                        img_data = f.read()

                                    # 尝试查找JPEG文件头和尾部标记
                                    jpg_header = b'\xff\xd8'
                                    jpg_footer = b'\xff\xd9'

                                    if img_data.startswith(jpg_header) and img_data.endswith(jpg_footer):
                                        logger.info(f"[WX849] 图片文件有效的JPEG头尾标记，但内部可能有损坏")
                                    else:
                                        # 查找JPEG头部标记的位置
                                        header_pos = img_data.find(jpg_header)
                                        if header_pos >= 0:
                                            # 查找JPEG尾部标记的位置
                                            footer_pos = img_data.rfind(jpg_footer)
                                            if footer_pos > header_pos:
                                                # 提取有效的JPEG数据
                                                valid_data = img_data[header_pos:footer_pos+2]
                                                # 重写文件
                                                with open(image_path, "wb") as f:
                                                    f.write(valid_data)
                                                logger.info(f"[WX849] 尝试修复图片文件，提取了 {len(valid_data)} 字节的有效JPEG数据")
                                                # 返回修复后的数据
                                                return valid_data
                                except Exception as fix_err:
                                    logger.error(f"[WX849] 尝试修复图片文件失败: {fix_err}")
                        except ImportError:
                            logger.warning(f"[WX849] PIL库未安装，无法验证图片有效性")

                        # 读取图片文件
                        with open(image_path, "rb") as f:
                            image_data = f.read()
                            logger.info(f"[WX849] 成功读取图片文件: {image_path}, 大小: {len(image_data)} 字节")
                            return image_data
                    except Exception as e:
                        logger.error(f"[WX849] 读取图片文件失败: {e}")
                        return None

        logger.error(f"[WX849] 未找到图片文件: msg_id={msg_id}")
        return None
    
    def _process_sharing_message(self, cmsg):
        """处理分享消息"""
        import re
        import xml.etree.ElementTree as ET

        cmsg.ctype = ContextType.SHARING

        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            split_content = cmsg.content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                cmsg.content = split_content[1]
            else:
                # 处理没有换行的情况
                split_content = cmsg.content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    cmsg.content = split_content[1]
                else:
                    cmsg.content = split_content[0]
                    cmsg.sender_wxid = ""

            # 设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

            # 私聊消息也设置actual_user_id和actual_user_nickname
            cmsg.actual_user_id = cmsg.from_user_id
            cmsg.actual_user_nickname = cmsg.from_user_id

        # 解析分享信息
        try:
            logger.debug(f"解析分享消息内容: {cmsg.content[:100]}")
            # 检查内容是否是XML
            if cmsg.content and (cmsg.content.startswith('<?xml') or cmsg.content.startswith('<msg>')):
                try:
                    root = ET.fromstring(cmsg.content)
                    appmsg_element = root.find('appmsg')
                    if appmsg_element is not None:
                        url_element = appmsg_element.find('url')
                        if url_element is not None:
                            cmsg.content = url_element.text
                            logger.debug(f"[WX849] 解析分享消息XML成功: URL={cmsg.content}")
                        else:
                            logger.warning(f"[WX849] XML中未找到URL")
                    else:
                        logger.warning(f"[WX849] XML中未找到appmsg")
                except ET.ParseError as xml_err:
                    # XML解析失败，创建一个默认的image_info
                    logger.warning(f"[WX849] XML解析失败: {xml_err}")
        except Exception as e:
            logger.debug(f"解析分享消息失败: {e}, 内容: {cmsg.content[:100]}")
            logger.debug(f"详细错误: {traceback.format_exc()}")

        # 输出日志 - 修改为显示完整XML内容
        logger.info(f"收到分享消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}")


    def _process_voice_message(self, cmsg):
        """处理语音消息"""
        import xml.etree.ElementTree as ET
        import re

        cmsg.ctype = ContextType.VOICE

        # 保存原始内容，避免修改
        original_content = cmsg.content

        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")

        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 语音消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML字符串中提取fromusername属性或元素
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 语音消息：从XML属性提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    # 尝试从元素中提取
                    match = re.search(r'<fromusername>(.*?)</fromusername>', original_content)
                    if match:
                        cmsg.sender_wxid = match.group(1)
                        logger.debug(f"[WX849] 语音消息：从XML元素提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        logger.debug("[WX849] 语音消息：未找到fromusername")

                        # 尝试使用ElementTree解析
                        try:
                            root = ET.fromstring(original_content)
                            # 尝试查找语音元素的fromusername属性
                            voice_element = root.find('voicemsg')
                            if voice_element is not None and 'fromusername' in voice_element.attrib:
                                cmsg.sender_wxid = voice_element.attrib['fromusername']
                                logger.debug(f"[WX849] 语音消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                        except Exception as e:
                            logger.debug(f"[WX849] 语音消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 语音消息：提取发送者失败: {e}")

        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 语音消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 语音消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")

        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id

        # 解析语音信息 (保留此功能以获取语音URL等信息)
        try:
            root = ET.fromstring(original_content)
            voice_element = root.find('voicemsg')
            if voice_element is not None:
                cmsg.voice_info = {
                    'voiceurl': voice_element.get('voiceurl'),
                    'length': voice_element.get('length')
                }
                logger.debug(f"解析语音XML成功: voiceurl={cmsg.voice_info['voiceurl']}, length={cmsg.voice_info['length']}")
        except Exception as e:
            logger.debug(f"解析语音消息失败: {e}, 内容: {original_content[:100]}")
            cmsg.voice_info = {}

        # 确保保留原始XML内容
        cmsg.content = original_content

        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid

        # 输出日志，显示完整XML内容
        logger.info(f"收到语音消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_video_message(self, cmsg):
        """处理视频消息"""
        import xml.etree.ElementTree as ET
        import re

        cmsg.ctype = ContextType.VIDEO

        # 保存原始内容，避免修改
        original_content = cmsg.content

        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")

        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 视频消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML字符串中提取fromusername属性或元素
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 视频消息：从XML属性提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    # 尝试从元素中提取
                    match = re.search(r'<fromusername>(.*?)</fromusername>', original_content)
                    if match:
                        cmsg.sender_wxid = match.group(1)
                        logger.debug(f"[WX849] 视频消息：从XML元素提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        logger.debug("[WX849] 视频消息：未找到fromusername")

                        # 尝试使用ElementTree解析
                        try:
                            root = ET.fromstring(original_content)
                            # 尝试查找video元素的fromusername属性
                            video_element = root.find('videomsg')
                            if video_element is not None and 'fromusername' in video_element.attrib:
                                cmsg.sender_wxid = video_element.attrib['fromusername']
                                logger.debug(f"[WX849] 视频消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                        except Exception as e:
                            logger.debug(f"[WX849] 视频消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 视频消息：提取发送者失败: {e}")

        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 视频消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 视频消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")

        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id

        # 确保保留原始XML内容
        cmsg.content = original_content

        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid

        # 输出日志，显示完整XML内容
        logger.info(f"收到视频消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_emoji_message(self, cmsg):
        """处理表情消息"""
        import xml.etree.ElementTree as ET
        import re

        cmsg.ctype = ContextType.TEXT  # 表情消息通常也用TEXT类型

        # 保存原始内容，避免修改
        original_content = cmsg.content

        # 检查内容是否为XML格式
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")

        # 首先尝试从XML中提取发送者信息
        if is_xml_content:
            logger.debug(f"[WX849] 表情消息：尝试从XML提取发送者")
            try:
                # 使用正则表达式从XML中提取fromusername属性
                match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                if match:
                    cmsg.sender_wxid = match.group(1)
                    logger.debug(f"[WX849] 表情消息：从XML提取的发送者ID: {cmsg.sender_wxid}")
                else:
                    logger.debug("[WX849] 表情消息：未找到fromusername属性")

                    # 尝试使用ElementTree解析
                    try:
                        root = ET.fromstring(original_content)
                        emoji_element = root.find('emoji')
                        if emoji_element is not None and 'fromusername' in emoji_element.attrib:
                            cmsg.sender_wxid = emoji_element.attrib['fromusername']
                            logger.debug(f"[WX849] 表情消息：使用ElementTree提取的发送者ID: {cmsg.sender_wxid}")
                    except Exception as e:
                        logger.debug(f"[WX849] 表情消息：使用ElementTree解析失败: {e}")
            except Exception as e:
                logger.debug(f"[WX849] 表情消息：提取发送者失败: {e}")

        # 如果无法从XML提取，再尝试传统的分割方法
        if not cmsg.sender_wxid and (cmsg.is_group or cmsg.from_user_id.endswith("@chatroom")):
            cmsg.is_group = True
            split_content = original_content.split(":\n", 1)
            if len(split_content) > 1:
                cmsg.sender_wxid = split_content[0]
                logger.debug(f"[WX849] 表情消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
            else:
                # 处理没有换行的情况
                split_content = original_content.split(":", 1)
                if len(split_content) > 1:
                    cmsg.sender_wxid = split_content[0]
                    logger.debug(f"[WX849] 表情消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")

        # 对于私聊消息，使用from_user_id作为发送者ID
        if not cmsg.sender_wxid and not cmsg.is_group:
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id

        # 确保保留原始XML内容
        cmsg.content = original_content

        # 最终检查，确保发送者不是XML内容
        if not cmsg.sender_wxid or "<" in cmsg.sender_wxid:
            cmsg.sender_wxid = "未知发送者"
            cmsg.actual_user_id = cmsg.sender_wxid
            cmsg.actual_user_nickname = cmsg.sender_wxid

        # 输出日志，显示完整XML内容
        logger.info(f"收到表情消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} \nXML内容: {cmsg.content}")

    def _process_xml_message(self, cmsg):
        """处理XML消息"""
        # 导入需要的模块
        import re
        import xml.etree.ElementTree as ET

        # 先默认设置为XML类型，添加错误处理
        try:
            cmsg.ctype = ContextType.XML
        except AttributeError:
            # 如果XML类型不存在，尝试添加它
            logger.error("[WX849] ContextType.XML 不存在，尝试动态添加")
            if not hasattr(ContextType, 'XML'):
                setattr(ContextType, 'XML', 'XML')
                logger.info("[WX849] 运行时添加 ContextType.XML 类型成功")
            try:
                cmsg.ctype = ContextType.XML
            except:
                # 如果仍然失败，回退到TEXT类型
                logger.error("[WX849] 设置 ContextType.XML 失败，回退到 TEXT 类型")
                cmsg.ctype = ContextType.TEXT

        # 添加调试日志，记录原始XML内容
        logger.debug(f"[WX849] 开始处理XML消息，消息ID: {cmsg.msg_id}, 内容长度: {len(cmsg.content)}")
        if cmsg.content and len(cmsg.content) > 0:
            logger.debug(f"[WX849] XML内容前100字符: {cmsg.content[:100]}")
        else:
            logger.debug(f"[WX849] XML内容为空")

        # 检查内容是否为XML格式
        original_content = cmsg.content
        is_xml_content = original_content.strip().startswith("<?xml") or original_content.strip().startswith("<msg")

        # 处理群聊/私聊消息发送者
        if cmsg.is_group or cmsg.from_user_id.endswith("@chatroom"):
            cmsg.is_group = True
            # 先默认设置一个空的sender_wxid
            cmsg.sender_wxid = ""

            # 尝试从XML中提取发送者信息
            if is_xml_content:
                logger.debug(f"[WX849] XML消息：尝试从XML提取发送者")
                try:
                    # 尝试解析XML
                    root = ET.fromstring(original_content)

                    # 检查是否是引用消息（XML类型57）
                    xml_type = None
                    appmsg_element = root.find(".//appmsg")
                    if appmsg_element is not None:
                        type_element = appmsg_element.find("type")
                        if type_element is not None and type_element.text:
                            xml_type = type_element.text

                    logger.debug(f"[WX849] 解析到的 XML 类型: {xml_type}, 完整内容: {original_content}")

                    # 如果是引用消息（类型57），特殊处理
                    if xml_type == "57":
                        logger.debug(f"[WX849] 检测到引用消息（类型57）")

                        # 从refermsg元素中提取发送者信息
                        refermsg = appmsg_element.find("refermsg")
                        if refermsg is not None:
                            # 提取原始发送者ID
                            fromusr_element = refermsg.find("fromusr")
                            if fromusr_element is not None and fromusr_element.text:
                                cmsg.sender_wxid = fromusr_element.text
                                logger.debug(f"[WX849] 引用消息：从refermsg/fromusr提取的发送者ID: {cmsg.sender_wxid}")

                            # 如果没有fromusr，尝试chatusr
                            if not cmsg.sender_wxid:
                                chatusr_element = refermsg.find("chatusr")
                                if chatusr_element is not None and chatusr_element.text:
                                    cmsg.sender_wxid = chatusr_element.text
                                    logger.debug(f"[WX849] 引用消息：从refermsg/chatusr提取的发送者ID: {cmsg.sender_wxid}")

                            # 提取原始消息内容
                            content_element = refermsg.find("content")
                            if content_element is not None and content_element.text:
                                # 保存原始引用的内容
                                cmsg.quoted_content = content_element.text
                                logger.debug(f"[WX849] 引用消息：引用的原始内容: {cmsg.quoted_content}")

                                # 检查是否是图片消息
                                if refermsg.find("type") is not None and refermsg.find("type").text == "3":
                                    try:
                                        # 解码XML实体
                                        decoded_content = cmsg.quoted_content.replace("&lt;", "<").replace("&gt;", ">")

                                        # 尝试解析XML
                                        img_root = ET.fromstring(decoded_content)
                                        img_element = img_root.find("img")

                                        if img_element is not None:
                                            # 提取图片信息
                                            cmsg.quoted_image_info = {
                                                'aeskey': img_element.get('aeskey', ''),
                                                'cdnmidimgurl': img_element.get('cdnmidimgurl', ''),
                                                'length': img_element.get('length', '0'),
                                                'md5': img_element.get('md5', '')
                                            }
                                            logger.debug(f"[WX849] 引用消息：提取图片信息成功: aeskey={cmsg.quoted_image_info.get('aeskey', '')}, length={cmsg.quoted_image_info.get('length', '0')}")
                                    except Exception as e:
                                        logger.debug(f"[WX849] 引用消息：解析图片信息失败: {e}")

                            # 提取显示名称
                            displayname_element = refermsg.find("displayname")
                            if displayname_element is not None and displayname_element.text:
                                cmsg.quoted_nickname = displayname_element.text
                                logger.debug(f"[WX849] 引用消息：引用的发送者昵称: {cmsg.quoted_nickname}")

                    # 如果不是引用消息或者无法从引用消息中提取，尝试其他方法
                    if not cmsg.sender_wxid:
                        # 尝试从fromusername元素提取
                        fromusername = root.find(".//fromusername")
                        if fromusername is not None and fromusername.text:
                            cmsg.sender_wxid = fromusername.text
                            logger.debug(f"[WX849] XML消息：从fromusername元素提取的发送者ID: {cmsg.sender_wxid}")
                        else:
                            # 使用正则表达式从XML中提取fromusername属性
                            match = re.search(r'fromusername\s*=\s*["\'](.*?)["\']', original_content)
                            if match:
                                cmsg.sender_wxid = match.group(1)
                                logger.debug(f"[WX849] XML消息：从XML属性提取的发送者ID: {cmsg.sender_wxid}")
                except Exception as e:
                    logger.debug(f"[WX849] XML消息：提取发送者失败: {e}")
                    logger.debug(traceback.format_exc())

            # 如果无法从XML提取，尝试传统的分割方法
            if not cmsg.sender_wxid:
                # 检查是否是引用消息格式（包含"引用:"的文本）
                if " 引用:" in original_content:
                    try:
                        # 尝试提取真实发送者ID
                        parts = original_content.split(" 引用:", 1)
                        if len(parts) > 1:
                            # 提取发送者ID
                            sender_part = parts[0]
                            # 如果发送者部分包含@，可能是格式为"@小小x 酱爆说了啥"
                            if sender_part.startswith("@"):
                                # 使用SenderWxid字段作为发送者ID
                                if "SenderWxid" in cmsg.msg and cmsg.msg["SenderWxid"]:
                                    cmsg.sender_wxid = cmsg.msg["SenderWxid"]
                                    logger.debug(f"[WX849] 引用消息：使用SenderWxid字段作为发送者ID: {cmsg.sender_wxid}")
                            else:
                                # 尝试常规分割方法
                                split_content = sender_part.split(":", 1)
                                if len(split_content) > 1 and not split_content[0].startswith("<"):
                                    cmsg.sender_wxid = split_content[0]
                                    logger.debug(f"[WX849] 引用消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")
                    except Exception as e:
                        logger.debug(f"[WX849] 引用消息：提取发送者失败: {e}")
                else:
                    # 常规分割方法
                    split_content = original_content.split(":\n", 1)
                    if len(split_content) > 1 and not split_content[0].startswith("<"):
                        cmsg.sender_wxid = split_content[0]
                        logger.debug(f"[WX849] XML消息：使用分割方法提取的发送者ID: {cmsg.sender_wxid}")
                    else:
                        # 处理没有换行的情况
                        split_content = original_content.split(":", 1)
                        if len(split_content) > 1 and not split_content[0].startswith("<"):
                            cmsg.sender_wxid = split_content[0]
                            logger.debug(f"[WX849] XML消息：使用冒号分割提取的发送者ID: {cmsg.sender_wxid}")

            # 如果仍然无法提取，尝试使用SenderWxid字段
            if not cmsg.sender_wxid and "SenderWxid" in cmsg.msg and cmsg.msg["SenderWxid"]:
                cmsg.sender_wxid = cmsg.msg["SenderWxid"]
                logger.debug(f"[WX849] XML消息：使用SenderWxid字段作为发送者ID: {cmsg.sender_wxid}")

            # 如果仍然无法提取，使用默认值
            if not cmsg.sender_wxid:
                cmsg.sender_wxid = f"未知用户_{cmsg.from_user_id}"
                logger.debug(f"[WX849] XML消息：使用默认发送者ID: {cmsg.sender_wxid}")
        else:
            # 私聊消息
            cmsg.sender_wxid = cmsg.from_user_id
            cmsg.is_group = False

        # 设置actual_user_id和actual_user_nickname
        cmsg.actual_user_id = cmsg.sender_wxid or cmsg.from_user_id
        cmsg.actual_user_nickname = cmsg.sender_wxid or cmsg.from_user_id

        # 检查XML消息内容中是否包含@机器人的文本
        if cmsg.is_group and cmsg.content:
            # 获取可能的机器人名称
            robot_names = []
            if self.name:
                robot_names.append(self.name)
            if hasattr(cmsg, 'self_display_name') and cmsg.self_display_name:
                robot_names.append(cmsg.self_display_name)

            # 检查消息中是否包含@机器人名称
            for name in robot_names:
                at_text = f"@{name}"
                if at_text in cmsg.content:
                    logger.debug(f"[WX849] 在XML消息内容中直接匹配到@机器人: {at_text}")
                    cmsg.is_at = True

                    # 确保at_list中包含机器人wxid
                    if not hasattr(cmsg, 'at_list'):
                        cmsg.at_list = []
                    if self.wxid not in cmsg.at_list:
                        cmsg.at_list.append(self.wxid)

                    # 确保设置了is_at标志
                    cmsg.is_at = True

                    # 尝试移除@文本，保留实际内容
                    for pattern in [f"@{name} ", f"@{name}\u2005", f"@{name}"]:
                        if pattern in cmsg.content:
                            cmsg.content = cmsg.content.replace(pattern, "", 1).strip()
                            logger.debug(f"[WX849] 去除XML消息中的@文本后的内容: {cmsg.content}")
                            break
                    break

        # 输出日志，显示完整XML内容
        logger.info(f"收到XML消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid}\nXML内容: {cmsg.content}")

    def _process_system_message(self, cmsg):
        """处理系统消息"""
        # 移除重复导入的ET

        # 检查是否是拍一拍消息
        if "<pat" in cmsg.content:
            try:
                root = ET.fromstring(cmsg.content)
                pat = root.find("pat")
                if pat is not None:
                    cmsg.ctype = ContextType.PAT  # 使用自定义类型
                    patter = pat.find("fromusername").text if pat.find("fromusername") is not None else ""
                    patted = pat.find("pattedusername").text if pat.find("pattedusername") is not None else ""
                    pat_suffix = pat.find("patsuffix").text if pat.find("patsuffix") is not None else ""
                    cmsg.pat_info = {
                        "patter": patter,
                        "patted": patted,
                        "suffix": pat_suffix
                    }

                    # 设置actual_user_id和actual_user_nickname
                    cmsg.sender_wxid = patter
                    cmsg.actual_user_id = patter
                    cmsg.actual_user_nickname = patter

                    # 日志输出
                    logger.info(f"收到拍一拍消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 拍者:{patter} 被拍:{patted} 后缀:{pat_suffix}")
                    return
            except Exception as e:
                logger.debug(f"[WX849] 解析拍一拍消息失败: {e}")

        # 如果不是特殊系统消息，按普通系统消息处理
        cmsg.ctype = ContextType.SYSTEM

        # 设置系统消息的actual_user_id和actual_user_nickname为系统
        cmsg.sender_wxid = "系统消息"
        cmsg.actual_user_id = "系统消息"
        cmsg.actual_user_nickname = "系统消息"

        logger.info(f"收到系统消息: ID:{cmsg.msg_id} 来自:{cmsg.from_user_id} 发送人:{cmsg.sender_wxid} 内容:{cmsg.content}")

    async def _call_api(self, endpoint, params):
        """通用API调用方法，用于直接访问WechatAPI的端点"""
        try:
            import aiohttp

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)

            # 确定API路径前缀
            protocol_version = conf().get("wx849_protocol_version", "849")
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建完整的API URL
            url = f"http://{api_host}:{api_port}{api_path_prefix}{endpoint}"

            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as response:
                    if response.status != 200:
                        logger.error(f"[WX849] API请求失败: {url}, 状态码: {response.status}")
                        return None

                    # 解析响应
                    result = await response.json()
                    return result
        except Exception as e:
            logger.error(f"[WX849] API调用失败: {endpoint}, 错误: {e}")
            return None

    async def _send_message(self, to_user_id, content, msg_type=1, at_list=None, context=None):
        """发送消息的异步方法"""
        try:
            # 移除ignore_protection参数，使用正确的API参数格式
            if not to_user_id:
                logger.error("[WX849] 发送消息失败: 接收者ID为空")
                return None

            # 如果有上下文对象，从上下文中获取接收者，确保使用正确的接收者
            if context and "receiver" in context:
                actual_receiver = context.get("receiver")
                if actual_receiver != to_user_id:
                    logger.warning(f"[WX849] 接收者不匹配! 参数接收者: {to_user_id}, 上下文接收者: {actual_receiver}, 使用上下文接收者")
                    to_user_id = actual_receiver

            # 检查是否是群聊
            is_group = to_user_id.endswith("@chatroom")

            # 处理@用户
            at_param = ""
            modified_content = content
            if is_group and at_list and len(at_list) > 0:
                # 获取第一个用户的wxid
                first_user_id = at_list[0]
                first_user_nickname = ""

                # 如果是被@的消息，尝试从context中获取发送者的昵称
                if context and "from_user_nickname" in context and "from_user_id" in context and context["from_user_id"] == first_user_id:
                    first_user_nickname = context["from_user_nickname"]
                    logger.debug(f"[WX849] 从context获取到用户 {first_user_id} 的昵称: {first_user_nickname}")
                else:
                    # 否则从群成员信息中获取昵称
                    # 获取群ID
                    group_id = to_user_id if to_user_id.endswith("@chatroom") else None
                    if group_id:
                        # 使用异步方法获取群成员昵称
                        first_user_nickname = await self._get_chatroom_member_nickname(group_id, first_user_id)
                        logger.debug(f"[WX849] 从群成员信息获取到用户 {first_user_id} 的昵称: {first_user_nickname}")
                    else:
                        # 如果不是群聊，从缓存中获取昵称
                        first_user_nickname = self._get_nickname_from_wxid(first_user_id)
                        logger.debug(f"[WX849] 从缓存获取到用户 {first_user_id} 的昵称: {first_user_nickname}")

                # 在消息内容前添加@用户的文本，并添加换行符
                modified_content = f"@{first_user_nickname}\n{modified_content}"
                logger.debug(f"[WX849] 修改后的消息内容: {modified_content}")

                # 使用用户wxid作为at_param，而不是昵称
                # 这是因为微信API需要wxid来正确地@用户
                at_param = first_user_id
                logger.debug(f"[WX849] 发送@消息，@列表: {at_param}")

            # 根据API文档调整参数格式
            params = {
                "ToWxid": to_user_id,
                "Content": modified_content,
                "Type": msg_type,
                "Wxid": self.wxid,   # 发送者wxid（机器人自己的wxid）
                "At": at_param       # @用户列表，逗号分隔
            }

            # 记录参数信息
            logger.debug(f"[WX849] 发送消息参数 - 接收者: {to_user_id}, 机器人wxid: {self.wxid}, @列表: {at_param}")

            # 记录API调用参数
            logger.debug(f"[WX849] 发送消息API参数: {json.dumps(params, ensure_ascii=False)}")

            # 使用自定义的API调用方法
            result = await self._call_api("/Msg/SendTxt", params)

            # 检查结果
            if result and isinstance(result, dict):
                success = result.get("Success", False)
                if success:
                    logger.debug(f"[WX849] 发送消息API返回成功: {json.dumps(result, ensure_ascii=False)}")
                else:
                    error_msg = result.get("Message", "未知错误")
                    logger.error(f"[WX849] 发送消息API返回错误: {error_msg}")
                    logger.error(f"[WX849] 完整错误响应: {json.dumps(result, ensure_ascii=False)}")

            return result
        except Exception as e:
            logger.error(f"[WX849] 发送消息失败: {e}")
            return None

    async def _send_image(self, to_user_id, image_path, context=None):
        """发送图片的异步方法"""
        try:
            # 检查文件是否存在
            if not os.path.exists(image_path):
                logger.error(f"[WX849] 发送图片失败: 文件不存在 {image_path}")
                return None

            # 检查接收者ID
            if not to_user_id:
                logger.error("[WX849] 发送图片失败: 接收者ID为空")
                return None

            # 如果有上下文对象，从上下文中获取接收者，确保使用正确的接收者
            if context and "receiver" in context:
                actual_receiver = context.get("receiver")
                if actual_receiver != to_user_id:
                    logger.warning(f"[WX849] 接收者不匹配! 参数接收者: {to_user_id}, 上下文接收者: {actual_receiver}, 使用上下文接收者")
                    to_user_id = actual_receiver

            # 读取图片文件并进行Base64编码
            import base64
            with open(image_path, "rb") as f:
                image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode('utf-8')

            # 构建API参数 - 使用正确的参数格式
            params = {
                "ToWxid": to_user_id,
                "Base64": image_base64,
                "Wxid": self.wxid
            }

            # 调用API - 使用正确的API端点
            result = await self._call_api("/Msg/UploadImg", params)

            # 检查结果
            if result and isinstance(result, dict):
                success = result.get("Success", False)
                if not success:
                    error_msg = result.get("Message", "未知错误")
                    logger.error(f"[WX849] 发送图片API返回错误: {error_msg}")

            return result
        except Exception as e:
            logger.error(f"[WX849] 发送图片失败: {e}")
            return None

    def _process_message_independently(self, message_id: str, msg: dict):
        """在独立线程中处理单条消息"""
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 记录处理信息
            thread_id = threading.get_ident()
            logger.debug(f"[WX849] 独立消息处理线程 {thread_id} 开始处理 - 消息ID: {message_id}")

            try:
                # 构建标准的消息对象
                is_group = False

                # 判断是否是群消息
                from_user_id = msg.get("fromUserName", msg.get("FromUserName", ""))
                to_user_id = msg.get("toUserName", msg.get("ToUserName", ""))

                if isinstance(from_user_id, dict) and "string" in from_user_id:
                    from_user_id = from_user_id["string"]
                if isinstance(to_user_id, dict) and "string" in to_user_id:
                    to_user_id = to_user_id["string"]

                if from_user_id and from_user_id.endswith("@chatroom"):
                    is_group = True
                elif to_user_id and to_user_id.endswith("@chatroom"):
                    is_group = True
                    # 交换发送者和接收者，确保from_user_id是群ID
                    from_user_id, to_user_id = to_user_id, from_user_id

                # 创建消息对象
                cmsg = WX849Message(msg, is_group)

                # 检查是否有发送者昵称信息，优先使用这个
                if "SenderNickName" in msg and msg["SenderNickName"]:
                    cmsg.sender_nickname = msg["SenderNickName"]
                    logger.debug(f"[WX849] 使用回调中的发送者昵称: {cmsg.sender_nickname}")

                # 处理被@消息
                if is_group and "@" in str(msg.get("Content", "")):
                    # 检查是否有@列表
                    at_list = []

                    # 方法1: 从RawLogLine中提取@列表
                    raw_log_line = msg.get("RawLogLine", "")

                    # 检查是否是被@消息
                    if raw_log_line and "收到被@消息" in raw_log_line:
                        logger.debug(f"[WX849] 检测到被@消息: {raw_log_line}")
                        # 设置is_at标志
                        cmsg.is_at = True
                    # 检查是否有IsAtMessage标志
                    elif "IsAtMessage" in msg and msg["IsAtMessage"]:
                        logger.debug(f"[WX849] 检测到IsAtMessage标志")
                        # 设置is_at标志
                        cmsg.is_at = True

                        # 确保at_list中包含机器人wxid
                        if not hasattr(cmsg, 'at_list'):
                            cmsg.at_list = []
                        if self.wxid not in cmsg.at_list:
                            cmsg.at_list.append(self.wxid)

                        # 尝试从日志行中提取@列表
                        if "@:" in raw_log_line:
                            try:
                                at_part = raw_log_line.split("@:", 1)[1].split(" ", 1)[0]
                                if at_part.startswith("[") and at_part.endswith("]"):
                                    # 解析@列表
                                    at_list_str = at_part[1:-1]  # 去除[]
                                    if at_list_str:
                                        at_items = at_list_str.split(",")
                                        for item in at_items:
                                            item = item.strip().strip("'\"")
                                            if item:
                                                at_list.append(item)
                                        logger.debug(f"[WX849] 从被@消息中提取到@列表: {at_list}")
                            except Exception as e:
                                logger.debug(f"[WX849] 从被@消息中提取@列表失败: {e}")
                    # 普通消息中的@列表提取
                    elif raw_log_line and "@:" in raw_log_line:
                        try:
                            # 尝试从日志行中提取@列表
                            at_part = raw_log_line.split("@:", 1)[1].split(" ", 1)[0]
                            if at_part.startswith("[") and at_part.endswith("]"):
                                # 解析@列表
                                at_list_str = at_part[1:-1]  # 去除[]
                                if at_list_str:
                                    at_items = at_list_str.split(",")
                                    for item in at_items:
                                        item = item.strip().strip("'\"")
                                        if item:
                                            at_list.append(item)
                                    logger.debug(f"[WX849] 从RawLogLine提取到@列表: {at_list}")
                        except Exception as e:
                            logger.debug(f"[WX849] 从RawLogLine提取@列表失败: {e}")

                    # 方法2: 从MsgSource中提取@列表
                    if not at_list and "MsgSource" in msg:
                        try:
                            msg_source = msg.get("MsgSource", "")
                            if msg_source:
                                root = ET.fromstring(msg_source)
                                atuserlist_elem = root.find('atuserlist')
                                if atuserlist_elem is not None and atuserlist_elem.text:
                                    at_users = atuserlist_elem.text.split(",")
                                    for user in at_users:
                                        if user.strip():
                                            at_list.append(user.strip())
                                    logger.debug(f"[WX849] 从MsgSource提取到@列表: {at_list}")
                        except Exception as e:
                            logger.debug(f"[WX849] 从MsgSource提取@列表失败: {e}")

                    # 设置@列表到消息对象
                    if at_list:
                        cmsg.at_list = at_list
                        # 设置is_at标志
                        cmsg.is_at = self.wxid in at_list
                        logger.debug(f"[WX849] 设置@列表: {at_list}, is_at: {cmsg.is_at}")

                # 处理消息
                logger.debug(f"[WX849] 处理回调消息: ID:{cmsg.msg_id} 类型:{cmsg.msg_type}")

                # 使用线程安全的方式检查和标记消息
                with self.__class__._message_lock:
                    # 检查消息是否已经处理过
                    if cmsg.msg_id in self.received_msgs:
                        logger.debug(f"[WX849] 消息 {cmsg.msg_id} 已处理过，忽略")
                        return

                    # 标记消息为已处理
                    self.received_msgs[cmsg.msg_id] = True

                # 检查消息时间是否过期
                create_time = cmsg.create_time  # 消息时间戳
                current_time = int(time.time())

                # 设置超时时间为60秒
                timeout = 60
                if int(create_time) < current_time - timeout:
                    logger.debug(f"[WX849] 历史消息 {cmsg.msg_id} 已跳过，时间差: {current_time - int(create_time)}秒")
                    return

                # 创建一个全新的消息对象，避免共享引用
                new_msg = WX849Message(msg, is_group)

                # 复制原始消息对象的属性
                for attr_name in dir(cmsg):
                    if not attr_name.startswith('_') and not callable(getattr(cmsg, attr_name)):
                        try:
                            setattr(new_msg, attr_name, getattr(cmsg, attr_name))
                        except Exception:
                            pass

                # 设置正确的接收者和会话ID
                if is_group:
                    # 如果是群聊，接收者应该是群ID
                    new_msg.to_user_id = from_user_id  # 群ID
                    new_msg.session_id = from_user_id  # 使用群ID作为会话ID
                    new_msg.other_user_id = from_user_id  # 群ID
                    new_msg.is_group = True

                    # 确保群聊消息的其他字段也是正确的
                    new_msg.group_id = from_user_id

                    # 清除可能从其他消息继承的私聊相关字段
                    if hasattr(new_msg, 'other_user_nickname'):
                        delattr(new_msg, 'other_user_nickname')
                else:
                    # 如果是私聊，接收者应该是发送者ID
                    sender_wxid = msg.get("SenderWxid", "")
                    if not sender_wxid:
                        sender_wxid = from_user_id

                    new_msg.to_user_id = sender_wxid
                    new_msg.session_id = sender_wxid  # 使用发送者ID作为会话ID
                    new_msg.other_user_id = sender_wxid
                    new_msg.is_group = False

                    # 清除可能从其他消息继承的群聊相关字段
                    if hasattr(new_msg, 'group_name'):
                        delattr(new_msg, 'group_name')
                    if hasattr(new_msg, 'group_id'):
                        delattr(new_msg, 'group_id')
                    if hasattr(new_msg, 'is_at'):
                        new_msg.is_at = False
                    if hasattr(new_msg, 'at_list'):
                        new_msg.at_list = []
                    # 确保没有任何群聊相关的属性
                    for attr_name in dir(new_msg):
                        if not attr_name.startswith('_') and not callable(getattr(new_msg, attr_name)):
                            if 'group' in attr_name.lower() or 'at' in attr_name.lower():
                                try:
                                    delattr(new_msg, attr_name)
                                except Exception:
                                    pass

                # 使用新的消息对象替换原始消息对象
                cmsg = new_msg

                # 创建一个新的线程来处理消息，确保每个消息都有完全独立的处理环境
                def process_message_in_new_thread():
                    try:
                        # 创建新的事件循环
                        msg_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(msg_loop)

                        try:
                            # 调用原有的消息处理逻辑
                            if is_group:
                                self.handle_group(cmsg)
                            else:
                                self.handle_single(cmsg)
                        finally:
                            # 关闭事件循环
                            msg_loop.close()
                    except Exception as e:
                        logger.error(f"[WX849] 消息处理线程执行异常: {e}")
                        logger.error(traceback.format_exc())

                # 启动新线程处理消息
                msg_thread = threading.Thread(target=process_message_in_new_thread)
                msg_thread.daemon = True
                msg_thread.start()

                # 等待消息处理线程完成
                msg_thread.join()
            finally:
                # 关闭事件循环
                loop.close()

            logger.debug(f"[WX849] 独立消息处理线程 {thread_id} 处理完成 - 消息ID: {message_id}")
        except Exception as e:
            logger.error(f"[WX849] 独立消息处理线程 {thread_id} 执行异常: {e}")
            logger.error(traceback.format_exc())

    async def _process_message_async(self, message_id: str, reply: Reply, context: Context, receiver: str, session_id: str):
        """异步处理消息"""
        try:
            # 记录处理信息
            logger.debug(f"[WX849] 异步处理消息 - ID: {message_id}, 接收者: {receiver}, 消息类型: {reply.type}")

            # 记录上下文信息，确保使用的是正确的上下文对象
            logger.debug(f"[WX849] 消息 {message_id} 使用的上下文对象ID: {id(context)}")
            logger.debug(f"[WX849] 上下文信息 - 接收者: {context.get('receiver')}, 会话ID: {context.get('session_id')}, 群组: {context.get('group_name', 'N/A')}")

            # 创建一个全新的上下文对象，避免共享引用
            new_context = Context(context.type, context.content)

            # 复制原始上下文对象的属性
            # Context 对象没有 items() 方法，需要从 kwargs 中复制
            for key in context.kwargs:
                # 对于复杂对象，创建深拷贝
                if isinstance(context.kwargs[key], dict):
                    new_context[key] = context.kwargs[key].copy()
                elif isinstance(context.kwargs[key], list):
                    new_context[key] = context.kwargs[key].copy()
                else:
                    new_context[key] = context.kwargs[key]

            # 使用新的上下文对象替换原始上下文对象
            context = new_context

            # 检查是否是群聊消息
            is_group = context.get("isgroup", False) or context.get("is_group", False)

            # 如果是群聊消息，确保接收者是群ID
            if is_group:
                # 如果接收者不是群ID（不以@chatroom结尾），但session_id是群ID
                if not receiver.endswith("@chatroom") and session_id and session_id.endswith("@chatroom"):
                    logger.warning(f"[WX849] 群聊消息接收者不是群ID! 接收者: {receiver}, 会话ID: {session_id}")
                    receiver = session_id
                    logger.info(f"[WX849] 已修正接收者为群ID: {receiver}")

                # 确保上下文中的接收者和会话ID是群ID
                context["receiver"] = receiver
                context["session_id"] = receiver

                # 确保上下文中的群聊相关字段是正确的
                if "group_id" not in context or context["group_id"] != receiver:
                    context["group_id"] = receiver

                # 清除可能从其他消息继承的私聊相关字段
                if "other_user_nickname" in context:
                    del context["other_user_nickname"]
            # 如果是私聊消息，确保接收者是用户ID
            else:
                # 如果接收者是群ID（以@chatroom结尾），但应该是私聊
                if receiver.endswith("@chatroom"):
                    # 尝试从from_user_id获取正确的接收者
                    from_user_id = context.get("from_user_id")
                    if from_user_id and not from_user_id.endswith("@chatroom"):
                        logger.warning(f"[WX849] 私聊消息接收者是群ID! 接收者: {receiver}, 发送者ID: {from_user_id}")
                        receiver = from_user_id
                        logger.info(f"[WX849] 已修正接收者为用户ID: {receiver}")
                    # 如果无法确定正确的接收者，使用other_user_id
                    elif context.get("other_user_id") and not context.get("other_user_id").endswith("@chatroom"):
                        logger.warning(f"[WX849] 私聊消息接收者是群ID! 接收者: {receiver}, other_user_id: {context.get('other_user_id')}")
                        receiver = context.get("other_user_id")
                        logger.info(f"[WX849] 已修正接收者为other_user_id: {receiver}")

                # 确保上下文中的接收者和会话ID是用户ID
                context["receiver"] = receiver
                context["session_id"] = receiver

                # 确保上下文中的私聊相关字段是正确的
                context["isgroup"] = False

                # 清除可能从其他消息继承的群聊相关字段
                if "group_name" in context:
                    del context["group_name"]
                if "group_id" in context:
                    del context["group_id"]
                if "is_at" in context:
                    context["is_at"] = False
                if "at_list" in context:
                    del context["at_list"]

            if reply.type == ReplyType.TEXT:
                reply.content = remove_markdown_symbol(reply.content)

                # 检查是否需要@用户
                at_list = None
                if context.get("isgroup", False) or context.get("is_group", False):
                    # 如果是群聊，则@原始发送者
                    if context.get("from_user_id"):
                        # 使用发送者ID作为@对象
                        at_list = [context.get("from_user_id")]
                        logger.debug(f"[WX849] 将@原始发送者: {at_list}")
                    # 检查at_list是否为空
                    if not at_list:
                        logger.debug(f"[WX849] at_list为空，检查context: {context}")

                # 发送消息，传递at_list和context参数 - 直接使用异步调用
                result = await self._send_message(receiver, reply.content, 1, at_list, context)

                if result and isinstance(result, dict) and result.get("Success", False):
                    logger.info(f"[WX849] 发送文本消息成功: 接收者: {receiver}")
                    if conf().get("log_level", "INFO") == "DEBUG":
                        logger.debug(f"[WX849] 消息内容: {reply.content[:50]}...")
                else:
                    logger.warning(f"[WX849] 发送文本消息可能失败: 接收者: {receiver}, 结果: {result}")

            elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
                reply.content = remove_markdown_symbol(reply.content)

                # 检查是否需要@用户
                at_list = None
                if context.get("isgroup", False) or context.get("is_group", False):
                    # 如果是群聊，则@原始发送者
                    if context.get("from_user_id"):
                        # 使用发送者ID作为@对象
                        at_list = [context.get("from_user_id")]
                        logger.debug(f"[WX849] 将@原始发送者: {at_list}")
                    # 检查at_list是否为空
                    if not at_list:
                        logger.debug(f"[WX849] at_list为空，检查context: {context}")

                # 发送消息，传递at_list和context参数 - 直接使用异步调用
                result = await self._send_message(receiver, reply.content, 1, at_list, context)

                if result and isinstance(result, dict) and result.get("Success", False):
                    logger.info(f"[WX849] 发送消息成功: 接收者: {receiver}")
                    if conf().get("log_level", "INFO") == "DEBUG":
                        logger.debug(f"[WX849] 消息内容: {reply.content[:50]}...")
                else:
                    logger.warning(f"[WX849] 发送消息可能失败: 接收者: {receiver}, 结果: {result}")

            elif reply.type == ReplyType.IMAGE or reply.type == ReplyType.IMAGE_URL:
                result = None
                # 处理图片消息发送
                image_path = reply.content
                logger.debug(f"[WX849] 开始发送图片, {'URL' if reply.type == ReplyType.IMAGE_URL else '文件路径'}={image_path}")
                try:
                    tmp_path = os.path.join(get_appdata_dir(), f"tmp_img_{int(time.time())}.jpg")
                    # 如果是图片URL，先下载图片
                    if reply.type == ReplyType.IMAGE_URL:
                        # 使用aiohttp异步下载图片
                        async with aiohttp.ClientSession() as session:
                            async with session.get(image_path) as response:
                                if response.status != 200:
                                    logger.error(f"[WX849] 下载图片失败, 状态码: {response.status}")
                                    return

                                # 创建临时文件保存图片
                                with open(tmp_path, 'wb') as f:
                                    f.write(await response.read())
                                # 使用下载后的本地文件路径
                                image_path = tmp_path
                    if reply.type == ReplyType.IMAGE:
                        if isinstance(reply.content, io.BytesIO):
                            image_io: BytesIO = image_path
                            image_io.seek(0)  # 重置指针到起始位置
                            # 保存为本地文件
                            with open(tmp_path, "wb") as f:
                                f.write(image_io.getvalue())  # 直接写入二进制数据
                            image_path = tmp_path
                        else:
                            image_path = reply.content

                    # 发送图片文件，传递上下文对象 - 直接使用异步调用
                    result = await self._send_image(receiver, image_path, context)
                    # 如果是URL类型，删除临时文件
                    try:
                        os.remove(tmp_path)
                    except Exception as e:
                        logger.debug(f"[WX849] 删除临时图片文件失败: {e}")

                    if result:
                        logger.info(f"[WX849] 发送图片成功: 接收者: {receiver}")
                    else:
                        logger.warning(f"[WX849] 发送图片失败: 接收者: {receiver}")
                except Exception as e:
                    logger.error(f"[WX849] 处理图片失败: {e}")
                    logger.error(traceback.format_exc())

            elif reply.type == ReplyType.VIDEO_URL:
                # 从网络下载视频并发送
                video_url = reply.content
                logger.debug(f"[WX849] 开始下载视频, url={video_url}")
                try:
                    # 下载视频 - 直接使用异步调用
                    result = await self._download_and_send_video(receiver, video_url)
                    if result:
                        logger.info(f"[WX849] 发送视频成功: 接收者: {receiver}")
                    else:
                        logger.warning(f"[WX849] 发送视频失败: 接收者: {receiver}")
                except Exception as e:
                    logger.error(f"[WX849] 处理视频URL失败: {e}")
                    logger.error(traceback.format_exc())

            elif reply.type == ReplyType.VOICE:
                # 发送语音消息
                voice_path = reply.content
                logger.debug(f"[WX849] 开始发送语音, 文件路径={voice_path}")
                try:
                    # 使用统一的语音发送方法，会自动处理短语音和长语音的分割 - 直接使用异步调用
                    result = await self._send_voice(receiver, voice_path)
                    if result:
                        logger.info(f"[WX849] 发送语音成功: 接收者: {receiver}")
                    else:
                        logger.warning(f"[WX849] 发送语音失败: 接收者: {receiver}")
                except Exception as e:
                    logger.error(f"[WX849] 处理语音失败: {e}")
                    logger.error(traceback.format_exc())

            elif reply.type == ReplyType.VOICE_URL:
                # 从网络下载语音并发送
                voice_url = reply.content
                logger.debug(f"[WX849] 开始下载语音, url={voice_url}")
                try:
                    # 使用aiohttp异步下载语音
                    async with aiohttp.ClientSession() as session:
                        async with session.get(voice_url) as response:
                            if response.status != 200:
                                logger.error(f"[WX849] 下载语音失败, 状态码: {response.status}")
                                return

                            # 创建临时文件保存语音
                            tmp_path = os.path.join(get_appdata_dir(), f"tmp_voice_{int(time.time())}.mp3")
                            with open(tmp_path, 'wb') as f:
                                f.write(await response.read())

                    # 使用统一的语音发送方法，会自动处理短语音和长语音的分割 - 直接使用异步调用
                    result = await self._send_voice(receiver, tmp_path)

                    if result:
                        logger.info(f"[WX849] 发送语音成功: 接收者: {receiver}")
                    else:
                        logger.warning(f"[WX849] 发送语音失败: 接收者: {receiver}")

                    # 删除临时文件
                    try:
                        os.remove(tmp_path)
                    except Exception as e:
                        logger.debug(f"[WX849] 删除临时语音文件失败: {e}")
                except Exception as e:
                    logger.error(f"[WX849] 处理语音URL失败: {e}")
                    logger.error(traceback.format_exc())

            else:
                logger.warning(f"[WX849] 不支持的回复类型: {reply.type}")

            logger.debug(f"[WX849] 异步处理消息完成 - ID: {message_id}, 接收者: {receiver}")

        except Exception as e:
            logger.error(f"[WX849] 异步处理消息异常 - ID: {message_id}, 错误: {e}")
            logger.error(traceback.format_exc())

    def send(self, reply: Reply, context: Context):
        """发送消息 - 完全独立的处理流程"""
        # 创建线程本地存储，确保每个线程都有自己的独立状态
        thread_local = threading.local()

        # 创建上下文的深拷贝，确保完全独立
        # 由于Context对象没有copy方法，我们需要手动创建一个新的Context对象
        thread_local.context = Context(
            type=context.type,
            content=context.content,
            kwargs={}  # 创建空字典，然后手动复制
        )

        # 手动复制 kwargs 字典中的内容
        for key in context.kwargs:
            # 对于复杂对象，创建深拷贝
            if isinstance(context.kwargs[key], dict):
                thread_local.context.kwargs[key] = context.kwargs[key].copy()
            elif isinstance(context.kwargs[key], list):
                thread_local.context.kwargs[key] = context.kwargs[key].copy()
            else:
                thread_local.context.kwargs[key] = context.kwargs[key]

        # 创建回复的深拷贝，确保完全独立
        thread_local.reply = Reply(
            type=reply.type,
            content=reply.content
        )

        # 获取接收者ID
        thread_local.receiver = thread_local.context.get("receiver")
        if not thread_local.receiver:
            # 如果context中没有接收者，尝试从消息对象中获取
            msg = thread_local.context.get("msg")
            if msg and hasattr(msg, "from_user_id"):
                thread_local.receiver = msg.from_user_id

        if not thread_local.receiver:
            logger.error("[WX849] 发送消息失败: 无法确定接收者ID")
            return

        # 添加安全检查，确保消息发送给正确的接收者
        thread_local.session_id = thread_local.context.get("session_id")

        # 检查是否是群聊消息
        thread_local.is_group = thread_local.context.get("isgroup", False) or thread_local.context.get("is_group", False)

        # 如果是群聊消息，确保接收者是群ID
        if thread_local.is_group:
            # 如果接收者不是群ID（不以@chatroom结尾），但session_id是群ID
            if not thread_local.receiver.endswith("@chatroom") and thread_local.session_id and thread_local.session_id.endswith("@chatroom"):
                logger.warning(f"[WX849] 群聊消息接收者不是群ID! 接收者: {thread_local.receiver}, 会话ID: {thread_local.session_id}")
                thread_local.receiver = thread_local.session_id
                logger.info(f"[WX849] 已修正接收者为群ID: {thread_local.receiver}")

            # 确保上下文中的群聊相关字段是正确的
            thread_local.context["receiver"] = thread_local.receiver
            thread_local.context["session_id"] = thread_local.receiver
            if "group_id" not in thread_local.context or thread_local.context["group_id"] != thread_local.receiver:
                thread_local.context["group_id"] = thread_local.receiver

            # 清除可能从其他消息继承的私聊相关字段
            if "other_user_nickname" in thread_local.context:
                del thread_local.context["other_user_nickname"]
        # 如果是私聊消息，确保接收者是用户ID
        else:
            # 如果接收者是群ID（以@chatroom结尾），但应该是私聊
            if thread_local.receiver.endswith("@chatroom"):
                # 尝试从from_user_id获取正确的接收者
                from_user_id = thread_local.context.get("from_user_id")
                if from_user_id and not from_user_id.endswith("@chatroom"):
                    logger.warning(f"[WX849] 私聊消息接收者是群ID! 接收者: {thread_local.receiver}, 发送者ID: {from_user_id}")
                    thread_local.receiver = from_user_id
                    logger.info(f"[WX849] 已修正接收者为用户ID: {thread_local.receiver}")
                # 如果无法确定正确的接收者，使用other_user_id
                elif thread_local.context.get("other_user_id") and not thread_local.context.get("other_user_id").endswith("@chatroom"):
                    logger.warning(f"[WX849] 私聊消息接收者是群ID! 接收者: {thread_local.receiver}, other_user_id: {thread_local.context.get('other_user_id')}")
                    thread_local.receiver = thread_local.context.get("other_user_id")
                    logger.info(f"[WX849] 已修正接收者为other_user_id: {thread_local.receiver}")

            # 确保上下文中的私聊相关字段是正确的
            thread_local.context["receiver"] = thread_local.receiver
            thread_local.context["session_id"] = thread_local.receiver
            thread_local.context["isgroup"] = False

            # 清除可能从其他消息继承的群聊相关字段
            if "group_name" in thread_local.context:
                del thread_local.context["group_name"]
            if "group_id" in thread_local.context:
                del thread_local.context["group_id"]
            if "is_at" in thread_local.context:
                thread_local.context["is_at"] = False
            if "at_list" in thread_local.context:
                del thread_local.context["at_list"]
            # 确保没有任何群聊相关的属性
            keys_to_delete = []
            for key in thread_local.context.kwargs:
                if 'group' in key.lower() or 'at' in key.lower() or 'trigger_prefix' in key.lower():
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                if key in thread_local.context.kwargs:
                    del thread_local.context.kwargs[key]

        # 生成唯一的消息ID，用于跟踪整个处理流程
        thread_local.message_id = f"msg_{int(time.time())}_{hash(str(thread_local.reply.content)[:20])}"

        # 记录发送消息的详细信息，便于调试
        logger.info(f"[WX849] 发送消息 - ID: {thread_local.message_id}, 接收者: {thread_local.receiver}, 会话ID: {thread_local.session_id}, 消息类型: {thread_local.reply.type}")
        if conf().get("log_level", "INFO") == "DEBUG":
            logger.debug(f"[WX849] 消息内容: {thread_local.reply.content[:50]}...")
            logger.debug(f"[WX849] 上下文信息: session_id={thread_local.session_id}, isgroup={thread_local.context.get('isgroup')}, from_user_id={thread_local.context.get('from_user_id')}")

        # 创建一个消息字典，包含所有必要的信息
        msg_dict = {
            "MsgId": thread_local.message_id,
            "FromUserName": thread_local.receiver if thread_local.is_group else self.wxid,
            "ToUserName": self.wxid if thread_local.is_group else thread_local.receiver,
            "Content": thread_local.reply.content,
            "Type": 1,  # 文本消息类型
            "CreateTime": int(time.time()),
            "SenderWxid": self.wxid,  # 发送者是机器人自己
            "SenderNickName": "机器人",  # 默认机器人昵称
            "IsAtMessage": False,
            "RawLogLine": "",
            "MsgSource": ""
        }

        # 如果是群聊消息，添加群聊相关信息
        if thread_local.is_group:
            msg_dict["IsGroup"] = True
            msg_dict["GroupId"] = thread_local.receiver

            # 如果有群名称，添加到消息中
            if "group_name" in thread_local.context:
                msg_dict["GroupName"] = thread_local.context["group_name"]

            # 如果需要@用户，添加@信息
            if "from_user_id" in thread_local.context:
                msg_dict["AtList"] = [thread_local.context["from_user_id"]]
                msg_dict["IsAtMessage"] = True

        # 根据回复类型设置消息类型
        if thread_local.reply.type == ReplyType.IMAGE or thread_local.reply.type == ReplyType.IMAGE_URL:
            msg_dict["Type"] = 3  # 图片消息
            msg_dict["Content"] = thread_local.reply.content  # 图片路径或URL
        elif thread_local.reply.type == ReplyType.VOICE:
            msg_dict["Type"] = 34  # 语音消息
            msg_dict["Content"] = thread_local.reply.content  # 语音路径或URL
        elif thread_local.reply.type == ReplyType.VIDEO_URL:
            msg_dict["Type"] = 43  # 视频消息
            msg_dict["Content"] = thread_local.reply.content  # 视频URL

        # 创建一个完全独立的处理流程
        # 每个消息都有自己的线程、事件循环和上下文对象

        # 创建一个副本，避免线程本地存储的问题
        message_id = thread_local.message_id
        reply_copy = thread_local.reply
        context_copy = thread_local.context
        receiver_copy = thread_local.receiver
        session_id_copy = thread_local.session_id

        def process_message_in_isolated_environment():
            try:
                # 创建新的事件循环
                isolated_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(isolated_loop)

                try:
                    # 调用独立处理函数
                    isolated_loop.run_until_complete(
                        self._process_message_async(
                            message_id,
                            reply_copy,
                            context_copy,
                            receiver_copy,
                            session_id_copy
                        )
                    )
                finally:
                    # 关闭事件循环
                    isolated_loop.close()
            except Exception as e:
                logger.error(f"[WX849] 独立处理环境执行异常: {e}")
                logger.error(traceback.format_exc())

        # 启动独立线程处理消息
        process = threading.Thread(
            target=process_message_in_isolated_environment,
            daemon=True  # 设置为守护线程，主线程退出时自动结束
        )
        process.start()

        # 不等待处理完成，立即返回
        logger.debug(f"[WX849] 已启动独立处理流程 - 消息ID: {thread_local.message_id}, 接收者: {thread_local.receiver}, 消息类型: {thread_local.reply.type}")

    async def _download_and_send_video(self, to_user_id, video_url):
        """下载视频并发送"""
        tmp_path = None
        try:
            # 1. 检查和创建临时目录
            tmp_dir = os.path.join(get_appdata_dir(), "video_tmp")
            os.makedirs(tmp_dir, exist_ok=True)

            # 创建临时文件
            tmp_path = os.path.join(tmp_dir, f"tmp_video_{int(time.time())}.mp4")

            # 2. 下载视频
            logger.debug(f"[WX849] 开始下载视频: {video_url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Referer': 'https://www.google.com/'
            }

            # 下载视频，设置30秒超时
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(video_url, headers=headers, timeout=30) as response:
                        if response.status != 200:
                            logger.error(f"[WX849] 下载视频失败, 状态码: {response.status}")
                            return False

                        # 检查内容类型
                        content_type = response.headers.get('Content-Type', '')
                        if 'video' not in content_type and 'octet-stream' not in content_type:
                            logger.warning(f"[WX849] 警告: 响应内容类型不是视频: {content_type}")

                        # 使用流式下载
                        with open(tmp_path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(8192)  # 8KB块
                                if not chunk:
                                    break
                                f.write(chunk)

                # 检查下载的文件
                if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024:  # 小于1KB
                    logger.error(f"[WX849] 下载的视频文件无效或过小: {os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 'not exists'}")
                    return False

                logger.debug(f"[WX849] 视频下载完成: {tmp_path}, 大小: {os.path.getsize(tmp_path)/1024:.2f}KB")
            except Exception as download_error:
                logger.error(f"[WX849] 下载视频失败: {download_error}")
                return False

            # 3. 获取视频时长
            video_duration = await self._extract_video_duration(tmp_path)
            logger.debug(f"[WX849] 视频时长: {video_duration}秒")

            # 4. 编码视频为Base64
            video_base64 = await self._encode_video(tmp_path)
            if not video_base64:
                logger.error("[WX849] 视频编码失败")
                return False

            # 5. 提取视频第一帧作为封面
            logger.debug(f"[WX849] 正在提取视频封面")
            cover_base64 = await self._extract_first_frame(tmp_path)
            if not cover_base64:
                logger.warning("[WX849] 未能获取视频封面，将使用无封面发送")
                cover_base64 = "None"  # 使用字符串"None"作为无封面的标记

            # 6. 发送视频
            logger.debug(f"[WX849] 开始发送视频到接收者: {to_user_id}")
            result = await self._send_video(to_user_id, video_base64, cover_base64, video_duration)

            # 7. 判断发送结果
            if result and isinstance(result, dict) and result.get("Success", False):
                logger.info(f"[WX849] 视频发送成功: {to_user_id}")
                return True
            else:
                logger.error(f"[WX849] 视频发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"[WX849] 处理视频失败: {e}")
            logger.error(traceback.format_exc())
            return False
        finally:
            # 删除临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.debug(f"[WX849] 已删除临时视频文件: {tmp_path}")
                except Exception as e:
                    logger.debug(f"[WX849] 删除临时视频文件失败: {e}")

    async def _encode_video(self, video_path):
        """将视频编码为base64"""
        try:
            with open(video_path, 'rb') as f:
                video_data = f.read()

            # 使用Base64编码
            import base64
            video_base64 = base64.b64encode(video_data).decode('utf-8')
            return video_base64
        except Exception as e:
            logger.error(f"[WX849] 视频Base64编码失败: {e}")
            return None

    async def _extract_first_frame(self, video_path):
        """从视频中提取第一帧并编码为Base64"""
        try:
            # 创建临时目录
            tmp_dir = os.path.join(get_appdata_dir(), "video_frames")
            os.makedirs(tmp_dir, exist_ok=True)

            # 临时图片文件路径
            thumbnail_path = os.path.join(tmp_dir, f"frame_{int(time.time())}.jpg")

            # 查找ffmpeg可执行文件
            ffmpeg_cmd = "ffmpeg"
            # 在Windows上检查常见安装路径
            if os.name == 'nt':
                possible_paths = [
                    r"C:\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        ffmpeg_cmd = path
                        break

            logger.debug(f"[WX849] 使用ffmpeg命令: {ffmpeg_cmd}")

            # 使用ffmpeg提取第一帧，尝试多个时间点
            success = False
            for timestamp in ["00:00:01", "00:00:00.5", "00:00:00"]:
                try:
                    # 使用subprocess.run来执行ffmpeg命令
                    process = subprocess.run([
                        ffmpeg_cmd,
                        "-i", video_path,
                        "-ss", timestamp,
                        "-vframes", "1",
                        "-q:v", "2",  # 设置高质量输出
                        thumbnail_path,
                        "-y"
                    ], check=False, capture_output=True)

                    if process.returncode == 0 and os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                        logger.debug(f"[WX849] 成功提取视频帧，使用时间点: {timestamp}")
                        success = True
                        break
                    else:
                        logger.debug(f"[WX849] 提取视频帧失败，时间点: {timestamp}, 返回码: {process.returncode}")
                        if process.stderr:
                            logger.debug(f"[WX849] ffmpeg错误: {process.stderr.decode()[:200]}")
                except Exception as e:
                    logger.debug(f"[WX849] 使用时间点 {timestamp} 提取帧时出错: {e}")

            # 如果所有尝试都失败，则返回空
            if not success:
                logger.warning("[WX849] 所有提取视频帧的尝试都失败，将发送无封面视频")
                return None

            # 读取并编码图片
            if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                with open(thumbnail_path, "rb") as f:
                    image_data = f.read()

                import base64
                image_base64 = base64.b64encode(image_data).decode('utf-8')

                # 删除临时图片文件
                try:
                    os.remove(thumbnail_path)
                except Exception:
                    pass

                return image_base64

            logger.warning("[WX849] 未能生成有效的封面图片")
            return None
        except Exception as e:
            logger.error(f"[WX849] 提取视频帧失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def _send_voice(self, to_user_id, voice_path):
        """发送语音消息，如果语音时长超过30秒，会自动分割成多个片段发送"""
        # 参数检查
        if not to_user_id:
            logger.error("[WX849] 发送语音失败: 接收者ID为空")
            return None

        if not voice_path or not os.path.exists(voice_path):
            logger.error(f"[WX849] 发送语音失败: 语音文件不存在 - {voice_path}")
            return None

        # 创建临时目录和处理后的文件路径
        tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        processed_file = os.path.join(tmp_dir, f"voice_processed_{int(time.time())}.mp3")

        result = None
        try:
            # 导入base64模块
            import base64

            # 查找ffmpeg可执行文件
            ffmpeg_cmd = "ffmpeg"
            if os.name == 'nt':
                possible_paths = [
                    r"C:\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        ffmpeg_cmd = path
                        break

            # 使用ffmpeg处理音频文件
            cmd = [
                ffmpeg_cmd, "-y", "-i", voice_path,
                "-acodec", "libmp3lame", "-ar", "44100", "-ab", "192k",
                "-ac", "2", processed_file
            ]

            # 执行ffmpeg命令
            logger.debug(f"[WX849] 处理音频文件: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            # 如果处理成功，使用处理后的文件；否则使用原始文件
            voice_file = processed_file if result.returncode == 0 and os.path.exists(processed_file) else voice_path
            logger.debug(f"[WX849] 使用音频文件: {voice_file}")

            try:
                # 使用pydub和pysilk处理音频
                from pydub import AudioSegment
                import pysilk
                from io import BytesIO

                # 读取音频文件
                with open(voice_file, 'rb') as f:
                    voice_data = f.read()

                # 转换为AudioSegment
                audio = AudioSegment.from_file(BytesIO(voice_data), format="mp3").set_channels(1)

                # 获取最接近的支持的采样率
                supported_rates = [8000, 12000, 16000, 24000]
                closest_rate = min(supported_rates, key=lambda x: abs(x - audio.frame_rate))
                audio = audio.set_frame_rate(closest_rate)

                # 获取音频时长（毫秒）
                total_duration = len(audio)
                logger.debug(f"[WX849] 总音频时长: {total_duration}毫秒, 采样率: {audio.frame_rate}Hz")

                # 最大语音片段时长（毫秒）
                max_segment_duration = 20 * 1000  # 20秒，确保更可靠的发送

                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 注意：之前这里强制使用/VXAPI前缀，现在根据协议版本动态选择
                logger.debug(f"[WX849] 语音消息使用API路径前缀: {api_path_prefix} (适用于{protocol_version}协议)")

                # 如果语音时长超过最大片段时长，将其分割成多个片段发送
                if total_duration > max_segment_duration:
                    logger.info(f"[WX849] 语音时长超过20秒 ({total_duration/1000:.1f}秒)，将分割成多个片段发送")

                    # 计算需要分割的片段数
                    segments_count = (total_duration + max_segment_duration - 1) // max_segment_duration
                    logger.info(f"[WX849] 将分割成 {segments_count} 个片段")

                    # 创建存放临时分段文件的目录
                    segment_dir = os.path.join(tmp_dir, f"voice_segments_{int(time.time())}")
                    os.makedirs(segment_dir, exist_ok=True)

                    # 保存所有临时分段文件路径
                    segment_files = []

                    # 第一阶段：分割并保存所有片段
                    logger.info(f"[WX849] 开始分割并保存所有语音片段")
                    for i in range(segments_count):
                        start_time = i * max_segment_duration
                        end_time = min((i + 1) * max_segment_duration, total_duration)

                        # 截取片段
                        segment = audio[start_time:end_time]
                        segment_duration = len(segment)

                        # 保存片段到临时文件
                        segment_file = os.path.join(segment_dir, f"segment_{i+1}.mp3")
                        segment_files.append((segment_file, segment_duration))
                        segment.export(segment_file, format="mp3")

                        logger.debug(f"[WX849] 保存语音片段 {i+1}/{segments_count} 到: {segment_file}, 时长: {segment_duration/1000:.1f}秒")

                    # 检查所有分段文件是否都已成功创建
                    all_segments_exist = True
                    for segment_file, _ in segment_files:
                        if not os.path.exists(segment_file):
                            logger.error(f"[WX849] 语音片段文件不存在: {segment_file}")
                            all_segments_exist = False
                            break

                    if not all_segments_exist:
                        logger.error(f"[WX849] 部分语音片段未能成功保存，取消发送")
                        return None

                    logger.info(f"[WX849] 所有 {len(segment_files)} 个语音片段已成功保存，开始发送")

                    # 发送文本消息通知语音长度
                    try:
                        async with aiohttp.ClientSession() as session:
                            text_url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendTxt"
                            text_params = {
                                "Wxid": self.wxid,
                                "ToWxid": to_user_id,
                                "Content": f"长语音消息 (总长{total_duration/1000:.1f}秒)，将分 {segments_count} 段发送..."
                            }

                            # 发送文本提示
                            async with session.post(text_url, json=text_params, timeout=60) as text_response:
                                text_json_resp = await text_response.json()
                                if text_json_resp and text_json_resp.get("Success", False):
                                    logger.info(f"[WX849] 发送语音分段通知成功")
                    except Exception as e:
                        logger.error(f"[WX849] 发送语音分段通知失败: {e}")

                    # 第二阶段：发送所有已保存的片段
                    success_count = 0
                    for i, (segment_file, segment_duration) in enumerate(segment_files):
                        try:
                            # 按短语音方式处理分段文件
                            # 读取文件数据
                            with open(segment_file, 'rb') as f:
                                segment_data = f.read()

                            # 处理为音频对象
                            segment_audio = AudioSegment.from_file(BytesIO(segment_data), format="mp3").set_channels(1)
                            segment_audio = segment_audio.set_frame_rate(closest_rate)

                            # 编码为SILK
                            segment_silk_data = await pysilk.async_encode(segment_audio.raw_data, sample_rate=segment_audio.frame_rate)
                            segment_base64 = base64.b64encode(segment_silk_data).decode('utf-8')

                            # 准备API请求
                            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendVoice"
                            params = {
                                "Wxid": self.wxid,
                                "ToWxid": to_user_id,
                                "Base64": segment_base64,
                                "Type": 4,  # SILK格式
                                "VoiceTime": segment_duration
                            }

                            # 记录日志，隐藏base64数据
                            debug_params = params.copy()
                            debug_params["Base64"] = f"[Base64 data, length: {len(segment_base64)}]"
                            logger.debug(f"[WX849] 语音片段 {i+1}/{segments_count} API参数: {json.dumps(debug_params, ensure_ascii=False)}")

                            # 发送语音片段
                            async with aiohttp.ClientSession() as session:
                                async with session.post(api_url, json=params, timeout=60) as response:
                                    json_resp = await response.json()

                                    # 检查响应
                                    if json_resp and json_resp.get("Success", False):
                                        logger.info(f"[WX849] 语音片段 {i+1}/{segments_count} 发送成功")
                                        success_count += 1

                                        # 添加延迟，避免发送过快导致的问题
                                        await asyncio.sleep(1.0)  # 增加延迟到1秒
                                    else:
                                        error_msg = json_resp.get("Message", "未知错误")
                                        logger.error(f"[WX849] 语音片段 {i+1}/{segments_count} API返回错误: {error_msg}")
                        except Exception as e:
                            logger.error(f"[WX849] 发送语音片段 {i+1}/{segments_count} 失败: {e}")
                            logger.error(traceback.format_exc())

                    # 发送完成通知
                    try:
                        async with aiohttp.ClientSession() as session:
                            text_url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendTxt"
                            text_params = {
                                "Wxid": self.wxid,
                                "ToWxid": to_user_id,
                                "Content": f"长语音发送完成，成功 {success_count}/{segments_count} 段"
                            }

                            # 发送文本提示
                            async with session.post(text_url, json=text_params, timeout=60) as text_response:
                                text_json_resp = await text_response.json()
                                if text_json_resp and text_json_resp.get("Success", False):
                                    logger.info(f"[WX849] 发送语音完成通知成功")
                    except Exception as e:
                        logger.error(f"[WX849] 发送语音完成通知失败: {e}")

                    # 清理临时分段文件
                    for segment_file, _ in segment_files:
                        try:
                            if os.path.exists(segment_file):
                                os.remove(segment_file)
                                logger.debug(f"[WX849] 已删除临时分段文件: {segment_file}")
                        except Exception as e:
                            logger.debug(f"[WX849] 删除临时分段文件失败: {e}")

                    # 尝试删除分段目录
                    try:
                        if os.path.exists(segment_dir):
                            os.rmdir(segment_dir)
                            logger.debug(f"[WX849] 已删除临时分段目录: {segment_dir}")
                    except Exception as e:
                        logger.debug(f"[WX849] 删除临时分段目录失败: {e}")

                    # 设置结果状态
                    if success_count > 0:
                        result = {"Success": True}
                    else:
                        result = None
                else:
                    # 语音时长不超过最大片段时长，直接发送
                    logger.info(f"[WX849] 语音时长不超过20秒 ({total_duration/1000:.1f}秒)，直接发送")
                    silk_data = await pysilk.async_encode(audio.raw_data, sample_rate=audio.frame_rate)
                    voice_base64 = base64.b64encode(silk_data).decode('utf-8')

                    api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendVoice"
                    params = {
                        "Wxid": self.wxid,
                        "ToWxid": to_user_id,
                        "Base64": voice_base64,
                        "Type": 4,  # SILK格式
                        "VoiceTime": total_duration
                    }

                    # 记录日志，隐藏base64数据
                    debug_params = params.copy()
                    debug_params["Base64"] = f"[Base64 data, length: {len(voice_base64)}]"
                    logger.debug(f"[WX849] 语音API参数: {json.dumps(debug_params, ensure_ascii=False)}")

                    # 发送请求
                    async with aiohttp.ClientSession() as session:
                        async with session.post(api_url, json=params, timeout=60) as response:
                            json_resp = await response.json()

                            # 检查响应
                            if json_resp and json_resp.get("Success", False):
                                logger.info(f"[WX849] 语音发送成功")
                                result = {"Success": True}
                            else:
                                error_msg = json_resp.get("Message", "未知错误")
                                logger.error(f"[WX849] 语音API返回错误: {error_msg}")
                                logger.error(f"[WX849] 响应详情: {json.dumps(json_resp, ensure_ascii=False)}")
                                result = None
            except Exception as e:
                logger.error(f"[WX849] 处理音频数据失败: {e}")
                logger.error(traceback.format_exc())
                result = None
        except Exception as e:
            logger.error(f"[WX849] 发送语音失败: {e}")
            logger.error(traceback.format_exc())
            result = None
        finally:
            # 删除处理后的临时文件
            try:
                if os.path.exists(processed_file):
                    os.remove(processed_file)
                    logger.debug(f"[WX849] 已删除临时文件: {processed_file}")
            except Exception as e:
                logger.debug(f"[WX849] 删除临时文件失败: {e}")

        return result

    async def _send_video(self, to_user_id, video_base64, cover_base64=None, video_duration=10):
        """发送视频消息"""
        try:
            # 检查参数
            if not to_user_id:
                logger.error("[WX849] 发送视频失败: 接收者ID为空")
                return None

            if not video_base64:
                logger.error("[WX849] 发送视频失败: 视频数据为空")
                return None

            # 设置默认封面
            if not cover_base64 or cover_base64 == "None":
                try:
                    # 使用1x1像素的透明PNG作为最小封面
                    cover_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    logger.debug("[WX849] 使用内置1x1像素作为默认封面")
                except Exception as e:
                    logger.error(f"[WX849] 准备默认封面图片失败: {e}")
                    # 使用1x1像素的透明PNG作为最小封面
                    cover_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    logger.debug("[WX849] 使用内置1x1像素作为默认封面")

            # 打印预估时间
            try:
                # 计算视频base64长度
                base64_content = video_base64
                if base64_content.startswith("data:video/mp4;base64,"):
                    base64_content = base64_content[len("data:video/mp4;base64,"):]

                # 计算文件大小 (KB)
                file_len = len(base64.b64decode(base64_content)) / 1024

                # 预估时间 (秒)，按300KB/s计算
                predict_time = int(file_len / 300)
                logger.info(f"[WX849] 开始发送视频: 预计{predict_time}秒, 视频大小:{file_len:.2f}KB, 时长:{video_duration}秒")
            except Exception as e:
                logger.debug(f"[WX849] 计算预估时间失败: {e}")

            # 处理视频和封面的base64数据
            pure_video_base64 = video_base64
            if pure_video_base64.startswith("data:video/mp4;base64,"):
                pure_video_base64 = pure_video_base64[len("data:video/mp4;base64,"):]

            pure_cover_base64 = cover_base64
            if pure_cover_base64 and pure_cover_base64 != "None" and pure_cover_base64.startswith("data:image/jpeg;base64,"):
                pure_cover_base64 = pure_cover_base64[len("data:image/jpeg;base64,"):]

            # 记录API调用参数
            logger.debug(f"[WX849] 发送视频至接收者: {to_user_id}, 视频base64长度: {len(pure_video_base64)}, 封面base64长度: {len(pure_cover_base64)}")

            # 直接使用API发送视频（绕过bot.send_video_message方法，避免参数不兼容问题）
            # 确保base64前缀正确
            video_data = "data:video/mp4;base64," + pure_video_base64
            cover_data = "data:image/jpeg;base64," + pure_cover_base64

            # 构建API参数 - 根据API文档确保参数名称和格式正确
            params = {
                "Wxid": self.wxid,
                "ToWxid": to_user_id,
                "Base64": video_data,
                "ImageBase64": cover_data,
                "PlayLength": video_duration  # 这是必需的参数，缺少会导致[Key:]数据不存在错误
            }

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)

            # 确定API路径前缀
            protocol_version = conf().get("wx849_protocol_version", "849")
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建完整API URL
            url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendVideo"

            logger.debug(f"[WX849] 直接调用SendVideo API: {url}")

            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as response:
                    json_resp = await response.json()

                    # 检查响应
                    if json_resp and json_resp.get("Success", False):
                        data = json_resp.get("Data", {})
                        client_msg_id = data.get("clientMsgId")
                        new_msg_id = data.get("newMsgId")

                        logger.info(f"[WX849] 视频发送成功，返回ID: {client_msg_id}, {new_msg_id}")
                        return {"Success": True, "client_msg_id": client_msg_id, "new_msg_id": new_msg_id}
                    else:
                        error_msg = json_resp.get("Message", "未知错误")
                        logger.error(f"[WX849] 视频API返回错误: {error_msg}")
                        logger.error(f"[WX849] 响应详情: {json.dumps(json_resp, ensure_ascii=False)}")
                        return None

        except Exception as e:
            logger.error(f"[WX849] 发送视频失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def _get_group_member_details(self, group_id):
        """获取群成员详情"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的成员详情")

            # 检查是否已存在群成员信息，并检查是否需要更新
            # 定义群聊信息文件路径
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            # 读取现有的群聊信息（如果存在）
            chatrooms_info = {}
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                    logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                except Exception as e:
                    logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

            # 检查该群聊是否已存在且成员信息是否已更新
            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())

            if (group_id in chatrooms_info and
                "members" in chatrooms_info[group_id] and
                len(chatrooms_info[group_id]["members"]) > 0 and
                "last_update" in chatrooms_info[group_id] and
                current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):
                logger.debug(f"[WX849] 群 {group_id} 成员信息已存在且未过期，跳过更新")
                return chatrooms_info[group_id]

            logger.debug(f"[WX849] 群 {group_id} 成员信息不存在或已过期，开始更新")

            # 调用API获取群成员详情
            params = {
                "QID": group_id,  # 群ID参数
                "Wxid": self.wxid  # 自己的wxid参数
            }

            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomMemberDetail"
                logger.debug(f"[WX849] 正在请求群成员详情API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

                # 调用API获取群成员详情
                response = await self._call_api("/Group/GetChatRoomMemberDetail", params)

                if not response or not isinstance(response, dict):
                    logger.error(f"[WX849] 获取群成员详情失败: 无效响应")
                    return None

                # 检查响应是否成功
                if not response.get("Success", False):
                    logger.error(f"[WX849] 获取群成员详情失败: {response.get('Message', '未知错误')}")
                    return None

                # 提取NewChatroomData
                data = response.get("Data", {})
                new_chatroom_data = data.get("NewChatroomData", {})

                if not new_chatroom_data:
                    logger.error(f"[WX849] 获取群成员详情失败: 响应中无NewChatroomData")
                    return None

                # 检查当前群聊是否已存在
                if group_id not in chatrooms_info:
                    chatrooms_info[group_id] = {
                        "chatroomId": group_id,
                        "nickName": group_id,
                        "chatRoomOwner": "",
                        "members": [],
                        "last_update": int(time.time())
                    }

                # 提取成员信息
                member_count = new_chatroom_data.get("MemberCount", 0)
                chat_room_members = new_chatroom_data.get("ChatRoomMember", [])

                # 确保是有效的成员列表
                if not isinstance(chat_room_members, list):
                    logger.error(f"[WX849] 获取群成员详情失败: ChatRoomMember不是有效的列表")
                    return None

                # 更新群聊成员信息
                members = []
                for member in chat_room_members:
                    if not isinstance(member, dict):
                        continue

                    # 提取成员必要信息
                    member_info = {
                        "UserName": member.get("UserName", ""),
                        "NickName": member.get("NickName", ""),
                        "DisplayName": member.get("DisplayName", ""),
                        "ChatroomMemberFlag": member.get("ChatroomMemberFlag", 0),
                        "InviterUserName": member.get("InviterUserName", ""),
                        "BigHeadImgUrl": member.get("BigHeadImgUrl", ""),
                        "SmallHeadImgUrl": member.get("SmallHeadImgUrl", "")
                    }

                    members.append(member_info)

                # 更新群聊信息
                chatrooms_info[group_id]["members"] = members
                chatrooms_info[group_id]["last_update"] = int(time.time())
                chatrooms_info[group_id]["memberCount"] = member_count

                # 同时更新群主信息
                for member in members:
                    if member.get("ChatroomMemberFlag") == 2049:  # 群主标志
                        chatrooms_info[group_id]["chatRoomOwner"] = member.get("UserName", "")
                        break

                # 保存到文件
                with open(chatrooms_file, 'w', encoding='utf-8') as f:
                    json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

                logger.info(f"[WX849] 已更新群聊 {group_id} 成员信息，成员数: {len(members)}")

                # 返回成员信息
                return new_chatroom_data
            except Exception as e:
                logger.error(f"[WX849] 获取群成员详情失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                return None
        except Exception as e:
            logger.error(f"[WX849] 获取群成员详情过程中出错: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_group_name(self, group_id):
        """获取群名称"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的名称")

            # 检查缓存中是否有群名
            cache_key = f"group_name_{group_id}"
            if hasattr(self, "group_name_cache") and cache_key in self.group_name_cache:
                cached_name = self.group_name_cache[cache_key]
                logger.debug(f"[WX849] 从缓存中获取群名: {cached_name}")

                # 检查是否需要更新群成员详情
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

                need_update = True
                # 设定缓存有效期为24小时(86400秒)
                cache_expiry = 86400
                current_time = int(time.time())

                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)

                        # 检查群信息是否存在且未过期
                        if (group_id in chatrooms_info and
                            "last_update" in chatrooms_info[group_id] and
                            current_time - chatrooms_info[group_id]["last_update"] < cache_expiry and
                            "members" in chatrooms_info[group_id] and
                            len(chatrooms_info[group_id]["members"]) > 0):
                            logger.debug(f"[WX849] 群 {group_id} 信息已存在且未过期，跳过更新")
                            need_update = False
                    except Exception as e:
                        logger.error(f"[WX849] 检查群信息缓存时出错: {e}")

                # 只有需要更新时才启动线程获取群成员详情
                if need_update:
                    logger.debug(f"[WX849] 群 {group_id} 信息需要更新，启动更新线程")
                    threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                return cached_name

            # 检查文件中是否已经有群信息，且未过期
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())

            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)

                    # 检查群信息是否存在且未过期
                    if (group_id in chatrooms_info and
                        "nickName" in chatrooms_info[group_id] and
                        chatrooms_info[group_id]["nickName"] and
                        chatrooms_info[group_id]["nickName"] != group_id and
                        "last_update" in chatrooms_info[group_id] and
                        current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):

                        # 从文件中获取群名
                        group_name = chatrooms_info[group_id]["nickName"]
                        logger.debug(f"[WX849] 从文件缓存中获取群名: {group_name}")

                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name

                        # 检查是否需要更新群成员详情
                        need_update_members = not ("members" in chatrooms_info[group_id] and
                                                len(chatrooms_info[group_id]["members"]) > 0)

                        if need_update_members:
                            logger.debug(f"[WX849] 群 {group_id} 名称已缓存，但需要更新成员信息")
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                        else:
                            logger.debug(f"[WX849] 群 {group_id} 信息已完整且未过期，无需更新")

                        return group_name
                except Exception as e:
                    logger.error(f"[WX849] 从文件获取群名出错: {e}")

            logger.debug(f"[WX849] 群 {group_id} 信息不存在或已过期，需要从API获取")

            # 调用API获取群信息 - 使用群聊API
            params = {
                "QID": group_id,  # 群ID参数，正确的参数名是QID
                "Wxid": self.wxid  # 自己的wxid参数
            }

            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomInfo"
                logger.debug(f"[WX849] 正在请求群信息API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")  # 记录请求参数

                # 尝试使用群聊专用API
                group_info = await self._call_api("/Group/GetChatRoomInfo", params)

                # 保存群聊详情到统一的JSON文件
                try:
                    # 读取现有的群聊信息（如果存在）
                    chatrooms_info = {}
                    if os.path.exists(chatrooms_file):
                        try:
                            with open(chatrooms_file, 'r', encoding='utf-8') as f:
                                chatrooms_info = json.load(f)
                            logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                        except Exception as e:
                            logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

                    # 提取必要的群聊信息
                    if group_info and isinstance(group_info, dict):
                        # 递归函数用于查找特定key的值
                        def find_value(obj, key):
                            # 如果是字典
                            if isinstance(obj, dict):
                                # 直接检查当前字典
                                if key in obj:
                                    return obj[key]
                                # 检查带有"string"嵌套的字典
                                if key in obj and isinstance(obj[key], dict) and "string" in obj[key]:
                                    return obj[key]["string"]
                                # 递归检查字典的所有值
                                for k, v in obj.items():
                                    result = find_value(v, key)
                                    if result is not None:
                                        return result
                            # 如果是列表
                            elif isinstance(obj, list):
                                # 递归检查列表的所有项
                                for item in obj:
                                    result = find_value(item, key)
                                    if result is not None:
                                        return result
                            return None

                        # 尝试提取群名称及其他信息
                        group_name = None

                        # 首先尝试从NickName中获取
                        nickname_obj = find_value(group_info, "NickName")
                        if isinstance(nickname_obj, dict) and "string" in nickname_obj:
                            group_name = nickname_obj["string"]
                        elif isinstance(nickname_obj, str):
                            group_name = nickname_obj

                        # 如果没找到，尝试其他可能的字段
                        if not group_name:
                            for name_key in ["ChatRoomName", "nickname", "name", "DisplayName"]:
                                name_value = find_value(group_info, name_key)
                                if name_value:
                                    if isinstance(name_value, dict) and "string" in name_value:
                                        group_name = name_value["string"]
                                    elif isinstance(name_value, str):
                                        group_name = name_value
                                    if group_name:
                                        break

                        # 提取群主ID
                        owner_id = None
                        for owner_key in ["ChatRoomOwner", "chatroomowner", "Owner"]:
                            owner_value = find_value(group_info, owner_key)
                            if owner_value:
                                if isinstance(owner_value, dict) and "string" in owner_value:
                                    owner_id = owner_value["string"]
                                elif isinstance(owner_value, str):
                                    owner_id = owner_value
                                if owner_id:
                                    break

                        # 检查群聊信息是否已存在
                        if group_id in chatrooms_info:
                            # 更新已有群聊信息
                            if group_name:
                                chatrooms_info[group_id]["nickName"] = group_name
                            if owner_id:
                                chatrooms_info[group_id]["chatRoomOwner"] = owner_id
                            chatrooms_info[group_id]["last_update"] = int(time.time())
                        else:
                            # 创建新群聊信息
                            chatrooms_info[group_id] = {
                                "chatroomId": group_id,
                                "nickName": group_name or group_id,
                                "chatRoomOwner": owner_id or "",
                                "members": [],
                                "last_update": int(time.time())
                            }

                        # 保存到文件
                        with open(chatrooms_file, 'w', encoding='utf-8') as f:
                            json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

                        logger.info(f"[WX849] 已更新群聊 {group_id} 基础信息")

                        # 缓存群名
                        if group_name:
                            if not hasattr(self, "group_name_cache"):
                                self.group_name_cache = {}
                            self.group_name_cache[cache_key] = group_name

                            # 异步获取群成员详情（不阻塞当前方法）
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                            return group_name

                except Exception as save_err:
                    logger.error(f"[WX849] 保存群聊信息到文件失败: {save_err}")
                    import traceback
                    logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")

                # 如果上面的处理没有返回群名称，再次尝试从原始数据中提取
                if group_info and isinstance(group_info, dict):
                    # 尝试从API返回中获取群名称
                    group_name = None

                    # 尝试多种可能的字段名
                    possible_fields = ["NickName", "nickname", "ChatRoomName", "chatroomname", "DisplayName", "displayname"]
                    for field in possible_fields:
                        if field in group_info and group_info[field]:
                            group_name = group_info[field]
                            if isinstance(group_name, dict) and "string" in group_name:
                                group_name = group_name["string"]
                            break

                    if group_name:
                        logger.debug(f"[WX849] 获取到群名称: {group_name}")

                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name

                        # 异步获取群成员详情
                        threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                        return group_name
                    else:
                        logger.warning(f"[WX849] API返回成功但未找到群名称字段: {json.dumps(group_info, ensure_ascii=False)}")
                else:
                    logger.warning(f"[WX849] API返回无效数据: {group_info}")
            except Exception as e:
                # 详细记录API请求失败的错误信息
                logger.error(f"[WX849] 使用群聊API获取群名称失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                logger.error(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 如果无法获取群名，使用群ID作为名称
            logger.debug(f"[WX849] 无法获取群名称，使用群ID代替: {group_id}")
            # 缓存结果
            if not hasattr(self, "group_name_cache"):
                self.group_name_cache = {}
            self.group_name_cache[cache_key] = group_id

            # 尽管获取群名失败，仍然尝试获取群成员详情
            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

            return group_id
        except Exception as e:
            logger.error(f"[WX849] 获取群名称失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return group_id

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        """重写父类方法，构建消息上下文"""
        try:
            # 直接创建Context对象，确保结构正确
            context = Context()
            context.type = ctype
            context.content = content

            # 获取消息对象
            msg = kwargs.get('msg')

            # 检查是否是群聊消息
            isgroup = kwargs.get('isgroup', False)
            if isgroup and msg and hasattr(msg, 'from_user_id'):
                # 设置群组相关信息
                context["isgroup"] = True

                # 使用或提取实际发送者信息
                if hasattr(msg, 'actual_user_nickname') and msg.actual_user_nickname and not msg.actual_user_nickname.startswith("未知用户_"):
                    # 有效的发送者昵称
                    sender_nickname = msg.actual_user_nickname
                    sender_id = getattr(msg, 'actual_user_id', getattr(msg, 'sender_wxid', "unknown_user"))
                elif hasattr(msg, 'sender_nickname') and msg.sender_nickname:
                    # 备选：使用sender_nickname
                    sender_nickname = msg.sender_nickname
                    sender_id = getattr(msg, 'sender_wxid', "unknown_user")
                elif hasattr(msg, 'sender_wxid') and msg.sender_wxid and not msg.sender_wxid.startswith("未知用户_"):
                    # 备选：使用sender_wxid
                    sender_id = msg.sender_wxid
                    sender_nickname = msg.sender_wxid  # 默认使用ID作为昵称
                else:
                    # 无法获取有效发送者信息时
                    sender_id = "unknown_user"
                    sender_nickname = "未知用户"

                context["from_user_nickname"] = sender_nickname
                context["from_user_id"] = sender_id
                context["to_user_id"] = getattr(msg, 'to_user_id', self.wxid)
                context["other_user_id"] = msg.from_user_id  # 群ID
                context["group_name"] = msg.from_user_id  # 临时使用群ID作为群名
                context["group_id"] = msg.from_user_id  # 群ID
                context["msg"] = msg  # 消息对象

                # 设置session_id为群ID
                context["session_id"] = msg.from_user_id

                # 启动异步任务获取群名称并更新
                loop = asyncio.get_event_loop()
                try:
                    # 尝试创建异步任务获取群名
                    async def update_group_name():
                        try:
                            group_name = await self._get_group_name(msg.from_user_id)
                            if group_name:
                                context['group_name'] = group_name
                                logger.debug(f"[WX849] 更新群名称: {group_name}")
                        except Exception as e:
                            logger.error(f"[WX849] 更新群名称失败: {e}")

                    # 使用已有事件循环运行更新任务
                    def run_async_task():
                        try:
                            asyncio.run(update_group_name())
                        except Exception as e:
                            logger.error(f"[WX849] 异步获取群名称任务失败: {e}")

                    # 启动线程执行异步任务
                    threading.Thread(target=run_async_task).start()
                except Exception as e:
                    logger.error(f"[WX849] 创建获取群名称任务失败: {e}")
            else:
                # 私聊消息
                context["isgroup"] = False

                # 使用可用的发送者昵称
                if hasattr(msg, 'sender_nickname') and msg.sender_nickname:
                    context["from_user_nickname"] = msg.sender_nickname
                else:
                    context["from_user_nickname"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""

                context["from_user_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""
                context["to_user_id"] = msg.to_user_id if msg and hasattr(msg, 'to_user_id') else ""
                context["other_user_id"] = None
                context["msg"] = msg

                # 设置session_id为发送者ID
                context["session_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""

            # 添加接收者信息
            context["receiver"] = msg.from_user_id if isgroup else msg.sender_wxid

            # 记录原始消息类型
            context["origin_ctype"] = ctype

            # 添加调试日志
            logger.debug(f"[WX849] 生成Context对象: type={context.type}, content={context.content}, isgroup={context['isgroup']}, session_id={context.get('session_id', 'None')}")
            if isgroup:
                logger.debug(f"[WX849] 群聊消息详情: group_id={context.get('group_id')}, from_user_id={context.get('from_user_id')}")

            return context
        except Exception as e:
            logger.error(f"[WX849] 构建上下文失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_chatroom_member_nickname(self, group_id, member_wxid):
        """获取群成员的昵称"""
        if not group_id or not member_wxid:
            return member_wxid

        try:
            # 优先从缓存获取群成员信息
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            if os.path.exists(chatrooms_file):
                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                    chatrooms_info = json.load(f)

                if group_id in chatrooms_info and "members" in chatrooms_info[group_id]:
                    for member in chatrooms_info[group_id]["members"]:
                        if member.get("UserName") == member_wxid:
                            # 优先使用群内显示名称(群昵称)
                            if member.get("DisplayName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                                return member.get("DisplayName")
                            # 次选使用个人昵称
                            elif member.get("NickName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                                return member.get("NickName")
                            else:
                                return member_wxid

            # 如果缓存中没有，启动一个后台任务获取群成员，但本次先返回wxid
            logger.debug(f"[WX849] 未找到成员 {member_wxid} 的昵称信息，启动更新任务")
            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
            return member_wxid
        except Exception as e:
            logger.error(f"[WX849] 获取群成员昵称失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return member_wxid

    async def _get_contact_name(self, contact_id):
        """获取联系人昵称，与gewechat保持一致"""
        if not contact_id or contact_id.endswith("@chatroom"):
            return contact_id

        try:
            # 优先从缓存获取联系人信息
            cache_key = f"contact_name_{contact_id}"
            if hasattr(self, "contact_name_cache") and cache_key in self.contact_name_cache:
                cached_name = self.contact_name_cache[cache_key]
                logger.debug(f"[WX849] 从缓存中获取联系人昵称: {cached_name}")
                return cached_name

            # 检查文件中是否已经有联系人信息，且未过期
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            contacts_file = os.path.join(tmp_dir, 'wx849_contacts.json')

            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())

            if os.path.exists(contacts_file):
                try:
                    with open(contacts_file, 'r', encoding='utf-8') as f:
                        contacts_info = json.load(f)

                    # 检查联系人信息是否存在且未过期
                    if (contact_id in contacts_info and
                        "NickName" in contacts_info[contact_id] and
                        contacts_info[contact_id]["NickName"] and
                        contacts_info[contact_id]["NickName"] != contact_id and
                        "last_update" in contacts_info[contact_id] and
                        current_time - contacts_info[contact_id]["last_update"] < cache_expiry):

                        # 从文件中获取联系人昵称
                        contact_name = contacts_info[contact_id]["NickName"]
                        logger.debug(f"[WX849] 从文件缓存中获取联系人昵称: {contact_name}")

                        # 缓存联系人昵称
                        if not hasattr(self, "contact_name_cache"):
                            self.contact_name_cache = {}
                        self.contact_name_cache[cache_key] = contact_name

                        return contact_name
                except Exception as e:
                    logger.error(f"[WX849] 从文件获取联系人昵称出错: {e}")

            logger.debug(f"[WX849] 联系人 {contact_id} 信息不存在或已过期，需要从API获取")

            # 调用API获取联系人信息
            params = {
                "Wxid": self.wxid,
                "ToWxid": contact_id
            }

            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Friend/GetContractDetail"
                logger.debug(f"[WX849] 正在请求联系人详情API: {api_url}")

                # 准备请求参数
                params = {
                    "Wxid": self.wxid,
                    "Towxids": contact_id,
                    "ChatRoom": ""
                }

                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

                # 尝试使用联系人详情API
                contact_detail_response = await self._call_api("/Friend/GetContractDetail", params)

                # 从联系人详情中提取信息
                contact_info = None
                if contact_detail_response and isinstance(contact_detail_response, dict) and contact_detail_response.get("Success", False):
                    data = contact_detail_response.get("Data", {})
                    if data:
                        contact_info = data

                # 保存联系人详情到统一的JSON文件
                try:
                    # 读取现有的联系人信息（如果存在）
                    contacts_info = {}
                    if os.path.exists(contacts_file):
                        try:
                            with open(contacts_file, 'r', encoding='utf-8') as f:
                                contacts_info = json.load(f)
                            logger.debug(f"[WX849] 已加载 {len(contacts_info)} 个现有联系人信息")
                        except Exception as e:
                            logger.error(f"[WX849] 加载现有联系人信息失败: {str(e)}")

                    # 提取必要的联系人信息
                    if contact_info and isinstance(contact_info, dict):
                        # 递归函数用于查找特定key的值
                        def find_value(obj, key):
                            # 如果是字典
                            if isinstance(obj, dict):
                                # 直接检查当前字典
                                if key in obj:
                                    return obj[key]
                                # 检查带有"string"嵌套的字典
                                if key in obj and isinstance(obj[key], dict) and "string" in obj[key]:
                                    return obj[key]["string"]
                                # 递归检查字典的所有值
                                for k, v in obj.items():
                                    result = find_value(v, key)
                                    if result is not None:
                                        return result
                            # 如果是列表
                            elif isinstance(obj, list):
                                # 递归检查列表的所有项
                                for item in obj:
                                    result = find_value(item, key)
                                    if result is not None:
                                        return result
                            return None

                        # 尝试提取联系人昵称及其他信息
                        contact_name = None

                        # 首先尝试从NickName中获取
                        nickname_obj = find_value(contact_info, "NickName")
                        if isinstance(nickname_obj, dict) and "string" in nickname_obj:
                            contact_name = nickname_obj["string"]
                        elif isinstance(nickname_obj, str):
                            contact_name = nickname_obj

                        # 如果没找到，尝试其他可能的字段
                        if not contact_name:
                            for name_key in ["nickname", "name", "DisplayName"]:
                                name_value = find_value(contact_info, name_key)
                                if name_value:
                                    if isinstance(name_value, dict) and "string" in name_value:
                                        contact_name = name_value["string"]
                                    elif isinstance(name_value, str):
                                        contact_name = name_value
                                    if contact_name:
                                        break

                        # 如果找到了联系人昵称，更新缓存
                        if contact_name:
                            # 更新联系人信息
                            if contact_id not in contacts_info:
                                contacts_info[contact_id] = {}

                            contacts_info[contact_id]["NickName"] = contact_name
                            contacts_info[contact_id]["last_update"] = current_time

                            # 保存到文件
                            with open(contacts_file, 'w', encoding='utf-8') as f:
                                json.dump(contacts_info, f, ensure_ascii=False, indent=2)

                            # 更新内存缓存
                            if not hasattr(self, "contact_name_cache"):
                                self.contact_name_cache = {}
                            self.contact_name_cache[cache_key] = contact_name

                            logger.debug(f"[WX849] 已更新联系人 {contact_id} 昵称: {contact_name}")
                            return contact_name
                except Exception as e:
                    logger.error(f"[WX849] 处理联系人信息失败: {e}")

                # 如果API获取失败，返回联系人ID
                logger.debug(f"[WX849] 未找到联系人 {contact_id} 的昵称信息")
                return contact_id
            except Exception as e:
                logger.error(f"[WX849] 获取联系人昵称失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                return contact_id
        except Exception as e:
            logger.error(f"[WX849] 获取联系人昵称过程中出错: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return contact_id

    async def _check_original_framework_status(self) -> bool:
        """检查原始框架状态

        Returns:
            bool: 如果原始框架仍然活跃返回True，否则返回False
        """
        try:
            # 获取原始框架配置文件路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            channel_dir = os.path.dirname(current_dir)
            dow_dir = os.path.dirname(channel_dir)
            root_dir = os.path.dirname(dow_dir)
            robot_stat_file = os.path.join(root_dir, "resource", "robot_stat.json")

            # 检查文件是否存在
            if not os.path.exists(robot_stat_file):
                logger.error(f"[WX849] 原始框架配置文件不存在: {robot_stat_file}")
                return False

            # 读取原始框架配置
            try:
                with open(robot_stat_file, "r", encoding="utf-8") as f:
                    robot_stat = json.load(f)
                    stored_wxid = robot_stat.get("wxid", "")

                    # 如果没有wxid或与当前wxid不同，表示原始框架已退出或重新登录
                    if not stored_wxid:
                        logger.error("[WX849] 原始框架配置文件中没有wxid，可能已退出登录")
                        return False

                    if stored_wxid != self.wxid:
                        logger.warning(f"[WX849] 原始框架wxid已变更: 原wxid={self.wxid}, 新wxid={stored_wxid}")
                        # 此处可以选择更新为新的wxid
                        # self.wxid = stored_wxid
                        # self.user_id = stored_wxid
                        return False
            except Exception as e:
                logger.error(f"[WX849] 读取原始框架配置文件失败: {e}")
                return False

            # 尝试发送心跳包检查会话有效性
            try:
                # 准备心跳请求参数
                protocol_version = conf().get("wx849_protocol_version", "849")
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)

                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建心跳包URL
                heart_url = f"http://{api_host}:{api_port}{api_path_prefix}/Login/HeartBeat"

                # 准备心跳请求参数
                heart_form_data = {"wxid": self.wxid}
                encoded_heart_data = urllib.parse.urlencode(heart_form_data)
                headers = {'Content-Type': 'application/x-www-form-urlencoded'}

                async with aiohttp.ClientSession() as session:
                    async with session.post(heart_url, data=encoded_heart_data, headers=headers) as response:
                        if response.status == 200:
                            heart_json = await response.json()
                            if heart_json.get("Success", False):
                                logger.info("[WX849] 原始框架会话仍然有效")
                                return True
                            else:
                                logger.error(f"[WX849] 原始框架会话已失效: {heart_json.get('Message', '未知错误')}")
                                return False
                        else:
                            logger.error(f"[WX849] 心跳包请求失败，状态码: {response.status}")
                            return False
            except Exception as e:
                logger.error(f"[WX849] 检查原始框架会话状态失败: {e}")
                return False

            return False
        except Exception as e:
            logger.error(f"[WX849] 检查原始框架状态时发生异常: {e}")
            logger.error(traceback.format_exc())
            return False

    async def _extract_video_duration(self, video_path):
        """从视频文件中提取时长（秒）

        Args:
            video_path: 视频文件路径

        Returns:
            int: 视频时长（秒），如果提取失败则返回默认值10
        """
        try:
            # 查找ffmpeg可执行文件
            ffmpeg_cmd = "ffmpeg"
            ffprobe_cmd = "ffprobe"
            # 在Windows上检查常见安装路径
            if os.name == 'nt':
                possible_paths = [
                    r"C:\ffmpeg\bin",
                    r"C:\Program Files\ffmpeg\bin",
                    r"C:\Program Files (x86)\ffmpeg\bin"
                ]
                for path in possible_paths:
                    if os.path.exists(os.path.join(path, "ffprobe.exe")):
                        ffprobe_cmd = os.path.join(path, "ffprobe.exe")
                        break

            logger.debug(f"[WX849] 使用ffprobe命令: {ffprobe_cmd}")

            # 使用ffprobe提取视频时长
            process = subprocess.run([
                ffprobe_cmd,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ], check=False, capture_output=True)

            if process.returncode == 0:
                stdout = process.stdout.decode().strip()
                try:
                    duration = float(stdout)
                    logger.debug(f"[WX849] 提取到视频时长: {duration}秒")

                    # 确保时长为整数秒
                    return int(duration)
                except (ValueError, TypeError) as e:
                    logger.error(f"[WX849] 解析视频时长失败: {e}, stdout: {stdout}")
            else:
                stderr = process.stderr.decode() if process.stderr else "无stderr输出"
                logger.error(f"[WX849] 运行ffprobe失败，返回码: {process.returncode}, 错误: {stderr}")

            # 如果提取失败，返回默认值
            logger.warning("[WX849] 未能提取视频时长，使用默认值10秒")
            return 10

        except Exception as e:
            logger.error(f"[WX849] 获取视频时长时出错: {e}")
            logger.error(traceback.format_exc())
            return 10  # 默认10秒

    async def _download_and_send_video(self, to_user_id, video_url):
        """下载视频并发送"""
        tmp_path = None
        try:
            # 1. 检查和创建临时目录
            tmp_dir = os.path.join(get_appdata_dir(), "video_tmp")
            os.makedirs(tmp_dir, exist_ok=True)

            # 创建临时文件
            tmp_path = os.path.join(tmp_dir, f"tmp_video_{int(time.time())}.mp4")

            # 2. 下载视频
            logger.debug(f"[WX849] 开始下载视频: {video_url}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Referer': 'https://www.google.com/'
            }

            # 下载视频，设置30秒超时
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(video_url, headers=headers, timeout=30) as response:
                        if response.status != 200:
                            logger.error(f"[WX849] 下载视频失败, 状态码: {response.status}")
                            return False

                        # 检查内容类型
                        content_type = response.headers.get('Content-Type', '')
                        if 'video' not in content_type and 'octet-stream' not in content_type:
                            logger.warning(f"[WX849] 警告: 响应内容类型不是视频: {content_type}")

                        # 使用流式下载
                        with open(tmp_path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(8192)  # 8KB块
                                if not chunk:
                                    break
                                f.write(chunk)

                # 检查下载的文件
                if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024:  # 小于1KB
                    logger.error(f"[WX849] 下载的视频文件无效或过小: {os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 'not exists'}")
                    return False

                logger.debug(f"[WX849] 视频下载完成: {tmp_path}, 大小: {os.path.getsize(tmp_path)/1024:.2f}KB")
            except Exception as download_error:
                logger.error(f"[WX849] 下载视频失败: {download_error}")
                return False

            # 3. 获取视频时长
            video_duration = await self._extract_video_duration(tmp_path)
            logger.debug(f"[WX849] 视频时长: {video_duration}秒")

            # 4. 编码视频为Base64
            video_base64 = await self._encode_video(tmp_path)
            if not video_base64:
                logger.error("[WX849] 视频编码失败")
                return False

            # 5. 提取视频第一帧作为封面
            logger.debug(f"[WX849] 正在提取视频封面")
            cover_base64 = await self._extract_first_frame(tmp_path)
            if not cover_base64:
                logger.warning("[WX849] 未能获取视频封面，将使用无封面发送")
                cover_base64 = "None"  # 使用字符串"None"作为无封面的标记

            # 6. 发送视频
            logger.debug(f"[WX849] 开始发送视频到接收者: {to_user_id}")
            result = await self._send_video(to_user_id, video_base64, cover_base64, video_duration)

            # 7. 判断发送结果
            if result and isinstance(result, dict) and result.get("Success", False):
                logger.info(f"[WX849] 视频发送成功: {to_user_id}")
                return True
            else:
                logger.error(f"[WX849] 视频发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"[WX849] 处理视频失败: {e}")
            logger.error(traceback.format_exc())
            return False
        finally:
            # 删除临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.debug(f"[WX849] 已删除临时视频文件: {tmp_path}")
                except Exception as e:
                    logger.debug(f"[WX849] 删除临时视频文件失败: {e}")

    async def _encode_video(self, video_path):
        """将视频编码为base64"""
        try:
            with open(video_path, 'rb') as f:
                video_data = f.read()

            # 使用Base64编码
            import base64
            video_base64 = base64.b64encode(video_data).decode('utf-8')
            return video_base64
        except Exception as e:
            logger.error(f"[WX849] 视频Base64编码失败: {e}")
            return None

    async def _extract_first_frame(self, video_path):
        """从视频中提取第一帧并编码为Base64"""
        try:
            # 创建临时目录
            tmp_dir = os.path.join(get_appdata_dir(), "video_frames")
            os.makedirs(tmp_dir, exist_ok=True)

            # 临时图片文件路径
            thumbnail_path = os.path.join(tmp_dir, f"frame_{int(time.time())}.jpg")

            # 查找ffmpeg可执行文件
            ffmpeg_cmd = "ffmpeg"
            # 在Windows上检查常见安装路径
            if os.name == 'nt':
                possible_paths = [
                    r"C:\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        ffmpeg_cmd = path
                        break

            logger.debug(f"[WX849] 使用ffmpeg命令: {ffmpeg_cmd}")

            # 使用ffmpeg提取第一帧，尝试多个时间点
            success = False
            for timestamp in ["00:00:01", "00:00:00.5", "00:00:00"]:
                try:
                    # 使用subprocess.run来执行ffmpeg命令
                    process = subprocess.run([
                        ffmpeg_cmd,
                        "-i", video_path,
                        "-ss", timestamp,
                        "-vframes", "1",
                        "-q:v", "2",  # 设置高质量输出
                        thumbnail_path,
                        "-y"
                    ], check=False, capture_output=True)

                    if process.returncode == 0 and os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                        logger.debug(f"[WX849] 成功提取视频帧，使用时间点: {timestamp}")
                        success = True
                        break
                    else:
                        logger.debug(f"[WX849] 提取视频帧失败，时间点: {timestamp}, 返回码: {process.returncode}")
                        if process.stderr:
                            logger.debug(f"[WX849] ffmpeg错误: {process.stderr.decode()[:200]}")
                except Exception as e:
                    logger.debug(f"[WX849] 使用时间点 {timestamp} 提取帧时出错: {e}")

            # 如果所有尝试都失败，则返回空
            if not success:
                logger.warning("[WX849] 所有提取视频帧的尝试都失败，将发送无封面视频")
                return None

            # 读取并编码图片
            if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                with open(thumbnail_path, "rb") as f:
                    image_data = f.read()

                import base64
                image_base64 = base64.b64encode(image_data).decode('utf-8')

                # 删除临时图片文件
                try:
                    os.remove(thumbnail_path)
                except Exception:
                    pass

                return image_base64

            logger.warning("[WX849] 未能生成有效的封面图片")
            return None
        except Exception as e:
            logger.error(f"[WX849] 提取视频帧失败: {e}")
            logger.error(traceback.format_exc())
            return None

    async def _send_video(self, to_user_id, video_base64, cover_base64=None, video_duration=10):
        """发送视频消息"""
        try:
            # 检查参数
            if not to_user_id:
                logger.error("[WX849] 发送视频失败: 接收者ID为空")
                return None

            if not video_base64:
                logger.error("[WX849] 发送视频失败: 视频数据为空")
                return None

            # 设置默认封面
            if not cover_base64 or cover_base64 == "None":
                try:
                    # 使用1x1像素的透明PNG作为最小封面
                    cover_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    logger.debug("[WX849] 使用内置1x1像素作为默认封面")
                except Exception as e:
                    logger.error(f"[WX849] 准备默认封面图片失败: {e}")
                    # 使用1x1像素的透明PNG作为最小封面
                    cover_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
                    logger.debug("[WX849] 使用内置1x1像素作为默认封面")

            # 打印预估时间
            try:
                # 计算视频base64长度
                base64_content = video_base64
                if base64_content.startswith("data:video/mp4;base64,"):
                    base64_content = base64_content[len("data:video/mp4;base64,"):]

                # 计算文件大小 (KB)
                file_len = len(base64.b64decode(base64_content)) / 1024

                # 预估时间 (秒)，按300KB/s计算
                predict_time = int(file_len / 300)
                logger.info(f"[WX849] 开始发送视频: 预计{predict_time}秒, 视频大小:{file_len:.2f}KB, 时长:{video_duration}秒")
            except Exception as e:
                logger.debug(f"[WX849] 计算预估时间失败: {e}")

            # 处理视频和封面的base64数据
            pure_video_base64 = video_base64
            if pure_video_base64.startswith("data:video/mp4;base64,"):
                pure_video_base64 = pure_video_base64[len("data:video/mp4;base64,"):]

            pure_cover_base64 = cover_base64
            if pure_cover_base64 and pure_cover_base64 != "None" and pure_cover_base64.startswith("data:image/jpeg;base64,"):
                pure_cover_base64 = pure_cover_base64[len("data:image/jpeg;base64,"):]

            # 记录API调用参数
            logger.debug(f"[WX849] 发送视频至接收者: {to_user_id}, 视频base64长度: {len(pure_video_base64)}, 封面base64长度: {len(pure_cover_base64)}")

            # 直接使用API发送视频（绕过bot.send_video_message方法，避免参数不兼容问题）
            # 确保base64前缀正确
            video_data = "data:video/mp4;base64," + pure_video_base64
            cover_data = "data:image/jpeg;base64," + pure_cover_base64

            # 构建API参数 - 根据API文档确保参数名称和格式正确
            params = {
                "Wxid": self.wxid,
                "ToWxid": to_user_id,
                "Base64": video_data,
                "ImageBase64": cover_data,
                "PlayLength": video_duration  # 这是必需的参数，缺少会导致[Key:]数据不存在错误
            }

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)

            # 确定API路径前缀
            protocol_version = conf().get("wx849_protocol_version", "849")
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建完整API URL
            url = f"http://{api_host}:{api_port}{api_path_prefix}/Msg/SendVideo"

            logger.debug(f"[WX849] 直接调用SendVideo API: {url}")

            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as response:
                    json_resp = await response.json()

                    # 检查响应
                    if json_resp and json_resp.get("Success", False):
                        data = json_resp.get("Data", {})
                        client_msg_id = data.get("clientMsgId")
                        new_msg_id = data.get("newMsgId")

                        logger.info(f"[WX849] 视频发送成功，返回ID: {client_msg_id}, {new_msg_id}")
                        return {"Success": True, "client_msg_id": client_msg_id, "new_msg_id": new_msg_id}
                    else:
                        error_msg = json_resp.get("Message", "未知错误")
                        logger.error(f"[WX849] 视频API返回错误: {error_msg}")
                        logger.error(f"[WX849] 响应详情: {json.dumps(json_resp, ensure_ascii=False)}")
                        return None

        except Exception as e:
            logger.error(f"[WX849] 发送视频失败: {e}")
            logger.error(traceback.format_exc())
            return None

    def _send_api_request(self, url, data):
        """同步发送API请求"""
        try:
            # 设置请求头
            headers = {
                'Content-Type': 'application/json'
            }

            # 发送请求
            response = requests.post(url, json=data, headers=headers, timeout=10)

            # 检查响应状态码
            if response.status_code != 200:
                logger.error(f"[WX849] API请求失败: {url}, 状态码: {response.status_code}")
                return None

            # 解析响应
            result = response.json()
            return result
        except Exception as e:
            logger.error(f"[WX849] API请求失败: {url}, 错误: {e}")
            return None

    def _get_nickname_from_wxid(self, wxid):
        """从wxid获取昵称"""
        try:
            # 检查是否是群ID
            if wxid.endswith("@chatroom"):
                # 尝试从群聊缓存中获取群名称
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)

                        if wxid in chatrooms_info and "nickName" in chatrooms_info[wxid]:
                            return chatrooms_info[wxid]["nickName"]
                    except Exception as e:
                        logger.debug(f"[WX849] 从缓存获取群名称失败: {e}")

                # 如果没有找到，返回默认值
                return "群聊"

            # 检查是否是个人ID
            # 首先尝试从群成员列表中获取昵称
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)

                    # 遍历所有群聊
                    for group_id, group_info in chatrooms_info.items():
                        if "members" in group_info:
                            # 遍历群成员
                            for member in group_info["members"]:
                                if member.get("UserName") == wxid:
                                    # 优先使用群内显示名称(群昵称)
                                    if member.get("DisplayName"):
                                        logger.debug(f"[WX849] 从群成员列表获取到用户 {wxid} 的群昵称: {member.get('DisplayName')}")
                                        return member.get("DisplayName")
                                    # 次选使用个人昵称
                                    elif member.get("NickName"):
                                        logger.debug(f"[WX849] 从群成员列表获取到用户 {wxid} 的昵称: {member.get('NickName')}")
                                        return member.get("NickName")
                except Exception as e:
                    logger.debug(f"[WX849] 从群成员列表获取昵称失败: {e}")

            # 如果在群成员列表中没有找到，尝试从联系人缓存中获取昵称
            contacts_file = os.path.join(tmp_dir, 'wx849_contacts.json')

            if os.path.exists(contacts_file):
                try:
                    with open(contacts_file, 'r', encoding='utf-8') as f:
                        contacts_info = json.load(f)

                    for contact in contacts_info:
                        if contact.get("wxid") == wxid and contact.get("nickname"):
                            logger.debug(f"[WX849] 从联系人列表获取到用户 {wxid} 的昵称: {contact.get('nickname')}")
                            return contact.get("nickname")
                except Exception as e:
                    logger.debug(f"[WX849] 从缓存获取联系人昵称失败: {e}")

            # 如果是机器人自己的wxid，返回机器人昵称
            if wxid == self.wxid and hasattr(self, "name") and self.name:
                return self.name

            # 如果没有找到，尝试使用上下文中的昵称
            if hasattr(self, "context_nicknames") and wxid in self.context_nicknames:
                return self.context_nicknames[wxid]

            # 如果都没有找到，返回"用户"作为默认值
            return "用户"

        except Exception as e:
            logger.error(f"[WX849] 获取昵称失败: {e}")
            return "用户"

    async def _send_api_request(self, endpoint, params):
        """异步发送API请求"""
        try:
            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建完整的API URL
            url = f"http://{api_host}:{api_port}{api_path_prefix}{endpoint}"
            logger.debug(f"[WX849] 发送API请求: {url}")
            logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 发送POST请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.debug(f"[WX849] API响应: {json.dumps(result, ensure_ascii=False)}")
                        return result
                    else:
                        logger.error(f"[WX849] API请求失败: {url}, 状态码: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"[WX849] API请求失败: {endpoint}, 错误: {e}")
            return None

    async def _get_group_members(self, group_id):
        """获取群成员列表"""
        try:
            # 调用API获取群成员详情
            params = {
                "QID": group_id,  # 群ID参数
                "Wxid": self.wxid  # 自己的wxid参数
            }

            # 发送API请求
            result = await self._send_api_request("/Group/GetChatRoomMemberDetail", params)

            if not result or not isinstance(result, dict):
                logger.error(f"[WX849] 获取群成员列表失败: 无效响应")
                return None

            # 检查响应是否成功
            if not result.get("Success", False):
                logger.error(f"[WX849] 获取群成员列表失败: {result.get('Message', '未知错误')}")
                return None

            # 提取成员信息
            data = result.get("Data", {})
            new_chatroom_data = data.get("NewChatroomData", {})

            if not new_chatroom_data:
                logger.error(f"[WX849] 获取群成员列表失败: 响应中无NewChatroomData")
                return None

            # 提取成员列表
            member_count = new_chatroom_data.get("MemberCount", 0)
            chat_room_members = new_chatroom_data.get("ChatRoomMember", [])

            # 确保是有效的成员列表
            if not isinstance(chat_room_members, list):
                logger.error(f"[WX849] 获取群成员列表失败: 成员列表格式无效")
                return None

            # 处理成员信息
            members = []
            for member in chat_room_members:
                if isinstance(member, dict):
                    # 直接获取字符串值，不假设是嵌套字典
                    wxid = member.get("UserName", "")
                    nickname = member.get("NickName", "")
                    display_name = member.get("DisplayName", "")

                    # 使用显示名称（群昵称）如果有，否则使用昵称
                    name = display_name if display_name else nickname

                    if wxid:
                        members.append({
                            "wxid": wxid,
                            "nickname": name
                        })

            logger.debug(f"[WX849] 成功获取群 {group_id} 的成员列表，共 {len(members)} 人")
            return members

        except Exception as e:
            logger.error(f"[WX849] 获取群成员列表失败: {e}")
            return None

    async def _get_group_member_details(self, group_id):
        """获取群成员详情"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的成员详情")

            # 检查是否已存在群成员信息，并检查是否需要更新
            # 定义群聊信息文件路径
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            # 读取现有的群聊信息（如果存在）
            chatrooms_info = {}
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                    logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                except Exception as e:
                    logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

            # 检查该群聊是否已存在且成员信息是否已更新
            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())

            if (group_id in chatrooms_info and
                "members" in chatrooms_info[group_id] and
                len(chatrooms_info[group_id]["members"]) > 0 and
                "last_update" in chatrooms_info[group_id] and
                current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):
                logger.debug(f"[WX849] 群 {group_id} 成员信息已存在且未过期，跳过更新")
                return chatrooms_info[group_id]

            logger.debug(f"[WX849] 群 {group_id} 成员信息不存在或已过期，开始更新")

            # 调用API获取群成员详情
            params = {
                "QID": group_id,  # 群ID参数
                "Wxid": self.wxid  # 自己的wxid参数
            }

            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomMemberDetail"
                logger.debug(f"[WX849] 正在请求群成员详情API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

                # 使用新的_get_group_members方法获取群成员
                members_data = await self._get_group_members(group_id)

                if not members_data:
                    logger.error(f"[WX849] 获取群成员详情失败: 无法获取成员列表")
                    return None

                # 构建新的chatroom_data结构
                new_chatroom_data = {
                    "ChatRoomName": group_id,
                    "MemberCount": len(members_data),
                    "ChatRoomMember": members_data
                }

                # 检查当前群聊是否已存在
                if group_id not in chatrooms_info:
                    chatrooms_info[group_id] = {
                        "chatroomId": group_id,
                        "nickName": group_id,
                        "chatRoomOwner": "",
                        "members": [],
                        "last_update": int(time.time())
                    }

                # 提取成员信息
                member_count = new_chatroom_data.get("MemberCount", 0)
                chat_room_members = new_chatroom_data.get("ChatRoomMember", [])

                # 确保是有效的成员列表
                if not isinstance(chat_room_members, list):
                    logger.error(f"[WX849] 获取群成员详情失败: ChatRoomMember不是有效的列表")
                    return None

                # 更新群聊成员信息
                members = []
                for member in chat_room_members:
                    if not isinstance(member, dict):
                        continue

                    # 提取成员必要信息，直接使用原始成员信息
                    members.append(member)

                # 更新群聊信息
                chatrooms_info[group_id]["members"] = members
                chatrooms_info[group_id]["last_update"] = int(time.time())
                chatrooms_info[group_id]["memberCount"] = member_count

                # 同时更新群主信息
                for member in members:
                    if member.get("ChatroomMemberFlag") == 2049:  # 群主标志
                        chatrooms_info[group_id]["chatRoomOwner"] = member.get("UserName", "")
                        break

                # 保存到文件
                with open(chatrooms_file, 'w', encoding='utf-8') as f:
                    json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

                logger.info(f"[WX849] 已更新群聊 {group_id} 成员信息，成员数: {len(members)}")

                # 返回成员信息
                return new_chatroom_data
            except Exception as e:
                logger.error(f"[WX849] 获取群成员详情失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                return None
        except Exception as e:
            logger.error(f"[WX849] 获取群成员详情过程中出错: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_group_details_by_contract_detail(self, group_id):
        """使用GetContractDetail API获取群组详细信息"""
        if not group_id or not group_id.endswith("@chatroom"):
            return None

        try:
            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建API请求参数
            params = {
                "Wxid": self.wxid,
                "Towxids": group_id,
                "ChatRoom": ""
            }

            # 构建完整的API URL用于日志
            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Friend/GetContractDetail"
            logger.debug(f"[WX849] 正在请求群组详情API: {api_url}")
            logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 调用API获取群组详情
            response = await self._call_api("/Friend/GetContractDetail", params)

            if not response or not isinstance(response, dict):
                logger.error(f"[WX849] 获取群组详情失败: 无效响应")
                return None

            # 检查响应是否成功
            if not response.get("Success", False):
                logger.error(f"[WX849] 获取群组详情失败: {response.get('Message', '未知错误')}")
                return None

            # 提取群组详情
            data = response.get("Data", {})
            if not data:
                logger.error(f"[WX849] 获取群组详情失败: 响应中无Data")
                return None

            # 提取群组信息
            group_details = {}

            # 递归函数用于查找特定key的值
            def find_value(obj, key):
                # 如果是字典
                if isinstance(obj, dict):
                    # 直接检查当前字典
                    if key in obj:
                        return obj[key]
                    # 检查带有"string"嵌套的字典
                    if key in obj and isinstance(obj[key], dict) and "string" in obj[key]:
                        return obj[key]["string"]
                    # 递归检查字典的所有值
                    for k, v in obj.items():
                        result = find_value(v, key)
                        if result is not None:
                            return result
                # 如果是列表
                elif isinstance(obj, list):
                    # 递归检查列表的所有项
                    for item in obj:
                        result = find_value(item, key)
                        if result is not None:
                            return result
                return None

            # 尝试提取群名称
            nickname = find_value(data, "NickName")
            if nickname:
                if isinstance(nickname, dict) and "string" in nickname:
                    group_details["nickName"] = nickname["string"]
                elif isinstance(nickname, str):
                    group_details["nickName"] = nickname

            # 如果没找到，尝试其他可能的字段
            if "nickName" not in group_details:
                for name_key in ["nickname", "name", "DisplayName", "ChatRoomName"]:
                    name_value = find_value(data, name_key)
                    if name_value:
                        if isinstance(name_value, dict) and "string" in name_value:
                            group_details["nickName"] = name_value["string"]
                        elif isinstance(name_value, str):
                            group_details["nickName"] = name_value
                        if "nickName" in group_details:
                            break

            # 如果找到了群名称，返回群组详情
            if "nickName" in group_details:
                logger.debug(f"[WX849] 获取到群组 {group_id} 名称: {group_details['nickName']}")
                return group_details

            # 如果没有找到群名称，返回None
            logger.debug(f"[WX849] 未找到群组 {group_id} 的名称信息")
            return None
        except Exception as e:
            logger.error(f"[WX849] 获取群组详情失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_group_name(self, group_id):
        """获取群名称"""
        try:
            logger.debug(f"[WX849] 尝试获取群 {group_id} 的名称")

            # 检查缓存中是否有群名
            cache_key = f"group_name_{group_id}"
            if hasattr(self, "group_name_cache") and cache_key in self.group_name_cache:
                cached_name = self.group_name_cache[cache_key]
                logger.debug(f"[WX849] 从缓存中获取群名: {cached_name}")

                # 检查是否需要更新群成员详情
                tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

                need_update = True
                # 设定缓存有效期为24小时(86400秒)
                cache_expiry = 86400
                current_time = int(time.time())

                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)

                        # 检查群信息是否存在且未过期
                        if (group_id in chatrooms_info and
                            "last_update" in chatrooms_info[group_id] and
                            current_time - chatrooms_info[group_id]["last_update"] < cache_expiry and
                            "members" in chatrooms_info[group_id] and
                            len(chatrooms_info[group_id]["members"]) > 0):
                            logger.debug(f"[WX849] 群 {group_id} 信息已存在且未过期，跳过更新")
                            need_update = False
                    except Exception as e:
                        logger.error(f"[WX849] 检查群信息缓存时出错: {e}")

                # 只有需要更新时才启动线程获取群成员详情
                if need_update:
                    logger.debug(f"[WX849] 群 {group_id} 信息需要更新，启动更新线程")
                    threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                return cached_name

            # 检查文件中是否已经有群信息，且未过期
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            # 设定缓存有效期为24小时(86400秒)
            cache_expiry = 86400
            current_time = int(time.time())

            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)

                    # 检查群信息是否存在且未过期
                    if (group_id in chatrooms_info and
                        "nickName" in chatrooms_info[group_id] and
                        chatrooms_info[group_id]["nickName"] and
                        chatrooms_info[group_id]["nickName"] != group_id and
                        "last_update" in chatrooms_info[group_id] and
                        current_time - chatrooms_info[group_id]["last_update"] < cache_expiry):

                        # 从文件中获取群名
                        group_name = chatrooms_info[group_id]["nickName"]
                        logger.debug(f"[WX849] 从文件缓存中获取群名: {group_name}")

                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name

                        # 检查是否需要更新群成员详情
                        need_update_members = not ("members" in chatrooms_info[group_id] and
                                                len(chatrooms_info[group_id]["members"]) > 0)

                        if need_update_members:
                            logger.debug(f"[WX849] 群 {group_id} 名称已缓存，但需要更新成员信息")
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()
                        else:
                            logger.debug(f"[WX849] 群 {group_id} 信息已完整且未过期，无需更新")

                        return group_name
                except Exception as e:
                    logger.error(f"[WX849] 从文件获取群名出错: {e}")

            logger.debug(f"[WX849] 群 {group_id} 信息不存在或已过期，需要从API获取")

            # 首先尝试使用GetContractDetail API获取群组信息
            group_details = await self._get_group_details_by_contract_detail(group_id)
            if group_details and "nickName" in group_details:
                group_name = group_details["nickName"]

                # 保存到缓存
                if not os.path.exists(tmp_dir):
                    os.makedirs(tmp_dir)

                chatrooms_info = {}
                if os.path.exists(chatrooms_file):
                    try:
                        with open(chatrooms_file, 'r', encoding='utf-8') as f:
                            chatrooms_info = json.load(f)
                    except Exception as e:
                        logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

                if group_id not in chatrooms_info:
                    chatrooms_info[group_id] = {}

                chatrooms_info[group_id]["nickName"] = group_name
                chatrooms_info[group_id]["last_update"] = int(time.time())

                with open(chatrooms_file, 'w', encoding='utf-8') as f:
                    json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

                # 缓存群名
                if not hasattr(self, "group_name_cache"):
                    self.group_name_cache = {}
                self.group_name_cache[cache_key] = group_name

                logger.debug(f"[WX849] 已更新群组 {group_id} 名称: {group_name}")

                # 异步获取群成员详情
                threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                return group_name

            # 调用API获取群信息 - 使用群聊API
            params = {
                "QID": group_id,  # 群ID参数，正确的参数名是QID
                "Wxid": self.wxid  # 自己的wxid参数
            }

            try:
                # 获取API配置
                api_host = conf().get("wx849_api_host", "127.0.0.1")
                api_port = conf().get("wx849_api_port", 9011)
                protocol_version = conf().get("wx849_protocol_version", "849")

                # 确定API路径前缀
                if protocol_version == "855" or protocol_version == "ipad":
                    api_path_prefix = "/api"
                else:
                    api_path_prefix = "/VXAPI"

                # 构建完整的API URL用于日志
                api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomInfo"
                logger.debug(f"[WX849] 正在请求群信息API: {api_url}")
                logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")  # 记录请求参数

                # 尝试使用群聊专用API
                group_info = await self._call_api("/Group/GetChatRoomInfo", params)

                # 保存群聊详情到统一的JSON文件
                try:
                    # 读取现有的群聊信息（如果存在）
                    chatrooms_info = {}
                    if os.path.exists(chatrooms_file):
                        try:
                            with open(chatrooms_file, 'r', encoding='utf-8') as f:
                                chatrooms_info = json.load(f)
                            logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                        except Exception as e:
                            logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

                    # 提取必要的群聊信息
                    if group_info and isinstance(group_info, dict):
                        # 递归函数用于查找特定key的值
                        def find_value(obj, key):
                            # 如果是字典
                            if isinstance(obj, dict):
                                # 直接检查当前字典
                                if key in obj:
                                    return obj[key]
                                # 检查带有"string"嵌套的字典
                                if key in obj and isinstance(obj[key], dict) and "string" in obj[key]:
                                    return obj[key]["string"]
                                # 递归检查字典的所有值
                                for k, v in obj.items():
                                    result = find_value(v, key)
                                    if result is not None:
                                        return result
                            # 如果是列表
                            elif isinstance(obj, list):
                                # 递归检查列表的所有项
                                for item in obj:
                                    result = find_value(item, key)
                                    if result is not None:
                                        return result
                            return None

                        # 尝试提取群名称及其他信息
                        group_name = None

                        # 首先尝试从NickName中获取
                        nickname_obj = find_value(group_info, "NickName")
                        if isinstance(nickname_obj, dict) and "string" in nickname_obj:
                            group_name = nickname_obj["string"]
                        elif isinstance(nickname_obj, str):
                            group_name = nickname_obj

                        # 如果没找到，尝试其他可能的字段
                        if not group_name:
                            for name_key in ["ChatRoomName", "nickname", "name", "DisplayName"]:
                                name_value = find_value(group_info, name_key)
                                if name_value:
                                    if isinstance(name_value, dict) and "string" in name_value:
                                        group_name = name_value["string"]
                                    elif isinstance(name_value, str):
                                        group_name = name_value
                                    if group_name:
                                        break

                        # 提取群主ID
                        owner_id = None
                        for owner_key in ["ChatRoomOwner", "chatroomowner", "Owner"]:
                            owner_value = find_value(group_info, owner_key)
                            if owner_value:
                                if isinstance(owner_value, dict) and "string" in owner_value:
                                    owner_id = owner_value["string"]
                                elif isinstance(owner_value, str):
                                    owner_id = owner_value
                                if owner_id:
                                    break

                        # 检查群聊信息是否已存在
                        if group_id in chatrooms_info:
                            # 更新已有群聊信息
                            if group_name:
                                chatrooms_info[group_id]["nickName"] = group_name
                            if owner_id:
                                chatrooms_info[group_id]["chatRoomOwner"] = owner_id
                            chatrooms_info[group_id]["last_update"] = int(time.time())
                        else:
                            # 创建新群聊信息
                            chatrooms_info[group_id] = {
                                "chatroomId": group_id,
                                "nickName": group_name or group_id,
                                "chatRoomOwner": owner_id or "",
                                "members": [],
                                "last_update": int(time.time())
                            }

                        # 保存到文件
                        with open(chatrooms_file, 'w', encoding='utf-8') as f:
                            json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

                        logger.info(f"[WX849] 已更新群聊 {group_id} 基础信息")

                        # 缓存群名
                        if group_name:
                            if not hasattr(self, "group_name_cache"):
                                self.group_name_cache = {}
                            self.group_name_cache[cache_key] = group_name

                            # 异步获取群成员详情（不阻塞当前方法）
                            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                            return group_name

                except Exception as save_err:
                    logger.error(f"[WX849] 保存群聊信息到文件失败: {save_err}")
                    import traceback
                    logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")

                # 如果上面的处理没有返回群名称，再次尝试从原始数据中提取
                if group_info and isinstance(group_info, dict):
                    # 尝试从API返回中获取群名称
                    group_name = None

                    # 尝试多种可能的字段名
                    possible_fields = ["NickName", "nickname", "ChatRoomName", "chatroomname", "DisplayName", "displayname"]
                    for field in possible_fields:
                        if field in group_info and group_info[field]:
                            group_name = group_info[field]
                            if isinstance(group_name, dict) and "string" in group_name:
                                group_name = group_name["string"]
                            break

                    if group_name:
                        logger.debug(f"[WX849] 获取到群名称: {group_name}")

                        # 缓存群名
                        if not hasattr(self, "group_name_cache"):
                            self.group_name_cache = {}
                        self.group_name_cache[cache_key] = group_name

                        # 异步获取群成员详情
                        threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

                        return group_name
                    else:
                        logger.warning(f"[WX849] API返回成功但未找到群名称字段: {json.dumps(group_info, ensure_ascii=False)}")
                else:
                    logger.warning(f"[WX849] API返回无效数据: {group_info}")
            except Exception as e:
                # 详细记录API请求失败的错误信息
                logger.error(f"[WX849] 使用群聊API获取群名称失败: {e}")
                logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
                logger.error(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 如果无法获取群名，使用群ID作为名称
            logger.debug(f"[WX849] 无法获取群名称，使用群ID代替: {group_id}")
            # 缓存结果
            if not hasattr(self, "group_name_cache"):
                self.group_name_cache = {}
            self.group_name_cache[cache_key] = group_id

            # 尽管获取群名失败，仍然尝试获取群成员详情
            threading.Thread(target=lambda: asyncio.run(self._get_group_member_details(group_id))).start()

            return group_id
        except Exception as e:
            logger.error(f"[WX849] 获取群名称失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return group_id

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        """重写父类方法，构建消息上下文，与gewechat保持一致"""
        try:
            # 导入 WX849Message 类
            from channel.wx849.wx849_message import WX849Message

            # 直接创建Context对象，确保结构正确
            context = Context()
            context.type = ctype
            context.content = content

            # 获取消息对象
            msg = kwargs.get('msg')
            if not msg:
                logger.error("[WX849] 构建上下文失败: 缺少消息对象")
                return None

            # 创建消息对象的深拷贝，避免共享引用
            if hasattr(msg, '__dict__') and isinstance(msg, WX849Message):
                # 对于 WX849Message 对象，我们需要特殊处理
                # 首先创建一个新的 WX849Message 对象，使用原始的 msg.msg 和 is_group
                msg_copy = WX849Message(msg.msg, msg.is_group)

                # 然后复制所有其他属性
                for attr_name, attr_value in msg.__dict__.items():
                    if not attr_name.startswith('_') and attr_name not in ['msg', 'is_group']:
                        # 对于复杂对象，创建深拷贝
                        if isinstance(attr_value, dict):
                            setattr(msg_copy, attr_name, attr_value.copy())
                        elif isinstance(attr_value, list):
                            setattr(msg_copy, attr_name, attr_value.copy())
                        else:
                            setattr(msg_copy, attr_name, attr_value)

                # 使用复制的消息对象
                msg = msg_copy

            # 检查是否是群聊消息
            isgroup = kwargs.get('isgroup', False)
            if isgroup and hasattr(msg, 'from_user_id'):
                # 设置群组相关信息
                context["isgroup"] = True

                # 使用或提取实际发送者信息
                if hasattr(msg, 'actual_user_nickname') and msg.actual_user_nickname and not msg.actual_user_nickname.startswith("未知用户_"):
                    # 有效的发送者昵称
                    sender_nickname = msg.actual_user_nickname
                    sender_id = getattr(msg, 'actual_user_id', getattr(msg, 'sender_wxid', "unknown_user"))
                elif hasattr(msg, 'sender_nickname') and msg.sender_nickname:
                    # 备选：使用sender_nickname
                    sender_nickname = msg.sender_nickname
                    sender_id = getattr(msg, 'sender_wxid', "unknown_user")
                elif hasattr(msg, 'sender_wxid') and msg.sender_wxid and not msg.sender_wxid.startswith("未知用户_"):
                    # 备选：使用sender_wxid
                    sender_id = msg.sender_wxid
                    sender_nickname = msg.sender_wxid  # 默认使用ID作为昵称
                else:
                    # 无法获取有效发送者信息时
                    sender_id = "unknown_user"
                    sender_nickname = "未知用户"

                context["from_user_nickname"] = sender_nickname
                context["from_user_id"] = sender_id
                context["to_user_id"] = getattr(msg, 'to_user_id', self.wxid)
                context["other_user_id"] = msg.from_user_id  # 群ID

                # 使用other_user_nickname作为群名称，与gewechat保持一致
                if hasattr(msg, 'other_user_nickname') and msg.other_user_nickname:
                    context["group_name"] = msg.other_user_nickname
                else:
                    context["group_name"] = msg.from_user_id  # 临时使用群ID作为群名

                context["group_id"] = msg.from_user_id  # 群ID
                context["msg"] = msg  # 消息对象

                # 设置is_at标志，与gewechat保持一致
                if hasattr(msg, 'is_at'):
                    context["is_at"] = msg.is_at
                    if msg.is_at:
                        logger.debug(f"[WX849] 从msg.is_at标志检测到@机器人")
                elif hasattr(msg, 'at_list') and self.wxid in msg.at_list:
                    context["is_at"] = True
                    logger.debug(f"[WX849] 从at_list中检测到@机器人: {self.wxid}")
                # 检查是否有IsAtMessage标志
                elif hasattr(msg, 'msg') and "IsAtMessage" in msg.msg and msg.msg["IsAtMessage"]:
                    context["is_at"] = True
                    logger.debug(f"[WX849] 从IsAtMessage标志检测到@机器人")
                # 检查消息内容中是否包含@机器人的文本
                elif ctype == ContextType.XML and content and (f"@{self.name}" in content or (hasattr(msg, 'self_display_name') and msg.self_display_name and f"@{msg.self_display_name}" in content)):
                    context["is_at"] = True
                    logger.debug(f"[WX849] 从XML消息内容中检测到@机器人: {content}")
                else:
                    context["is_at"] = False

                # 记录at_list到上下文
                if hasattr(msg, 'at_list') and msg.at_list:
                    # 创建at_list的副本，避免共享引用
                    context["at_list"] = list(msg.at_list)
                    logger.debug(f"[WX849] 设置at_list到上下文: {context.get('at_list', [])}")

                # 添加引用消息信息到上下文
                if hasattr(msg, 'msg') and "QuotedMessage" in msg.msg:
                    quoted_message = msg.msg["QuotedMessage"]
                    context["quoted_message"] = quoted_message

                    # 记录引用消息的关键信息
                    if "Content" in quoted_message:
                        context["quoted_content"] = quoted_message["Content"]
                        logger.debug(f"[WX849] 设置quoted_content到上下文: {quoted_message['Content']}")

                    if "Nickname" in quoted_message:
                        context["quoted_nickname"] = quoted_message["Nickname"]
                        logger.debug(f"[WX849] 设置quoted_nickname到上下文: {quoted_message['Nickname']}")

                    # 如果引用的是图片消息，尝试下载图片
                    if quoted_message.get("MsgType") == 3:
                        logger.debug(f"[WX849] 检测到引用图片消息")

                        # 检查是否有图片URL或其他信息
                        if "cdnmidimgurl" in quoted_message:
                            image_url = quoted_message["cdnmidimgurl"]
                            logger.debug(f"[WX849] 引用图片URL: {image_url}")
                            context["quoted_image_url"] = image_url

                        # 如果有图片的md5和aeskey，也记录下来
                        if "md5" in quoted_message:
                            context["quoted_image_md5"] = quoted_message["md5"]
                            logger.debug(f"[WX849] 引用图片MD5: {quoted_message['md5']}")

                        if "aeskey" in quoted_message:
                            context["quoted_image_aeskey"] = quoted_message["aeskey"]
                            logger.debug(f"[WX849] 引用图片AESKey: {quoted_message['aeskey']}")

                # 设置session_id为群ID
                context["session_id"] = msg.from_user_id

                # 启动异步任务获取群名称并更新
                try:
                    # 使用已有事件循环运行更新任务
                    def run_async_task():
                        try:
                            # 创建新的事件循环
                            task_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(task_loop)
                            # 执行异步任务
                            task_loop.run_until_complete(self._update_group_nickname_async(msg))
                            # 关闭事件循环
                            task_loop.close()
                        except Exception as e:
                            logger.error(f"[WX849] 异步获取群名称任务失败: {e}")

                    # 启动线程执行异步任务
                    threading.Thread(target=run_async_task).start()
                except Exception as e:
                    logger.error(f"[WX849] 创建获取群名称任务失败: {e}")
            else:
                # 私聊消息
                context["isgroup"] = False

                # 使用可用的发送者昵称
                if hasattr(msg, 'sender_nickname') and msg.sender_nickname:
                    context["from_user_nickname"] = msg.sender_nickname
                else:
                    context["from_user_nickname"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""

                context["from_user_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""
                context["to_user_id"] = msg.to_user_id if msg and hasattr(msg, 'to_user_id') else ""

                # 使用other_user_id和other_user_nickname，与gewechat保持一致
                if hasattr(msg, 'other_user_id') and msg.other_user_id:
                    context["other_user_id"] = msg.other_user_id
                else:
                    context["other_user_id"] = msg.from_user_id

                # 使用other_user_nickname作为联系人昵称，与gewechat保持一致
                if hasattr(msg, 'other_user_nickname') and msg.other_user_nickname:
                    context["other_user_nickname"] = msg.other_user_nickname
                else:
                    context["other_user_nickname"] = context["from_user_nickname"]

                context["msg"] = msg

                # 设置session_id为发送者ID
                context["session_id"] = msg.sender_wxid if msg and hasattr(msg, 'sender_wxid') else ""

                # 清除可能从其他消息继承的群聊相关字段
                keys_to_delete = []
                for key in context.kwargs:
                    if 'group' in key.lower() or 'at' in key.lower() or 'trigger_prefix' in key.lower():
                        keys_to_delete.append(key)
                for key in keys_to_delete:
                    if key in context.kwargs:
                        del context.kwargs[key]

                # 启动异步任务获取联系人昵称并更新
                try:
                    # 使用已有事件循环运行更新任务
                    def run_async_task():
                        try:
                            # 创建新的事件循环
                            task_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(task_loop)
                            # 执行异步任务
                            task_loop.run_until_complete(self._update_contact_nickname_async(msg))
                            # 关闭事件循环
                            task_loop.close()
                        except Exception as e:
                            logger.error(f"[WX849] 异步获取联系人昵称任务失败: {e}")

                    # 启动线程执行异步任务
                    threading.Thread(target=run_async_task).start()
                except Exception as e:
                    logger.error(f"[WX849] 创建获取联系人昵称任务失败: {e}")

            # 添加接收者信息
            if isgroup:
                # 如果是群聊，接收者应该是群ID
                context["receiver"] = msg.from_user_id
            else:
                # 如果是私聊，接收者应该是发送者ID
                # 确保使用正确的发送者ID，避免使用群ID
                if hasattr(msg, 'sender_wxid') and msg.sender_wxid and not msg.sender_wxid.endswith("@chatroom"):
                    context["receiver"] = msg.sender_wxid
                elif hasattr(msg, 'from_user_id') and msg.from_user_id and not msg.from_user_id.endswith("@chatroom"):
                    context["receiver"] = msg.from_user_id
                else:
                    # 如果无法确定正确的接收者，使用other_user_id
                    context["receiver"] = msg.other_user_id

            # 记录原始消息类型
            context["origin_ctype"] = ctype

            # 添加调试日志
            logger.debug(f"[WX849] 生成Context对象: type={context.type}, content={context.content}, isgroup={context.get('isgroup', False)}, session_id={context.get('session_id', 'None')}")
            if isgroup:
                logger.debug(f"[WX849] 群聊消息详情: group_id={context.get('group_id')}, group_name={context.get('group_name')}, from_user_id={context.get('from_user_id')}")
            else:
                logger.debug(f"[WX849] 私聊消息详情: other_user_id={context.get('other_user_id')}, other_user_nickname={context.get('other_user_nickname')}")

            return context
        except Exception as e:
            logger.error(f"[WX849] 构建上下文失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return None

    async def _get_chatroom_member_nickname(self, group_id, member_wxid):
        """获取群成员的昵称"""
        if not group_id or not member_wxid:
            return member_wxid

        try:
            # 优先从缓存获取群成员信息
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            if os.path.exists(chatrooms_file):
                with open(chatrooms_file, 'r', encoding='utf-8') as f:
                    chatrooms_info = json.load(f)

                if group_id in chatrooms_info and "members" in chatrooms_info[group_id]:
                    for member in chatrooms_info[group_id]["members"]:
                        if member.get("UserName") == member_wxid:
                            # 优先使用群内显示名称(群昵称)
                            if member.get("DisplayName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                                return member.get("DisplayName")
                            # 次选使用个人昵称
                            elif member.get("NickName"):
                                logger.debug(f"[WX849] 获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                                return member.get("NickName")
                            else:
                                return member_wxid

            # 如果缓存中没有，尝试立即获取群成员信息
            logger.debug(f"[WX849] 未找到成员 {member_wxid} 的昵称信息，尝试立即获取")

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 构建API请求参数
            params = {
                "QID": group_id,
                "Wxid": self.wxid
            }

            # 构建完整的API URL用于日志
            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Group/GetChatRoomMemberDetail"
            logger.debug(f"[WX849] 正在请求群成员详情API: {api_url}")
            logger.debug(f"[WX849] 请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 调用API获取群成员详情
            response = await self._call_api("/Group/GetChatRoomMemberDetail", params)

            if not response or not isinstance(response, dict):
                logger.error(f"[WX849] 获取群成员详情失败: 无效响应")
                return member_wxid

            # 检查响应是否成功
            if not response.get("Success", False):
                logger.error(f"[WX849] 获取群成员详情失败: {response.get('Message', '未知错误')}")
                return member_wxid

            # 提取群成员详情
            data = response.get("Data", {})
            if not data:
                logger.error(f"[WX849] 获取群成员详情失败: 响应中无Data")
                return member_wxid

            # 提取NewChatroomData
            new_chatroom_data = data.get("NewChatroomData", {})
            if not new_chatroom_data:
                logger.error(f"[WX849] 获取群成员列表失败: 响应中无NewChatroomData")
                return member_wxid

            # 提取成员列表
            chat_room_members = new_chatroom_data.get("ChatRoomMember", [])

            # 确保是有效的成员列表
            if not isinstance(chat_room_members, list):
                logger.error(f"[WX849] 获取群成员详情失败: ChatRoomMember不是有效的列表")
                return member_wxid

            # 更新群聊成员信息
            members = []
            for member in chat_room_members:
                if not isinstance(member, dict):
                    continue

                # 提取成员必要信息，直接使用原始成员信息
                members.append(member)

                # 检查是否是要查找的成员
                if member.get("UserName") == member_wxid:
                    # 优先使用群内显示名称(群昵称)
                    if member.get("DisplayName"):
                        logger.debug(f"[WX849] 获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                        nickname = member.get("DisplayName")
                    # 次选使用个人昵称
                    elif member.get("NickName"):
                        logger.debug(f"[WX849] 获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                        nickname = member.get("NickName")
                    else:
                        nickname = member_wxid

            # 更新群聊信息
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                except Exception as e:
                    logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")
                    chatrooms_info = {}
            else:
                chatrooms_info = {}

            if group_id not in chatrooms_info:
                chatrooms_info[group_id] = {
                    "chatroomId": group_id,
                    "nickName": group_id,
                    "chatRoomOwner": "",
                    "members": [],
                    "last_update": int(time.time())
                }

            # 更新群聊成员信息
            chatrooms_info[group_id]["members"] = members
            chatrooms_info[group_id]["last_update"] = int(time.time())

            # 保存到文件
            with open(chatrooms_file, 'w', encoding='utf-8') as f:
                json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

            logger.info(f"[WX849] 已更新群聊 {group_id} 成员信息，成员数: {len(members)}")

            # 再次尝试查找成员昵称
            for member in members:
                if member.get("UserName") == member_wxid:
                    # 优先使用群内显示名称(群昵称)
                    if member.get("DisplayName"):
                        logger.debug(f"[WX849] 获取到成员 {member_wxid} 的群昵称: {member.get('DisplayName')}")
                        return member.get("DisplayName")
                    # 次选使用个人昵称
                    elif member.get("NickName"):
                        logger.debug(f"[WX849] 获取到成员 {member_wxid} 的昵称: {member.get('NickName')}")
                        return member.get("NickName")
                    else:
                        return member_wxid

            # 如果仍然找不到，返回wxid
            return member_wxid
        except Exception as e:
            logger.error(f"[WX849] 获取群成员昵称失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")
            return member_wxid

    async def _update_chatrooms_info(self):
        """更新群聊信息缓存"""
        try:
            logger.debug(f"[WX849] 开始更新群聊信息缓存")

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 首先获取联系人列表，找出所有群聊
            # 构建完整的API URL用于日志
            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Friend/GetContractList"
            logger.debug(f"[WX849] 正在请求联系人列表API: {api_url}")

            # 准备请求参数
            params = {
                "Wxid": self.wxid,
                "CurrentWxcontactSeq": 0,
                "CurrentChatRoomContactSeq": 0
            }

            # 调用API获取联系人列表
            response = await self._call_api("/Friend/GetContractList", params)

            if not response or not isinstance(response, dict):
                logger.error(f"[WX849] 获取联系人列表失败: 无效响应")
                return

            # 检查响应是否成功
            if not response.get("Success", False):
                logger.error(f"[WX849] 获取联系人列表失败: {response.get('Message', '未知错误')}")
                return

            # 提取联系人列表
            data = response.get("Data", {})
            contact_list = data.get("ContactList", [])

            if not contact_list or not isinstance(contact_list, list):
                logger.error(f"[WX849] 获取联系人列表失败: 响应中无ContactList或格式不正确")
                return

            # 创建临时目录
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            # 定义群聊信息文件路径
            chatrooms_file = os.path.join(tmp_dir, 'wx849_rooms.json')

            # 读取现有的群聊信息（如果存在）
            chatrooms_info = {}
            if os.path.exists(chatrooms_file):
                try:
                    with open(chatrooms_file, 'r', encoding='utf-8') as f:
                        chatrooms_info = json.load(f)
                    logger.debug(f"[WX849] 已加载 {len(chatrooms_info)} 个现有群聊信息")
                except Exception as e:
                    logger.error(f"[WX849] 加载现有群聊信息失败: {str(e)}")

            # 更新群聊信息
            updated_count = 0
            for contact in contact_list:
                if not isinstance(contact, dict):
                    continue

                # 检查是否是群聊
                user_name = contact.get("UserName", "")
                if not user_name or not user_name.endswith("@chatroom"):
                    continue

                # 提取群聊信息
                nick_name = contact.get("NickName", "")

                # 更新群聊信息
                if user_name not in chatrooms_info:
                    chatrooms_info[user_name] = {
                        "chatroomId": user_name,
                        "nickName": nick_name or user_name,
                        "chatRoomOwner": "",
                        "members": [],
                        "last_update": int(time.time())
                    }
                else:
                    # 只更新昵称和时间戳
                    if nick_name:
                        chatrooms_info[user_name]["nickName"] = nick_name
                    chatrooms_info[user_name]["last_update"] = int(time.time())

                updated_count += 1

            # 保存到文件
            with open(chatrooms_file, 'w', encoding='utf-8') as f:
                json.dump(chatrooms_info, f, ensure_ascii=False, indent=2)

            logger.info(f"[WX849] 已更新 {updated_count} 个群聊基础信息")

            # 更新群成员信息
            for group_id in list(chatrooms_info.keys())[:10]:  # 限制一次最多更新10个群
                try:
                    await self._get_group_member_details(group_id)
                except Exception as e:
                    logger.error(f"[WX849] 更新群 {group_id} 成员信息失败: {e}")

        except Exception as e:
            logger.error(f"[WX849] 更新群聊信息缓存失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")

    async def _update_contacts_info(self):
        """更新联系人信息缓存"""
        try:
            logger.debug(f"[WX849] 开始更新联系人信息缓存")

            # 获取API配置
            api_host = conf().get("wx849_api_host", "127.0.0.1")
            api_port = conf().get("wx849_api_port", 9011)
            protocol_version = conf().get("wx849_protocol_version", "849")

            # 确定API路径前缀
            if protocol_version == "855" or protocol_version == "ipad":
                api_path_prefix = "/api"
            else:
                api_path_prefix = "/VXAPI"

            # 首先获取联系人列表
            # 构建完整的API URL用于日志
            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Friend/GetContractList"
            logger.debug(f"[WX849] 正在请求联系人列表API: {api_url}")

            # 准备请求参数
            params = {
                "Wxid": self.wxid,
                "CurrentWxcontactSeq": 0,
                "CurrentChatRoomContactSeq": 0
            }

            # 调用API获取联系人列表
            response = await self._call_api("/Friend/GetContractList", params)

            if not response or not isinstance(response, dict):
                logger.error(f"[WX849] 获取联系人列表失败: 无效响应")
                return

            # 检查响应是否成功
            if not response.get("Success", False):
                logger.error(f"[WX849] 获取联系人列表失败: {response.get('Message', '未知错误')}")
                return

            # 提取联系人列表
            data = response.get("Data", {})
            contact_list = data.get("ContactList", [])

            if not contact_list or not isinstance(contact_list, list):
                logger.error(f"[WX849] 获取联系人列表失败: 响应中无ContactList或格式不正确")
                return

            # 创建临时目录
            tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            # 定义联系人信息文件路径
            contacts_file = os.path.join(tmp_dir, 'wx849_contacts.json')

            # 读取现有的联系人信息（如果存在）
            contacts_info = {}
            if os.path.exists(contacts_file):
                try:
                    with open(contacts_file, 'r', encoding='utf-8') as f:
                        contacts_info = json.load(f)
                    logger.debug(f"[WX849] 已加载 {len(contacts_info)} 个现有联系人信息")
                except Exception as e:
                    logger.error(f"[WX849] 加载现有联系人信息失败: {str(e)}")

            # 更新联系人信息
            updated_count = 0
            for contact in contact_list:
                if not isinstance(contact, dict):
                    continue

                # 检查是否是联系人（非群聊）
                user_name = contact.get("UserName", "")
                if not user_name or user_name.endswith("@chatroom"):
                    continue

                # 提取联系人信息
                nick_name = contact.get("NickName", "")
                remark_name = contact.get("RemarkName", "")

                # 更新联系人信息
                if user_name not in contacts_info:
                    contacts_info[user_name] = {
                        "UserName": user_name,
                        "NickName": nick_name or user_name,
                        "RemarkName": remark_name or "",
                        "last_update": int(time.time())
                    }
                else:
                    # 更新昵称、备注和时间戳
                    if nick_name:
                        contacts_info[user_name]["NickName"] = nick_name
                    if remark_name:
                        contacts_info[user_name]["RemarkName"] = remark_name
                    contacts_info[user_name]["last_update"] = int(time.time())

                updated_count += 1

            # 保存到文件
            with open(contacts_file, 'w', encoding='utf-8') as f:
                json.dump(contacts_info, f, ensure_ascii=False, indent=2)

            logger.info(f"[WX849] 已更新 {updated_count} 个联系人信息")

        except Exception as e:
            logger.error(f"[WX849] 更新联系人信息缓存失败: {e}")
            logger.error(f"[WX849] 详细错误: {traceback.format_exc()}")

    def download_image(self, msg_id, group_id=None):
        """下载图片，供外部调用

        Args:
            msg_id: 消息ID
            group_id: 群ID，如果是群消息

        Returns:
            str: 图片文件路径，如果下载失败则返回None
        """
        logger.debug(f"[WX849] 尝试下载图片: msg_id={msg_id}, group_id={group_id}")

        # 创建临时目录
        tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp", "images")
        os.makedirs(tmp_dir, exist_ok=True)

        # 生成图片文件名
        image_filename = f"img_{msg_id}_{int(time.time())}.jpg"
        image_path = os.path.join(tmp_dir, image_filename)

        # 检查是否已经存在相同的图片文件
        existing_files = [f for f in os.listdir(tmp_dir) if f.startswith(f"img_{msg_id}_")]
        if existing_files:
            # 找到最新的文件
            latest_file = sorted(existing_files, key=lambda x: os.path.getmtime(os.path.join(tmp_dir, x)), reverse=True)[0]
            existing_path = os.path.join(tmp_dir, latest_file)

            # 检查文件是否有效
            if os.path.exists(existing_path) and os.path.getsize(existing_path) > 0:
                logger.debug(f"[WX849] 找到已存在的图片文件: {existing_path}")
                return existing_path

        # 构建API请求参数
        api_host = conf().get("wx849_api_host", "127.0.0.1")
        api_port = conf().get("wx849_api_port", 9011)
        protocol_version = conf().get("wx849_protocol_version", "849")

        # 确定API路径前缀
        if protocol_version == "855" or protocol_version == "ipad":
            api_path_prefix = "/api"
        else:
            api_path_prefix = "/VXAPI"

        # 使用传入的图片大小或使用默认值
        data_len = getattr(self, "data_len", 345519)  # 如果设置了data_len属性，则使用它，否则使用默认值
        logger.debug(f"[WX849] 使用图片大小: {data_len} 字节")

        # 分段大小
        chunk_size = 65536  # 64KB - 必须使用这个大小，API限制每次最多下载64KB

        # 计算分段数
        num_chunks = (data_len + chunk_size - 1) // chunk_size
        if num_chunks <= 0:
            num_chunks = 1  # 至少分1段

        logger.info(f"[WX849] 开始分段下载图片，总大小: {data_len} 字节，分 {num_chunks} 段下载")

        # 创建一个空文件
        with open(image_path, "wb") as f:
            pass

        # 分段下载
        all_chunks_success = True
        for i in range(num_chunks):
            start_pos = i * chunk_size
            current_chunk_size = min(chunk_size, data_len - start_pos)
            if current_chunk_size <= 0:
                current_chunk_size = chunk_size

            # 构建API请求参数
            params = {
                "MsgId": msg_id,
                "ToWxid": group_id if group_id else "filehelper",
                "Wxid": self.wxid,
                "DataLen": data_len,
                "CompressType": 0,
                "Section": {
                    "StartPos": start_pos,
                    "DataLen": current_chunk_size
                }
            }

            logger.debug(f"[WX849] 尝试下载图片分段: MsgId={msg_id}, ToWxid={group_id if group_id else 'filehelper'}, DataLen={data_len}, StartPos={start_pos}, ChunkSize={current_chunk_size}")

            # 构建完整的API URL
            api_url = f"http://{api_host}:{api_port}{api_path_prefix}/Tools/DownloadImg"

            # 记录完整的请求URL和参数
            logger.debug(f"[WX849] 图片下载API URL: {api_url}")
            logger.debug(f"[WX849] 图片下载API参数: {params}")

            try:
                # 使用同步请求
                import requests
                response = requests.post(api_url, json=params, timeout=10)

                if response.status_code != 200:
                    logger.error(f"[WX849] 下载图片分段失败, 状态码: {response.status_code}")
                    all_chunks_success = False
                    break

                # 获取响应内容
                result = response.json()

                # 检查响应是否成功
                if not result.get("Success", False):
                    logger.error(f"[WX849] 下载图片分段失败: {result.get('Message', '未知错误')}")
                    all_chunks_success = False
                    break

                # 提取图片数据
                data = result.get("Data", {})

                # 记录响应结构以便调试
                if isinstance(data, dict):
                    logger.debug(f"[WX849] 响应Data字段包含键: {list(data.keys())}")

                # 尝试不同的响应格式
                chunk_base64 = None

                # 参考 WechatAPI/Client/tool_extension.py 中的处理方式
                if isinstance(data, dict):
                    # 如果是字典，尝试获取buffer字段
                    if "buffer" in data:
                        logger.debug(f"[WX849] 从data.buffer字段获取图片数据")
                        chunk_base64 = data.get("buffer")
                    elif "data" in data and isinstance(data["data"], dict) and "buffer" in data["data"]:
                        logger.debug(f"[WX849] 从data.data.buffer字段获取图片数据")
                        chunk_base64 = data["data"]["buffer"]
                    else:
                        # 尝试其他可能的字段名
                        for field in ["Chunk", "Image", "Data", "FileData", "data"]:
                            if field in data:
                                logger.debug(f"[WX849] 从data.{field}字段获取图片数据")
                                chunk_base64 = data.get(field)
                                break
                elif isinstance(data, str):
                    # 如果直接返回字符串，可能就是base64数据
                    logger.debug(f"[WX849] Data字段是字符串，直接使用")
                    chunk_base64 = data

                # 如果在data中没有找到，尝试在整个响应中查找
                if not chunk_base64 and isinstance(result, dict):
                    for field in ["data", "Data", "FileData", "Image"]:
                        if field in result:
                            logger.debug(f"[WX849] 从result.{field}字段获取图片数据")
                            chunk_base64 = result.get(field)
                            break

                if not chunk_base64:
                    logger.error(f"[WX849] 下载图片分段失败: 响应中无图片数据")
                    all_chunks_success = False
                    break

                # 解码数据并保存图片分段
                try:
                    # 尝试确定数据类型并正确处理
                    if isinstance(chunk_base64, str):
                        # 尝试作为Base64解码
                        try:
                            # 修复：确保字符串是有效的Base64
                            # 移除可能的非Base64字符
                            clean_base64 = chunk_base64.strip()
                            # 确保长度是4的倍数，如果不是，添加填充
                            padding = 4 - (len(clean_base64) % 4) if len(clean_base64) % 4 != 0 else 0
                            clean_base64 = clean_base64 + ('=' * padding)

                            import base64
                            chunk_data = base64.b64decode(clean_base64)
                            logger.debug(f"[WX849] 成功解码Base64数据，大小: {len(chunk_data)} 字节")
                        except Exception as decode_err:
                            logger.error(f"[WX849] Base64解码失败: {decode_err}")
                            all_chunks_success = False
                            break
                    elif isinstance(chunk_base64, bytes):
                        # 已经是二进制数据，直接使用
                        logger.debug(f"[WX849] 使用二进制数据，大小: {len(chunk_base64)} 字节")
                        chunk_data = chunk_base64
                    else:
                        logger.error(f"[WX849] 未知数据类型: {type(chunk_base64)}")
                        all_chunks_success = False
                        break

                    # 追加到文件
                    with open(image_path, "ab") as f:
                        f.write(chunk_data)
                    logger.debug(f"[WX849] 第 {i+1}/{num_chunks} 段下载成功，大小: {len(chunk_data)} 字节")
                except Exception as decode_err:
                    logger.error(f"[WX849] 解码Base64图片分段数据失败: {decode_err}")
                    all_chunks_success = False
                    break
            except Exception as api_err:
                logger.error(f"[WX849] 调用图片分段API失败: {api_err}")
                all_chunks_success = False
                break

        if all_chunks_success:
            # 检查文件大小
            file_size = os.path.getsize(image_path)
            logger.info(f"[WX849] 分段下载图片成功，总大小: {file_size} 字节")

            # 检查文件是否存在且有效
            if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
                # 验证图片文件是否为有效的图片格式
                try:
                    from PIL import Image
                    try:
                        # 尝试打开图片文件
                        with Image.open(image_path) as img:
                            # 获取图片格式和大小
                            img_format = img.format
                            img_size = img.size
                            logger.info(f"[WX849] 图片验证成功: 格式={img_format}, 大小={img_size}")
                            return image_path
                    except Exception as img_err:
                        logger.error(f"[WX849] 图片验证失败，可能不是有效的图片文件: {img_err}")
                except ImportError:
                    # 如果PIL库未安装，假设文件有效
                    if os.path.getsize(image_path) > 10000:  # 至少10KB
                        logger.info(f"[WX849] 图片下载完成，保存到: {image_path}")
                        return image_path

        # 如果下载失败，删除可能存在的不完整文件
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                logger.error(f"[WX849] 删除不完整的图片文件失败: {e}")

        return None

    def reply(self, reply: Reply, context: Context = None):
        """回复消息的统一处理函数"""
        if reply.type in self.NOT_SUPPORT_REPLYTYPE:
            logger.warning(f"[WX849] 暂不支持回复类型: {reply.type}")
            return

        receiver = context["receiver"] if context and "receiver" in context else ""
        if not receiver:
            logger.error("[WX849] 回复失败: 接收者为空")
            return

        # 创建简单的事件循环，用于执行异步任务
        loop = asyncio.new_event_loop()

        if reply.type == ReplyType.TEXT:
            # 发送文本消息
            logger.debug(f"[WX849] 开始发送文本消息: {reply.content}")
            try:
                # 发送文本
                result = loop.run_until_complete(self._send_text_message(receiver, reply.content))
                if result:
                    logger.info(f"[WX849] 发送文本成功: 接收者: {receiver}, 内容: {reply.content[:20]}...")
                else:
                    logger.warning(f"[WX849] 发送文本失败: 接收者: {receiver}, 内容: {reply.content[:20]}...")
            except Exception as e:
                logger.error(f"[WX849] 发送文本失败: {e}")
                logger.error(traceback.format_exc())

        elif reply.type == ReplyType.IMAGE or reply.type == ReplyType.IMAGE_URL:
            # 处理图片消息发送
            image_path = reply.content
            logger.debug(f"[WX849] 开始发送图片, {'URL' if reply.type == ReplyType.IMAGE_URL else '文件路径'}={image_path}")
            try:
                # 如果是图片URL，先下载图片
                if reply.type == ReplyType.IMAGE_URL:
                    # 下载图片
                    img_res = requests.get(image_path, stream=True)
                    # 创建临时文件保存图片
                    tmp_path = os.path.join(get_appdata_dir(), f"tmp_img_{int(time.time())}.jpg")
                    with open(tmp_path, 'wb') as f:
                        for block in img_res.iter_content(1024):
                            f.write(block)
                    # 使用下载后的本地文件路径
                    image_path = tmp_path

                # 发送图片文件
                result = loop.run_until_complete(self._send_image(receiver, image_path))

                # 如果是URL类型，删除临时文件
                if reply.type == ReplyType.IMAGE_URL:
                    try:
                        os.remove(tmp_path)
                    except Exception as e:
                        logger.debug(f"[WX849] 删除临时图片文件失败: {e}")

                if result:
                    logger.info(f"[WX849] 发送图片成功: 接收者: {receiver}")
                else:
                    logger.warning(f"[WX849] 发送图片失败: 接收者: {receiver}")
            except Exception as e:
                logger.error(f"[WX849] 处理图片失败: {e}")
                logger.error(traceback.format_exc())

        elif reply.type == ReplyType.VOICE:
            # 发送语音消息
            voice_path = reply.content
            logger.debug(f"[WX849] 开始发送语音, 文件路径={voice_path}")
            try:
                # 使用统一的语音发送方法，会自动处理短语音和长语音的分割
                result = loop.run_until_complete(self._send_voice(receiver, voice_path))
                if result:
                    logger.info(f"[WX849] 发送语音成功: 接收者: {receiver}")
                else:
                    logger.warning(f"[WX849] 发送语音失败: 接收者: {receiver}")
            except Exception as e:
                logger.error(f"[WX849] 处理语音失败: {e}")
                logger.error(traceback.format_exc())

        elif reply.type == ReplyType.VOICE_URL:
            # 从网络下载语音并发送
            voice_url = reply.content
            logger.debug(f"[WX849] 开始下载语音, url={voice_url}")
            try:
                # 下载语音文件
                voice_res = requests.get(voice_url, stream=True)
                # 使用临时文件保存语音
                tmp_path = os.path.join(get_appdata_dir(), f"tmp_voice_{int(time.time())}.mp3")
                with open(tmp_path, 'wb') as f:
                    for block in voice_res.iter_content(1024):
                        f.write(block)

                # 使用统一的语音发送方法，会自动处理短语音和长语音的分割
                result = loop.run_until_complete(self._send_voice(receiver, tmp_path))

                if result:
                    logger.info(f"[WX849] 发送语音成功: 接收者: {receiver}")
                else:
                    logger.warning(f"[WX849] 发送语音失败: 接收者: {receiver}")

                # 删除临时文件
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    logger.debug(f"[WX849] 删除临时语音文件失败: {e}")
            except Exception as e:
                logger.error(f"[WX849] 处理语音URL失败: {e}")
                logger.error(traceback.format_exc())

        else:
            logger.warning(f"[WX849] 不支持的回复类型: {reply.type}")

        loop.close()