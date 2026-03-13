#!/usr/bin/env python3
"""テスト用Webhookスクリプト

Usage:
    python test_webhook.py normal        # 正常系：通常の問い合わせ
    python test_webhook.py invalid_sig   # 異常系：不正な署名（401）
    python test_webhook.py duplicate     # 異常系：重複イベントID（スキップ）
    python test_webhook.py parse_error   # 異常系：JSONパースエラー
"""

import base64
import hashlib
import hmac
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.getenv("TEST_WEBHOOK_URL", "http://localhost:5000/webhook")
ZENDESK_WEBHOOK_SECRET = os.getenv("ZENDESK_WEBHOOK_SECRET", "")

# 重複テスト用の固定イベントID
DUPLICATE_EVENT_ID = "test-duplicate-event-12345"


def sign_payload(payload_bytes):
    """正しいWebhook署名を生成"""
    sig = hmac.new(
        ZENDESK_WEBHOOK_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


def send_request(data, signature=None):
    payload = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Zendesk-Webhook-Signature"] = signature
    else:
        headers["X-Zendesk-Webhook-Signature"] = sign_payload(payload)

    resp = requests.post(WEBHOOK_URL, data=payload, headers=headers, timeout=60)
    return resp


def test_normal():
    """正常系：通常の問い合わせ"""
    print("=" * 60)
    print("TEST: normal - 通常の問い合わせ")
    print("=" * 60)

    data = {
        "event_id": f"test-normal-{os.urandom(4).hex()}",
        "ticket_id": f"TEST-{os.urandom(4).hex()}",
        "email": "test@example.com",
        "body": "ログインできないのですが、パスワードをリセットする方法を教えてください。",
    }

    resp = send_request(data)
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), ensure_ascii=False, indent=2)}")
    print()

    if resp.status_code == 200:
        print("✅ PASS: 正常にレスポンスが返りました")
    else:
        print(f"❌ FAIL: 期待値 200, 実際 {resp.status_code}")
    print()


def test_invalid_sig():
    """異常系：不正な署名"""
    print("=" * 60)
    print("TEST: invalid_sig - 不正な署名")
    print("=" * 60)

    data = {
        "event_id": f"test-invalid-{os.urandom(4).hex()}",
        "ticket_id": f"TEST-{os.urandom(4).hex()}",
        "email": "test@example.com",
        "body": "テスト問い合わせ",
    }

    resp = send_request(data, signature="invalid-signature-xxxxx")
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), ensure_ascii=False, indent=2)}")
    print()

    if resp.status_code == 401:
        print("✅ PASS: 401で拒否されました")
    else:
        print(f"❌ FAIL: 期待値 401, 実際 {resp.status_code}")
    print()


def test_duplicate():
    """異常系：重複イベントID"""
    print("=" * 60)
    print("TEST: duplicate - 重複イベントID")
    print("=" * 60)

    data = {
        "event_id": DUPLICATE_EVENT_ID,
        "ticket_id": f"TEST-DUP-{os.urandom(4).hex()}",
        "email": "test@example.com",
        "body": "ログインできません",
    }

    # 1回目の送信
    print("1回目の送信...")
    resp1 = send_request(data)
    print(f"Status: {resp1.status_code}")
    print(f"Response: {json.dumps(resp1.json(), ensure_ascii=False, indent=2)}")
    print()

    # 2回目の送信（同じevent_id）
    print("2回目の送信（同じevent_id）...")
    resp2 = send_request(data)
    print(f"Status: {resp2.status_code}")
    result = resp2.json()
    print(f"Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
    print()

    if resp2.status_code == 200 and result.get("status") == "duplicate":
        print("✅ PASS: 重複イベントがスキップされました")
    else:
        print(f"❌ FAIL: 重複検知されませんでした")
    print()


def test_parse_error():
    """異常系：JSONパースエラーを引き起こすケース"""
    print("=" * 60)
    print("TEST: parse_error - JSONパースエラー")
    print("=" * 60)

    # Claude APIが非JSON応答を返すようなリクエスト
    # (テンプレートにマッチしない非常に特殊な問い合わせ)
    data = {
        "event_id": f"test-parse-{os.urandom(4).hex()}",
        "ticket_id": f"TEST-PARSE-{os.urandom(4).hex()}",
        "email": "test@example.com",
        "body": "asdkfjhaslkdjfh asdlfkjh qweoiru これはテスト用の意味のない文字列です 12345 !@#$%",
    }

    resp = send_request(data)
    print(f"Status: {resp.status_code}")
    print(f"Response: {json.dumps(resp.json(), ensure_ascii=False, indent=2)}")
    print()

    # パースエラーの場合もステータス200が返る（エラーハンドリングされるため）
    if resp.status_code == 200:
        print("✅ PASS: リクエストが処理されました（パースエラーの場合はerror.logを確認）")
    else:
        print(f"❌ FAIL: 期待値 200, 実際 {resp.status_code}")
    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    test_name = sys.argv[1]
    tests = {
        "normal": test_normal,
        "invalid_sig": test_invalid_sig,
        "duplicate": test_duplicate,
        "parse_error": test_parse_error,
    }

    if test_name not in tests:
        print(f"Unknown test: {test_name}")
        print(f"Available tests: {', '.join(tests.keys())}")
        sys.exit(1)

    print(f"\n🧪 Running test: {test_name}\n")
    tests[test_name]()


if __name__ == "__main__":
    main()
