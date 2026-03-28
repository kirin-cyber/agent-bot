"""
Telegram Bot — Long Polling ハンドラー
Telegram のリプライメッセージを受信し、Zendesk チケットに返信する。

起動:
    python3 telegram_bot.py          # 単体起動
    main.py から start_polling() を呼ぶ  # gunicorn 連携
"""

import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode

# health_app.py と同じディレクトリにあることを前提
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from health_app import _load_env, access_log, error_log, DRYRUN_MODE

_load_env()

# --- 設定 ---

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
ZENDESK_SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "")
ZENDESK_EMAIL = os.environ.get("ZENDESK_EMAIL", "")
ZENDESK_API_TOKEN = os.environ.get("ZENDESK_API_TOKEN", "")

POLL_TIMEOUT = 30  # Long Polling タイムアウト（秒）

bot_log = logging.getLogger("telegram_bot")
if not bot_log.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    bot_log.addHandler(sh)
    bot_log.setLevel(logging.INFO)


# ---------------------------------------------------------------
# Telegram Bot API ヘルパー
# ---------------------------------------------------------------

def _tg_api(method: str, params: dict = None) -> dict:
    """Telegram Bot API を呼び出す（JSON形式で送信）"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _tg_send(chat_id: str, text: str, reply_markup: dict = None) -> dict:
    """Telegram にメッセージを送信"""
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return _tg_api("sendMessage", params)


def _tg_answer_callback(callback_query_id: str, text: str = "") -> dict:
    """コールバッククエリに応答"""
    params = {"callback_query_id": callback_query_id}
    if text:
        params["text"] = text
    return _tg_api("answerCallbackQuery", params)


def _tg_edit_message(chat_id: str, message_id: int, text: str) -> dict:
    """既存メッセージを編集"""
    return _tg_api("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    })


# ---------------------------------------------------------------
# Zendesk API ヘルパー
# ---------------------------------------------------------------

def _zendesk_auth_header() -> str:
    """Zendesk API の Basic 認証ヘッダー値"""
    creds = f"{ZENDESK_EMAIL}/token:{ZENDESK_API_TOKEN}"
    return "Basic " + b64encode(creds.encode("utf-8")).decode("utf-8")


def _zendesk_api(method: str, path: str, body: dict = None) -> dict:
    """Zendesk API を呼び出す"""
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _zendesk_auth_header())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        error_log.error("Zendesk API エラー: %s %s → %s %s", method, path, e, err_body)
        raise


def zendesk_add_comment(ticket_id: int, comment_body: str) -> bool:
    """Zendesk チケットにパブリックコメントを追加"""
    if DRYRUN_MODE:
        bot_log.info("[DRYRUN] Zendesk返信スキップ: ticket #%s — %s",
                     ticket_id, comment_body[:100])
        return True
    payload = {
        "ticket": {
            "comment": {
                "body": comment_body,
                "public": True,
            }
        }
    }
    _zendesk_api("PUT", f"/tickets/{ticket_id}.json", payload)
    bot_log.info("Zendesk返信完了: ticket #%s", ticket_id)
    return True


def zendesk_update_status(ticket_id: int, status: str) -> bool:
    """Zendesk チケットのステータスを更新"""
    if DRYRUN_MODE:
        bot_log.info("[DRYRUN] ステータス更新スキップ: ticket #%s → %s",
                     ticket_id, status)
        return True
    payload = {"ticket": {"status": status}}
    _zendesk_api("PUT", f"/tickets/{ticket_id}.json", payload)
    bot_log.info("ステータス更新完了: ticket #%s → %s", ticket_id, status)
    return True


# ---------------------------------------------------------------
# メッセージ処理
# ---------------------------------------------------------------

def _extract_ticket_id(text: str) -> int | None:
    """メッセージ本文から #チケットID を抽出"""
    match = re.search(r"#(\d+)", text)
    return int(match.group(1)) if match else None


def _is_admin(message: dict) -> bool:
    """送信者が管理者かチェック"""
    sender_id = str(message.get("from", {}).get("id", ""))
    return sender_id == ADMIN_CHAT_ID


def _build_status_buttons(ticket_id: int) -> dict:
    """チケットステータス変更用のインラインキーボードを構築"""
    return {
        "inline_keyboard": [[
            {"text": "✅ 解決済み", "callback_data": f"solve:{ticket_id}"},
            {"text": "📂 オープンのまま", "callback_data": f"open:{ticket_id}"},
        ]]
    }


