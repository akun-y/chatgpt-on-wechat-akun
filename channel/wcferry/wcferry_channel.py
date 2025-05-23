import datetime
import hashlib
import io
import json
import os.path
import random
import re
import threading
import uuid
import xml.dom.minidom
import requests
import tempfile
import time

from PIL import Image
from bridge.context import *
from bridge.reply import *
from channel.chat_channel import ChatChannel
from channel.chat_message import ChatMessage
from channel.contact_info import ContactInfo
from channel.wcferry.robot import Robot, __version__
from channel.wcferry.wcferry_message import WcFerryMessage
from common.singleton import singleton
from common.log import logger
from common.time_check import time_checker
from config import conf
from channel.wcferry.wcferry_run import *
from wcferry import Wcf, WxMsg

from channel.wcferry.wcferry_run import save_json_to_file
from wcferry.roomdata_pb2 import RoomData

from plugins.plugin_manager import PluginManager

from typing import TypedDict, Dict

# 下载文件,并压缩图片,使用文件hash进行保存,如果下次遇到相同文件,那就免去下载步骤
def download_and_compress_image(url, filename, quality=80):
    # 确定保存图片的目录
    directory = os.path.join(os.getcwd(), "tmp", "images")
    # 如果目录不存在，则创建目录
    if not os.path.exists(directory):
        os.makedirs(directory)

    # 下载图片
    response = requests.get(url)
    # 打开图片
    image = Image.open(io.BytesIO(response.content))
    # 计算文件哈希
    file_hash = hashlib.sha256(response.content).hexdigest()
    image_path = os.path.join(directory, f"{file_hash}.{image.format}")

    # 检查文件是否已经存在
    if os.path.exists(image_path):
        return image_path

    # 压缩图片并保存
    image.save(image_path,image.format, quality=quality)
    return image_path


def download_video(url, filename):
    # 确定保存视频的目录
    directory = os.path.join(os.getcwd(), "tmp", "videos")
    # 如果目录不存在，则创建目录
    if not os.path.exists(directory):
        os.makedirs(directory)

    # 下载视频
    response = requests.get(url, stream=True)
    # 计算文件哈希
    file_hash = hashlib.sha256(response.content).hexdigest()
    video_path = os.path.join(directory, f"{file_hash}.mp4")
    
    # 检查文件是否已经存在
    if os.path.exists(video_path):
        return video_path
    
    total_size = 0
    with open(video_path, "wb") as f:
        for block in response.iter_content(1024):
            total_size += len(block)

            # 如果视频的总大小超过30MB (30 * 1024 * 1024 bytes)，则停止下载并返回
            if total_size > 300 * 1024 * 1024:
                logger.error("[WX] Video is larger than 30MB, skipping...")
                return None

            f.write(block)

    return video_path


# def get_wxid_by_name(room_members, group_wxid, name):
#     if group_wxid in room_members:
#         for member_id in room_members[group_wxid]:
#             member = room_members[group_wxid][member_id]
#             if member["display_name"] == name or member["nickname"] == name:
#                 return member_id
#     return None  # 如果没有找到对应的group_wxid或name，则返回None


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


# 注册消息回调
def all_msg_handler(wcf: Wcf, message: WxMsg):
    try:
        cmsg = WcFerryMessage(WcFerryChannel(), wcf, message)
        ifgroup = message._is_group
    except NotImplementedError as e:
        logger.debug("[WX]single message {} skipped: {}".format(message["MsgId"], e))
        return None

    if ifgroup:
        WcFerryChannel().handle_group(cmsg)
    else:
        WcFerryChannel().handle_single(cmsg)
    return None


# 注册好友请求监听
def on_recv_text_msg(wechat_instance, message):
    xml_content = message["data"]["raw_msg"]
    dom = xml.dom.minidom.parseString(xml_content)

    # 从xml取相关参数
    encryptusername = dom.documentElement.getAttribute("encryptusername")
    ticket = dom.documentElement.getAttribute("ticket")
    scene = dom.documentElement.getAttribute("scene")

    if conf().get("accept_friend", False):
        # 自动同意好友申请
        delay = random.randint(1, 180)
        threading.Timer(
            delay,
            wechat_instance.accept_friend_request,
            args=(encryptusername, ticket, int(scene)),
        ).start()
    else:
        logger.debug("wcferry未开启自动同意好友申请")


