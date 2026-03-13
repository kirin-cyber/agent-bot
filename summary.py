#!/usr/bin/env python3
"""週次サマリー送信スクリプト"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
JST = timezone(timedelta(hours=9))


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram credentials not configured", file=sys.stderr)
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
        print(f"ERROR: Telegram send failed: {e}", file=sys.stderr)
        return False


def get_last_week_stats():
    now = datetime.now(tz=JST)
    # 先週の月曜日
    last_monday = now - timedelta(days=now.weekday() + 7)
    week_start = last_monday.strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    row = conn.execute(
        "SELECT auto_replied, forwarded, errors, category_hits_json "
        "FROM weekly_stats WHERE week_start = ?",
        (week_start,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "week_start": week_start,
        "auto_replied": row[0],
        "forwarded": row[1],
        "errors": row[2],
        "category_hits": json.loads(row[3]) if row[3] else {},
    }


def main():
    try:
        stats = get_last_week_stats()

        if stats is None:
            send_telegram("📊 先週のデータがありません。")
            return

        total = stats["auto_replied"] + stats["forwarded"] + stats["errors"]
        rate = round(stats["auto_replied"] / total * 100, 1) if total > 0 else 0

        category_lines = ""
        if stats["category_hits"]:
            hits = sorted(
                stats["category_hits"].items(), key=lambda x: x[1], reverse=True
            )
            category_lines = " / ".join(f"{k}：{v}件" for k, v in hits)
        else:
            category_lines = "データなし"

        message = (
            f"📊 <b>先週の自動化サマリー</b>\n"
            f"（{stats['week_start']}〜）\n\n"
            f"自動返信完了：{stats['auto_replied']}件 ✅\n"
            f"担当者に転送：{stats['forwarded']}件 🔔\n"
            f"エラー発生：{stats['errors']}件 ⚠️\n"
            f"自動化率：{rate}%\n\n"
            f"カテゴリ別ヒット数：\n{category_lines}"
        )

        if not send_telegram(message):
            raise RuntimeError("Telegram send failed")

        print("Weekly summary sent successfully")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        send_telegram(
            "⚠️ 週次サマリーの送信に失敗しました。\n"
            "journalctl -u sixamo-summary で確認してください"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
