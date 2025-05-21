import os
import re
import threading
import time
from asyncio import CancelledError
from concurrent.futures import Future, ThreadPoolExecutor

from bridge.context import *
from bridge.reply import *
from channel.channel import Channel
from common.dequeue import Dequeue
from common import memory
from plugins import *
from common.log import logger
from config import conf

try:
    from voice.audio_convert import any_to_wav
except Exception as e:
    pass

handler_pool = ThreadPoolExecutor(max_workers=8)  # 处理消息的线程池


# 抽象类, 它包含了与消息通道无关的通用处理逻辑
class ChatChannel(Channel):
    name = None  # 登录的用户名
    user_id = None  # 登录的用户id
    futures = {}  # 记录每个session_id提交到线程池的future对象, 用于重置会话时把没执行的future取消掉，正在执行的不会被取消
    sessions = {}  # 用于控制并发，每个session_id同时只能有一个context在处理
    lock = threading.Lock()  # 用于控制对sessions的访问

    def __init__(self):
        _thread = threading.Thread(target=self.consume)
        _thread.setDaemon(True)
        _thread.start()

    # 根据消息构造context，消息内容相关的触发项写在这里
    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if ctype == ContextType.ACCEPT_FRIEND:
            return context
        # context首次传入时，origin_ctype是None,
        # 引入的起因是：当输入语音时，会嵌套生成两个context，第一步语音转文本，第二步通过文本生成文字回复。
        # origin_ctype用于第二步文本回复时，判断是否需要匹配前缀，如果是私聊的语音，就不需要匹配前缀
        if "origin_ctype" not in context:
            context["origin_ctype"] = ctype
        # context首次传入时，receiver是None，根据类型设置receiver
        first_in = "receiver" not in context
        # 群名匹配过程，设置session_id和receiver
        if first_in:  # context首次传入时，receiver是None，根据类型设置receiver
            config = conf()
            cmsg = context["msg"]
            user_data = conf().get_user_data(cmsg.from_user_id)
            context["openai_api_key"] = user_data.get("openai_api_key")
            context["gpt_model"] = user_data.get("gpt_model")
            if context.get("isgroup", False):
                group_name = cmsg.other_user_nickname
                group_id = cmsg.other_user_id
                context["group_name"] = group_name

                group_name_white_list = config.get("group_name_white_list", [])
                group_name_keyword_white_list = config.get("group_name_keyword_white_list", [])
                if any(
                        [
                            group_name in group_name_white_list,
                            "ALL_GROUP" in group_name_white_list,
                            check_contain(group_name, group_name_keyword_white_list),
                        ]
                ):
                    group_chat_in_one_session = conf().get("group_chat_in_one_session", [])
                    session_id = f"{cmsg.actual_user_id}@@{group_id}" # 当群聊未共享session时，session_id为user_id与group_id的组合，用于区分不同群聊以及单聊
                    context["is_shared_session_group"] = False  # 默认为非共享会话群
                    if any(
                            [
                                group_name in group_chat_in_one_session,
                                "ALL_GROUP" in group_chat_in_one_session,
                            ]
                    ):
                        session_id = group_id
                        context["is_shared_session_group"] = True  # 如果是共享会话群，设置为True
                else:
                    logger.debug(f"No need reply, groupName not in whitelist, group_name={group_name}")
                    return None
                context["session_id"] = session_id
                context["receiver"] = group_id
            else:
                context["session_id"] = cmsg.other_user_id
                context["receiver"] = cmsg.other_user_id
            e_context = PluginManager().emit_event(EventContext(Event.ON_RECEIVE_MESSAGE, {"channel": self, "context": context}))
            context = e_context["context"]
            if e_context.is_pass() or context is None:
                return context
            if cmsg.from_user_id == self.user_id and not config.get("trigger_by_self", True):
                logger.debug("[chat_channel]self message skipped")
                return None

        # 消息内容匹配过程，并处理content
        if ctype == ContextType.TEXT:
            nick_name_black_list = conf().get("nick_name_black_list", [])
            if context.get("isgroup", False):  # 群聊
                # 校验关键字
                match_prefix = check_prefix(content, conf().get("group_chat_prefix"))
                match_contain = check_contain(content, conf().get("group_chat_keyword"))
                flag = False
                if context["msg"].to_user_id != context["msg"].actual_user_id:
                    if match_prefix is not None or match_contain is not None:
                        flag = True
                        if match_prefix:
                            content = content.replace(match_prefix, "", 1).strip()
                    if context["msg"].is_at:
                        nick_name = context["msg"].actual_user_nickname
                        if nick_name and nick_name in nick_name_black_list:
                            # 黑名单过滤
                            logger.warning(f"[chat_channel] Nickname {nick_name} in In BlackList, ignore")
                            return None

                        logger.info("[chat_channel]receive group at")
                        if not conf().get("group_at_off", False):
                            flag = True
                        self.name = self.name if self.name is not None else ""  # 部分渠道self.name可能没有赋值
                        pattern = f"@{re.escape(self.name)}(\u2005|\u0020)"
                        subtract_res = re.sub(pattern, r"", content)
                        if isinstance(context["msg"].at_list, list):
                            for at in context["msg"].at_list:
                                pattern = f"@{re.escape(at)}(\u2005|\u0020)"
                                subtract_res = re.sub(pattern, r"", subtract_res)
                        if subtract_res == content and context["msg"].self_display_name:
                            # 前缀移除后没有变化，使用群昵称再次移除
                            pattern = f"@{re.escape(context['msg'].self_display_name)}(\u2005|\u0020)"
                            subtract_res = re.sub(pattern, r"", content)
                        content = subtract_res
                if not flag:
                    if context["origin_ctype"] == ContextType.VOICE:
                        logger.info("[chat_channel]receive group voice, but checkprefix didn't match")
                    return None
            else:  # 单聊
                nick_name = context["msg"].from_user_nickname
                if nick_name and nick_name in nick_name_black_list:
                    # 黑名单过滤
                    logger.warning(f"[chat_channel] Nickname '{nick_name}' in In BlackList, ignore")
                    return None

                match_prefix = check_prefix(content, conf().get("single_chat_prefix", [""]))
                if match_prefix is not None:  # 判断如果匹配到自定义前缀，则返回过滤掉前缀+空格后的内容
                    content = content.replace(match_prefix, "", 1).strip()
                elif self.channel_type == 'wechatcom_app':
                    # todo:企业微信自建应用不需要前导字符
                    pass
                elif context["origin_ctype"] == ContextType.VOICE:  # 如果源消息是私聊的语音消息，允许不匹配前缀，放宽条件
                    pass
                else:
                    return None
            content = content.strip()
            img_match_prefix = check_prefix(content, conf().get("image_create_prefix",[""]))
            if img_match_prefix:
                content = content.replace(img_match_prefix, "", 1)
                context.type = ContextType.IMAGE_CREATE
            else:
                context.type = ContextType.TEXT
            context.content = content.strip()
            if "desire_rtype" not in context and conf().get(
                    "always_reply_voice") and ReplyType.VOICE not in self.NOT_SUPPORT_REPLYTYPE:
                context["desire_rtype"] = ReplyType.VOICE
        elif context.type == ContextType.VOICE:
            if "desire_rtype" not in context and conf().get(
                    "voice_reply_voice") and ReplyType.VOICE not in self.NOT_SUPPORT_REPLYTYPE:
                context["desire_rtype"] = ReplyType.VOICE
        return context

    def _handle(self, context: Context):
        if context is None or not context.content:
            return

        # 创建上下文的深拷贝，确保完全独立
        # 由于Context对象没有copy方法，我们需要手动创建一个新的Context对象
        independent_context = Context(
            type=context.type,
            content=context.content,
            kwargs={}  # 创建空字典，然后手动复制
        )

        # 手动复制 kwargs 字典中的内容
        for key in context.kwargs:
            # 对于复杂对象，创建深拷贝
            if isinstance(context.kwargs[key], dict):
                independent_context.kwargs[key] = context.kwargs[key].copy()
            elif isinstance(context.kwargs[key], list):
                independent_context.kwargs[key] = context.kwargs[key].copy()
            else:
                independent_context.kwargs[key] = context.kwargs[key]

        # 记录上下文信息，确保使用的是正确的上下文对象
        logger.debug("[chat_channel] ready to handle context: {}".format(independent_context))

        # 记录关键信息，用于调试
        session_id = independent_context.get("session_id", "unknown")
        receiver = independent_context.get("receiver", "unknown")
        is_group = independent_context.get("isgroup", False)
        logger.debug(f"[chat_channel] Processing message - session_id: {session_id}, receiver: {receiver}, isgroup: {is_group}")

        # reply的构建步骤
        reply = self._generate_reply(independent_context)

        logger.debug("[chat_channel] ready to decorate reply: {}".format(reply))

        # reply的包装步骤
        if reply and reply.content:
            reply = self._decorate_reply(independent_context, reply)

            # reply的发送步骤
            self._send_reply(independent_context, reply)

    def _generate_reply(self, context: Context, reply: Reply = Reply()) -> Reply:
        # 确保上下文中包含 isgroup 键
        if "isgroup" not in context:
            context["isgroup"] = False

        e_context = PluginManager().emit_event(
            EventContext(
                Event.ON_HANDLE_CONTEXT,
                {"channel": self, "context": context, "reply": reply},
            )
        )
        reply = e_context["reply"]
        if not e_context.is_pass():
            logger.debug("[chat_channel] ready to handle context: type={}, content={}".format(context.type, context.content))
            if context.type == ContextType.TEXT or context.type == ContextType.IMAGE_CREATE:  # 文字和图片消息
                context["channel"] = e_context["channel"]

                # 添加对trigger_prefix标志的检查，只有当trigger_prefix为True或未设置时，才调用AI进行回复
                # 对于私聊消息，始终触发AI对话，不检查trigger_prefix
                if context.get("isgroup", False) and context.get("trigger_prefix", True) == False:
                    logger.info("[chat_channel] 群聊消息不满足触发条件，跳过AI对话: content={}".format(context.content[:20]))
                    # 不需要生成回复，直接返回空回复
                    return Reply()

                reply = super().build_reply_content(context.content, context)
            elif context.type == ContextType.VOICE:  # 语音消息
                cmsg = context["msg"]
                cmsg.prepare()
                file_path = context.content
                wav_path = os.path.splitext(file_path)[0] + ".wav"
                try:
                    any_to_wav(file_path, wav_path)
                except Exception as e:  # 转换失败，直接使用mp3，对于某些api，mp3也可以识别
                    logger.warning("[chat_channel]any to wav error, use raw path. " + str(e))
                    wav_path = file_path
                # 语音识别
                reply = super().build_voice_to_text(wav_path)
                # 删除临时文件
                try:
                    os.remove(file_path)
                    if wav_path != file_path:
                        os.remove(wav_path)
                except Exception as e:
                    pass
                    # logger.warning("[chat_channel]delete temp file error: " + str(e))

                if reply.type == ReplyType.TEXT:
                    new_context = self._compose_context(ContextType.TEXT, reply.content, **context.kwargs)
                    if new_context:
                        reply = self._generate_reply(new_context)
                    else:
                        return
            elif context.type == ContextType.IMAGE:  # 图片消息，当前仅做下载保存到本地的逻辑
                memory.USER_IMAGE_CACHE[context["session_id"]] = {
                    "path": context.content,
                    "msg": context.get("msg")
                }
            elif context.type == ContextType.ACCEPT_FRIEND:  # 好友申请，匹配字符串
                reply = self._build_friend_request_reply(context)
            elif context.type == ContextType.SHARING:  # 分享信息，当前无默认逻辑
                pass
            elif context.type == ContextType.FUNCTION or context.type == ContextType.FILE:  # 文件消息及函数调用等，当前无默认逻辑
                pass
            elif context.type == ContextType.XML:  # XML消息，当前无默认逻辑，但需要处理
                # 检查是否是@机器人的消息
                is_at_bot = context.get("is_at", False)

                # 如果context中没有is_at标志，检查at_list中是否包含机器人wxid
                if not is_at_bot and "at_list" in context.kwargs and "IsAtMessage" in context.kwargs.get("msg", {}).msg:
                    # 只有当IsAtMessage为True时，才检查at_list中是否包含机器人wxid
                    if context.kwargs["msg"].msg["IsAtMessage"]:
                        # 从配置文件中读取机器人wxid列表
                        bot_wxids = conf().get("robot_wxids", ["wxid_p60yfpl5zg2m29", "wxid_uz9za1pqr3ea22", "wxid_l5im9jaxhr4412"])
                        # 遍历所有可能的机器人wxid
                        for bot_wxid in bot_wxids:
                            if bot_wxid in context.kwargs["at_list"]:
                                is_at_bot = True
                                logger.debug(f"[chat_channel] 从at_list中检测到@机器人: {bot_wxid}")
                                break

                # 检查消息内容中是否包含@机器人的文本，并且确认IsAtMessage为True
                if not is_at_bot and context.content and "IsAtMessage" in context.kwargs.get("msg", {}).msg:
                    if context.kwargs["msg"].msg["IsAtMessage"]:
                        # 从配置文件中读取机器人名称列表
                        robot_names = conf().get("robot_names", ["小小x", "小x", "机器人"])
                        for bot_name in robot_names:
                            if f"@{bot_name}" in context.content:
                                is_at_bot = True
                                logger.debug(f"[chat_channel] 从消息内容中检测到@机器人: @{bot_name}")
                                break

                # 如果是@机器人的消息，按照文本消息处理
                if is_at_bot:
                    logger.debug("[chat_channel] 处理XML类型的@机器人消息: {}".format(context.content))
                    # 检查是否有引用消息
                    quoted_content = context.get("quoted_content")
                    quoted_nickname = context.get("quoted_nickname")

                    # 构建包含引用信息的消息内容
                    enhanced_content = context.content

                    # 检查是否引用了图片消息
                    quoted_msg_type = None
                    if "quoted_message" in context.kwargs:
                        quoted_msg_type = context.kwargs["quoted_message"].get("MsgType")

                    # 如果引用的是图片消息
                    if quoted_msg_type == 3:
                        logger.debug(f"[chat_channel] 检测到引用图片消息")

                        # 检查上下文中是否有图片URL
                        image_url = context.get("quoted_image_url")

                        # 如果上下文中没有图片URL，尝试从引用消息中提取
                        if not image_url and "msg" in context.kwargs and hasattr(context.kwargs["msg"], "msg") and "QuotedMessage" in context.kwargs["msg"].msg:
                            quoted_message = context.kwargs["msg"].msg["QuotedMessage"]

                            # 尝试从引用消息中提取图片URL
                            if "cdnthumburl" in quoted_message:
                                image_url = quoted_message["cdnthumburl"]
                                logger.debug(f"[chat_channel] 从引用消息的cdnthumburl字段获取到图片URL: {image_url}")
                            elif "cdnmidimgurl" in quoted_message:
                                image_url = quoted_message["cdnmidimgurl"]
                                logger.debug(f"[chat_channel] 从引用消息的cdnmidimgurl字段获取到图片URL: {image_url}")
                            # 如果没有直接的URL字段，尝试从Content中提取
                            elif "Content" in quoted_message:
                                try:
                                    import re
                                    # 尝试使用正则表达式提取图片URL
                                    url_match = re.search(r'cdnthumburl="([^"]+)"', quoted_message["Content"])
                                    if url_match:
                                        image_url = url_match.group(1)
                                        logger.debug(f"[chat_channel] 从引用消息Content中提取到cdnthumburl: {image_url}")
                                    else:
                                        url_match = re.search(r'cdnmidimgurl="([^"]+)"', quoted_message["Content"])
                                        if url_match:
                                            image_url = url_match.group(1)
                                            logger.debug(f"[chat_channel] 从引用消息Content中提取到cdnmidimgurl: {image_url}")
                                except Exception as e:
                                    logger.error(f"[chat_channel] 提取图片URL失败: {e}")

                        # 如果找到了图片URL，尝试下载图片并分析
                        if image_url:
                            try:
                                # 创建临时目录
                                import os
                                import tempfile
                                import requests
                                import uuid

                                # 创建临时文件名
                                temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                                if not os.path.exists(temp_dir):
                                    os.makedirs(temp_dir)

                                # 生成唯一的文件名
                                image_filename = f"quoted_image_{uuid.uuid4().hex}.jpg"
                                image_path = os.path.join(temp_dir, image_filename)

                                # 下载图片
                                logger.debug(f"[chat_channel] 尝试下载引用图片: {image_url}")
                                response = requests.get(image_url, timeout=10)
                                if response.status_code == 200:
                                    with open(image_path, 'wb') as f:
                                        f.write(response.content)
                                    logger.debug(f"[chat_channel] 成功下载引用图片: {image_path}")

                                    # 添加图片路径到上下文
                                    context["quoted_image_path"] = image_path

                                    # 尝试使用图像识别API分析图片内容
                                    try:
                                        # 这里可以调用图像识别API，例如百度OCR、Google Vision等
                                        # 为了简单起见，我们这里只是添加一个占位符
                                        image_description = "[图片内容无法自动识别，请查看图片后回答]"

                                        # 修改增强消息内容
                                        enhanced_content = f"{context.content}\n\n[引用了一张图片] {image_description}"
                                        logger.debug(f"[chat_channel] 增强消息内容，添加图片引用信息: {enhanced_content}")
                                    except Exception as e:
                                        logger.error(f"[chat_channel] 图片识别失败: {e}")
                                        enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法识别内容]"
                                else:
                                    logger.error(f"[chat_channel] 下载引用图片失败，状态码: {response.status_code}")
                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，但下载失败]"
                            except Exception as e:
                                logger.error(f"[chat_channel] 下载引用图片异常: {e}")
                                enhanced_content = f"{context.content}\n\n[引用了一张图片，但处理过程中出错]"
                        # 如果没有找到图片URL，尝试使用消息ID和其他信息下载图片
                        elif "msg" in context.kwargs and hasattr(context.kwargs["msg"], "msg") and "QuotedMessage" in context.kwargs["msg"].msg:
                            quoted_message = context.kwargs["msg"].msg["QuotedMessage"]

                            # 尝试从引用消息中提取svrid（消息ID）
                            msg_id = None
                            logger.debug(f"[chat_channel] 引用消息内容: {quoted_message}")
                            if "NewMsgId" in quoted_message:
                                msg_id = quoted_message["NewMsgId"]
                                logger.debug(f"[chat_channel] 从NewMsgId字段获取到消息ID: {msg_id}")
                            elif "svrid" in quoted_message:
                                msg_id = quoted_message["svrid"]
                                logger.debug(f"[chat_channel] 从svrid字段获取到消息ID: {msg_id}")
                            else:
                                logger.warning(f"[chat_channel] 引用消息中没有NewMsgId或svrid字段: {quoted_message}")

                            # 尝试从原始日志行中提取svrid
                            if not msg_id and "RawLogLine" in context.kwargs["msg"].msg:
                                raw_log = context.kwargs["msg"].msg["RawLogLine"]
                                import re  # 确保re模块在这里可用
                                svrid_match = re.search(r'<svrid>(.*?)</svrid>', raw_log)
                                if svrid_match:
                                    msg_id = svrid_match.group(1)
                                    logger.debug(f"[chat_channel] 从原始日志行中提取到svrid: {msg_id}")

                            # 如果找到了消息ID，尝试下载图片
                            if msg_id:
                                try:
                                    # 尝试使用消息ID下载图片
                                    logger.debug(f"[chat_channel] 尝试使用消息ID下载图片: {msg_id}")

                                    # 获取群ID
                                    group_id = context.kwargs.get("group_id")
                                    if not group_id and "fromusr" in quoted_message:
                                        group_id = quoted_message["fromusr"]
                                        logger.debug(f"[chat_channel] 从引用消息中获取到群ID: {group_id}")

                                    # 这里需要调用channel对象的方法来下载图片
                                    if "channel" in context.kwargs and hasattr(context.kwargs["channel"], "download_image"):
                                        image_path = context.kwargs["channel"].download_image(msg_id, group_id)
                                        if image_path and os.path.exists(image_path):
                                            logger.debug(f"[chat_channel] 成功使用消息ID下载图片: {image_path}")
                                            context["quoted_image_path"] = image_path
                                            enhanced_content = f"{context.content}\n\n[引用了一张图片，已下载]"
                                        else:
                                            logger.error(f"[chat_channel] 使用消息ID下载图片失败")
                                            enhanced_content = f"{context.content}\n\n[引用了一张图片，但下载失败]"
                                    else:
                                        logger.error(f"[chat_channel] 无法使用消息ID下载图片，channel对象不可用或没有download_image方法")
                                        enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法下载]"
                                except Exception as e:
                                    logger.error(f"[chat_channel] 使用消息ID下载图片异常: {e}")
                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，但处理过程中出错]"
                            else:
                                # 尝试直接从XML中提取图片信息
                                if "RawLogLine" in context.kwargs["msg"].msg:
                                    raw_log = context.kwargs["msg"].msg["RawLogLine"]
                                    try:
                                        # 提取cdnthumburl
                                        import re  # 确保re模块在这里可用
                                        cdnthumburl_match = re.search(r'cdnthumburl="([^"]*)"', raw_log)

                                        # 如果从原始日志行中没有找到cdnthumburl，尝试从DEBUG日志中查找最近的XML内容
                                        if not cdnthumburl_match:
                                            try:
                                                # 查找最近的XML日志
                                                import glob
                                                import os

                                                # 获取日志文件路径
                                                log_dir = "logs"
                                                if not os.path.exists(log_dir):
                                                    os.makedirs(log_dir)

                                                # 查找最新的日志文件
                                                log_files = glob.glob(os.path.join(log_dir, "*.log"))
                                                # 特别查找wx849_callback_daemon日志文件
                                                callback_logs = glob.glob(os.path.join(log_dir, "wx849_callback_daemon*.log"))
                                                # 特别查找XYBot日志文件
                                                xybot_logs = glob.glob(os.path.join(log_dir, "XYBot_*.log"))

                                                # 如果用户提供了具体的日志文件路径，直接使用
                                                user_log_path = context.kwargs.get("msg", {}).get("RawLogLine", "")
                                                if "logs\\" in user_log_path:
                                                    log_path = user_log_path.split("logs\\")[1].split(" ")[0]
                                                    if log_path:
                                                        user_log = os.path.join(log_dir, log_path)
                                                        if os.path.exists(user_log):
                                                            logger.debug(f"[chat_channel] 使用用户提供的日志文件: {user_log}")
                                                            latest_logs = [user_log]
                                                            # 不要在这里返回，继续执行后面的代码

                                                # 记录找到的所有日志文件
                                                logger.debug(f"[chat_channel] 找到 {len(callback_logs)} 个回调守护进程日志文件")
                                                logger.debug(f"[chat_channel] 找到 {len(xybot_logs)} 个XYBot日志文件")
                                                logger.debug(f"[chat_channel] 找到 {len(log_files)} 个日志文件")

                                                # 按照优先级查找日志文件
                                                latest_logs = []

                                                # 优先使用XYBot日志文件
                                                if xybot_logs:
                                                    latest_xybot_log = max(xybot_logs, key=os.path.getmtime)
                                                    latest_logs.append(latest_xybot_log)
                                                    logger.debug(f"[chat_channel] 找到最新的XYBot日志文件: {latest_xybot_log}")

                                                # 其次使用wx849_callback_daemon日志文件
                                                if callback_logs:
                                                    latest_callback_log = max(callback_logs, key=os.path.getmtime)
                                                    latest_logs.append(latest_callback_log)
                                                    logger.debug(f"[chat_channel] 找到最新的回调守护进程日志文件: {latest_callback_log}")

                                                # 最后使用其他日志文件
                                                if log_files:
                                                    latest_log = max(log_files, key=os.path.getmtime)
                                                    latest_logs.append(latest_log)
                                                    logger.debug(f"[chat_channel] 找到最新的日志文件: {latest_log}")

                                                # 如果没有找到任何日志文件，返回错误
                                                if not latest_logs:
                                                    logger.error(f"[chat_channel] 没有找到任何日志文件")
                                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法找到日志文件]"
                                                    return enhanced_content

                                                # 从日志文件中查找最近的XML内容
                                                xml_debug_pattern = re.compile(r'解析到的 XML 类型: 57, 完整内容: (.*?)$')
                                                # 备用模式，匹配DEBUG日志中的XML内容
                                                xml_debug_pattern2 = re.compile(r'DEBUG \| 解析到的 XML 类型: 57, 完整内容: (.*?)$')
                                                xml_content = None

                                                # 首先检查回调消息中是否包含完整的XML内容
                                                if "msg" in context.kwargs and "QuotedMessage" in context.kwargs["msg"].msg and "FullXmlContent" in context.kwargs["msg"].msg:
                                                    xml_content = context.kwargs["msg"].msg["FullXmlContent"]
                                                    logger.debug(f"[chat_channel] 从回调消息中提取到完整的XML内容，长度: {len(xml_content)}")

                                                # 如果回调消息中没有完整的XML内容，尝试从日志文件中查找
                                                if not xml_content:
                                                    # 遍历所有找到的日志文件，查找XML内容
                                                    for log_file in latest_logs:
                                                        logger.debug(f"[chat_channel] 正在搜索日志文件: {log_file}")
                                                        try:
                                                            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                                lines = f.readlines()
                                                                for i in range(len(lines) - 1, max(0, len(lines) - 50), -1):
                                                                    # 尝试使用第一种模式匹配
                                                                    xml_match = xml_debug_pattern.search(lines[i])
                                                                    if not xml_match:
                                                                        # 如果第一种模式匹配失败，尝试使用第二种模式
                                                                        xml_match = xml_debug_pattern2.search(lines[i])

                                                                    if xml_match:
                                                                        xml_content = xml_match.group(1)
                                                                        logger.debug(f"[chat_channel] 在文件 {log_file} 中找到XML内容，长度: {len(xml_content)}")
                                                                        break

                                                            # 如果在当前日志文件中找到了XML内容，就不再继续查找
                                                            if xml_content:
                                                                break
                                                        except Exception as e:
                                                            logger.error(f"[chat_channel] 读取日志文件 {log_file} 异常: {e}")
                                                            continue

                                                if xml_content:
                                                    # 从XML内容中提取cdnthumburl
                                                    cdnthumburl_match = re.search(r'cdnthumburl="([^"]*)"', xml_content)
                                                    if cdnthumburl_match:
                                                        image_url = cdnthumburl_match.group(1)
                                                        logger.debug(f"[chat_channel] 从XML内容中提取到cdnthumburl: {image_url}")
                                                        context["quoted_image_url"] = image_url

                                                        # 提取length（图片大小）
                                                        length_match = re.search(r'length="([^"]*)"', xml_content)
                                                        if length_match:
                                                            length = length_match.group(1)
                                                            logger.debug(f"[chat_channel] 从XML内容中提取到length: {length}")
                                                            context["quoted_image_length"] = length

                                                        # 提取svrid（消息ID）
                                                        svrid_match = re.search(r'<svrid>(.*?)</svrid>', xml_content)
                                                        if svrid_match:
                                                            svrid = svrid_match.group(1)
                                                            logger.debug(f"[chat_channel] 从XML内容中提取到svrid: {svrid}")
                                                            context["quoted_message"]["svrid"] = svrid
                                                            context["quoted_message"]["NewMsgId"] = svrid

                                                            # 获取群ID
                                                            group_id = context.kwargs.get("group_id")
                                                            fromusr_match = re.search(r'<fromusr>(.*?)</fromusr>', xml_content)
                                                            if fromusr_match:
                                                                group_id = fromusr_match.group(1)
                                                                logger.debug(f"[chat_channel] 从XML内容中提取到fromusr: {group_id}")

                                                            # 提取图片大小
                                                            length_match = re.search(r'length="([^"]*)"', xml_content)
                                                            data_len = 345519  # 默认大小
                                                            if length_match:
                                                                try:
                                                                    data_len = int(length_match.group(1))
                                                                    logger.debug(f"[chat_channel] 从XML内容中提取到length: {data_len}")
                                                                except ValueError:
                                                                    logger.error(f"[chat_channel] 无法将length转换为整数: {length_match.group(1)}")

                                                            # 这里需要调用channel对象的方法来下载图片
                                                            if "channel" in context.kwargs and hasattr(context.kwargs["channel"], "download_image"):
                                                                # 将提取到的参数传递给download_image方法
                                                                # 修改wx849_channel.py中的download_image方法，使其使用传入的data_len
                                                                setattr(context.kwargs["channel"], "data_len", data_len)  # 保存图片大小供download_image方法使用
                                                                image_path = context.kwargs["channel"].download_image(svrid, group_id)
                                                                if image_path and os.path.exists(image_path):
                                                                    logger.debug(f"[chat_channel] 成功使用消息ID下载图片: {image_path}")
                                                                    context["quoted_image_path"] = image_path
                                                                    # 使用已经导入的Reply和ReplyType
                                                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，已下载]"
                                                                    return Reply(ReplyType.TEXT, enhanced_content)
                                                                else:
                                                                    logger.error(f"[chat_channel] 使用消息ID下载图片失败")
                                                            else:
                                                                logger.error(f"[chat_channel] 无法使用消息ID下载图片，channel对象不可用或没有download_image方法")

                                                        logger.debug(f"[chat_channel] 从XML内容中提取到cdnthumburl")
                                            except Exception as e:
                                                logger.error(f"[chat_channel] 查找XML内容异常: {e}")

                                        if cdnthumburl_match:
                                            image_url = cdnthumburl_match.group(1)
                                            logger.debug(f"[chat_channel] 从原始日志行中提取到cdnthumburl: {image_url}")
                                            context["quoted_image_url"] = image_url

                                            # 下载图片
                                            try:
                                                # 创建临时目录
                                                import os
                                                import tempfile
                                                import requests
                                                import uuid

                                                # 创建临时文件名
                                                temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tmp")
                                                if not os.path.exists(temp_dir):
                                                    os.makedirs(temp_dir)

                                                # 生成唯一的文件名
                                                image_filename = f"quoted_image_{uuid.uuid4().hex}.jpg"
                                                image_path = os.path.join(temp_dir, image_filename)

                                                # 下载图片
                                                logger.debug(f"[chat_channel] 尝试下载引用图片: {image_url}")
                                                response = requests.get(image_url, timeout=10)
                                                if response.status_code == 200:
                                                    with open(image_path, 'wb') as f:
                                                        f.write(response.content)
                                                    logger.debug(f"[chat_channel] 成功下载引用图片: {image_path}")

                                                    # 添加图片路径到上下文
                                                    context["quoted_image_path"] = image_path
                                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，已下载]"
                                                else:
                                                    logger.error(f"[chat_channel] 下载引用图片失败，状态码: {response.status_code}")
                                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，但下载失败]"
                                            except Exception as e:
                                                logger.error(f"[chat_channel] 下载引用图片异常: {e}")
                                                enhanced_content = f"{context.content}\n\n[引用了一张图片，但处理过程中出错]"
                                        else:
                                            enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法获取图片URL]"
                                            logger.debug(f"[chat_channel] 增强消息内容，添加图片引用信息(无URL): {enhanced_content}")
                                    except Exception as e:
                                        logger.error(f"[chat_channel] 从原始日志行中提取图片信息失败: {e}")
                                        enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法提取图片信息]"
                                else:
                                    enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法获取消息ID或图片URL]"
                                    logger.debug(f"[chat_channel] 增强消息内容，添加图片引用信息(无消息ID或URL): {enhanced_content}")
                        else:
                            enhanced_content = f"{context.content}\n\n[引用了一张图片，但无法获取图片URL或消息ID]"
                            logger.debug(f"[chat_channel] 增强消息内容，添加图片引用信息(无URL或消息ID): {enhanced_content}")
                    # 如果引用的是文本消息
                    elif quoted_content and quoted_nickname:
                        enhanced_content = f"{context.content}\n\n引用 {quoted_nickname} 的消息: \"{quoted_content}\""
                        logger.debug(f"[chat_channel] 增强消息内容，添加引用信息: {enhanced_content}")

                    # 创建一个新的文本类型上下文
                    text_context = self._compose_context(ContextType.TEXT, enhanced_content, **context.kwargs)
                    if text_context:
                        # 使用文本处理逻辑处理消息
                        reply = super().build_reply_content(text_context.content, text_context)
                    else:
                        logger.error("[chat_channel] 创建文本上下文失败")
                else:
                    # 如果不是@机器人的消息，不处理
                    logger.debug("[chat_channel] 忽略非@机器人的XML消息")
                    pass
            else:
                logger.warning("[chat_channel] unknown context type: {}".format(context.type))
                return
        return reply

    def _decorate_reply(self, context: Context, reply: Reply) -> Reply:
        if reply and reply.type:
            e_context = PluginManager().emit_event(
                EventContext(
                    Event.ON_DECORATE_REPLY,
                    {"channel": self, "context": context, "reply": reply},
                )
            )
            reply = e_context["reply"]
            desire_rtype = context.get("desire_rtype")
            if not e_context.is_pass() and reply and reply.type:
                if reply.type in self.NOT_SUPPORT_REPLYTYPE:
                    logger.error("[chat_channel]reply type not support: " + str(reply.type))
                    reply.type = ReplyType.ERROR
                    reply.content = "不支持发送的消息类型: " + str(reply.type)

                if reply.type == ReplyType.TEXT:
                    reply_text = reply.content
                    if desire_rtype == ReplyType.VOICE and ReplyType.VOICE not in self.NOT_SUPPORT_REPLYTYPE:
                        reply = super().build_text_to_voice(reply.content)
                        return self._decorate_reply(context, reply)
                    if context.get("isgroup", False):
                        # 不再添加@前缀，因为我们使用API的At参数来实现@功能
                        # 只添加配置的前缀和后缀
                        reply_text = conf().get("group_chat_reply_prefix", "") + reply_text.strip() + conf().get(
                            "group_chat_reply_suffix", "")
                    else:
                        reply_text = conf().get("single_chat_reply_prefix", "") + reply_text + conf().get(
                            "single_chat_reply_suffix", "")
                    reply.content = reply_text
                elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
                    reply.content = "[" + str(reply.type) + "]\n" + reply.content
                elif reply.type == ReplyType.IMAGE_URL or reply.type == ReplyType.VOICE or reply.type == ReplyType.IMAGE or reply.type == ReplyType.FILE or reply.type == ReplyType.VIDEO or reply.type == ReplyType.VIDEO_URL:
                    pass
                elif reply.type == ReplyType.ACCEPT_FRIEND:
                    pass
                else:
                    logger.error("[chat_channel] unknown reply type: {}".format(reply.type))
                    return
            if desire_rtype and desire_rtype != reply.type and reply.type not in [ReplyType.ERROR, ReplyType.INFO]:
                logger.warning("[chat_channel] desire_rtype: {}, but reply type: {}".format(context.get("desire_rtype"), reply.type))
            return reply

    def _send_reply(self, context: Context, reply: Reply):
        if reply and reply.type:
            e_context = PluginManager().emit_event(
                EventContext(
                    Event.ON_SEND_REPLY,
                    {"channel": self, "context": context, "reply": reply},
                )
            )
            reply = e_context["reply"]
            if not e_context.is_pass() and reply and reply.type:
                logger.debug("[chat_channel] ready to send reply: {}, context: {}".format(reply, context))
                self._send(reply, context)

    def _send(self, reply: Reply, context: Context, retry_cnt=0):
        try:
            self.send(reply, context)
        except Exception as e:
            logger.error("[chat_channel] sendMsg error: {}".format(str(e)))
            if isinstance(e, NotImplementedError):
                return
            logger.exception(e)
            if retry_cnt < 2:
                time.sleep(3 + 3 * retry_cnt)
                self._send(reply, context, retry_cnt + 1)

    # 处理好友申请
    def _build_friend_request_reply(self, context):
        if isinstance(context.content, dict) and "Content" in context.content:
            logger.info("friend request content: {}".format(context.content["Content"]))
            if context.content["Content"] in conf().get("accept_friend_commands", []):
                return Reply(type=ReplyType.ACCEPT_FRIEND, content=True)
            else:
                return Reply(type=ReplyType.ACCEPT_FRIEND, content=False)
        else:
            logger.error("Invalid context content: {}".format(context.content))
            return None

    def _success_callback(self, session_id, **kwargs):  # 线程正常结束时的回调函数
        logger.debug("Worker return success, session_id = {}".format(session_id))

    def _fail_callback(self, session_id, exception, **kwargs):  # 线程异常结束时的回调函数
        logger.exception("Worker return exception: {}".format(exception))

    def _thread_pool_callback(self, session_id, **kwargs):
        def func(worker: Future):
            try:
                worker_exception = worker.exception()
                if worker_exception:
                    self._fail_callback(session_id, exception=worker_exception, **kwargs)
                else:
                    self._success_callback(session_id, **kwargs)
            except CancelledError as e:
                logger.info("Worker cancelled, session_id = {}".format(session_id))
            except Exception as e:
                logger.exception("Worker raise exception: {}".format(e))
            with self.lock:
                self.sessions[session_id][1].release()

        return func

    def produce(self, context: Context):
        session_id = context.get("session_id", 0)
        with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = [
                    Dequeue(),
                    threading.BoundedSemaphore(conf().get("concurrency_in_session", 4)),
                ]
            if context.type == ContextType.TEXT and context.content.startswith("#"):
                self.sessions[session_id][0].putleft(context)  # 优先处理管理命令
            else:
                self.sessions[session_id][0].put(context)

    # 消费者函数，单独线程，用于从消息队列中取出消息并处理
    def consume(self):
        while True:
            with self.lock:
                session_ids = list(self.sessions.keys())
            for session_id in session_ids:
                with self.lock:
                    context_queue, semaphore = self.sessions[session_id]
                if semaphore.acquire(blocking=False):  # 等线程处理完毕才能删除
                    if not context_queue.empty():
                        context = context_queue.get()
                        logger.debug("[chat_channel] consume context: {}".format(context))
                        future: Future = handler_pool.submit(self._handle, context)
                        future.add_done_callback(self._thread_pool_callback(session_id, context=context))
                        with self.lock:
                            if session_id not in self.futures:
                                self.futures[session_id] = []
                            self.futures[session_id].append(future)
                    elif semaphore._initial_value == semaphore._value + 1:  # 除了当前，没有任务再申请到信号量，说明所有任务都处理完毕
                        with self.lock:
                            self.futures[session_id] = [t for t in self.futures[session_id] if not t.done()]
                            assert len(self.futures[session_id]) == 0, "thread pool error"
                            del self.sessions[session_id]
                    else:
                        semaphore.release()
            time.sleep(0.2)

    # 取消session_id对应的所有任务，只能取消排队的消息和已提交线程池但未执行的任务
    def cancel_session(self, session_id):
        with self.lock:
            if session_id in self.sessions:
                for future in self.futures[session_id]:
                    future.cancel()
                cnt = self.sessions[session_id][0].qsize()
                if cnt > 0:
                    logger.info("Cancel {} messages in session {}".format(cnt, session_id))
                self.sessions[session_id][0] = Dequeue()

    def cancel_all_session(self):
        with self.lock:
            for session_id in self.sessions:
                for future in self.futures[session_id]:
                    future.cancel()
                cnt = self.sessions[session_id][0].qsize()
                if cnt > 0:
                    logger.info("Cancel {} messages in session {}".format(cnt, session_id))
                self.sessions[session_id][0] = Dequeue()


def check_prefix(content, prefix_list):
    if not prefix_list:
        return None
    for prefix in prefix_list:
        if content.startswith(prefix):
            return prefix
    return None


def check_contain(content, keyword_list):
    if not keyword_list:
        return None
    for ky in keyword_list:
        if content.find(ky) != -1:
            return True
    return None
