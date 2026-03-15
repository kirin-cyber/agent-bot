"""
Sixamo API Server
VPS (133.117.75.92) 上で動作するAPIサーバー。
- /health    : ヘルスチェック
- /webhook   : Zendesk Webhook 受信 → Telegram 通知
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import subprocess
import time
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

START_TIME = time.monotonic()

# --- 設定（.env から読み込み） ---

def _load_env(path: str = "/opt/sixamo/.env"):
    """簡易 .env ローダー（外部依存なし）"""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


_load_env()

ZENDESK_WEBHOOK_SECRET = os.environ.get("ZENDESK_WEBHOOK_SECRET", "")
ZENDESK_IP_RANGES = os.environ.get("ZENDESK_IP_RANGES", "216.198.0.0/18")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ---------------------------------------------------------------
# Zendesk 署名検証
# ---------------------------------------------------------------

def verify_zendesk_signature(signature: str, timestamp: str, body: bytes) -> bool:
    """Zendesk Webhook の HMAC-SHA256 署名を検証"""
    if not ZENDESK_WEBHOOK_SECRET:
        return False
    sign_payload = timestamp.encode("utf-8") + body
    expected = base64.b64encode(
        hmac.new(
            ZENDESK_WEBHOOK_SECRET.encode("utf-8"),
            sign_payload,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(signature, expected)


def is_zendesk_ip(client_ip: str) -> bool:
    """リクエスト元IPがZendeskのIP範囲内か確認"""
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in ZENDESK_IP_RANGES.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


# ---------------------------------------------------------------
# Telegram 通知
# ---------------------------------------------------------------

def send_telegram(text: str) -> bool:
    """Telegram Bot API でメッセージを送信"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[WARN] Telegram未設定。メッセージ: {text}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram送信失敗: {e}")
        return False


def format_ticket_message(payload: dict) -> str:
    """Zendesk チケット情報を Telegram 用にフォーマット"""
    ticket = payload.get("ticket", payload)
    ticket_id = ticket.get("id", "不明")
    subject = ticket.get("subject", ticket.get("title", "件名なし"))
    status = ticket.get("status", "不明")
    priority = ticket.get("priority", "未設定")
    requester = ticket.get("requester", {})
    requester_name = requester.get("name", "不明") if isinstance(requester, dict) else str(requester)
    description = ticket.get("description", ticket.get("comment", {}).get("body", ""))
    if len(description) > 200:
        description = description[:200] + "..."

    return (
        f"🔔 <b>新しいZendeskチケット</b>\n"
        f"\n"
        f"<b>ID:</b> #{ticket_id}\n"
        f"<b>件名:</b> {subject}\n"
        f"<b>ステータス:</b> {status}\n"
        f"<b>優先度:</b> {priority}\n"
        f"<b>依頼者:</b> {requester_name}\n"
        f"\n"
        f"<b>説明:</b>\n{description}"
    )


# ---------------------------------------------------------------
# ヘルスチェック
# ---------------------------------------------------------------

def _service_status(name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _disk_usage() -> dict:
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        return {
            "total_gb": round(total / (1024 ** 3), 1),
            "used_gb": round(used / (1024 ** 3), 1),
            "free_gb": round(free / (1024 ** 3), 1),
            "usage_percent": round(used / total * 100, 1) if total > 0 else 0,
        }
    except Exception:
        return {"error": "unable to read disk info"}


def build_health_response() -> dict:
    nginx_status = _service_status("nginx")
    disk = _disk_usage()
    disk_ok = disk.get("usage_percent", 100) < 90
    overall = "ok" if nginx_status == "active" and disk_ok else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.monotonic() - START_TIME, 1),
        "services": {
            "nginx": nginx_status,
            "health_app": "active",
            "telegram": "configured" if TELEGRAM_BOT_TOKEN else "not_configured",
            "zendesk_webhook": "configured" if ZENDESK_WEBHOOK_SECRET else "not_configured",
        },
        "disk": disk,
    }


# ---------------------------------------------------------------
# HTTP ハンドラー
# ---------------------------------------------------------------

class AppHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            data = build_health_response()
            code = 200 if data["status"] == "ok" else 503
            self._json_response(code, data)
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/webhook":
            self._handle_webhook()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_webhook(self):
        # 1. IP制限チェック
        client_ip = self.headers.get("X-Real-IP", self.client_address[0])
        if ZENDESK_IP_RANGES and not is_zendesk_ip(client_ip):
            print(f"[REJECT] IP制限: {client_ip}")
            self._json_response(403, {"error": "forbidden: IP not allowed"})
            return

        # 2. リクエストボディ読み取り
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 1_048_576:  # 1MB制限
            self._json_response(413, {"error": "payload too large"})
            return
        body = self.rfile.read(content_length)

        # 3. Zendesk署名検証
        signature = self.headers.get("X-Zendesk-Webhook-Signature", "")
        timestamp = self.headers.get("X-Zendesk-Webhook-Signature-Timestamp", "")

        if ZENDESK_WEBHOOK_SECRET:
            if not signature or not timestamp:
                self._json_response(401, {"error": "missing signature headers"})
                return
            if not verify_zendesk_signature(signature, timestamp, body):
                print(f"[REJECT] 署名検証失敗: {client_ip}")
                self._json_response(401, {"error": "invalid signature"})
                return

        # 4. ペイロード解析
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return

        # 5. Telegram通知
        message = format_ticket_message(payload)
        sent = send_telegram(message)
        print(f"[WEBHOOK] チケット受信, Telegram送信: {'成功' if sent else '失敗'}")

        status = "notified" if sent else "received_but_notification_failed"
        self._json_response(200, {"status": status})

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "/health" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    host = os.environ.get("HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("HEALTH_PORT", "5000"))
    server = HTTPServer((host, port), AppHandler)
    print(f"Sixamo API server started on {host}:{port}")
    print(f"  Zendesk webhook: {'enabled' if ZENDESK_WEBHOOK_SECRET else 'disabled (no secret)'}")
    print(f"  Telegram:        {'enabled' if TELEGRAM_BOT_TOKEN else 'disabled (no token)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
