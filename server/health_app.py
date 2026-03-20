"""
Sixamo API Server
VPS (133.117.75.92) 上で動作するAPIサーバー。
- /health    : ヘルスチェック
- /webhook   : Zendesk Webhook 受信 → Telegram 通知
"""

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

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
DRYRUN_MODE = os.environ.get("DRYRUN_MODE", "false").lower() in ("true", "1", "yes")
LOG_DIR = os.environ.get("LOG_DIR", "/opt/sixamo")

# --- ログ設定 ---

def _setup_logger(name: str, filename: str, level=logging.INFO) -> logging.Logger:
    """ファイル出力付きロガーを作成"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    # ファイルハンドラー (10MB, 5世代ローテーション)
    filepath = os.path.join(LOG_DIR, filename)
    try:
        fh = RotatingFileHandler(filepath, maxBytes=10*1024*1024, backupCount=5)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except (PermissionError, FileNotFoundError):
        pass  # ログディレクトリが無い場合はstdoutのみ
    # stdoutハンドラー
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


access_log = _setup_logger("access", "access.log")
error_log = _setup_logger("error", "error.log", logging.WARNING)

# --- 重複検知 ---

class DuplicateDetector:
    """チケットIDベースの重複検知（メモリ内TTLキャッシュ）"""

    def __init__(self, ttl_seconds: int = 300):
        self._seen: dict[str, float] = {}  # key -> expiry timestamp
        self._ttl = ttl_seconds

    def is_duplicate(self, ticket_id) -> bool:
        key = str(ticket_id)
        now = time.time()
        # 期限切れエントリを掃除
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if key in self._seen:
            return True
        self._seen[key] = now + self._ttl
        return False


_dedup = DuplicateDetector(ttl_seconds=300)

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

def _send_telegram_request(url: str, text: str, parse_mode: str = "") -> bool:
    """Telegram sendMessage API を呼び出す（内部用）"""
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status == 200


def _strip_html_tags(text: str) -> str:
    """HTML タグを除去しエンティティを復元してプレーンテキストに変換"""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text


def send_telegram(text: str) -> bool:
    """Telegram Bot API でメッセージを送信（HTML失敗時はプレーンテキストで再送）"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        access_log.warning("Telegram未設定。メッセージ: %s", text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # 1) HTML モードで送信を試みる
    try:
        return _send_telegram_request(url, text, parse_mode="HTML")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        error_log.error("Telegram送信失敗(HTML): %s — %s", e, err_body)
        # 2) 400 の場合はプレーンテキストにフォールバック
        if e.code == 400:
            error_log.info("プレーンテキストで再送信を試みます")
            try:
                return _send_telegram_request(url, _strip_html_tags(text))
            except Exception as e2:
                error_log.error("Telegram再送信も失敗: %s", e2)
                return False
        return False
    except Exception as e:
        error_log.error("Telegram送信失敗: %s", e)
        return False


def format_ticket_message(payload: dict) -> str:
    """Zendesk チケット情報を Telegram 用にフォーマット"""
    ticket = payload.get("ticket", payload)
    ticket_id = ticket.get("id", "不明")
    subject = html.escape(str(ticket.get("subject", ticket.get("title", "件名なし"))))
    status = html.escape(str(ticket.get("status", "不明")))
    priority = html.escape(str(ticket.get("priority", "未設定")))
    requester = ticket.get("requester", {})
    requester_name = html.escape(
        requester.get("name", "不明") if isinstance(requester, dict) else str(requester)
    )
    description = ticket.get("description", ticket.get("comment", {}).get("body", ""))
    if len(description) > 200:
        description = description[:200] + "..."
    description = html.escape(str(description))

    msg = (
        f"✅ <b>Zendesk返信案</b>\n"
        f"\n"
        f"<b>ID:</b> #{ticket_id}\n"
        f"<b>件名:</b> {subject}\n"
        f"<b>ステータス:</b> {status}\n"
        f"<b>優先度:</b> {priority}\n"
        f"<b>依頼者:</b> {requester_name}\n"
        f"\n"
        f"<b>説明:</b>\n{description}"
    )

    if DRYRUN_MODE:
        msg += "\n\n⚠️ DRYRUNモード中 — 自動返信は送信されません"

    return msg


