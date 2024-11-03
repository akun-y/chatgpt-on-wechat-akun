import os
import re
import time
import xml.etree.ElementTree as ET

import requests
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.wcferry.wcferry_run import load_json_from_file, save_json_to_file
from common.log import logger
from time import sleep

def process_payment_info(text):
    # 将文本按行分割，以便处理
    lines = text.split("\n")
    # 检查文本行数是否足够
    if len(lines) >= 3:
        # 选取前两行
        result_lines = lines[:2]
        # 检查第二行是否包含特定关键字
        if "付款方备注" in result_lines[1]:
            # 只返回前两行
            return "\n".join(result_lines)
        elif "来自" in result_lines[1]:
            # 返回前三行
            return "\n".join(lines[:3])
    # 如果文本行数不符合要求，返回原始文本
    return text


def get_emoji_file(xmlContent):
    root = ET.XML(xmlContent)
    emoji = root.find("emoji")
    url = emoji.get("cdnurl")
    filename = emoji.get("md5")
    if url is None or filename is None:
        path = "发送了一张本地图片"
    else:
        # 将表情下载到emoji文件夹下
        path = os.path.join(os.getcwd(), "tmp", "emoji")
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, filename)
        if not os.path.exists(path):
            # 下载文件并设置超时时间
            # 发送 GET 请求
            try:
                # 连接在10秒后超时，读取在20秒后超时,即使设置了超时个别机器依旧会长时间无反应，导致后续无法再接收信息
                logger.info(f"开始下载emoji文件:{url}")
                with requests.get(url, stream=True, timeout=(10, 20)) as response:
                    response.raise_for_status()  # 检查请求是否成功

                    # 下载文件
                    with open(path, "wb") as file:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:  # 过滤掉保持连接的chunk
                                file.write(chunk)
                print(f"EMOJI文件已下载到：{path}")
            except requests.exceptions.HTTPError as e:
                print(f"HTTP 错误：{e}")
            except requests.exceptions.ConnectionError as e:
                print(f"连接错误：{e}")
            except requests.exceptions.Timeout as e:
                print(f"请求超时：{e}")
            except requests.exceptions.RequestException as e:
                print(f"请求异常：{e}")
            exist = False
        else:
            exist = True

    return path


# 获取邀请进群人员列表
def extract_invite_names(text: str) -> list:
    """获取邀请进群人员列表

    Args:
        text (str): 邀请进群的文本内容

    Returns:
        list: 邀请进群人员列表
    """
    # 正则表达式模式，匹配不同的邀请格式
    pattern = r'"(.*?)"邀请(?:你和)?"(.+?)"加入了群聊'

    # 使用正则表达式查找所有匹配项
    matches = re.findall(pattern, text)

    # 初始化结果列表
    results = []

    # 遍历所有匹配项
    for inviter, invitees in matches:
        # 判断invitees是否包含逗号，如果有，说明有多个被邀请者
        if "、" in invitees:
            # 分割多个被邀请者
            invitees_list = invitees.split("、")
        else:
            invitees_list = [invitees]

        # 添加邀请人和被邀请者到结果列表
        results.append(inviter)
        results.extend(invitees_list)

    return results


# # 测试函数
# texts = [
#     '"扁鵲子"邀请你和"狮子座、会更丰富"加入了群聊',
#     '"张三"邀请"狮子座、会更丰富"加入了群聊',
#     '"张三"邀请"狮子座"加入了群聊',
#     '"张三"邀请你加入了群聊',
#     '我邀请"狮子座、会更丰富"加入了群聊'
# ]

# for text in texts:
#     print(extract_names(text))


# 获取双引号之间的内容
def extract_quoted_content(text: str) -> list:
    """提取字符串中双引号之间的内容。

    Args:
        text (str): 包含要提取内容的字符串。

    Returns:
        list: 双引号之间的内容列表。
    """
    # 正则表达式模式，用于匹配双引号之间的内容
    pattern = r"\"(.*?)\""
    # 使用 re.findall 提取所有匹配的内容
    return re.findall(pattern, text)


