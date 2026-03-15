#!/bin/bash
# ============================================================
# Sixamo API - HTTPS (SSL) セットアップスクリプト
# ============================================================
# 使用方法: sudo bash setup-ssl.sh [ドメイン名]
#
# 例:
#   sudo bash setup-ssl.sh support.sixamo.forex
#   sudo bash setup-ssl.sh sixamo.forex
#
# このスクリプトは以下を実行します:
#   Step1: ドメインのDNS確認
#   Step2: certbot インストール
#   Step3: SSL証明書の取得
#   Step4: Nginx設定の更新（HTTPS対応）
#   Step5: 設定反映・動作確認
#
# 前提条件:
#   - Ubuntu/Debian系OS
#   - Nginx インストール済み
#   - ポート 80, 443 が開いていること
#   - 対象ドメインの A レコードがこのサーバーIP (133.117.75.92) に向いていること
# ============================================================
set -euo pipefail

# --- 引数・設定 ---
DOMAIN="${1:-}"
EXPECTED_IP="133.117.75.92"
NGINX_CONF="/etc/nginx/sites-available/sixamo"
CERTBOT_WEBROOT="/var/www/certbot"
EMAIL="admin@sixamo.forex"

if [ -z "$DOMAIN" ]; then
    echo "使用方法: sudo bash setup-ssl.sh <ドメイン名>"
    echo ""
    echo "例:"
    echo "  sudo bash setup-ssl.sh support.sixamo.forex"
    echo "  sudo bash setup-ssl.sh sixamo.forex"
    exit 1
fi

echo "============================================"
echo " Sixamo HTTPS (SSL) セットアップ"
echo " ドメイン: $DOMAIN"
echo "============================================"
echo ""

# ============================================================
# Step1: ドメインのDNS確認
# ============================================================
echo "=== [Step1/5] ドメインのDNS確認 ==="

if ! command -v dig &>/dev/null; then
    echo "  -> dig コマンドが見つかりません。インストールします..."
    apt-get update -qq
    apt-get install -y dnsutils
fi

RESOLVED_IP=$(dig +short "$DOMAIN" A 2>/dev/null | head -1 || true)

if [ -z "$RESOLVED_IP" ]; then
    echo "  [エラー] $DOMAIN の A レコードが見つかりません。"
    echo ""
    echo "  DNS設定で以下の A レコードを追加してください:"
    echo "    $DOMAIN  ->  $EXPECTED_IP"
    echo ""
    echo "  設定後、DNSの反映を待ってから再実行してください。"
    exit 1
fi

echo "  -> $DOMAIN -> $RESOLVED_IP"

if [ "$RESOLVED_IP" != "$EXPECTED_IP" ]; then
    echo ""
    echo "  [警告] 期待するIP ($EXPECTED_IP) と異なります。"
    echo "  DNS設定を確認してください。"
    echo ""
    read -rp "  このまま続行しますか？ (y/N): " CONTINUE
    if [ "$CONTINUE" != "y" ] && [ "$CONTINUE" != "Y" ]; then
        echo "  中止しました。"
        exit 1
    fi
else
    echo "  -> OK: $EXPECTED_IP に正しく向いています"
fi

# ============================================================
# Step2: certbot インストール
# ============================================================
echo ""
echo "=== [Step2/5] certbot インストール ==="

if ! command -v certbot &>/dev/null; then
    apt-get update -qq
    apt-get install -y certbot python3-certbot-nginx
    echo "  -> certbot をインストールしました"
else
    echo "  -> certbot は既にインストール済み ($(certbot --version 2>&1 | head -1))"
fi

# ============================================================
# Step3: SSL証明書の取得
# ============================================================
echo ""
echo "=== [Step3/5] SSL証明書の取得 ==="

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "  -> 証明書は既に存在します。更新確認を行います..."
    certbot renew --dry-run 2>/dev/null && echo "  -> 自動更新: 正常" || echo "  -> [警告] 自動更新テスト失敗"
