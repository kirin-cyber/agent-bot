#!/usr/bin/env python3
"""Zendesk問い合わせ自動化システム - メインサーバー"""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import anthropic
import requests
import yaml
from dotenv import load_dotenv
from flask import Flask, Request, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

# ---------------------------------------------------------------------------
# 環境変数
# ---------------------------------------------------------------------------
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN", "")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL", "")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN", "")
ZENDESK_WEBHOOK_SECRET = os.getenv("ZENDESK_WEBHOOK_SECRET", "")
ZENDESK_IP_RANGES = os.getenv("ZENDESK_IP_RANGES", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

REPLY_EMAIL = os.getenv("REPLY_EMAIL", "no-reply@sixamo.forex")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "")

DRYRUN_MODE = os.getenv("DRYRUN_MODE", "true").lower() == "true"
GUNICORN_WORKERS = int(os.getenv("GUNICORN_WORKERS", "4"))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
TEMPLATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates.yaml")

JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------
def setup_logging():
    log_dir = os.path.dirname(os.path.abspath(__file__))

    access_handler = RotatingFileHandler(
        os.path.join(log_dir, "access.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "error.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )

    access_logger = logging.getLogger("access")
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(access_handler)

    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.ERROR)
    error_logger.addHandler(error_handler)

    return access_logger, error_logger


access_log, error_log = setup_logging()

# ---------------------------------------------------------------------------
# テンプレート読み込み
# ---------------------------------------------------------------------------
TEMPLATES_CACHE = None


def load_templates():
    global TEMPLATES_CACHE
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
            TEMPLATES_CACHE = yaml.safe_load(f)
        if not isinstance(TEMPLATES_CACHE, list):
            raise ValueError("templates.yaml must be a list")
        return True
    except Exception as e:
        error_log.error("templates.yaml load error: %s", e, exc_info=True)
        send_telegram(
            "⚠️ templates.yamlに構文エラーがあります。"
            "バックアップファイルに戻してから再起動してください\n"
            f"エラー: {e}"
        )
        return False