def handle_reply(message: dict) -> None:
    """リプライメッセージを処理 — Zendesk チケットに返信"""
    # 1. 管理者チェック
    if not _is_admin(message):
        bot_log.info("管理者以外のメッセージを無視: user_id=%s",
                     message.get("from", {}).get("id"))
        return

    # 2. リプライ元メッセージの確認
    reply_to = message.get("reply_to_message")
    if not reply_to:
        return  # リプライでなければ無視

    # 3. チケットID抽出
    original_text = reply_to.get("text", "") or reply_to.get("caption", "")
    ticket_id = _extract_ticket_id(original_text)
    if not ticket_id:
        _tg_send(
            str(message["chat"]["id"]),
            "⚠️ リプライ元のメッセージからチケットIDを取得できませんでした。\n"
            "チケット通知メッセージにリプライしてください。",
        )
        return

    # 4. 返信テキスト
    reply_text = message.get("text", "").strip()
    if not reply_text:
        _tg_send(str(message["chat"]["id"]),
                 "⚠️ 返信テキストが空です。")
        return

    # 5. Zendesk にコメント追加
    chat_id = str(message["chat"]["id"])
    try:
        zendesk_add_comment(ticket_id, reply_text)
    except Exception as e:
        _tg_send(chat_id,
                 f"❌ Zendesk返信に失敗しました\n"
                 f"チケット: #{ticket_id}\n"
                 f"エラー: {e}")
        return

    # 6. 成功通知 + ステータスボタン
    dryrun_note = "\n⚠️ DRYRUNモード — 実際のZendesk送信はスキップされました" if DRYRUN_MODE else ""
    _tg_send(
        chat_id,
        f"✅ チケット <b>#{ticket_id}</b> に返信しました{dryrun_note}\n\n"
        f"チケットのステータスを変更しますか？",
        reply_markup=_build_status_buttons(ticket_id),
    )


def handle_callback(callback_query: dict) -> None:
    """インラインボタンのコールバックを処理"""
    sender_id = str(callback_query.get("from", {}).get("id", ""))
    if sender_id != ADMIN_CHAT_ID:
        _tg_answer_callback(callback_query["id"], "権限がありません")
        return

    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    message_id = message.get("message_id")

    # data 形式: "solve:12345" or "open:12345"
    match = re.match(r"^(solve|open):(\d+)$", data)
    if not match:
        _tg_answer_callback(callback_query["id"], "不明な操作です")
        return

    action, ticket_id_str = match.groups()
    ticket_id = int(ticket_id_str)

    try:
        if action == "solve":
            zendesk_update_status(ticket_id, "solved")
            status_text = "解決済み"
            status_emoji = "✅"
        else:
            status_text = "オープンのまま"
            status_emoji = "📂"
            # open の場合はステータス変更不要
    except Exception as e:
        _tg_answer_callback(callback_query["id"], f"エラー: {e}")
        return

    # ボタンメッセージを更新（ボタン除去）
    dryrun_note = " (DRYRUN)" if DRYRUN_MODE else ""
    _tg_edit_message(
        chat_id, message_id,
        f"{status_emoji} チケット <b>#{ticket_id}</b>: {status_text}{dryrun_note}",
    )
    _tg_answer_callback(callback_query["id"], f"{status_text}に設定しました")
    bot_log.info("チケット #%s → %s", ticket_id, status_text)


# ---------------------------------------------------------------
# Long Polling ループ
# ---------------------------------------------------------------

_running = False


def start_polling() -> None:
    """Telegram Bot Long Polling を開始（ブロッキング）"""
    global _running

    if not TELEGRAM_BOT_TOKEN:
        bot_log.error("TELEGRAM_BOT_TOKEN が未設定です。Botを起動できません。")
        return
    if not ADMIN_CHAT_ID:
        bot_log.warning("ADMIN_CHAT_ID が未設定です。全メッセージが無視されます。")

    zendesk_ok = all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN])
    if not zendesk_ok and not DRYRUN_MODE:
        bot_log.error("Zendesk API 認証情報が不足しています。DRYRUNモードで起動します。")

    bot_log.info("Telegram Bot ポーリング開始 (ADMIN=%s, DRYRUN=%s)",
                 ADMIN_CHAT_ID or "未設定", DRYRUN_MODE)

    _running = True
    offset = 0

    while _running:
        try:
            result = _tg_api("getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message", "callback_query"],
            })

            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_reply(update["message"])

        except urllib.error.URLError as e:
            error_log.error("Telegram ポーリングエラー: %s", e)
            time.sleep(5)
        except Exception as e:
            error_log.error("Telegram Bot 予期しないエラー: %s", e)
            time.sleep(5)


def stop_polling() -> None:
    """ポーリングを停止"""
    global _running
    _running = False
    bot_log.info("Telegram Bot ポーリング停止")


# ---------------------------------------------------------------
# 単体起動
# ---------------------------------------------------------------

if __name__ == "__main__":
    bot_log.info("Telegram Bot を単体起動します")
    try:
        start_polling()
    except KeyboardInterrupt:
        stop_polling()
        bot_log.info("Telegram Bot を終了しました")
