# -*- coding: utf-8 -*-#

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf

class WeChatMPMessage(ChatMessage):
    def __init__(self, msg, client=None):
        super().__init__(msg)
        self.msg_id = msg.id
        self.create_time = msg.time
        self.is_group = False
        self.client = client

        if msg.type == "text":
            self.ctype = ContextType.TEXT
            self.content = msg.content
        elif msg.type == "voice":
            if msg.recognition == None:
                self.ctype = ContextType.VOICE
                self.content = TmpDir().path() + msg.media_id + "." + msg.format  # content直接存临时目录路径

                def download_voice():
                    # 如果响应状态码是200，则将响应内容写入本地文件
                    response = client.media.download(msg.media_id)
                    if response.status_code == 200:
                        with open(self.content, "wb") as f:
                            f.write(response.content)
                    else:
                        logger.info(f"[wechatmp] Failed to download voice file, {response.content}")

                self._prepare_fn = download_voice
            else:
                self.ctype = ContextType.TEXT
                self.content = msg.recognition
        elif msg.type == "image":
            self.ctype = ContextType.IMAGE
            self.content = TmpDir().path() + msg.media_id + ".png"  # content直接存临时目录路径

            def download_image():
                # 如果响应状态码是200，则将响应内容写入本地文件
                response = client.media.download(msg.media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechatmp] Failed to download image file, {response.content}")

            self._prepare_fn = download_image
        else:
            raise NotImplementedError("Unsupported message type: Type:{} ".format(msg.type))

        self.from_user_id = msg.source
        self.from_user_nickname = None #self.get_user_name(self.from_user_id)

        
        self.to_user_id = msg.target
        self.to_user_nickname = conf().get("bot_name")

        self.other_user_id = msg.source
        self.other_user_id = msg.source
        
    def get_user_name(self, user_id):
        try:
            # 通过微信公众号API获取用户基本信息,自 2021年12月27日 起不再返回用户的基本信息（如 nickname、headimgurl 等）
            response = self.client.user.get(user_id)
            if response and 'nickname' in response:
                logger.info(f"[wechatmp] Got userinfo for user {user_id}: {response}")
                return response['nickname']
            else:
                logger.warning(f"[wechatmp] Failed to get nickname for user {user_id}")
                return None
        except Exception as e:
            logger.error(f"[wechatmp] Error getting user info: {str(e)}")
            return None