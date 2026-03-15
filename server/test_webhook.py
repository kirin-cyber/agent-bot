#!/usr/bin/env python3
"""
Zendesk Webhook テストスクリプト

使用方法:
    python test_webhook.py normal        # 正常系テスト → Telegramに✅返信案通知
    python test_webhook.py invalid_sig   # 異常系: 不正な署名 → 401
    python test_webhook.py duplicate     # 異常系: 重複チケット → 200 (スキップ)
    python test_webhook.py parse_error   # 異常系: 不正JSON → Telegramに⚠️パースエラー通知
    python test_webhook.py all           # 全テスト実行

前提:
    - health_app.py が http://127.0.0.1:5000 で起動していること
    - /opt/sixamo/.env に ZENDESK_WEBHOOK_SECRET が設定されていること
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error

# --- 設定 ---
BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:5000")
ENV_FILE = os.environ.get("ENV_FILE", "/opt/sixamo/.env")

# テスト用チケットペイロード
NORMAL_PAYLOAD = {
    "ticket": {
        "id": 99999,
        "subject": "[テスト] Webhook動作確認",
        "status": "new",
        "priority": "high",
        "requester": {
            "name": "テストユーザー"
        },
        "description": "これはWebhook設定の動作確認テストです。"
                       "Telegramに通知が届けば成功です。"
    }
}

# 重複テスト用（normalと同じIDを使用）
DUPLICATE_PAYLOAD = {
    "ticket": {
        "id": 99999,
        "subject": "[テスト] 重複チケット",
        "status": "new",
        "priority": "low",
        "requester": {
            "name": "重複テストユーザー"
        },
        "description": "この通知は重複検知でスキップされるべきです。"
    }
}

PARSE_ERROR_PAYLOAD = b"<html>this is not json!!!</html>"


def _load_secret() -> str:
    """ZENDESK_WEBHOOK_SECRET を .env から読み取り"""
    secret = os.environ.get("ZENDESK_WEBHOOK_SECRET", "")
    if secret:
        return secret
    if not os.path.isfile(ENV_FILE):
        return ""
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("ZENDESK_WEBHOOK_SECRET="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val and not val.startswith("your_"):
                    return val
    return ""


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    """Zendesk Webhook 署名を生成"""
    sign_payload = timestamp.encode("utf-8") + body
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), sign_payload, hashlib.sha256).digest()
    ).decode("utf-8")


def _send_request(path: str, body: bytes, headers: dict = None) -> tuple:
    """HTTPリクエストを送信し (status_code, response_body) を返す"""
    url = f"{BASE_URL}{path}"
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            resp_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            resp_body = {"raw": e.read().decode("utf-8", errors="replace")}
        return e.code, resp_body


def _print_result(test_name: str, expected_code: int, actual_code: int,
                  response: dict, extra_check: str = None):
    """テスト結果を整形表示"""
    passed = actual_code == expected_code
    icon = "✅" if passed else "❌"
    print(f"\n{'='*50}")
    print(f"{icon} テスト: {test_name}")
    print(f"{'='*50}")
    print(f"  期待HTTP: {expected_code}")
    print(f"  実際HTTP: {actual_code}")
    print(f"  レスポンス: {json.dumps(response, ensure_ascii=False)}")
    if extra_check:
        print(f"  追加確認: {extra_check}")
    print(f"  結果: {'PASS' if passed else 'FAIL'}")
    return passed


# ---------------------------------------------------------------
# テストケース
# ---------------------------------------------------------------

def test_normal(secret: str) -> bool:
    """正常系: 正しい署名付きリクエスト → 200 + Telegram通知"""
    body = json.dumps(NORMAL_PAYLOAD).encode("utf-8")
    timestamp = str(int(time.time()))

    headers = {}
    if secret:
        sig = _sign(secret, timestamp, body)
        headers["X-Zendesk-Webhook-Signature"] = sig
        headers["X-Zendesk-Webhook-Signature-Timestamp"] = timestamp

    code, resp = _send_request("/webhook", body, headers)
    return _print_result(
        "normal (正常系)",
        200, code, resp,
        "→ Telegramに✅返信案通知が届くことを確認 (⚠️ DRYRUNモード中 と表示)"
    )


def test_invalid_sig(secret: str) -> bool:
    """異常系: 不正な署名 → 401"""
    body = json.dumps(NORMAL_PAYLOAD).encode("utf-8")
    timestamp = str(int(time.time()))

    headers = {
        "X-Zendesk-Webhook-Signature": "invalid_signature_xxxxxxxxxx",
        "X-Zendesk-Webhook-Signature-Timestamp": timestamp,
    }

    code, resp = _send_request("/webhook", body, headers)
    return _print_result(
        "invalid_sig (不正署名)",
        401, code, resp,
        "→ 401が返りTelegramに通知なし"
    )


def test_duplicate(secret: str) -> bool:
    """異常系: 重複チケット → 200 (duplicate_skipped)"""
    # まず normalを送信して重複検知キャッシュに登録（既に登録済みの場合もある）
    body_first = json.dumps(NORMAL_PAYLOAD).encode("utf-8")
    timestamp = str(int(time.time()))
    headers = {}
    if secret:
        sig = _sign(secret, timestamp, body_first)
        headers["X-Zendesk-Webhook-Signature"] = sig
        headers["X-Zendesk-Webhook-Signature-Timestamp"] = timestamp
    _send_request("/webhook", body_first, headers)

    # 同じチケットIDで再送信
    time.sleep(0.5)
    body = json.dumps(DUPLICATE_PAYLOAD).encode("utf-8")
    timestamp2 = str(int(time.time()))
    headers2 = {}
    if secret:
        sig2 = _sign(secret, timestamp2, body)
        headers2["X-Zendesk-Webhook-Signature"] = sig2
        headers2["X-Zendesk-Webhook-Signature-Timestamp"] = timestamp2
    code, resp = _send_request("/webhook", body, headers2)

    is_skipped = resp.get("status") == "duplicate_skipped"
    passed = code == 200 and is_skipped
    icon = "✅" if passed else "❌"
    print(f"\n{'='*50}")
    print(f"{icon} テスト: duplicate (重複検知)")
    print(f"{'='*50}")
    print(f"  期待HTTP: 200 (duplicate_skipped)")
    print(f"  実際HTTP: {code}")
    print(f"  レスポンス: {json.dumps(resp, ensure_ascii=False)}")
    print(f"  重複スキップ: {'はい' if is_skipped else 'いいえ'}")
    print(f"  結果: {'PASS' if passed else 'FAIL'}")
    return passed


def test_parse_error(secret: str) -> bool:
    """異常系: 不正なJSON → 400 + Telegram⚠️パースエラー通知"""
    body = PARSE_ERROR_PAYLOAD
    timestamp = str(int(time.time()))

    headers = {}
    if secret:
        sig = _sign(secret, timestamp, body)
        headers["X-Zendesk-Webhook-Signature"] = sig
        headers["X-Zendesk-Webhook-Signature-Timestamp"] = timestamp

    code, resp = _send_request("/webhook", body, headers)
    return _print_result(
        "parse_error (不正JSON)",
        400, code, resp,
        "→ Telegramに⚠️パースエラー通知が届くことを確認"
    )


# ---------------------------------------------------------------
# メイン
# ---------------------------------------------------------------

TESTS = {
    "normal": test_normal,
    "invalid_sig": test_invalid_sig,
    "duplicate": test_duplicate,
    "parse_error": test_parse_error,
}


def main():
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python test_webhook.py normal        # 正常系テスト")
        print("  python test_webhook.py invalid_sig   # 不正署名テスト")
        print("  python test_webhook.py duplicate     # 重複検知テスト")
        print("  python test_webhook.py parse_error   # パースエラーテスト")
        print("  python test_webhook.py all           # 全テスト実行")
        sys.exit(1)

    test_name = sys.argv[1]
    secret = _load_secret()

    print(f"Webhook Secret: {'設定済み' if secret else '未設定 (署名なしモード)'}")
    print(f"ターゲット: {BASE_URL}/webhook")
    print(f"DRYRUN_MODE: 確認するには curl {BASE_URL}/health")

    # ヘルスチェック
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=5) as resp:
            health = json.loads(resp.read().decode("utf-8"))
            print(f"サーバー状態: {health.get('status', 'unknown')}")
            print(f"DRYRUN: {health.get('dryrun_mode', 'N/A')}")
    except Exception as e:
        print(f"\n❌ サーバーに接続できません: {e}")
        print(f"  health_app.py が起動しているか確認してください:")
        print(f"  systemctl status sixamo-health")
        sys.exit(1)

    if test_name == "all":
        results = {}
        for name, func in TESTS.items():
            results[name] = func(secret)
            time.sleep(1)  # テスト間の間隔

        print(f"\n{'='*50}")
        print("テスト結果サマリ")
        print(f"{'='*50}")
        all_passed = True
        for name, passed in results.items():
            icon = "✅" if passed else "❌"
            print(f"  {icon} {name}")
            if not passed:
                all_passed = False
        print(f"\n{'全テストPASS' if all_passed else '一部テストFAIL'}")
        sys.exit(0 if all_passed else 1)

    elif test_name in TESTS:
        passed = TESTS[test_name](secret)
        sys.exit(0 if passed else 1)

    else:
        print(f"不明なテスト: {test_name}")
        print(f"有効なテスト: {', '.join(TESTS.keys())}, all")
        sys.exit(1)


if __name__ == "__main__":
    main()
