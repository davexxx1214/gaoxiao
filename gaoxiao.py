import json
import plugins
from bridge.reply import Reply, ReplyType
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from plugins import *
from common.log import logger
from common.expired_dict import ExpiredDict

import os
import requests

@plugins.register(
    name="gaoxiao",
    desire_priority=3,
    desc="A plugin to call gaoxiao model",
    version="0.0.1",
    author="davexxx",
)

class gaoxiao(Plugin):
    def __init__(self):
        super().__init__()
        try:
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                # 使用父类的方法来加载配置
                self.config = super().load_config()

                if not self.config:
                    raise Exception("config.json not found")
            
            # 设置事件处理函数
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            # 从配置中提取所需的设置
            self.image_model = self.config.get("image_model","")
            self.chat_model = self.config.get("chat_model","")
            self.image_url = self.config.get("image_url","")
            self.chat_url = self.config.get("chat_url","")
            self.token = self.config.get("token","")
            self.gaoxiao_start_prefix = self.config.get("gaoxiao_start_prefix","")
            self.gaoxiao_stop_prefix = self.config.get("gaoxiao_stop_prefix","")
            self.total_timeout = self.config.get("total_timeout", 5)

            self.params_cache = ExpiredDict(500)
            # 初始化成功日志
            logger.info("[gaoxiao] inited.")
        except Exception as e:
            # 初始化失败日志
            logger.warn(f"gaoxiao init failed: {e}")
    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [ContextType.TEXT, ContextType.SHARING,ContextType.FILE,ContextType.IMAGE]:
            return
        msg: ChatMessage = e_context["context"]["msg"]
        user_id = msg.from_user_id
        content = context.content

        # 将用户信息存储在params_cache中
        if user_id not in self.params_cache:
            self.params_cache[user_id] = {}
            self.params_cache[user_id]['gaoxiao_quota'] = 0

            logger.debug('Added new user to params_cache. user id = ' + user_id)

        if e_context['context'].type == ContextType.TEXT:
            if content.startswith(self.gaoxiao_start_prefix):
                tip = f"💡已经为您开启表情包模式，您的模型已经加载为:\n笑你命3000。\n💡想结束此模式，您可以随时使用:\n{self.gaoxiao_stop_prefix}"
                self.params_cache[user_id]['gaoxiao_quota'] = 1
                reply = Reply(type=ReplyType.TEXT, content= tip)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            if content.startswith(self.gaoxiao_stop_prefix):
                tip = f"💡已经停止表情包模式"
                self.params_cache[user_id]['gaoxiao_quota'] = 0
                reply = Reply(type=ReplyType.TEXT, content= tip)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            if (self.params_cache[user_id]['gaoxiao_quota'] < 1):
                # 进行下一步的操作                
                logger.debug("on_handle_context: 当前用户识图配额不够，不进行识别")
                return
            
            logger.info(f"query = {content}")
            chat_result = self.chat(content)
            logger.info(f"chat result = {chat_result}")
            imageUrl = self.image(content)
            logger.info(f"imageUrl result = {imageUrl}")
            self.send_reply(chat_result, e_context)

            if imageUrl is not '':
                rt = ReplyType.IMAGE_URL
                rc = imageUrl
                reply = Reply(rt, rc)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
            else:
                rt = ReplyType.TEXT
                rc = "表情包罢工了~"
                reply = Reply(rt, rc)
                logger.error("[gaoxiao] image service exception")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS

            


    def chat(self, query):
        body = {
            "model": f"{self.chat_model}",
            "messages": [
                {
                    "role": "system",
                    "content": f"非常简短且应景的回复用户消息，要非常搞笑，不需要解释，直接输出你回应的消息。用户信息如下:\n{query}" 
                }
            ]
        }

        # 设置headers，包括Authorization
        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        # 发送POST请求
        response = requests.post(self.chat_url, headers=headers, json=body)

        if response.status_code == 200:
            # 成功响应
             try:
                res = response.json()
                result = res["choices"][0]["message"]["content"]
                return result
             except Exception as e:
                return '未知错误，服务暂不可用'
        else:
            # 打印错误信息
            logger.error(response.json())
            return '未知错误，服务暂不可用'
        
    def image(self, query):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # 注意修改size以符合API的要求
        payload = {
            "prompt": f"{query}",
            "model": f"{self.image_model}"  
        }

        response = requests.post(self.image_url, headers=headers, json=payload)

        # 检查响应内容
        if response.status_code == 200:
            # 成功响应
            try:
                res = response.json()
                result = res["data"][0]["url"]
                return result
            except Exception as e:
                return ''
        else:
            # 打印错误信息
            logger.error(response.json())
            return ''
        
    def send_reply(self, reply, e_context: EventContext, reply_type=ReplyType.TEXT):
        if isinstance(reply, Reply):
            if not reply.type and reply_type:
                reply.type = reply_type
        else:
            reply = Reply(reply_type, reply)
        channel = e_context['channel']
        context = e_context['context']
        # reply的包装步骤
        rd = channel._decorate_reply(context, reply)
        # reply的发送步骤
        return channel._send_reply(context, rd)

    