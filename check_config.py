"""
Configuration checker for lark-news-bot.
"""
import os
from dotenv import load_dotenv


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def show_value(key: str, value: str) -> str:
    sensitive_markers = ("KEY", "SECRET", "TOKEN")
    if any(marker in key for marker in sensitive_markers):
        return mask(value)
    return value


def check_config() -> bool:
    load_dotenv()

    print("\n" + "=" * 60)
    print("lark-news-bot configuration check")
    print("=" * 60)

    ok = True

    llm_api_key = os.getenv("LLM_API_KEY")
    if llm_api_key:
        print(f"[OK] LLM_API_KEY: {show_value('LLM_API_KEY', llm_api_key)}")
    else:
        print("[ERROR] Missing LLM_API_KEY")
        ok = False

    webhook_url = os.getenv("LARK_WEBHOOK_URL")
    app_id = os.getenv("LARK_APP_ID")
    app_secret = os.getenv("LARK_APP_SECRET")
    receive_id = os.getenv("LARK_RECEIVE_ID")
    receive_id_type = os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")

    print("\nFeishu delivery mode:")
    if webhook_url:
        print(f"[OK] Webhook mode: {show_value('LARK_WEBHOOK_URL', webhook_url)}")
        print("     This mode can only send to a group bot webhook.")
    elif app_id and app_secret:
        print(f"[OK] App mode: {show_value('LARK_APP_ID', app_id)} / {show_value('LARK_APP_SECRET', app_secret)}")
        if receive_id:
            print(f"[OK] LARK_RECEIVE_ID_TYPE: {receive_id_type}")
            print(f"[OK] LARK_RECEIVE_ID: {show_value('LARK_RECEIVE_ID', receive_id)}")
        else:
            print("[INFO] LARK_RECEIVE_ID is not set.")
            print("       You can bind a private chat by running `python listen_and_bind.py` and messaging the app once.")
    else:
        print("[ERROR] Configure either:")
        print("        1. LARK_WEBHOOK_URL")
        print("        2. LARK_APP_ID + LARK_APP_SECRET")
        ok = False

    optional_keys = (
        "SOURCE_CONFIG_PATH",
        "SCHEDULE_TIME",
        "RUN_ON_START",
        "LLM_API_URL",
        "LLM_MODEL",
        "SEMANTIC_SCHOLAR_API_KEY",
        "HOURS_LOOKBACK",
        "TOP_N",
        "MAX_PER_CATEGORY",
        "FEED_CONCURRENCY",
        "FEED_TIMEOUT",
        "SCORING_BATCH_SIZE",
        "SCORING_CONCURRENCY",
        "STATE_PATH",
        "STATE_TTL_DAYS",
        "DEBUG_MODE",
        "MARKDOWN_OUTPUT_DIR",
    )

    print("\nOptional settings:")
    for key in optional_keys:
        value = os.getenv(key)
        if value:
            print(f"[OK] {key}: {show_value(key, value)}")
        else:
            print(f"[INFO] {key}: using default")

    print("\nFollow Builders:")
    follow_builders_enabled = os.getenv("FOLLOW_BUILDERS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    print(f"[OK] FOLLOW_BUILDERS_ENABLED: {follow_builders_enabled}")
    if follow_builders_enabled:
        mode = os.getenv("FOLLOW_BUILDERS_MODE", "remote")
        print(f"[OK] FOLLOW_BUILDERS_MODE: {mode}")
        if mode == "remote":
            for key in (
                "FOLLOW_BUILDERS_FEED_X_URL",
                "FOLLOW_BUILDERS_FEED_PODCASTS_URL",
                "FOLLOW_BUILDERS_FEED_BLOGS_URL",
            ):
                value = os.getenv(key)
                if value:
                    print(f"[OK] {key}: {show_value(key, value)}")
                else:
                    print(f"[ERROR] Missing {key}")
                    ok = False
        elif mode == "local":
            for key in ("RSSHUB_BASE_URL", "X_BEARER_TOKEN", "POD2TXT_API_KEY"):
                value = os.getenv(key)
                if value:
                    print(f"[OK] {key}: {show_value(key, value)}")
                else:
                    print(f"[INFO] {key}: not configured")
            print("[INFO] Local Follow Builders fetching is planned but not implemented in this bot yet.")
        else:
            print(f"[ERROR] Unsupported FOLLOW_BUILDERS_MODE: {mode}")
            ok = False
        if os.getenv("DEBUG_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}:
            print("[INFO] DEBUG_MODE=true: Follow Builders seen-state will not be written.")

    print("\nNext steps:")
    print("1. Run `python listen_and_bind.py` if you want echo-bot-style private binding.")
    print("2. Run `python test_send.py` to verify Feishu delivery.")
    print("3. Run `python src/main.py --dry-run` to preview the multi-source digest locally.")
    print("4. Run `python src/main.py --test` for the full RSS + LLM + card flow.")

    print("=" * 60 + "\n")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if check_config() else 1)