else
    echo "  -> SSL証明書を取得します..."

    # certbot 用の一時HTTP設定を適用
    cat > "$NGINX_CONF" <<TMPEOF
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root $CERTBOT_WEBROOT;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
TMPEOF

    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/sixamo
    # default サイトを無効化（競合防止）
    [ -L /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default

    mkdir -p "$CERTBOT_WEBROOT"
    nginx -t && systemctl reload nginx

    certbot certonly \
        --webroot \
        --webroot-path "$CERTBOT_WEBROOT" \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        --no-eff-email

    echo "  -> SSL証明書を取得しました"
fi

# ============================================================
# Step4: Nginx設定の更新（HTTPS対応）
# ============================================================
echo ""
echo "=== [Step4/5] Nginx HTTPS 設定を適用 ==="

cat > "$NGINX_CONF" <<NGINXEOF
# ============================================================
# Sixamo API - Nginx HTTPS 設定
# ドメイン: $DOMAIN
# 生成日時: $(date '+%Y-%m-%d %H:%M:%S')
# ============================================================

# --- HTTPS (443) ---
server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    # SSL証明書 (Let's Encrypt / certbot 管理)
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    # SSL 推奨設定
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # セキュリティヘッダー
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # ログ
    access_log /var/log/nginx/sixamo-api.access.log;
    error_log /var/log/nginx/sixamo-api.error.log;

    # Zendesk Webhook エンドポイント
    location /webhook {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 1m;

        # タイムアウト設定
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # ヘルスチェック (ログ出力なし)
    location /health {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        access_log off;
    }
}

# --- HTTP (80) -> HTTPS リダイレクト ---
server {
    listen 80;
    server_name $DOMAIN;

    # Let's Encrypt 証明書更新用
    location /.well-known/acme-challenge/ {
        root $CERTBOT_WEBROOT;
    }

    # その他は全て HTTPS にリダイレクト
    location / {
        return 301 https://\$host\$request_uri;
    }
}
NGINXEOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/sixamo
echo "  -> Nginx設定を書き出しました: $NGINX_CONF"

# ============================================================
# Step5: 設定反映・動作確認
# ============================================================
echo ""
echo "=== [Step5/5] 設定反映・動作確認 ==="

echo "  -> nginx -t (設定テスト)..."
nginx -t
echo "  -> OK"

echo "  -> systemctl reload nginx..."
systemctl reload nginx
echo "  -> OK"

echo ""
echo "  -> HTTPS 疎通確認:"
HEALTH_RESPONSE=$(curl -s --max-time 10 "https://$DOMAIN/health" 2>/dev/null || echo "接続失敗")
echo "     curl https://$DOMAIN/health"
echo "     -> $HEALTH_RESPONSE"

if echo "$HEALTH_RESPONSE" | grep -q '"status"'; then
    echo ""
    echo "  ✓ HTTPS セットアップ成功!"
else
    echo ""
    echo "  [警告] ヘルスチェックの応答が期待と異なります。"
    echo "  以下を確認してください:"
    echo "    1. sixamo-health サービスが起動しているか: systemctl status sixamo-health"
    echo "    2. ローカル疎通: curl http://127.0.0.1:5000/health"
    echo "    3. ファイアウォール: ufw status (ポート443が開いているか)"
fi

# ============================================================
# 完了サマリ
# ============================================================
echo ""
echo "============================================"
echo " HTTPS セットアップ完了"
echo "============================================"
echo ""
echo " エンドポイント:"
echo "   https://$DOMAIN/health   (ヘルスチェック)"
echo "   https://$DOMAIN/webhook  (Zendesk Webhook)"
echo ""
echo " 確認コマンド:"
echo "   curl https://$DOMAIN/health"
echo ""
echo " SSL証明書の確認:"
echo "   certbot certificates"
echo ""
echo " 証明書自動更新の確認:"
echo "   systemctl list-timers | grep certbot"
echo ""
echo " Zendesk Webhook URLに設定する値:"
echo "   https://$DOMAIN/webhook"
echo ""
