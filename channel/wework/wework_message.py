import datetime
import json
import os
import re
import time
import pilk

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.contact_info import ContactInfo, make_contact_info
from common.log import logger

_ROOMS_CACHE = None
_ROOMS_CACHE_MTIME = None

def load_rooms_cache(file_path):
    global _ROOMS_CACHE, _ROOMS_CACHE_MTIME
    mtime = os.path.getmtime(file_path)
    if _ROOMS_CACHE is not None and _ROOMS_CACHE_MTIME == mtime:
        return _ROOMS_CACHE
    with open(file_path, 'r', encoding='utf-8') as file:
        _ROOMS_CACHE = json.load(file)
        _ROOMS_CACHE_MTIME = mtime
        return _ROOMS_CACHE

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


def get_room_info_from_wework(wework, conversation_id):    
    rooms = wework.get_rooms()
    if not rooms or 'room_list' not in rooms:
        logger.error(f"[wework] 传入的 conversation_id: {conversation_id}")
        logger.error(f"[wework] 获取群信息失败: {rooms}")
        return None
    time.sleep(1)
    logger.warn(f"[wework] 获取所有微信群: {len(rooms['room_list'])}个")
    for room in rooms['room_list']:
        if room['conversation_id'] == conversation_id:
            logger.warn(f"[wework] 获取群信息成功: {room}")
            # 更新本地缓存
            directory = os.path.join(os.getcwd(), "tmp")
            if not os.path.exists(directory):
                os.makedirs(directory)
            file_path = os.path.join(directory, "wework_rooms.json")
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(rooms, file, ensure_ascii=False, indent=4)
            return room
    logger.error(f"[wework] 未找到对应的群信息: {conversation_id}")
    return None

def get_room_info(wework, conversation_id):
    directory = os.path.join(os.getcwd(), "tmp")
    file_path = os.path.join(directory, "wework_rooms.json")
    rooms_data = load_rooms_cache(file_path)

    if 'room_list'  in rooms_data:
        rooms = rooms_data['room_list']
        for room in rooms:
            if room['conversation_id'] == conversation_id:
                logger.info(f"[local] 获取群信息成功: {room}")
                return room
    logger.error(f"[local] 未找到对应的群信息: {conversation_id}")
    return get_room_info_from_wework(wework, conversation_id)


def cdn_download(wework, message, file_name):
    data = message["data"]
    url = data["cdn"]["url"]
    auth_key = data["cdn"]["auth_key"]
    aes_key = data["cdn"]["aes_key"]
    file_size = data["cdn"]["size"]

    # 获取当前工作目录，然后与文件名拼接得到保存路径
    current_dir = os.getcwd()
    save_path = os.path.join(current_dir, "tmp", file_name)

    result = wework.wx_cdn_download(url, auth_key, aes_key, file_size, save_path)
    logger.debug(result)


def c2c_download_and_convert(wework, message, file_name):
    data = message["data"]
    aes_key = data["cdn"]["aes_key"]
    file_size = data["cdn"]["size"]
    file_type = 5
    file_id = data["cdn"]["file_id"]

    current_dir = os.getcwd()
    save_path = os.path.join(current_dir, "tmp", file_name)
    result = wework.c2c_cdn_download(file_id, aes_key, file_size, file_type, save_path)
    logger.debug(result)

    # 在下载完SILK文件之后，立即将其转换为WAV文件
    base_name, _ = os.path.splitext(save_path)
    wav_file = base_name + ".wav"
    pilk.silk_to_wav(save_path, wav_file, rate=24000)


