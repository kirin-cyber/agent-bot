"""
Sixamo Health Check Service
VPS (133.117.75.92) 上で動作する軽量ヘルスチェックサービス。
gunicorn で 127.0.0.1:5000 にバインドし、Nginx からプロキシされる。
"""

import json
import os
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

START_TIME = time.monotonic()


def _service_status(name: str) -> str:
    """systemctl で指定サービスの状態を取得"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _disk_usage() -> dict:
    """ルートパーティションのディスク使用状況"""
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


def _uptime_seconds() -> float:
    return round(time.monotonic() - START_TIME, 1)


def build_health_response() -> dict:
    nginx_status = _service_status("nginx")
    disk = _disk_usage()
    disk_ok = disk.get("usage_percent", 100) < 90

    overall = "ok" if nginx_status == "active" and disk_ok else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": _uptime_seconds(),
        "services": {
            "nginx": nginx_status,
            "health_app": "active",
        },
        "disk": disk,
    }


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            data = build_health_response()
            status_code = 200 if data["status"] == "ok" else 503
            self._json_response(status_code, data)
        else:
            self._json_response(404, {"error": "not found"})

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # /health のアクセスログを抑制
        if "/health" not in (args[0] if args else ""):
            super().log_message(format, *args)


def main():
    host = os.environ.get("HEALTH_HOST", "127.0.0.1")
    port = int(os.environ.get("HEALTH_PORT", "5000"))
    server = HTTPServer((host, port), HealthHandler)
    print(f"Health check service started on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
