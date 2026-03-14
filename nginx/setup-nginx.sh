#!/bin/bash
# Sixamo API - Nginx + Let's Encrypt セットアップスクリプト
# 使用方法: sudo bash setup-nginx.sh
#
# 前提条件:
#   - Ubuntu/Debian系OS
#   - api.sixamo.forex のDNS Aレコードが このサーバーのIPに向いていること
#   - ポート80, 443 が開いていること
set -euo pipefail

DOMAIN="api.sixamo.forex"
CONF_SRC="$(cd "$(dirname "$0")" && pwd)/sixamo-api.conf"
CONF_DEST="/etc/nginx/sites-available/sixamo-api.conf"
CERTBOT_WEBROOT="/var/www/certbot"

# ---------------------------------------------------------------
# 1. Nginx インストール
# ---------------------------------------------------------------
echo "=== [1/5] Nginx インストール ==="
if ! command -v nginx &>/dev/null; then
    apt-get update -qq
    apt-get install -y nginx
    echo "Nginx をインストールしました"
else
    echo "Nginx は既にインストール済み"
fi

# ---------------------------------------------------------------
# 2. Certbot インストール
# ---------------------------------------------------------------
echo "=== [2/5] Certbot インストール ==="
if ! command -v certbot &>/dev/null; then
    apt-get install -y certbot python3-certbot-nginx
    echo "Certbot をインストールしました"
else
    echo "Certbot は既にインストール済み"
fi

# ---------------------------------------------------------------
# 3. Nginx設定を配置
# ---------------------------------------------------------------
echo "=== [3/5] Nginx設定を配置 ==="
mkdir -p "$CERTBOT_WEBROOT"
cp "$CONF_SRC" "$CONF_DEST"
ln -sf "$CONF_DEST" /etc/nginx/sites-enabled/sixamo-api.conf

# defaultサイトを無効化（競合防止）
if [ -L /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
    echo "default サイトを無効化しました"
fi

# まずHTTPのみ（SSL証明書取得前）の一時設定をテスト
# SSL部分をコメントアウトした一時版を作成
cat > /tmp/sixamo-api-temp.conf <<'TEMPEOF'
server {
    listen 80;
    server_name api.sixamo.forex;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
TEMPEOF

cp /tmp/sixamo-api-temp.conf "$CONF_DEST"
nginx -t
systemctl reload nginx
echo "HTTP設定を適用しました（SSL証明書取得用）"

# ---------------------------------------------------------------
# 4. SSL証明書を取得
# ---------------------------------------------------------------
echo "=== [4/5] SSL証明書を取得 ==="
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "証明書は既に存在します。更新を試みます..."
    certbot renew --dry-run
else
    certbot certonly \
        --webroot \
        --webroot-path "$CERTBOT_WEBROOT" \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "admin@sixamo.forex" \
        --no-eff-email
    echo "SSL証明書を取得しました"
fi

# ---------------------------------------------------------------
# 5. 本番Nginx設定を適用
# ---------------------------------------------------------------
echo "=== [5/5] HTTPS設定を適用 ==="
cp "$CONF_SRC" "$CONF_DEST"
nginx -t
systemctl reload nginx
echo "HTTPS設定を適用しました"

# ---------------------------------------------------------------
# 完了
# ---------------------------------------------------------------
echo ""
echo "====================================="
echo " セットアップ完了!"
echo "====================================="
echo ""
echo " URL: https://$DOMAIN/health"
echo ""
echo " 確認コマンド:"
echo "   curl https://$DOMAIN/health"
echo ""
echo " certbot自動更新の確認:"
echo "   systemctl list-timers | grep certbot"
echo ""