class WeworkMessage(ChatMessage):
    def __init__(self, wework_msg, wework, is_group=False):
        try:
            super().__init__(wework_msg)
            self.msg_id = wework_msg['data'].get('conversation_id', wework_msg['data'].get('room_conversation_id'))
            # 使用.get()防止 'send_time' 键不存在时抛出错误
            self.create_time = wework_msg['data'].get("send_time")
            self.is_group = is_group
            self.wework = wework
            
            if wework_msg["type"] == 11041:  # 文本消息类型
                if any(substring in wework_msg['data']['content'] for substring in ("该消息类型暂不能展示", "不支持的消息类型")):
                    return
                self.ctype = ContextType.TEXT
                self.content = wework_msg['data']['content']
            elif wework_msg["type"] == 11044:  # 语音消息类型，需要缓存文件
                file_name = datetime.datetime.now().strftime('%Y%m%d%H%M%S') + ".silk"
                base_name, _ = os.path.splitext(file_name)
                file_name_2 = base_name + ".wav"
                current_dir = os.getcwd()
                self.ctype = ContextType.VOICE
                self.content = os.path.join(current_dir, "tmp", file_name_2)
                self._prepare_fn = lambda: c2c_download_and_convert(wework, wework_msg, file_name)
            elif wework_msg["type"] == 11042:  # 图片消息类型，需要下载文件
                file_name = datetime.datetime.now().strftime('%Y%m%d%H%M%S') + ".jpg"
                current_dir = os.getcwd()
                self.ctype = ContextType.IMAGE
                self.content = os.path.join(current_dir, "tmp", file_name)
                self._prepare_fn = lambda: cdn_download(wework, wework_msg, file_name)
            elif wework_msg["type"] == 11072:  # 新成员入群通知
                self.ctype = ContextType.JOIN_GROUP
                member_list = wework_msg['data']['member_list']
                self.actual_user_nickname = member_list[0]['name']
                self.actual_user_id = member_list[0]['user_id']
                self.content = f"{self.actual_user_nickname}加入了群聊！"
                directory = os.path.join(os.getcwd(), "tmp")
                rooms = get_with_retry(wework.get_rooms)
                if not rooms:
                    logger.error("更新群信息失败···")
                else:
                    result = {}
                    for room in rooms['room_list']:
                        # 获取聊天室ID
                        room_wxid = room['conversation_id']
                        room_nickname = room['nickname']
                        # 获取聊天室成员
                        room_members = wework.get_room_members(room_wxid)                        
                        room_members['nickname'] = room_nickname
                        
                        logger.info(f"获取聊天室成员: {room_wxid} - {room_nickname} 成员个数: {len(room_members['member_list'])}")
                        # 将聊天室成员保存到结果字典中
                        result[room_wxid] = room_members
                    with open(os.path.join(directory, 'wework_room_members.json'), 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=4)
                    logger.warn("有新成员加入，已自动更新群成员列表缓存！")
            else:
                logger.error(f"不支持的消息类型: {wework_msg['type']}")
                raise NotImplementedError(
                    "Unsupported message type: Type:{} MsgType:{}".format(wework_msg["type"], wework_msg["MsgType"]))

            data = wework_msg['data']
            login_info = self.wework.get_login_info()
            logger.info(f"login_info:{login_info}")
            nickname = login_info['nickname'] or login_info['username']
            user_id = login_info['user_id']

            sender_id = data.get('sender')
            conversation_id = data.get('conversation_id')
            sender_name = data.get("sender_name")

            self.from_user_id = user_id if sender_id == user_id else conversation_id
            self.from_user_nickname = nickname if sender_id == user_id else sender_name
            self.to_user_id = user_id
            self.to_user_nickname = nickname
            self.other_user_nickname = sender_name
            self.other_user_id = conversation_id            

            if self.is_group:
                conversation_id = data.get('conversation_id') or data.get('room_conversation_id')
                self.other_user_id = conversation_id
                if conversation_id:
                    room_info = get_room_info(wework=wework, conversation_id=conversation_id)
                    self.other_user_nickname = room_info.get('nickname', None) if room_info else None
                    at_list = data.get('at_list', [])
                    self.is_at = nickname in at_list
                    logger.info(f"[wework_message]是否@消息？:{nickname} in {at_list}")
                    # 检查消息内容是否包含@用户名。处理复制粘贴的消息，这类消息可能不会触发@通知，但内容中可能包含 "@用户名"。
                    content = data.get('content', '')
                    name = nickname
                    pattern = f"@{re.escape(name)}(?:[\\u2005\\u0020]|$)"
                    if re.search(pattern, content):
                        logger.warn(f"微信消息 {self.msg_id} 包含@ {name}")
                        self.is_at = True

                    if not self.actual_user_id:
                        self.actual_user_id = data.get("sender")
                    self.actual_user_nickname = sender_name if self.ctype != ContextType.JOIN_GROUP else self.actual_user_nickname
                    
                    if self._rawmsg:
                        usr = wework.get_contact_detail(self.actual_user_id)
                        self._rawmsg['sender_info'] = make_contact_info(
                            name=usr.get('username', ''),
                            wxid=usr.get('unionid', ''),
                            alias=usr.get('acctid', ''),
                            avatar=usr.get('avatar', ''),
                            display_name=usr.get('nickname', self.actual_user_nickname),
                            corp_id=usr.get('corp_id', ''),
                            remark=usr.get('remark', ''),
                            real_name=usr.get('real_name', ''),
                            mobile=usr.get('mobile', ''),
                        )
                        logger.debug(f"添加 actual_user_id 用户信息到 _rawmsg: {self._rawmsg}")

                else:
                    logger.error("群聊消息中没有找到 conversation_id 或 room_conversation_id")

            logger.debug(f"WeworkMessage has been successfully instantiated with message id: {self.msg_id}")
        except Exception as e:
            logger.error(f"在 WeworkMessage 的初始化过程中出现错误：{e}")
            raise e
