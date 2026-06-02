"""
Send a simple Feishu test message with the current configuration.
"""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from binding_store import load_binding
from lark_service import LarkService


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return "xxxxxxxx" in lowered or "example.com" in lowered


def build_service() -> LarkService:
    load_dotenv()

    app_id = os.getenv("LARK_APP_ID")
    app_secret = os.getenv("LARK_APP_SECRET")
    webhook_url = os.getenv("LARK_WEBHOOK_URL")
    receive_id = os.getenv("LARK_RECEIVE_ID")
    receive_id_type = os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")

    if webhook_url:
        return LarkService(webhook_url=webhook_url)

    if app_id and app_secret:
        if is_placeholder(receive_id):
            binding = load_binding()
            if binding:
                receive_id = binding.get("receive_id")
                receive_id_type = binding.get("receive_id_type", "chat_id")
            else:
                receive_id = None

        return LarkService(
            app_id=app_id,
            app_secret=app_secret,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
        )

    raise ValueError("Configure either webhook mode or app mode first.")


def main() -> int:
    service = build_service()
    success = service.send_text("Test message from lark-news-bot.")
    print("Success" if success else "Failed")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
