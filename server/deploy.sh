#!/bin/bash
# Sixamo API Server - ワンコマンドデプロイスクリプト
# 使用方法: sudo bash deploy.sh
#
# このスクリプトは以下を行います:
#   1. .env ファイルの確認
#   2. アプリケーションを /opt/sixamo に配置
#   3. systemd サービスを登録・起動
#   4. Nginx 設定を適用
#   5. (オプション) DNS設定済みなら SSL証明書を取得
set -euo pipefail

DOMAIN="api.sixamo.forex"
APP_DIR="/opt/sixamo"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo " Sixamo API Server デプロイ"
echo "============================================"
echo ""

# ---------------------------------------------------------------
# 1. .env ファイル確認
# ---------------------------------------------------------------
echo "=== [1/6] 環境変数確認 ==="
if [ -f "$APP_DIR/.env" ]; then
    echo "  -> $APP_DIR/.env が見つかりました"
    # 設定項目の存在チェック（値は表示しない）
    for key in ZENDESK_WEBHOOK_SECRET TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
        if grep -q "^${key}=" "$APP_DIR/.env" 2>/dev/null; then
            echo "  -> $key: 設定済み"
        else
            echo "  -> [警告] $key: 未設定"
        fi
    done
else
    echo "  -> [警告] $APP_DIR/.env が見つかりません"
    echo "  -> テンプレートをコピーします..."
    mkdir -p "$APP_DIR"
    cp "$SCRIPT_DIR/.env.example" "$APP_DIR/.env"
    echo "  -> $APP_DIR/.env を編集して設定値を入力してください"
    echo "     vi $APP_DIR/.env"
    echo ""
    read -rp "  設定後、Enterを押して続行... " || true
fi

# ---------------------------------------------------------------
# 2. アプリケーション配置
# ---------------------------------------------------------------
echo ""
echo "=== [2/6] アプリケーション配置 ==="
mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/health_app.py" "$APP_DIR/health_app.py"
chown -R www-data:www-data "$APP_DIR"
echo "  -> $APP_DIR/health_app.py を配置しました"

# ---------------------------------------------------------------
# 3. systemd サービス登録
# ---------------------------------------------------------------
echo ""
echo "=== [3/6] systemd サービス登録 ==="
cp "$SCRIPT_DIR/sixamo-health.service" /etc/systemd/system/sixamo-health.service
systemctl daemon-reload
systemctl enable sixamo-health
systemctl restart sixamo-health
echo "  -> sixamo-health サービスを起動しました"

# 起動確認
sleep 2
if systemctl is-active --quiet sixamo-health; then
    echo "  -> ステータス: active (正常)"
else
    echo "  -> [警告] サービスの起動に失敗しました"
    systemctl status sixamo-health --no-pager || true
fi