# 从超链接中提取herf和 text
def extrat_herf_content(text: str) -> list:
    pattern = r'<a href="([^"]*)">(.*?)</a>'

    matches = re.findall(pattern, text)

    result = []
    for href, text in matches:
        result.append(href)
        result.append(text)
    return result


def ensure_file_ready(file_path, timeout=10, interval=0.5):
    """确保文件可读。

    :param file_path: 文件路径。
    :param timeout: 超时时间，单位为秒。
    :param interval: 检查间隔，单位为秒。
    :return: 文件是否可读。
    """
    start_time = time.time()
    while True:
        if os.path.exists(file_path) and os.access(file_path, os.R_OK):
            return True
        elif time.time() - start_time > timeout:
            return False
        else:
            time.sleep(interval)


# def get_display_name_or_nickname(room_members, group_wxid, wxid):
#     try:
#         if group_wxid in room_members:
#             members = room_members[group_wxid]
#             for member_id in members.get(wxid, ""):
#                 member = members[wxid]
#                 return (
#                     member["display_name"]
#                     if member["display_name"]
#                     else member["nickname"]
#                 )
#     except Exception as e:
#         logger.error(f"Error occurred while getting display name or nickname: {e}")
#     return None  # 如果没有找到对应的group_wxid或wxid，则返回None


