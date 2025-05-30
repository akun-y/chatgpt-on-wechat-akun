"""
Google gemini bot

@author zhayujie
@Date 2023/12/15
"""
# encoding:utf-8

from bot.bot import Bot
import google.generativeai as genai
from bot.gemini.google_genimi_vision import GeminiVision

from bot.session_manager import SessionManager
from bridge.context import ContextType, Context
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from bot.baidu.baidu_wenxin_session import BaiduWenxinSession
import os
os.environ["http_proxy"] = "http://127.0.0.1:7890"
os.environ["https_proxy"] = "http://127.0.0.1:7890"
# OpenAI对话模型API (可用)
class GoogleGeminiBot(Bot,GeminiVision):

    def __init__(self):
        super().__init__()
        self.api_key = conf().get("gemini_api_key")
        # 复用文心的token计算方式
        self.sessions = SessionManager(BaiduWenxinSession, model=conf().get("model") or "gpt-3.5-turbo")
        self.model = conf().get("model") or "gemini-pro"
        if self.model == "gemini":
            self.model = "gemini-pro"
    def reply(self, query, context: Context = None) -> Reply:
        try:
            if context.type != ContextType.TEXT:
                logger.warn(f"[Gemini] Unsupported message type, type={context.type}")
                return Reply(ReplyType.TEXT, None)
            logger.info(f"[Gemini] query={query}")
            session_id = context["session_id"]
            session = self.sessions.session_query(query, session_id)
            gemini_messages = self._convert_to_gemini_messages(self._filter_messages(session.messages))

            vision_res = self.do_vision_completion_if_need(session_id,query) # Image recongnition and vision completion
            if vision_res:
                return vision_res

            genai.configure(api_key=self.api_key,transport='rest')
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(gemini_messages)
            reply_text = self.remove_markdown(response.text)
            self.sessions.session_reply(reply_text, session_id)
            logger.info(f"[Gemini] reply={reply_text}")
            return Reply(ReplyType.TEXT, reply_text)
        except Exception as e:
            logger.error("[Gemini] fetch reply error, may contain unsafe content")
            logger.error(e)


    def remove_markdown(self, text):
        # 替换Markdown的粗体标记
        text = text.replace("**", "")
        # 替换Markdown的标题标记
        text = text.replace("### ", "").replace("## ", "").replace("# ", "")
        return text

    def _convert_to_gemini_messages(self, messages: list):
        res = []
        for msg in messages:
            if msg.get("role") == "user":
                role = "user"
            elif msg.get("role") == "assistant":
                role = "model"
            else:
                continue
            res.append({
                "role": role,
                "parts": [{"text": msg.get("content")}]
            })
        return res

    def _filter_messages(self, messages: list):
        res = []
        turn = "user"
        if not messages:
            return res
        for i in range(len(messages) - 1, -1, -1):
            message = messages[i]
            if message.get("role") != turn:
                continue
            res.insert(0, message)
            if turn == "user":
                turn = "assistant"
            elif turn == "assistant":
                turn = "user"
        return res