"""
Listen for inbound Feishu messages via long connection.

When a user sends a P2P message to the app, save the chat_id locally so
later pushes can reuse it.
"""
from __future__ import annotations

import json
import os
import sys

import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, P2ImMessageReceiveV1

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from binding_store import save_binding


load_dotenv()

APP_ID = os.getenv("LARK_APP_ID")
APP_SECRET = os.getenv("LARK_APP_SECRET")

if not APP_ID or not APP_SECRET:
    raise ValueError("Missing LARK_APP_ID or LARK_APP_SECRET in .env")


client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()


def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    if data.event.message.chat_type != "p2p":
        return

    sender_open_id = None
    if data.event.sender and data.event.sender.sender_id:
        sender_open_id = data.event.sender.sender_id.open_id

    chat_id = data.event.message.chat_id
    save_binding(chat_id=chat_id, user_open_id=sender_open_id, user_name=None)

    content = json.dumps(
        {
            "text": (
                "绑定成功。之后这个新闻机器人会复用当前私聊会话主动发送消息。\n"
                "现在可以运行 python test_send.py 或 python src/main.py --test。"
            )
        }
    )

    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(content)
            .build()
        )
        .build()
    )

    response = client.im.v1.message.create(request)
    if not response.success():
        raise RuntimeError(
            f"Failed to send bind confirmation: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
        )


event_handler = (
    lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
    .build()
)


def main() -> None:
    print("Listening for Feishu messages...")
    print("Send any private message to the app once to bind this chat.")
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