def _sanitize_text(text: str) -> str:
    """制御文字（タブ・改行以外）を除去"""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def format_parse_error_message(raw_body: str, error_msg: str) -> str:
    """パースエラー時の Telegram 通知メッセージ"""
    raw_body = _sanitize_text(raw_body)
    preview = raw_body[:200] + "..." if len(raw_body) > 200 else raw_body
    safe_preview = html.escape(preview)
    safe_error = html.escape(error_msg)
    return (
        f"⚠️ <b>Webhook パースエラー</b>\n"
        f"\n"
        f"<b>エラー:</b> {safe_error}\n"
        f"\n"
        f"<b>受信データ:</b>\n<code>{safe_preview}</code>"
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
        "dryrun_mode": DRYRUN_MODE,
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
        client_ip = self.headers.get("X-Real-IP", self.client_address[0])

        # 1. IP制限チェック
        if ZENDESK_IP_RANGES and not is_zendesk_ip(client_ip):
            access_log.warning("IP制限で拒否: %s", client_ip)
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
                access_log.warning("署名ヘッダー不足: %s", client_ip)
                self._json_response(401, {"error": "missing signature headers"})
                return
            if not verify_zendesk_signature(signature, timestamp, body):
                error_log.warning("署名検証失敗: %s", client_ip)
                self._json_response(401, {"error": "invalid signature"})
                return

        # 4. ペイロード解析
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            error_log.error("JSONパースエラー: %s", e)
            # パースエラーをTelegramに通知
            raw = body.decode("utf-8", errors="replace")
            err_msg = format_parse_error_message(raw, str(e))
            send_telegram(err_msg)
            self._json_response(400, {"error": "invalid JSON"})
            return

        # 5. 重複チェック
        ticket = payload.get("ticket", payload)
        ticket_id = ticket.get("id")
        if ticket_id and _dedup.is_duplicate(ticket_id):
            access_log.info("重複スキップ: ticket #%s", ticket_id)
            self._json_response(200, {"status": "duplicate_skipped",
                                      "ticket_id": ticket_id})
            return

        # 6. Telegram通知
        message = format_ticket_message(payload)
        sent = send_telegram(message)
        access_log.info("Webhook処理完了: ticket #%s, Telegram=%s, dryrun=%s",
                        ticket_id, "sent" if sent else "failed", DRYRUN_MODE)

        status = "notified" if sent else "received_but_notification_failed"
        self._json_response(200, {"status": status, "dryrun": DRYRUN_MODE})

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        msg = fmt % args if args else fmt
        if "/health" not in msg:
            access_log.info(msg)


def _count_templates() -> int:
    """templates.yaml から返信テンプレート数をカウント"""
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "templates.yaml")
    if not os.path.isfile(template_path):
        return 0
    try:
        import yaml
        with open(template_path) as f:
            data = yaml.safe_load(f)
        templates = data.get("templates", []) if isinstance(data, dict) else []
        return len(templates)
    except ImportError:
        # PyYAML が無い場合は簡易パース（"- category:" の行数をカウント）
        try:
            with open(template_path) as f:
                return sum(1 for line in f
                           if line.strip().startswith("- category:"))
        except Exception:
            return 0
    except Exception:
        return 0


def _send_startup_notification():
    """サーバー起動時にTelegramへ通知を送信"""
    dryrun_label = "ON" if DRYRUN_MODE else "OFF"
    template_count = _count_templates()
    worker_count = 1  # シングルスレッドHTTPServer

    msg = (
        f"🚀 <b>サーバーが起動しました</b>\n"
        f"\n"
        f"DRYRUNモード：{dryrun_label}\n"
        f"テンプレート数：{template_count}件\n"
        f"ワーカー数：{worker_count}"
    )
    sent = send_telegram(msg)
    if sent:
        access_log.info("起動通知をTelegramに送信しました")
    else:
        access_log.warning("起動通知の送信に失敗しました")


def main():
    host = os.environ.get("HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("HEALTH_PORT", "5000"))
    server = HTTPServer((host, port), AppHandler)
    access_log.info("Sixamo API server started on %s:%d", host, port)
    access_log.info("  Zendesk webhook: %s",
                    "enabled" if ZENDESK_WEBHOOK_SECRET else "disabled (no secret)")
    access_log.info("  Telegram:        %s",
                    "enabled" if TELEGRAM_BOT_TOKEN else "disabled (no token)")
    access_log.info("  DRYRUN_MODE:     %s", DRYRUN_MODE)

    # 起動通知をTelegramに送信
    _send_startup_notification()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        access_log.info("Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
