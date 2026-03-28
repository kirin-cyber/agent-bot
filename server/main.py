"""
Sixamo API Server — WSGI エントリーポイント
gunicorn から起動される WSGI アプリケーション。

起動例:
    gunicorn main:app -b 127.0.0.1:5000 --workers 2 --timeout 60
"""

import json
import os
import sys
import threading

# health_app.py と同じディレクトリにあることを前提にインポート
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_app import (
    _load_env,
    build_health_response,
    verify_zendesk_signature,
    is_zendesk_ip,
    send_telegram,
    format_ticket_message,
    format_parse_error_message,
    access_log,
    error_log,
    ZENDESK_WEBHOOK_SECRET,
    ZENDESK_IP_RANGES,
    DRYRUN_MODE,
    ADMIN_CHAT_ID,
    _dedup,
)
import telegram_bot


# ---------------------------------------------------------------
# WSGI アプリケーション
# ---------------------------------------------------------------

def app(environ, start_response):
    """WSGI callable — gunicorn のエントリーポイント (main:app)"""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path in ("/", "/health"):
        return _handle_health(environ, start_response)
    elif method == "POST" and path == "/webhook":
        return _handle_webhook(environ, start_response)
    else:
        return _json_response(start_response, 404, {"error": "not found"})


# 後方互換: main:application でも起動可能
application = app


def _handle_health(environ, start_response):
    data = build_health_response()
    code = 200 if data["status"] == "ok" else 503
    return _json_response(start_response, code, data)


def _handle_webhook(environ, start_response):
    # 1. IP制限チェック
    client_ip = environ.get("HTTP_X_REAL_IP",
                            environ.get("REMOTE_ADDR", ""))
    if ZENDESK_IP_RANGES and not is_zendesk_ip(client_ip):
        access_log.warning("IP制限で拒否: %s", client_ip)
        return _json_response(start_response, 403,
                              {"error": "forbidden: IP not allowed"})

    # 2. リクエストボディ読み取り
    try:
        content_length = int(environ.get("CONTENT_LENGTH", 0))
    except (ValueError, TypeError):
        content_length = 0
    if content_length > 1_048_576:  # 1MB制限
        return _json_response(start_response, 413,
                              {"error": "payload too large"})
    body = environ["wsgi.input"].read(content_length)

    # 3. Zendesk署名検証
    signature = environ.get("HTTP_X_ZENDESK_WEBHOOK_SIGNATURE", "")
    timestamp = environ.get("HTTP_X_ZENDESK_WEBHOOK_SIGNATURE_TIMESTAMP", "")

    if ZENDESK_WEBHOOK_SECRET:
        if not signature or not timestamp:
            access_log.warning("署名ヘッダー不足: %s", client_ip)
            return _json_response(start_response, 401,
                                  {"error": "missing signature headers"})
        if not verify_zendesk_signature(signature, timestamp, body):
            error_log.warning("署名検証失敗: %s", client_ip)
            return _json_response(start_response, 401,
                                  {"error": "invalid signature"})

    # 4. ペイロード解析
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        error_log.error("JSONパースエラー: %s", e)
        raw = body.decode("utf-8", errors="replace")
        err_msg = format_parse_error_message(raw, str(e))
        send_telegram(err_msg)
        return _json_response(start_response, 400,
                              {"error": "invalid JSON"})

    # 5. 重複チェック
    ticket = payload.get("ticket", payload)
    ticket_id = ticket.get("id")
    if ticket_id and _dedup.is_duplicate(ticket_id):
        access_log.info("重複スキップ: ticket #%s", ticket_id)
        return _json_response(start_response, 200,
                              {"status": "duplicate_skipped",
                               "ticket_id": ticket_id})

    # 6. Telegram通知
    message = format_ticket_message(payload)
    sent = send_telegram(message)
    access_log.info("Webhook処理完了: ticket #%s, Telegram=%s, dryrun=%s",
                    ticket_id, "sent" if sent else "failed", DRYRUN_MODE)

    status = "notified" if sent else "received_but_notification_failed"
    return _json_response(start_response, 200,
                          {"status": status, "dryrun": DRYRUN_MODE})


def _json_response(start_response, code, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    status_map = {
        200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized",
        403: "403 Forbidden", 404: "404 Not Found", 413: "413 Payload Too Large",
        503: "503 Service Unavailable",
    }
    status_line = status_map.get(code, f"{code} Error")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status_line, headers)
    return [body]


# ---------------------------------------------------------------
# 起動通知（gunicorn ワーカー初回ロード時に1回だけ送信）
# ---------------------------------------------------------------

def _send_startup_notification():
    """サーバー起動時にTelegramへ通知を送信"""
    from health_app import _count_templates, TELEGRAM_BOT_TOKEN
    dryrun_label = "ON" if DRYRUN_MODE else "OFF"
    template_count = _count_templates()
    webhook_status = "enabled" if ZENDESK_WEBHOOK_SECRET else "disabled"
    # gunicorn ワーカー数を取得
    worker_count = int(os.environ.get("WEB_CONCURRENCY",
                       os.environ.get("GUNICORN_WORKERS", "1")))

    tg_bot_status = "enabled" if ADMIN_CHAT_ID else "disabled (ADMIN_CHAT_ID未設定)"
    msg = (
        f"🚀 <b>サーバーが起動しました</b>\n"
        f"\n"
        f"DRYRUNモード：{dryrun_label}\n"
        f"Zendesk webhook：{webhook_status}\n"
        f"Telegram Bot：{tg_bot_status}\n"
        f"テンプレート数：{template_count}件\n"
        f"ワーカー数：{worker_count}"
    )
    sent = send_telegram(msg)
    if sent:
        access_log.info("起動通知をTelegramに送信しました")
    else:
        access_log.warning("起動通知の送信に失敗しました (token=%s)",
                           "set" if TELEGRAM_BOT_TOKEN else "missing")


# モジュールロード時に起動通知をバックグラウンドで送信
# （gunicorn のワーカー起動を遅延させないため）
_startup_thread = threading.Thread(target=_send_startup_notification, daemon=True)
_startup_thread.start()

# Telegram Bot ポーリングをバックグラウンドで起動
_bot_thread = threading.Thread(target=telegram_bot.start_polling, daemon=True)
_bot_thread.start()
