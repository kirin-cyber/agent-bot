#!/bin/bash
# Zendesk Webhook Secret を .env に設定し、サービスを再起動するスクリプト
#
# 使用方法:
#   sudo bash setup-webhook-secret.sh YOUR_ZENDESK_WEBHOOK_SECRET
#
# Zendesk管理画面での確認手順:
#   1. https://sixamo.zendesk.com/admin にログイン
#   2. 左メニュー →「アプリとインテグレーション」→「Webhook」
#   3. 「sixamo-automation」をクリック
#   4. 「署名シークレット」をコピー
set -euo pipefail

APP_DIR="/opt/sixamo"
ENV_FILE="$APP_DIR/.env"

# --- 引数チェック ---
if [ $# -lt 1 ]; then
    echo "使用方法: sudo bash setup-webhook-secret.sh YOUR_ZENDESK_WEBHOOK_SECRET"
    echo ""
    echo "Zendesk管理画面で署名シークレットを確認してください:"
    echo "  https://sixamo.zendesk.com/admin"
    echo "  → アプリとインテグレーション → Webhook → sixamo-automation → 署名シークレット"
    exit 1
fi

SECRET="$1"

if [ ${#SECRET} -lt 10 ]; then
    echo "[ERROR] シークレットが短すぎます（10文字以上必要）"
    exit 1
fi

echo "============================================"
echo " Zendesk Webhook Secret 設定"
echo "============================================"
echo ""

# --- .env ファイル確認 ---
if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] $ENV_FILE が見つかりません"
    echo "  先に quick-deploy.sh を実行してください"
    exit 1
fi

# --- Step1: ZENDESK_WEBHOOK_SECRET を設定 ---
echo "=== [Step1] Webhook Secret 設定 ==="
if grep -q "^ZENDESK_WEBHOOK_SECRET=" "$ENV_FILE"; then
    sed -i "s|^ZENDESK_WEBHOOK_SECRET=.*|ZENDESK_WEBHOOK_SECRET=${SECRET}|" "$ENV_FILE"
    echo "  -> ZENDESK_WEBHOOK_SECRET: 更新済み"
else
    echo "ZENDESK_WEBHOOK_SECRET=${SECRET}" >> "$ENV_FILE"
    echo "  -> ZENDESK_WEBHOOK_SECRET: 追加済み"
fi

# --- Step2: ZENDESK_IP_RANGES を確認・設定 ---
echo ""
echo "=== [Step2] Zendesk IPレンジ確認 ==="
if grep -q "^ZENDESK_IP_RANGES=" "$ENV_FILE"; then
    CURRENT_RANGES=$(grep "^ZENDESK_IP_RANGES=" "$ENV_FILE" | cut -d= -f2)
    echo "  -> ZENDESK_IP_RANGES: ${CURRENT_RANGES} (既存値を維持)"
else
    echo "ZENDESK_IP_RANGES=216.198.0.0/18" >> "$ENV_FILE"
    echo "  -> ZENDESK_IP_RANGES: 216.198.0.0/18 (デフォルト設定)"
fi

# --- Step3: サービス再起動 ---
echo ""
echo "=== [Step3] サービス再起動 ==="
systemctl stop sixamo 2>/dev/null || true
# ポート5000を使用しているプロセスを終了
fuser -k 5000/tcp 2>/dev/null || true
sleep 3
systemctl start sixamo
sleep 5

if systemctl is-active --quiet sixamo; then
    echo "  -> sixamo: active (正常)"
else
    echo "  -> [ERROR] sixamo の起動に失敗しました"
    systemctl status sixamo --no-pager || true
    exit 1
fi

# --- Step4: 確認 ---
echo ""
echo "=== [Step4] 確認 ==="
# ヘルスチェック
HEALTH=$(curl -s http://127.0.0.1:5000/health 2>/dev/null || echo '{"error":"接続失敗"}')
echo "  -> ヘルスチェック: $HEALTH"

# ログ確認
echo ""
if [ -f "$APP_DIR/access.log" ]; then
    echo "--- access.log (最新5行) ---"
    tail -5 "$APP_DIR/access.log"
fi

echo ""
echo "============================================"
echo " 設定完了!"
echo "============================================"
echo ""
echo " 確認事項:"
echo "   1. Telegramに🚀通知が届いたか確認"
echo "   2. 通知に「Zendesk webhook：enabled」が表示されていること"
echo "   3. Webhookテスト: python3 $APP_DIR/test_webhook.py all"
echo ""
