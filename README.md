# 简介

> **本项目属于chatgpt-on-wechat 的  PC windows端个人微信版**，基于[WeChat-AIChatbot-WinOnly](https://github.com/chazzjimel/WeChat-AIChatbot-WinOnly)，由于跃迁大佬停更，所以备份一下，同时丰富一下原ntchat消息通道监听类型，方便开发对应类型插件。
> 
> **本项目仅供学习和技术研究，请勿用于非法用途，如有任何人凭此做何非法事情，均于作者无关，特此声明。**


> - **2024.4月开始微信限制低版本登录，为提高本项目使用门槛，故不提供低版本登录解决方案，请自行解决** *
> 
> 
> - **只能在Win平台运行项目！只能在Win平台运行项目！只能在Win平台运行项目!  （ 重要的事情说三遍 ）**


 - 项目支持功能如下：

- [x] **Wechat** ：PC端的个微消息通道，依赖 [wcferry项目](https://github.com/lich0821/WeChatFerry) ，
，现支持[WeChat3.9.11.25版本](https://github.com/lich0821/WeChatFerry/releases/download/v39.3.3/WeChatSetup-3.9.11.25.exe)，

  - [x] 发送消息：文本/图片/视频/文件/群聊@/链接卡片/GIF/XML
  - [x] 接收消息：几乎涵盖所有消息类型
  - [x] 其他功能：同意加好友请求/创建群/添加好友入群/邀请好友入群/删除群成员/修改群名/修改群公告
  - [ ] 短板缺陷：无法发送语音条信息

# **详细功能列表：**

- [x] 聊天对话：私聊、群聊对话，支持fastgpt、coze、linkai、openai、azure、文心一言，通义千问，讯飞星火，ChatGLM-4，MiniMax，deepspeek，gemini，claudeapi，Kimi对话模型通道
- [x] 语音对话：语音消息可选文字或语音回复，支持 Azure, Openai，Google等语音模型
- [x] 插件：chatgpt-on-wechat项目的插件可以复制到本项目来使用，也可自行开发插件
- [x] 高度定制：依赖fastgpt接口，可实现每个群聊对应不同的应用知识库

# **交流群：**

加微信: wxid_y98arlwoeg9n12 ,然后私聊发送 "进群"即可获得进群邀请.

![alt text](image.png)



# 更新日志
>**2024.07.16：** 同步COW bot模型，ContextType.LINK 改为COW的ContextType.SHARING类型（避免使用一些总结文章插件报错）,修复文字转语音无法播放的问题，azure语音升级为多语言晓晓（有感情）

>**2024.07.07：** 更换失效点歌接口，新增coze模型，适配coze画图功能，新增XML回复类型，更新几个机场信息。

>**2024.07.01：** 修复lcard功能发送失败和导致bot无法回复的问题，修复一处Bug,新增退群提醒开关（务必使用最新版本，否则可能回复不了）

>**2024.06.20：** 适配COW的linkai bot,新增支持模型gpt-4o,godcmd增加全局管理员,适配linkai插件,优化Countdown插件.

>**2024.06.18：** 新增lcard插件可发送卡片天气，卡片音乐，小程序。内置群聊邀请插件，私聊下发送`加群`可直接邀请进群。

>**2024.06.16：** 新增群聊用户黑名单wxid，新增监听微信支付类型，修复收到表情包消息可能导致from_user_nickname为None的问题，内置bridge_room插件

>**2024.06.13：** 新增监听多种消息类型:小程序，xml，音乐，引用消息，表情包，视频号，退群....新增后缀触发，修复 godcmd群聊无法触发管理员命令，同步支持几个大模型，内置Countdown插件可搭配timetask使用。优化banwords，累计三次触发敏感词自动拉黑该用户。新增管理员模式插件。


# 快速开始

## 准备

### 1.运行环境

仅支持Windows 系统同时需安装 `Python`。
> 建议Python版本在 3.7.1~3.12 之间。

**(1) 下载项目代码：**

```bash
git clone https://github.com/akun-y/chatgpt-on-wechat-akun.git
cd chatgpt-on-wechat-akun/
```

**(2) 安装核心依赖 (必选)：**

```bash
pip3 install -r requirements.txt
```
**(3) 拓展依赖 (可选，建议安装)：**

```bash
pip3 install -r requirements-optional.txt
```

## 配置

配置文件的模板在根目录的`config-template.json`中，需复制该模板创建最终生效的 `config.json` 文件：

```bash
  cp config-template.json config.json
```


## 运行

### 1.本地运行（仅限window平台）

如果是开发机 **本地运行**，直接在项目根目录下执行：

```bash
python3 app.py
```
### 2. PC本地部署wechat（仅限window平台）

1.主项目安装主要依赖后，还需要安装wcferry依赖

```
pip install wcferry
```

2.安装指定PC微信版本：[WeChat3.9.11.25版本](https://github.com/lich0821/WeChatFerry/releases/download/v39.3.3/WeChatSetup-3.9.11.25.exe)，扫码登陆好，关闭自动更新微信

3.修改主项目配置项：config.json文件内

```json
"channel_type": "wcferry"
```


个人精力和水平有限，项目还有许多不足，欢迎提出 issues 或 pr。期待你的贡献。
