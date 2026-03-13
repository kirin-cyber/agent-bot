#!/usr/bin/env python3
"""SQLite DBバックアップスクリプト"""

import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from glob import glob

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BACKUP_S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "events.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MAX_GENERATIONS = 7
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


def cleanup_old_backups():
    """7世代を超えるバックアップを削除"""
    backups = sorted(glob(os.path.join(BACKUP_DIR, "events_backup_*.db")))
    while len(backups) > MAX_GENERATIONS:
        old = backups.pop(0)
        os.remove(old)
        print(f"Removed old backup: {old}")


def upload_to_s3(file_path):
    """S3にバックアップファイルをアップロード"""
    try:
        import boto3

        s3 = boto3.client("s3")
        filename = os.path.basename(file_path)
        s3.upload_file(file_path, BACKUP_S3_BUCKET, f"backups/{filename}")
        print(f"Uploaded to S3: s3://{BACKUP_S3_BUCKET}/backups/{filename}")
    except Exception as e:
        raise RuntimeError(f"S3 upload failed: {e}") from e


def main():
    try:
        if not os.path.exists(DB_PATH):
            print("WARNING: events.db not found, nothing to backup")
            return

        os.makedirs(BACKUP_DIR, exist_ok=True)

        today = datetime.now(tz=JST).strftime("%Y%m%d")
        backup_filename = f"events_backup_{today}.db"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        shutil.copy2(DB_PATH, backup_path)
        print(f"Backup created: {backup_path}")

        cleanup_old_backups()

        if BACKUP_S3_BUCKET:
            upload_to_s3(backup_path)

        print("Backup completed successfully")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        send_telegram(
            "⚠️ DBバックアップに失敗しました。\n"
            "journalctl -u sixamo-backup で確認してください"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