class WcFerryMessage(ChatMessage):
    def __init__(self, channel, scf, wechat_msg):
        try:
            super().__init__(wechat_msg)
            self.msg_id = wechat_msg.id
            self.create_time = wechat_msg.ts
            self.is_group = wechat_msg._is_group
            self.my_msg = wechat_msg._is_self
            self.scf = scf
            self.channel = channel

            # 获取一些可能多次使用的值
            self.login_info = self.scf.get_user_info()
            self.nickname = self.login_info["name"]
            self.user_id = self.login_info["wxid"]

            self.tmp_dir = os.path.join(os.getcwd(), "tmp")
            # 从文件读取数据，并构建以 wxid 为键的字典
            # contracts = self.channel.contacts
            data = wechat_msg
            self.from_user_id = data.sender

            if self.is_group:
                self.actual_user_nickname = self.channel.get_room_member_name(
                    data.roomid, data.sender
                )
                self.actual_user_id = data.sender
                self.from_user_nickname = self.channel.get_room_name(data.roomid)

                self.from_user_id = data.roomid

                self.other_user_nickname = self.from_user_nickname
                self.other_user_id = data.roomid
            else:
                self.from_user_nickname = self.channel.get_user_name(data.sender)
                self.actual_user_id = self.from_user_id
                self.actual_user_nickname = self.from_user_nickname

                self.other_user_nickname = self.from_user_nickname
                self.other_user_id = self.from_user_id

            self.to_user_id = self.user_id
            self.to_user_nickname = self.nickname
            # print(wechat_msg)  ##重要，检查type数字类型，查看xml内容参数时用
            if wechat_msg.type == 1:  # 文本消息类型
                if "gh_" in self.other_user_id:
                    self.ctype = ContextType.MP
                    self.content = data.content
                else:
                    self.ctype = ContextType.TEXT
                    self.content = data.content
            elif wechat_msg.type == 3:  # 需要缓存文件的消息类型-akun
                sleep(2)
                ret = self.scf.download_attach(data.id, "", data.extra)
                if ret == 0:
                    img_dir = os.path.join(self.tmp_dir, "images")
                    if not os.path.exists(img_dir):
                        os.makedirs(img_dir)
                    cnt = 0
                    while cnt < 30:
                        image_path = self.scf.decrypt_image(data.extra, img_dir)
                        if image_path:
                            self.ctype = ContextType.IMAGE
                            self.content = image_path # 成功获取了图片,content为图片路径
                            self._prepare_fn = lambda: None
                            break
                        sleep(1)
                        cnt += 1
                    if cnt >= 30:
                        logger.error(f"下载图片附件超时:{self.from_user_nickname} {self.actual_user_nickname}")
                    if not image_path:
                        self.ctype = ContextType.IMAGE
                        self.content = data.extra
                        logger.error(f"下载图片附件失败:{self.from_user_nickname} {self.actual_user_nickname}")
                else:
                    logger.error(f"下载图片附件失败2:{self.from_user_nickname} {self.actual_user_nickname}")
                    self.ctype = ContextType.IMAGE
                    self.content = data.extra
            elif wechat_msg.type == 34:  # 语音 akun
                # <msg><voicemsg endflag="1" cancelflag="0" forwardflag="0" voiceformat="4" voicelength="5176" length="8192" bufid="0" aeskey="333e54675198949dbbf281d2c580d0e5" voiceurl="3052020100044b30490201000204a3d6065c02032f56c3020415bead27020467025a86042430343339323339342d663433382d343333382d616632632d66373134336130373239366602040524000f0201000400588fffe3" voicemd5="" clientmsgid="41323231303163643938353964363400091738100624ec9355feae1104" fromusername="a37259705" /></msg>
                self.ctype = ContextType.VOICE
                self.content = data.content
            elif wechat_msg.type == 42:  # 公众号名片: akun
                #'<?xml version="1.0"?>\n<msg bigheadimgurl="http://wx.qlogo.cn/mmhead/aXUpZVUYfjxV6vZTDtAibfQ1vibiaWmwlvc26srXzbhtiaqY4jdGnPicGKlDSibvZ9IgV3jWeicBic5xXW8/0" smallheadimgurl="http://wx.qlogo.cn/mmhead/aXUpZVUYfjxV6vZTDtAibfQ1vibiaWmwlvc26srXzbhtiaqY4jdGnPicGKlDSibvZ9IgV3jWeicBic5xXW8/132" username="v3_020b3826fd0301000000000099a40b2be66ec4000000501ea9a3dba12f95f6b60a0536a1adb6cdf025fdfbff48a06d15a45a651629aed94bd29def619c5ad162a2b065ffc4ce1a75e2c30aa485503a2b46@stranger" nickname="熊猫侠户外" fullpy="" shortpy="" alias="" imagestatus="4" scene="17" province="浙江" city="中国大陆" sign="" sex="0" certflag="24" certinfo="杭州牧羽科技有限公司" brandIconUrl="http://mmbiz.qpic.cn/mmbiz_png/zibWicGL4mP95LibJQicZ2RWheGn8y8Yst4Hd0B4MptyjT3ewPzlxMCGQ7kNSFW5xPGicUGMJtBpJOiboY3x8RFjqsjg/0?wx_fmt=png" brandHomeUrl="" brandSubscriptConfigUrl="{&quot;urls&quot;:[{&quot;title&quot;:&quot;查看历史消息&quot;,&quot;url&quot;:&quot;http:\\/\\/mp.weixin.qq.com\\/mp\\/getmasssendmsg?__biz=MzUxNzYxNTk5Nw==#wechat_webview_type=1&amp;wechat_redirect&quot;,&quot;title_key&quot;:&quot;__mp_wording__brandinfo_history_massmsg&quot;},{&quot;title&quot;:&quot;查看地理位置&quot;,&quot;url&quot;:&quot;http:\\/\\/3gimg.qq.com\\/lightmap\\/v1\\/wxmarker\\/index.html?marker=coord:30.2460250854,120.210792542;title:%E7%86%8A%E7%8C%AB%E4%BE%A0%E6%88%B7%E5%A4%96;addr:%E6%B5%99%E6%B1%9F%E7%9C%81%E6%9D%AD%E5%B7%9E%E5%B8%82&amp;referer=wexinmp_profile&quot;,&quot;title_key&quot;:&quot;__mp_wording__brandinfo_location&quot;}]}" brandFlags="0" regionCode="CN_Zhejiang_Hangzhou" biznamecardinfo="ClRDZy9uaG9ybmpLdmt2cURtaUxmbHBKWVFHQm9BSWdFeEtOZUNuTFlHTWc5bmFGOWtaREUzWlRRM1ltWmtOMk02REZFeWIwZzFlRVUyWVdGdmN3PT0SeEFBZm1QY3dFQUFBQkFBQUFBQUJTWW5UVkJyMDhVRVU4VndISFppQUFBQUJ0RU5zTk9RK0MyNDVkMnBxS05QQlFmUWpVd09kdE5SQmhYc005eE90YTFtaVlhRDE5ck02bnQxU2ZjSVAxNEVWWUVqUDlhWjkzeWRSUg==" antispamticket="v4_000b708f0b04000001000000000006877be1eed14fcf4c67b209c7661000000050ded0b020927e3c97896a09d47e6e9e36d3ecbeff6ec13f1f53e4b83d9542d5d74182bb149b84553be6bce83c12e6343a9748714ea2981b00b99dfcfba26709ab48b1eae8f858b7d43161d9ab8309834028b519d41878bc16a72627fd398ebedece0f524508e27767a23f81c9ca33452ebfa4f7b0f74fd82c9eab99e4b14648ada57c4acf2e1fe0f89153b880281862a55e2ac52e12d3be0397c7bf438db4eb0b1b24dd9c925a7b7e8942943e01b465a7dd6b08b65cddcbf6e59d542f467e7b3172d03c82db8c6ddf8274ea758891dbcd0d0689ced4874484748457df6e7e1acfa010cceb0e07@stranger" />\n'
                self.ctype = ContextType.CARD
                self.content = data.content
            elif wechat_msg.type == 43:  # 引用消息类型: akun
                self.proc_quoted_wechat_msg(data)
            elif wechat_msg.type == 47:  # 需要缓存文件的消息类型---表情图片-akun
                self.ctype = ContextType.EMOJI
                # 下載超時，導致所有消息沒法接收
                # emoji_path = get_emoji_file(data.content)
                self.content = data.content
                self._prepare_fn = lambda: None
                if self.is_group:
                    self.from_user_nickname = self.channel.get_room_name(data.roomid)
                    # room_members = load_json_from_file(
                    #     directory, "wcferry_room_members.json"
                    # )
                    # self.from_user_nickname = get_display_name_or_nickname(
                    #     room_members, data.roomid, self.from_user_id
                    # )
            elif wechat_msg.type == 48:  # 需要缓存文件的消息类型
                #  <msg>
                #     <location x="28.778109" y="119.887352" scale="14" label="武义县" maptype="0" poiname="武义县泉溪镇丰溪村"
                # poiid="nearby_17630017737957653025" buildingId="" floorName=""
                # poiCategoryTips="" poiBusinessHour=""
                # poiPhone=""
                # poiPriceTips="0.0"
                # isFromPoiList="false" adcode="" cityname="" fromusername="a6666k" />
                # </msg>
                self.ctype = ContextType.XML
                xml = ET.XML(data.content)
                location = xml.find("location")
                self.content = location.get("label") + " " + location.get("poiname")
                # self.content = data.extra
            elif wechat_msg.type == 49:  # 需要缓存文件的消息类型
                self.ctype = ContextType.FILE
                self.content = data.extra
            elif wechat_msg.type == 11048:  # 需要缓存文件的消息类型
                self.ctype = ContextType.VOICE
                self.content = data.get("mp3_file")
                self._prepare_fn = lambda: None
            elif wechat_msg.type == 11050:  # 需要缓存的微信名片消息类型
                raw_msg = data["raw_msg"]
                self.ctype = ContextType.CARD
                self.content = raw_msg
            elif wechat_msg.type == 11051:  # 需要缓存文件的消息类型
                self.ctype = ContextType.VIDEO
                self.content = data.get("video")

            elif wechat_msg.type == 11054:  # 分享链接消息类型
                xmlContent = data["raw_msg"]
                from_wxid = data["from_wxid"]
                root = ET.XML(xmlContent)
                appmsg = root.find("appmsg")
                msg = appmsg.find("des")
                # type = appmsg.find("type")
                name = root.find(".//mmreader/category/name")
                name_text = name.text if name is not None else None
                if "gh_" in from_wxid and name_text != "微信支付":
                    self.ctype = (
                        ContextType.MP_LINK
                    )  # 关注的公众号主动推送的文章链接类型
                    self.content = xmlContent
                elif name_text == "微信支付":
                    self.content = process_payment_info(msg.text)
                    self.ctype = ContextType.WCPAY  # 微信扫码支付成功通知
                else:
                    self.ctype = ContextType.SHARING  # 用户转发分享的文章链接类型
                    self.content = re.findall(r"<url>(.*?)<\/url>", xmlContent)[0]

            elif wechat_msg.type == 11056:  # 小程序类型
                raw_msg = data["raw_msg"]
                self.ctype = ContextType.MINIAPP
                self.content = raw_msg
            elif wechat_msg.type == 11058:  # 系统消息类型

                self.content = data.get("raw_msg")
                if "移出了群聊" in self.content:
                    pattern = r'"(.*?)"'
                    match = re.search(pattern, data["raw_msg"])
                    if match:
                        self.nickname = match.group(1)
                    else:
                        self.nickname = "None"
                    self.content = f"{self.nickname} 因违反群内规则，已被踢出群聊！"
                    self.ctype = ContextType.EXIT_GROUP
                else:
                    self.ctype = ContextType.SYSTEM
            elif wechat_msg.type == 11060:  # 未知消息类型
                raw_msg = data["raw_msg"]
                self.ctype = ContextType.SYSTEM
                self.content = raw_msg

            elif wechat_msg.type == 10000:  #  系统消息
                self.proc_sys_wechat_msg(data)
            else:
                logger.error(
                    f"未处理的微信消息类型: Type: {wechat_msg.type} MsgType: {wechat_msg}"
                )
                raise NotImplementedError(
                    "Unsupported message type: Type:{} MsgType:{}".format(
                        wechat_msg.type, wechat_msg.type
                    )
                )

            if self.is_group:
                # 群名
                self.other_user_nickname = self.channel.get_room_name(data.roomid)
                self.other_user_id = data.roomid

                # room_info = get_room_info(wework=wework, conversation_id=conversation_id)
                at_list = getattr(data, 'at_list', [])
                self.is_at = self.user_id in at_list
                if self.is_at:
                    logger.info(f"收到is_at群消息:{self.user_id}")
                else:
                    content = data.content or ""
                    pattern = f"@{re.escape(self.nickname)}(\u2005|\u0020)"
                    self.is_at |= bool(re.search(pattern, content))
                    if self.is_at:
                        logger.info(f"收到is_at群消息:{self.nickname}")
                        self.content = re.sub(pattern, '', content)
                    else:
                        # bot在该群中的别名
                        user_name_in_group = self.channel.get_room_member_name(
                            data.roomid, self.user_id
                        )
                        pattern = f"@{re.escape(user_name_in_group)}(\u2005|\u0020)"
                        self.is_at |= bool(re.search(pattern, content))
                        if self.is_at:
                            logger.info(f"收到is_at群消息:{user_name_in_group}")
                            self.content = re.sub(pattern, '', content)

            logger.debug(
                f"WcFerryMessage has be en successfully instantiated with message id: {self.msg_id}"
            )
        except Exception as e:
            logger.error(f"在 WechatMessage 的初始化过程中出现错误：{e} {data.content}")
            raise e

    def proc_sys_wechat_msg(self, data):
        self.actual_user_nickname = self.channel.get_user_name(self.from_user_id)
        if "拍了拍" in data.content:
            self.ctype = ContextType.PATPAT
            self.content = data.content

            names = extract_invite_names(data.content)
            if names and len(names) == 2:
                self.actual_user_id = self.channel.get_room_member_wxid(
                    data.roomid, names[0]
                )
                self.actual_user_nickname = names[0]
                self.to_user_id = self.channel.get_room_member_wxid(
                    data.roomid, names[1]
                )
                self.to_user_nickname = names[1]

            elif "拍了拍我" in data.content:
                logger.warn("拍了拍我")
            else:  # 确保设置 to_user_id,区别与拍的不是我
                logger.warn("拍了拍未知")
                self.to_user_id = ""
                self.to_user_nickname = ""

            logger.info(
                f"【{self.actual_user_nickname}】 ID:{self.actual_user_id}  拍了拍了 【{self.to_user_nickname}】 ID:{self.to_user_id} "
            )

        elif "加入了群聊" in data.content:
            names = extract_invite_names(data.content)
            if names:
                if len(names) >= 2:
                    
                    self.actual_user_id = self.channel.get_room_member_wxid(
                        data.roomid, names[0]
                    ) or self.channel.get_user_wxid_by_name(names[0])
                    self.actual_user_nickname = names[0]
                    self.from_user_id = self.actual_user_id
                    self.from_user_nickname = self.actual_user_nickname

                    _name = names[1]
                    _user_id = self.to_user_id = self.channel.get_room_member_wxid(
                        data.roomid, names[1]
                    ) or self.channel.get_user_wxid_by_name(names[1])
                    
                    self.to_user_id = _user_id
                    self.to_user_nickname = _name
                elif len(names) == 1:
                    _name = names[0]
                    _user_id = self.channel.get_room_member_wxid(
                        data.roomid, _name
                    ) or self.channel.get_user_wxid_by_name(name)
                    
                    self.actual_user_nickname = _name
                    self.actual_user_id = _user_id
                    
                self.channel.add_room_member(data.roomid,_name,_user_id)
                
            self.ctype = ContextType.JOIN_GROUP
            self.content = data.content
            time.sleep(3)  # 確保群名稱已經寫入sqlite
            # save_json_to_file(directory, result, "wcferry_room_members.json")
        elif "移出了群聊" in data.content:
            names = extract_quoted_content(data.content)
            if names:
                if len(names) >= 2:
                    self.actual_user_id = self.channel.get_room_member_wxid(
                        data.roomid, names[0]
                    ) or self.channel.get_user_wxid_by_name(names[0])
                    self.actual_user_nickname = names[0]
                    self.from_user_id = self.actual_user_id
                    self.from_user_nickname = self.actual_user_nickname
                elif len(names) == 1:
                    name = names[0]
                    self.actual_user_nickname = name
                    self.actual_user_id = self.channel.get_room_member_wxid(
                        data.roomid, name
                    ) or self.channel.get_user_wxid_by_name(name)
                    self.from_user_id = self.actual_user_id
                    self.from_user_nickname = self.actual_user_nickname
                self.channel.remove_room_member(data.roomid,self.actual_user_id)
            self.ctype = ContextType.EXIT_GROUP
            self.content = data.content
        elif "与群里其他人都不是朋友关系" in data.content:
            names = extract_quoted_content(data.content)
            if names and len(names) == 1:
                name = names[0]
                self.actual_user_nickname = name
                self.actual_user_id = self.channel.get_room_member_wxid(
                    data.roomid, name
                ) or self.channel.get_user_wxid_by_name(name)
                self.from_user_id = self.actual_user_id
                self.from_user_nickname = self.actual_user_nickname

            self.ctype = ContextType.JOIN_GROUP_PROMPT
            self.content = data.content
        elif "撤回了" in data.content:
            names = extract_quoted_content(data.content)
            if names and len(names) == 1:
                name = names[0]
                self.actual_user_nickname = name
                self.actual_user_id = self.channel.get_room_member_wxid(
                    data.roomid, name
                ) or self.channel.get_user_wxid_by_name(name)
                if self.actual_user_id:
                    self.from_user_id = self.actual_user_id
                    self.from_user_nickname = self.actual_user_nickname

            self.ctype = ContextType.RE_CALL  # 撤回消息
            self.content = data.content
        elif "移除了一条置顶消息" in data.content:
            act_name_list = extrat_herf_content(data.content)
            self.ctype = ContextType.UNSTICK_TOP
            self.content = data.content
            if len(act_name_list) == 2:
                herf = act_name_list[0]
                oper_name = act_name_list[1]
                self.from_user_nickname = oper_name
                self.from_user_id = self.channel.get_room_member_wxid(
                    data.roomid, oper_name
                ) or self.channel.get_user_wxid_by_name(oper_name)
            logger.info(f"收到移除置顶消息:{self.content}")

        elif "置顶了一条消息" in data.content:
            #'"<a href="weixin://link_profile username=wxid_uc0z2quukz0w22">北高峰顶的男人</a>"置顶了一条消息'
            act_name_list = extrat_herf_content(data.content)
            self.ctype = ContextType.STICK_TOP
            self.content = data.content
            if len(act_name_list) == 2:
                herf = act_name_list[0]
                oper_name = act_name_list[1]
                self.from_user_nickname = oper_name
                self.from_user_id = self.channel.get_room_member_wxid(
                    data.roomid, oper_name
                ) or self.channel.get_user_wxid_by_name(oper_name)
            logger.info(f"收到置顶消息:{self.content}")
        elif "收到红包" in data.content:
            self.ctype = ContextType.RECEIVE_RED_PACKET
            self.content = data.content
        elif "群聊邀请确认" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "已成为新群主" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "<videomsg" in data.content and "<msg>" in data.content:
            # 视频信息
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "群收款消息" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "从群管理员中被移除" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "该类型文件可能存在安全风险" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        elif "被添加为群管理员" in data.content:
            act_name_list = extract_quoted_content(data.content)
            self.ctype = ContextType.GROUP_INVITE_CONFIRM_OPEN
            self.content = data.content
        else:  # 未知
            act_name_list = extract_quoted_content(data.content)
            if act_name_list:
                name = act_name_list[0]
                self.actual_user_nickname = name
                self.actual_user_id = self.channel.get_room_member_wxid(
                    data.roomid, name
                ) or self.channel.get_user_wxid_by_name(name)
                self.from_user_id = self.actual_user_id
                self.from_user_nickname = self.actual_user_nickname
                logger.info(f"收到未知消息:{self.content}")
            # self.ctype = ContextType.LEAVE_GROUP
            # self.content = f"{self.actual_user_nickname}退出了群聊！"
            # # 动态删除群成员
            # members = self.rooms[data.roomid]["member_list"]
            # if members and self.actual_user_id in members:
            #     members.remove(self.actual_user_id)
            #     self.rooms[data.roomid]["member_list"] = members

    def proc_quoted_wechat_msg(self, data):
        try:
            # 引用消息,视频号视频,QQ音乐,聊天记录,APP小程序,表情,微信直播,微信服务号
            xmlContent = data.xml

            # 解析XML
            root = ET.fromstring(xmlContent)

            # 获取type
            type = root.find(".//sec_msg_node/type").text

            appmsg = root.find("appmsg")
            if not appmsg:
                logger.error(f"收到引用类消息,未处理:{xmlContent}")
                return
            msg = appmsg.find("title")
            type = appmsg.find("type")
            if type.text == "51":  # 视频号视频
                self.content = xmlContent
                self.ctype = ContextType.WECHAT_VIDEO
            elif type.text == "3":  # QQ音乐
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "4":  # 腾讯为旗下小弟开的特权卡片，b站，小红书等
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "19" or type.text == "40":  # 聊天记录
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "36":  # APP小程序
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "8":  # 表情
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "63":  # 微信直播
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "24":  # 微信收藏
                self.content = xmlContent
                self.ctype = ContextType.XML
            elif type.text == "21":  # 未知
                self.content = xmlContent
                self.ctype = ContextType.XML
            else:
                # 引用消息类型
                refermsg = appmsg.find("refermsg")
                refwxid = refermsg.find("chatusr")
                refname = refermsg.find("displayname")
                refname_text = refname.text
                if refermsg is not None:
                    if self.is_group:
                        # room_members = load_json_from_file(
                        #     directory, "wcferry_room_members.json"
                        # )
                        # self.actual_user_nickname = get_display_name_or_nickname(
                        #     room_members, data.roomid, self.from_user_id
                        # )
                        self.actual_user_nickname = self.channel.get_user_name(
                            self.from_user_ids
                        )
                        self.content = msg.text
                        self.to_user_id = refwxid.text
                        self.ctype = ContextType.QUOTE
                        self.to_user_nickname = refname_text
                        if self.to_user_id is None:
                            self.to_user_id = self.from_user_id
                        print(
                            f"【{self.actual_user_nickname}】 ID:{self.from_user_id}  引用了 【{self.to_user_nickname}】 ID:{self.to_user_id} 的信息并回复 【{self.content}】"
                        )
                else:
                    pass
        except Exception as e:
            logger.error("proc_quoted_wechat_msg:", e)

    # def get_wxid_by_name(self, name):
    #     for item in self.channel.contracts_ary:
    #         if item.get("NickName") == name and item.get("UserName"):
    #             return item.get("UserName")