# ローカル疎通確認
echo ""
echo "  -> ローカル疎通確認:"
HEALTH_RESPONSE=$(curl -s http://127.0.0.1:5000/health 2>/dev/null || echo "接続失敗")
echo "     $HEALTH_RESPONSE"

# ---------------------------------------------------------------
# 4. Nginx インストール・設定
# ---------------------------------------------------------------
echo ""
echo "=== [4/6] Nginx 設定 ==="

if ! command -v nginx &>/dev/null; then
    apt-get update -qq
    apt-get install -y nginx
    echo "  -> Nginx をインストールしました"
else
    echo "  -> Nginx は既にインストール済み"
fi

NGINX_CONF="/etc/nginx/sites-available/sixamo-api.conf"
cp "$SCRIPT_DIR/../nginx/sixamo-api.conf" "$NGINX_CONF"
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/sixamo-api.conf

if [ -L /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
    echo "  -> default サイトを無効化しました"
fi

# ---------------------------------------------------------------
# 5. SSL 証明書 (DNS設定済みの場合のみ)
# ---------------------------------------------------------------
echo ""
echo "=== [5/6] SSL 証明書確認 ==="

RESOLVED_IP=$(dig +short "$DOMAIN" A 2>/dev/null || true)
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || true)

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "  -> SSL証明書は既に存在します"
    certbot certificates 2>/dev/null || true

elif [ -n "$RESOLVED_IP" ] && [ "$RESOLVED_IP" = "$SERVER_IP" ]; then
    echo "  -> DNS が正しく設定されています ($DOMAIN -> $RESOLVED_IP)"
    echo "  -> SSL証明書を取得します..."

    if ! command -v certbot &>/dev/null; then
        apt-get install -y certbot python3-certbot-nginx
    fi

    cat > "$NGINX_CONF" <<'HTTPEOF'
server {
    listen 80;
    server_name api.sixamo.forex;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
HTTPEOF

    mkdir -p /var/www/certbot
    nginx -t && systemctl reload nginx

    certbot certonly \
        --webroot \
        --webroot-path /var/www/certbot \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "admin@sixamo.forex" \
        --no-eff-email

    cp "$SCRIPT_DIR/../nginx/sixamo-api.conf" "$NGINX_CONF"
    echo "  -> SSL証明書を取得しました"
else
    echo "  -> [スキップ] DNS未設定のためSSL証明書の取得をスキップします"
    echo "     ドメイン: $DOMAIN"
    echo "     解決先IP: ${RESOLVED_IP:-未解決}"
    echo "     サーバーIP: ${SERVER_IP:-不明}"
    echo ""
    echo "  -> HTTP-only モードで動作します"

    cat > "$NGINX_CONF" <<'HTTPONLY'
server {
    listen 80;
    server_name _;

    access_log /var/log/nginx/sixamo-api.access.log;
    error_log /var/log/nginx/sixamo-api.error.log;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        client_max_body_size 1m;
    }

    location = /webhook {
        proxy_pass http://127.0.0.1:5000/webhook;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 1m;
    }

    location = /health {
        proxy_pass http://127.0.0.1:5000/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        access_log off;
    }
}
HTTPONLY
fi

# ---------------------------------------------------------------
# 6. Nginx 起動・リロード
# ---------------------------------------------------------------
echo ""
echo "=== [6/6] Nginx 起動 ==="
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl start nginx
echo "  -> Nginx を起動しました"

# ---------------------------------------------------------------
# 最終確認
# ---------------------------------------------------------------
echo ""
echo "============================================"
echo " デプロイ完了!"
echo "============================================"
echo ""
echo " サービス状態:"
echo "   sixamo-health: $(systemctl is-active sixamo-health)"
echo "   nginx:         $(systemctl is-active nginx)"
echo ""
echo " エンドポイント:"
echo "   GET  /health   -> ヘルスチェック"
echo "   POST /webhook  -> Zendesk Webhook受信 → Telegram通知"
echo ""
echo " 確認コマンド:"
echo "   curl http://127.0.0.1:5000/health"
echo "   curl http://$(hostname -I | awk '{print $1}')/health"

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "   curl https://$DOMAIN/health"
    echo "   curl https://$DOMAIN/webhook  (POST)"
fi

echo ""
echo " Webhook テスト:"
echo "   curl -X POST http://127.0.0.1:5000/webhook \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"ticket\":{\"id\":1,\"subject\":\"テスト\",\"status\":\"new\",\"priority\":\"high\",\"requester\":{\"name\":\"テストユーザー\"},\"description\":\"テスト通知\"}}'"
echo ""
echo " ログ確認:"
echo "   journalctl -u sixamo-health -f"
echo "   tail -f /var/log/nginx/sixamo-api.error.log"
echo ""

if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "============================================"
    echo " [次のステップ] HTTPS (SSL) セットアップ"
    echo "============================================"
    echo ""
    echo " ZendeskのWebhookにはHTTPS必須です。"
    echo " ドメインのDNS Aレコード設定後、以下を実行してください:"
    echo ""
    echo "   # Step1: DNS確認"
    echo "   dig +short support.sixamo.forex"
    echo "   dig +short sixamo.forex"
    echo "   # -> 133.117.75.92 が返ればOK"
    echo ""
    echo "   # Step2-5: SSL自動セットアップ"
    echo "   sudo bash $(cd "$(dirname "$0")" && pwd)/../nginx/setup-ssl.sh <ドメイン名>"
    echo ""
fi