# ---------------------------------------------------------------------------
# データベース
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processed_tickets (
            ticket_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS weekly_stats (
            week_start TEXT PRIMARY KEY,
            auto_replied INTEGER DEFAULT 0,
            forwarded INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            category_hits_json TEXT DEFAULT '{}'
        );
    """)
    conn.commit()
    # 30日前の processed_events を削除
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
    conn.execute("DELETE FROM processed_events WHERE processed_at < ?", (cutoff,))
    conn.commit()
    conn.close()


def is_event_processed(event_id):
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_event_processed(event_id):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO processed_events (event_id, processed_at) VALUES (?, ?)",
        (event_id, datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def is_ticket_processed(ticket_id):
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM processed_tickets WHERE ticket_id = ?", (str(ticket_id),)
    ).fetchone()
    conn.close()
    return row is not None


def mark_ticket_processed(ticket_id):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO processed_tickets (ticket_id, processed_at) VALUES (?, ?)",
        (str(ticket_id), datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def update_weekly_stats(stat_type, category=None):
    """stat_type: 'auto_replied' | 'forwarded' | 'errors'"""
    now = datetime.now(tz=JST)
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute(
        """INSERT INTO weekly_stats (week_start, auto_replied, forwarded, errors, category_hits_json)
           VALUES (?, 0, 0, 0, '{}')
           ON CONFLICT(week_start) DO NOTHING""",
        (week_start,),
    )
    conn.execute(
        f"UPDATE weekly_stats SET {stat_type} = {stat_type} + 1 WHERE week_start = ?",
        (week_start,),
    )
    if category:
        row = conn.execute(
            "SELECT category_hits_json FROM weekly_stats WHERE week_start = ?",
            (week_start,),
        ).fetchone()
        hits = json.loads(row[0]) if row and row[0] else {}
        hits[category] = hits.get(category, 0) + 1
        conn.execute(
            "UPDATE weekly_stats SET category_hits_json = ? WHERE week_start = ?",
            (json.dumps(hits, ensure_ascii=False), week_start),
        )
    conn.commit()
    conn.close()


def cleanup_old_events():
    """30日前のprocessed_eventsを削除"""
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
    conn = get_db()
    conn.execute("DELETE FROM processed_events WHERE processed_at < ?", (cutoff,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Telegram通知
# ---------------------------------------------------------------------------
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        error_log.error("Telegram credentials not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        error_log.error("Telegram send error: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Zendesk API
# ---------------------------------------------------------------------------
def zendesk_api(method, endpoint, json_data=None):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2{endpoint}"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    try:
        resp = requests.request(
            method, url, auth=auth, json=json_data, timeout=30
        )
        resp.raise_for_status()
        return resp
    except Exception as e:
        error_log.error("Zendesk API error: %s %s: %s", method, endpoint, e, exc_info=True)
        raise


def zendesk_reply(ticket_id, body):
    """チケットに返信メールを送信（Reply-Toヘッダー付き）"""
    return zendesk_api(
        "PUT",
        f"/tickets/{ticket_id}.json",
        {
            "ticket": {
                "comment": {
                    "body": body,
                    "public": True,
                    "via": {
                        "channel": "api",
                        "source": {
                            "from": {"address": REPLY_EMAIL},
                            "to": {"address": REPLY_TO_EMAIL},
                        },
                    },
                }
            }
        },
    )


def zendesk_solve_ticket(ticket_id):
    """チケットを解決済みに変更"""
    return zendesk_api(
        "PUT",
        f"/tickets/{ticket_id}.json",
        {"ticket": {"status": "solved"}},
    )


def zendesk_add_internal_note(ticket_id, note):
    """内部ノートを追加"""
    return zendesk_api(
        "PUT",
        f"/tickets/{ticket_id}.json",
        {
            "ticket": {
                "comment": {
                    "body": note,
                    "public": False,
                }
            }
        },
    )


# ---------------------------------------------------------------------------
# セキュリティ
# ---------------------------------------------------------------------------
def parse_ip_ranges():
    ranges = []
    if not ZENDESK_IP_RANGES:
        return ranges
    for r in ZENDESK_IP_RANGES.split(","):
        r = r.strip()
        if r:
            try:
                ranges.append(ipaddress.ip_network(r, strict=False))
            except ValueError:
                error_log.error("Invalid IP range: %s", r)
    return ranges


ZENDESK_NETWORKS = parse_ip_ranges()


def is_zendesk_ip(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in ZENDESK_NETWORKS)
    except ValueError:
        return False


def verify_webhook_signature(payload, signature):
    if not ZENDESK_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        ZENDESK_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected).decode("utf-8")
    return hmac.compare_digest(expected_b64, signature)


# ---------------------------------------------------------------------------
# キーワードマッチング
# ---------------------------------------------------------------------------
def match_templates(query_text):
    """キーワード一致でテンプレートを抽出（最大10件）"""
    if not TEMPLATES_CACHE:
        return []

    scored = []
    for tpl in TEMPLATES_CACHE:
        keywords = tpl.get("keywords", [])
        hits = sum(1 for kw in keywords if kw in query_text)
        if hits > 0:
            scored.append((hits, tpl))

    # キーワード一致があれば関連度順でソート
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:10]]

    # 一致なしの場合は全件から最大10件
    return TEMPLATES_CACHE[:10]


# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """あなたはカスタマーサポートAIです。
以下のテンプレートを参考に問い合わせに対応できるか判断してください。
reply・reasonフィールド両方に以下の表現を絶対に使わないこと：
「必ず」「確実に」「保証します」「絶対に」「間違いなく」「必ずしも」
返信文（reply）は500文字以内にすること。
必ずJSON形式のみで返してください。前置きや説明は一切不要です。
{"can_respond": true/false, "reply": "返信文", "reason": "判断理由（簡潔に）", "category": "マッチしたカテゴリ名（なければnull）"}"""


def ask_claude(query_text, templates):
    templates_text = ""
    for tpl in templates:
        templates_text += f"\n【{tpl['category']}】\n{tpl['template']}\n"

    user_message = f"テンプレート一覧：\n{templates_text}\n\n問い合わせ内容：\n{query_text}"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        timeout=30,
    )

    return response.content[0].text


# ---------------------------------------------------------------------------
# Flask アプリケーション
# ---------------------------------------------------------------------------
app = Flask(__name__)


def rate_limit_key():
    """ZendeskのIPはレート制限対象外"""
    remote_ip = request.remote_addr or "unknown"
    if is_zendesk_ip(remote_ip):
        return f"whitelist-{remote_ip}"
    return remote_ip


limiter = Limiter(
    key_func=rate_limit_key,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.errorhandler(429)
def ratelimit_handler(e):
    remote_ip = request.remote_addr or "unknown"
    error_log.error("Rate limit exceeded: IP=%s", remote_ip)
    access_log.info("RATE_LIMITED ip=%s", remote_ip)
    return jsonify({"error": "rate limit exceeded"}), 429


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
@limiter.limit("20/minute", exempt_when=lambda: is_zendesk_ip(request.remote_addr or ""))
def webhook():
    ticket_id = None
    try:
        payload = request.get_data()
        data = request.get_json(force=True)

        ticket_id = str(data.get("ticket_id", data.get("id", "")))
        event_id = str(data.get("event_id", ""))
        email = data.get("email", data.get("requester_email", ""))
        query_text = data.get("body", data.get("description", data.get("content", "")))

        # Step 2: processed_ticketsでチケットIDを確認（再問い合わせ検知）
        if ticket_id and is_ticket_processed(ticket_id):
            send_telegram(
                f"🔔 <b>再問い合わせ検知 - 担当者に転送</b>\n"
                f"チケット #{ticket_id}\n"
                f"既に処理済みのチケットから再度お問い合わせがありました。"
            )
            update_weekly_stats("forwarded")
            access_log.info(
                "ticket=%s result=re_inquiry_forwarded", ticket_id
            )
            return jsonify({"status": "forwarded", "reason": "re-inquiry"}), 200

        # Step 4: 署名検証
        signature = request.headers.get("X-Zendesk-Webhook-Signature", "")
        if not verify_webhook_signature(payload, signature):
            access_log.info("ticket=%s result=invalid_signature", ticket_id)
            return jsonify({"error": "invalid signature"}), 401

        # Step 5: イベントID重複チェック
        if event_id and is_event_processed(event_id):
            access_log.info(
                "ticket=%s event=%s result=duplicate_skipped", ticket_id, event_id
            )
            return jsonify({"status": "duplicate", "skipped": True}), 200

        # イベントIDを記録
        if event_id:
            mark_event_processed(event_id)

        # Step 6: データ抽出
        if not ticket_id or not query_text:
            return jsonify({"error": "missing required fields"}), 400

        # Step 7: キーワードマッチング
        matched_templates = match_templates(query_text)

        # Step 8: Claude API呼び出し
        ai_response_text = ask_claude(query_text, matched_templates)

        # Step 9: JSONパース
        try:
            ai_result = json.loads(ai_response_text)
        except json.JSONDecodeError:
            error_log.error(
                "JSON parse error for ticket #%s. Raw response: %s",
                ticket_id,
                ai_response_text,
            )
            send_telegram(
                f"⚠️ <b>AIの返答がJSON形式ではありませんでした</b>\n"
                f"チケット #{ticket_id} を手動確認してください"
            )
            update_weekly_stats("errors")
            access_log.info("ticket=%s result=parse_error", ticket_id)
            return jsonify({"status": "error", "reason": "parse_error"}), 200

        can_respond = ai_result.get("can_respond", False)
        reply_text = ai_result.get("reply", "")
        reason = ai_result.get("reason", "")
        category = ai_result.get("category")

        # Step 10: 分岐処理
        if can_respond:
            if DRYRUN_MODE:
                # DRYRUNモード
                send_telegram(
                    f"✅ <b>返信案確認（DRYRUN）</b>\n"
                    f"チケット #{ticket_id}\n"
                    f"カテゴリ: {category or '該当なし'}\n"
                    f"判断理由: {reason}\n\n"
                    f"返信案:\n{reply_text}\n\n"
                    f"⚠️ DRYRUNモード中：自動送信はされていません"
                )
                update_weekly_stats("auto_replied", category)
                mark_ticket_processed(ticket_id)
                access_log.info(
                    "ticket=%s result=dryrun_auto_reply reason=%s category=%s",
                    ticket_id, reason, category,
                )
                return jsonify({"status": "dryrun", "can_respond": True}), 200
            else:
                # 本番モード
                # Step1: Zendesk返信
                try:
                    zendesk_reply(ticket_id, reply_text)
                except Exception as e:
                    error_log.error("Reply failed ticket #%s: %s", ticket_id, e, exc_info=True)
                    send_telegram(
                        f"⚠️ <b>返信送信失敗</b>\n"
                        f"チケット #{ticket_id}\n"
                        f"エラー: {e}"
                    )
                    update_weekly_stats("errors")
                    access_log.info("ticket=%s result=reply_failed reason=%s", ticket_id, reason)
                    return jsonify({"status": "error", "reason": "reply_failed"}), 200

                # Step2: チケットを解決済みに
                try:
                    zendesk_solve_ticket(ticket_id)
                except Exception as e:
                    error_log.error("Solve failed ticket #%s: %s", ticket_id, e, exc_info=True)
                    send_telegram(
                        f"⚠️ <b>返信済みだがチケット更新失敗</b>\n"
                        f"チケット #{ticket_id}\n"
                        f"エラー: {e}"
                    )

                # Step3: 内部ノート
                now_str = datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M:%S")
                note = (
                    f"【自動返信ログ】\n"
                    f"送信日時：{now_str}\n"
                    f"判断理由：{reason}\n"
                    f"送信内容：{reply_text}"
                )
                try:
                    zendesk_add_internal_note(ticket_id, note)
                except Exception as e:
                    error_log.error("Internal note failed ticket #%s: %s", ticket_id, e, exc_info=True)

                # Step4: Telegram通知
                try:
                    send_telegram(
                        f"✅ <b>自動返信完了</b>\n"
                        f"チケット #{ticket_id}\n"
                        f"カテゴリ: {category or '該当なし'}\n"
                        f"判断理由: {reason}"
                    )
                except Exception as e:
                    error_log.error("Telegram notify failed ticket #%s: %s", ticket_id, e, exc_info=True)

                # Step5: チケットID記録
                update_weekly_stats("auto_replied", category)
                mark_ticket_processed(ticket_id)
                access_log.info(
                    "ticket=%s result=auto_replied reason=%s category=%s",
                    ticket_id, reason, category,
                )
                return jsonify({"status": "auto_replied"}), 200
        else:
            # 対応不可
            send_telegram(
                f"🔔 <b>担当者に転送</b>\n"
                f"チケット #{ticket_id}\n"
                f"判断理由: {reason}\n"
                f"カテゴリ: {category or '該当なし'}"
            )
            update_weekly_stats("forwarded", category)
            access_log.info(
                "ticket=%s result=forwarded reason=%s category=%s",
                ticket_id, reason, category,
            )
            return jsonify({"status": "forwarded"}), 200

    except Exception as e:
        error_log.error("Webhook processing error: %s", e, exc_info=True)
        if ticket_id:
            send_telegram(
                f"⚠️ <b>エラー発生</b>\n"
                f"チケット #{ticket_id}\n"
                f"エラー: {e}"
            )
        update_weekly_stats("errors")
        access_log.info("ticket=%s result=error", ticket_id)
        return jsonify({"status": "error"}), 500


# ---------------------------------------------------------------------------
# 起動処理
# ---------------------------------------------------------------------------
def startup():
    """サーバー起動時の初期化処理"""
    init_db()
    cleanup_old_events()

    if not load_templates():
        sys.exit(1)

    template_count = len(TEMPLATES_CACHE) if TEMPLATES_CACHE else 0
    dryrun_str = "ON" if DRYRUN_MODE else "OFF"

    send_telegram(
        f"🚀 サーバーが起動しました\n"
        f"DRYRUNモード：{dryrun_str}\n"
        f"テンプレート数：{template_count}件\n"
        f"ワーカー数：{GUNICORN_WORKERS}"
    )


startup()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