@singleton
class WcFerryChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()

        # self.rooms_ary = []
        self.contracts_global = {}
        self.directory = os.path.join(os.getcwd(), "tmp")

    # def _compose_context(self, ctype: ContextType, content, **kwargs):
    #     context =super()._compose_context(ctype, content, **kwargs)
    #     # context = Context(ctype, content)
    #     # context.kwargs = kwargs
    #     return context
    def merge_rooms(self, rooms1, rooms2):
        merged_rooms = rooms1.copy()  # Start with a copy of rooms1

        for room_id, room_data in rooms2.items():
            if room_id in merged_rooms:
                # Merge existing room data
                merged_rooms[room_id] = {
                    **merged_rooms[room_id],
                    **room_data,
                    "member_list": {
                        **merged_rooms[room_id].get("member_list", {}),
                        **room_data.get("member_list", {}),
                    },
                }
            else:
                # Add new room data
                merged_rooms[room_id] = room_data

        return merged_rooms

    def thread_run(self):
        def fun_proc():
            time.sleep(5)
            self.saveOtherInfo()

            save_json_to_file(self.directory, self.contacts, "wcferry_contacts.json")

            # 合并微信群信息
            new_rooms = self.getAllrooms()
            if new_rooms:
                self.rooms = self.merge_rooms(self.rooms, new_rooms)

            save_wxgroups_to_file(self.rooms)

        thread = threading.Thread(target=fun_proc)
        thread.start()

    def startup(self):
        logger.info("等待微信登录······")
        login_info = wcf.get_user_info()
        self.__avatar_urls = self.getAllAvatarUrl()

        self.contacts = self.getAllContacts()

        self.rooms = load_json_from_file(self.directory, "wcferry_rooms.json")
        if not self.rooms:
            self.rooms = self.getAllrooms()

        # self.rooms_ary = self.make_rooms_ary_groupx(self.rooms)
        # self.contracts_ary = self.make_contracts_ary_groupx(self.contacts)

        self.user_id = login_info["wxid"]
        self.name = login_info["name"]
        logger.info(f"\n\n登录信息:>>>user_id:{self.user_id}>>>>>>>>name:{self.name}\n\n")

        self.thread_run()
        # wcf 开始------------------------
        robot = Robot(wcf, all_msg_handler)
        logger.info(f"WeChatRobot【{__version__}】成功启动···")

        # 机器人启动发送测试消息
        robot.sendTextMsg(
            f"{__version__}启动成功！-{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "filehelper",
        )

        # 接收消息
        # robot.enableRecvMsg()     # 可能会丢消息？
        robot.enableReceivingMsg()  # 加队列
        self.robot = robot

        # 搜寻iKnowWxAPI 并使用其 post函数发送群及通讯录信息到groupx服务器
        plugins = PluginManager().list_plugins()
        for plugin in plugins:
            if plugins[plugin].enabled:
                if plugins[plugin].namecn == "iKnowWxAPI":
                    PluginManager().instances[plugin].post_contacts_to_groupx(
                        self.rooms, self.contacts
                    )
                    break
        # 让机器人一直跑
        forever()
        # wcf 结束------------------------

    def reload_conf(self):
        robot = Robot(wcf, all_msg_handler)
        logger.info(f"重载wcferry robot配置,,,,")

    def handle_single(self, cmsg: ChatMessage):
        # print(cmsg)
        if cmsg.ctype == ContextType.VOICE:
            if not conf().get("speech_recognition"):
                return
            logger.debug("[WX]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.VIDEO:
            logger.debug("[WX]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[WX]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[WX]receive text msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.QUOTE:
            logger.debug("[WX]receive quote msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.MP_LINK:
            logger.debug("[WX]receive mp_link msg: {}".format(cmsg.content))
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
        # print(cmsg)     ##重要~~~！！！！！群聊时测试监听消息专用

        """如果要使用bridge_room插件，需要取消下面这段代码的注释"""
        # root_dir=os.path.abspath(os.path.join(os.path.dirname(__file__),"..\.."))
        # base_dir = root_dir+'\plugins\plugins.json'
        # with open(base_dir, "r", encoding="utf-8") as f:
        #     config = json.load(f)
        #     if config["plugins"]["bridge_room"]["enabled"] == False:
        #         pass
        #     else:
        #         from plugins.bridge_room.main import send_message_synv
        #         try:
        #             send_message_synv(cmsg)
        #         except Exception as e:
        #             print(e)

        """如果要使用bridge_room插件，需要取消上面这段代码的注释"""
        if cmsg.ctype == ContextType.VOICE:
            if not conf().get("speech_recognition"):
                return
            logger.debug("[WX]receive voice for group msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image for group msg: {}".format(cmsg.content))
        elif cmsg.ctype in [
            ContextType.LEAVE_GROUP,
            ContextType.JOIN_GROUP,
            ContextType.EXIT_GROUP,
            ContextType.PATPAT,
        ]:
            logger.info("[WX]receive note msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            pass
        elif cmsg.ctype == ContextType.QUOTE:
            pass
        elif cmsg.ctype == ContextType.WCPAY:
            pass
        elif cmsg.ctype == ContextType.MP_LINK:
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
        receiver = context["receiver"]
        if reply.type == ReplyType.TEXT or reply.type == ReplyType.TEXT_:
            match = re.search(r"^@(.*?)\n", reply.content)
            if match:
                # name = match.group(1)  # 获取第一个组的内容，即名字
                # directory = os.path.join(os.getcwd(), "tmp")
                # file_path = os.path.join(directory, "wcferry_room_members.json")
                # with open(file_path, "r", encoding="utf-8") as file:
                #     room_members = json.load(file)
                # wxid = get_wxid_by_name(room_members, receiver, name)
                # wxid_list = [wxid]
                # self.robot.sendTextMsg(reply.content, receiver, wxid_list)
                self.robot.sendTextMsg(reply.content, receiver)
            else:
                wcf.send_text(reply.content, receiver)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))

        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            wcf.send_text(reply.content, receiver)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))
        elif reply.type == ReplyType.IMAGE_URL:  # 从网络下载图片
            img_url = reply.content
            filename = str(uuid.uuid4())
            image_path = download_and_compress_image(img_url, filename)
            wcf.send_image(image_path, receiver)
            logger.info("[WX] sendImage url={}, receiver={}".format(img_url, receiver))
        elif reply.type == ReplyType.VIDEO_URL:
            video_url = reply.content
            filename = str(uuid.uuid4())
            # 调用你的函数，下载视频并保存为本地文件
            video_path = download_video(video_url, filename)
            if video_path is None:
                # 如果视频太大，下载可能会被跳过，此时 video_path 将为 None
                wcf.send_text("抱歉，视频太大了！！！", receiver)
            else:
                wcf.send_file(video_path, receiver)
            logger.info("[WX] sendVideo, receiver={}".format(receiver))
        elif reply.type == ReplyType.IMAGE:  # 从文件读取图片
            if isinstance(reply.content, io.BytesIO):
                # 将 BytesIO 对象转换为本地文件                
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                temp_file.write(reply.content.getvalue())  # 使用 getvalue() 获取字节内容
                temp_file.close()  # 确保文件被正确关闭
                temp_file_path = temp_file.name
                try:
                    wcf.send_image(temp_file_path, receiver)
                finally:
                    # 发送完成后尝试删除临时文件
                    try:
                        # 添加短暂延时，等待文件释放
                        time.sleep(1)  
                        if os.path.exists(temp_file_path):
                            os.unlink(temp_file_path)
                    except PermissionError:
                        logger.warning(f"[WX] 无法立即删除临时文件 {temp_file_path}，文件可能仍在使用中")
                    except Exception as e:
                        logger.warning(f"[WX] 删除临时文件时发生错误: {str(e)}")
            else:
                wcf.send_image(reply.content, receiver)
            logger.info("[WX] sendImage, receiver={}".format(receiver))
        elif reply.type == ReplyType.VIDEO:  # 发送文件
            wcf.send_file(reply.content, receiver)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.FILE:  # 发送文件
            wcf.send_file(reply.content, receiver)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))

        elif reply.type == ReplyType.CARD:
            wcf.send_card(reply.content, receiver)
            logger.info("[WX] sendCARD={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.GIF:
            wcf.send_gif(reply.content, receiver)
            logger.info("[WX] sendCARD={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.CALL_UP:
            wcf.send_call_up(receiver)
            logger.info("[WX] sendCALLUP, receiver={}".format(receiver))
        elif reply.type == ReplyType.InviteRoom:
            member_list = receiver
            wcf.invite_chatroom_members(reply.content, member_list)
            logger.info(
                "[WX] sendInviteRoom={}, receiver={}".format(reply.content, receiver)
            )
        elif reply.type == ReplyType.VOICE:
            wcf.send_file(reply.content, receiver)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.MINIAPP:
            wcf.send_xml(reply.content, receiver)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.LINK:
            # wcf.send_xml(reply.content, receiver)
            jsonObj = json.loads(reply.content)
            ret = wcf.send_rich_text(
                name=jsonObj["name"],
                account=jsonObj["account"],
                title=jsonObj["title"],
                digest=jsonObj["digest"],
                url=jsonObj["url"],
                thumburl='', #jsonObj["thumburl"],某个版本的wcferry 不支持thumburl
                receiver=receiver,
            )
            logger.info("[WX] sendLink={}, receiver={},ret = {}".format(reply.content, receiver,ret))
            logger.info(jsonObj)
        elif reply.type == ReplyType.XML:
            ttt = wcf.get_msg_types()
            print("--------------------------------")
            print(ttt)
            print("--------------------------------")
           # xml2 = "<?xml version=\"1.0\"?><msg><appmsg appid=\"\" sdkver=\"0\"><title>叮当药房，24小时服务，28分钟送药到家！</title><des>叮当快药首家承诺范围内28分钟送药到家！叮当快药核心区域内7*24小时全天候服务，送药上门！叮当快药官网为您提供快捷便利，正品低价，安全放心的购药、送药服务体验。</des><action>view</action><type>33</type><showtype>0</showtype><content /><url>https://mp.weixin.qq.com/mp/waerrpage?appid=wxc2edadc87077fa2a&amp;type=upgrade&amp;upgradetype=3#wechat_redirect</url><dataurl /><lowurl /><lowdataurl /><recorditem /><thumburl /><messageaction /><md5>7f6f49d301ebf47100199b8a4fcf4de4</md5><extinfo /><sourceusername>gh_c2b88a38c424@app</sourceusername><sourcedisplayname>叮当快药 药店送药到家夜间买药</sourcedisplayname><commenturl /><appattach><totallen>0</totallen><attachid /><emoticonmd5></emoticonmd5><fileext>jpg</fileext><filekey>da0e08f5c7259d03da150d5e7ca6d950</filekey><cdnthumburl>3057020100044b30490201000204e4c0232702032f4ef20204a6bace6f02046401f62d042430326337303430352d333734332d343362652d623335322d6233333566623266376334620204012400030201000405004c537600</cdnthumburl><aeskey>0db26456caf243fbd4efb99058a01d66</aeskey><cdnthumbaeskey>0db26456caf243fbd4efb99058a01d66</cdnthumbaeskey><encryver>1</encryver><cdnthumblength>61558</cdnthumblength><cdnthumbheight>100</cdnthumbheight><cdnthumbwidth>100</cdnthumbwidth></appattach><weappinfo><pagepath>pages/index/index.html</pagepath><username>gh_c2b88a38c424@app</username><appid>wxc2edadc87077fa2a</appid><version>197</version><type>2</type><weappiconurl>http://wx.qlogo.cn/mmhead/Q3auHgzwzM4727n0NQ0ZIPQPlfp15m1WLsnrXbo1kLhFGcolgLyc0A/96</weappiconurl><appservicetype>0</appservicetype><shareId>1_wxc2edadc87077fa2a_29177e9a9b918cb9e75964f80bb8f32e_1677849476_0</shareId></weappinfo><websearch /></appmsg><fromusername>wxid_eob5qfcrv4zd22</fromusername><scene>0</scene><appinfo><version>1</version><appname /></appinfo><commenturl /></msg>"
            xml2 = '<?xml version="1.0"?>\n<msg>\n\t<appmsg appid="wx32540bd863b27570" sdkver="">\n\t\t<title>拼多多</title>\n\t\t<des>拼多多</des>\n\t\t<action>view</action>\n\t\t<type>33</type>\n\t\t<showtype>0</showtype>\n\t\t<content />\n\t\t<url>https://mp.weixin.qq.com/mp/waerrpage?appid=wx32540bd863b27570&amp;amp;type=upgrade&amp;amp;upgradetype=3#wechat_redirect</url>\n\t\t<dataurl />\n\t\t<lowurl />\n\t\t<lowdataurl />\n\t\t<recorditem />\n\t\t<thumburl>http://mmbiz.qpic.cn/mmbiz_png/I3ht2WMGrPjkBVPwWLHt9LbsXHnXaHKuT6LmFDpvV7jcJSEibYrN1Wc5SpVhRUXxv1vJyCgVETh7m9RRMzYLSiag/640?wx_fmt=png&amp;wxfrom=200</thumburl>\n\t\t<messageaction />\n\t\t<laninfo />\n\t\t<extinfo />\n\t\t<sourceusername />\n\t\t<sourcedisplayname>拼多多</sourcedisplayname>\n\t\t<commenturl />\n\t\t<appattach>\n\t\t\t<totallen>0</totallen>\n\t\t\t<attachid />\n\t\t\t<emoticonmd5></emoticonmd5>\n\t\t\t<fileext />\n\t\t\t<aeskey></aeskey>\n\t\t</appattach>\n\t\t<webviewshared>\n\t\t\t<publisherId />\n\t\t\t<publisherReqId>0</publisherReqId>\n\t\t</webviewshared>\n\t\t<weappinfo>\n\t\t\t<pagepath />\n\t\t\t<username>gh_0e7477744313@app</username>\n\t\t\t<appid />\n\t\t\t<type>1</type>\n\t\t\t<appservicetype>0</appservicetype>\n\t\t\t<shareId>2_wx32540bd863b27570_10221255_1739953303_1</shareId>\n\t\t</weappinfo>\n\t\t<websearch />\n\t</appmsg>\n\t<fromusername>yinghk</fromusername>\n\t<scene>0</scene>\n\t<appinfo>\n\t\t<version>7</version>\n\t\t<appname>拼多多</appname>\n\t</appinfo>\n\t<commenturl />\n</msg>\n'
            ret = wcf.send_xml(receiver, xml2, 49)
            logger.info("[WX] sendXML={}, receiver={},ret = {}".format(reply.content, receiver,ret))
        # elif reply.type == ReplyType.RICH_TEXT:
        #     # self, name: str, account: str, title: str, digest: str, url: str, thumburl: str, receiver: str) -> int:
        #     wcf.send_rich_text(
        #         name="name",
        #         account="account",
        #         title="title",
        #         digest="digest",
        #         url="https://www.baidu.com",
        #         thumburl="https://inews.gtimg.com/om_bt/O6SG7dHjdG0kWNyWz6WPo2_3v6A6eAC9ThTazwlKPO1qMAA/641",
        #         receiver=receiver,
        #     )

    # 获取所有用户的头像url
    def getAllAvatarUrl(self):
        data = wcf.query_sql(
            "MicroMsg.db",
            "SELECT usrName, bigHeadImgUrl, smallHeadImgUrl FROM ContactHeadImgUrl;",
        )

        return {contact["usrName"]: contact["bigHeadImgUrl"] for contact in data}

    # 获取通信录,包含个人及微信群
    def getAllContacts(self) -> Dict[str, ContactInfo]:
        """获取联系人（包括好友、公众号、服务号、群成员……）
        
        Returns:
            Dict[str, ContactInfo]: 返回一个字典，其中:
                - 键为联系人的wxid(str)
                - 值为包含联系人详细信息的ContactInfo字典，可能包含以下字段：
                    - name: 昵称
                    - code: 代码
                    - remark: 备注
                    - country: 国家
                    - province: 省份
                    - city: 城市
                    - gender: 性别
                    - alias: 别名
                    - avatar: 头像URL
        """
        contracts = {}
        for contact in wcf.get_contacts():
            # 微信群也加入到通讯录中:
            contracts[contact["wxid"]] = {
                "name": contact["name"],
                "code": contact["code"],
                "remark": contact["remark"],
                "country": contact["country"],
                "province": contact["province"],
                "city": contact["city"],
                "gender": contact["gender"],
            }

        contacts_rd = wcf.query_sql("MicroMsg.db", "SELECT * FROM Contact LIMIT 5000;")
        for contact in contacts_rd:
            old_item = contracts.get(contact["UserName"])
            if old_item:
                new_item = {
                    "name": (
                        contact["NickName"] if contact["NickName"] else old_item["name"]
                    ),
                    "alias": contact["Alias"],
                }
                old_item.update(new_item)
                new_item = old_item
            else:
                new_item = {
                    "name": contact["NickName"],
                    "alias": contact["Alias"],
                }
            new_item["avatar"] = self.get_user_avatar_url(contact["UserName"])
            contracts[contact["UserName"]] = new_item

        return contracts

    # 从通讯录中和获取微信群,不包含微信群成员
    def getRoomsFromContracts(self) -> dict:
        rooms = {}
        for wxid in self.contacts:
            if wxid and wxid.endswith("chatroom"):
                room = self.contacts[wxid]
                rooms[wxid] = {
                    "name": room["name"],
                    "code": room["code"],
                    "remark": room["remark"],
                    "country": room["country"],
                    "province": room["province"],
                    "city": room["city"],
                }

        return rooms

    def getMembersFromRoomData(self, bs):
        contacts = self.contacts
        if bs is None:
            return {}
        members = {}

        crd = RoomData()
        crd.ParseFromString(bs)

        for member in crd.members:
            display_name = member.name
            nickname = ""

            contract = {}
            if member.wxid in contacts:
                if not display_name:
                    display_name = contacts[member.wxid]["name"]
                if not nickname:
                    nickname = contacts[member.wxid]["name"]
                contract = contacts[member.wxid]

            new_item = {
                "nickname": nickname,
                "display_name": display_name,
            }
            new_item = new_item | contract if contract else new_item
            if not new_item.get("avatar"):
                new_item["avatar"] = self.__avatar_urls.get(member.wxid, "")
            members[member.wxid] = new_item
        return members

    # 获取微信群列表,包括微信群成员
    def getAllrooms(self) -> dict:
        contacts = self.contacts
        rooms = wcf.query_sql(
            "MicroMsg.db",
            "SELECT ChatRoomName,UserNameList,RoomData FROM ChatRoom LIMIT 2000;",
        )

        result = {}
        for room in rooms:
            bs = room.get("RoomData")
            if bs is None:
                continue
            members = self.getMembersFromRoomData(bs)
            room_id = room["ChatRoomName"]

            if not room_id or room_id not in contacts:
                logger.error(f"未找到群:{room_id} 的名称")
                continue
            nickname = contacts[room_id]["name"]
            chat_room_info = {
                "nickname": nickname,  # contracts 包含微信群
                "member_list": members,
            }
            result[room["ChatRoomName"]] = chat_room_info

        return result

    # 获取微信群所属成员
    def getAllroomsMembers(self) -> dict:
        rooms = wcf.query_sql(
            "MicroMsg.db",
            "SELECT ChatRoomName,UserNameList,RoomData FROM ChatRoom LIMIT 2000;",
        )

        result = {}
        for room in rooms:
            bs = room.get("RoomData")
            if bs is None:
                continue
            members = self.getMembersFromRoomData(bs)
            room_id = room["ChatRoomName"]
            chat_room_info = {
                "nickname": rooms[room_id]["name"],
                "member_list": members,
            }
            result[room["ChatRoomName"]] = chat_room_info

        return result

    def get_user_wxid_by_name(self, user_name):
        for wxid, contact in self.contacts.items():
            if contact.get("name") == user_name:
                return wxid
        return None

    def get_user_name(self, user_id):
        result = wcf.query_sql(
            "MicroMsg.db", f"SELECT NickName FROM Contact WHERE UserName = '{user_id}';"
        )
        if result:
            name = result[0].get("NickName")
            if name:
                return name

        contacts = wcf.get_contacts()
        for contact in contacts:
            if contact.get("wxid") == user_id:
                return contact.get("name", "")
        return ""

    def get_room_name(self, room_id):
        return self.get_user_name(room_id)

    def get_user_avatar_url(self, user_id):
        return self.__avatar_urls.get(user_id, "")

    # 获取微信群成员的特定昵称(display_name)或通用昵称(nickname)
    def get_room_member_name(self, room_id, member_id):
        if not room_id or not member_id:
            return ""
        member_name = ""
        if room_id in self.rooms:
            room = self.rooms[room_id]
            member_list = room.get("member_list", "")
            if member_id in member_list:
                member = member_list[member_id]
                member_name = member["display_name"] or member["nickname"]

        if not member_name:
            result = wcf.query_sql(
                "MicroMsg.db",
                f"SELECT ChatRoomName,UserNameList,RoomData FROM ChatRoom WHERE ChatRoomName = '{room_id}';",
            )
            if result:
                bs = result[0].get("RoomData")
                members = self.getMembersFromRoomData(bs)
                if member_id in members:
                    member_name = (
                        members[member_id]["display_name"]
                        or members[member_id]["nickname"]
                    )

        if not member_name:
            member_name = self.get_user_name(member_id)
        return member_name
    def add_room_member(self,room_id,user_name,user_wxid):
        room = self.rooms.get(room_id)
        if room:           
            room["member_list"][user_wxid] = {"nickname":user_name,"name":user_name,"display_name":user_name}
            save_wxgroups_to_file(self.rooms)
    def remove_room_member(self,room_id,user_wxid):
        room = self.rooms.get(room_id)
        if room:
            room["member_list"].pop(user_wxid)
            save_wxgroups_to_file(self.rooms)
    def get_room_member_wxid(self, room_id, name):
        if not room_id or not name:
            return ""
        if room_id in self.rooms:
            room = self.rooms[room_id]
            member_list = room.get("member_list", "")
            for member_id in member_list:
                member = member_list[member_id]
                member_name = member.get("nickname", None)
                if member_name and member_name == name:
                    return member_id
                member_name = member.get("name", None)
                if member_name and member_name == name:
                    return member_id
                member_name = member.get("display_name", None)
                if member_name and member_name == name:
                    return member_id
        wxid = self.get_user_wxid_by_name(name)
        if wxid:
            return wxid
        logger.error(f"未找到群:{room_id} 的成员:{name}")
        return ""

    # 保持一些辅助性查询数组列表
    def saveOtherInfo(self):
        wcf_rooms = {}
        wcf_rooms_wxid_name = {}
        wcf_rooms_wxid = []
        wcf_rooms_name = []

        for wxid in self.contacts:
            if wxid.endswith("chatroom"):
                contact = self.contacts[wxid]
                room_name = contact["name"]
                wcf_rooms[wxid] = {
                    "name": room_name,
                    "name": contact["name"],
                    "code": contact["code"],
                    "remark": contact["remark"],
                    "country": contact["country"],
                    "province": contact["province"],
                    "city": contact["city"],
                    "gender": contact["gender"],
                }

                wcf_rooms_wxid_name[wxid] = room_name
                wcf_rooms_wxid.append(wxid)
                if room_name:
                    wcf_rooms_name.append(room_name)

        directory = os.path.join(os.getcwd(), "tmp")
        save_json_to_file(directory, wcf_rooms_wxid_name, "rooms-wxid-name.json")
        save_json_to_file(directory, wcf_rooms_wxid, "rooms-wxid.json")
        save_json_to_file(directory, wcf_rooms_name, "rooms-name.json")

    def getAllRoomMembers(self):
        rooms = self.getAllRooms()
        result = {}
        for room_id in rooms:
            room = rooms[room_id]
            room_members = room["member_list"]
            result[room_id] = room_members
        return result

    def make_rooms_ary_groupx(self, rooms):
        _rooms_ary = []
        for wxid, item in rooms.items():
            nickname = item.get("nickname")
            member_list = []
            for wxid2, member in item.get("member_list").items():
                member_list.append(
                    {
                        "wxid": wxid2,
                        "UserName": wxid2,
                        "NickName": member.get("nickname"),
                    }
                )
            _rooms_ary.append(
                {
                    "wxid": wxid,
                    "UserName": wxid,
                    "NickName": nickname,
                    "MemberList": member_list,
                }
            )
        return _rooms_ary

    def make_contracts_ary_groupx(self, contracts):
        _contracts_ary = []
        for wxid, member in contracts.items():
            _contracts_ary.append(
                {
                    "alias": member.get("alias"),
                    "wxid": wxid,
                    "UserName": wxid,
                    "NickName": member.get("name"),
                    "Province": member.get("province"),
                    "Sex": 1 if member.get("gender") == "男" else 0,
                    "City": member.get("city"),
                    "Country": member.get("country"),
                    "code": member.get("code"),
                    "Remark": member.get("remark"),
                }
            )
        return _contracts_ary
