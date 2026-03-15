#!/bin/bash
# Sixamo クイックデプロイ（コード更新 + .env設定 + 再起動）
# 使用方法: sudo bash quick-deploy.sh
#
# 前提: 初回デプロイ (deploy.sh) が完了済みであること
set -euo pipefail

APP_DIR="/opt/sixamo"
BRANCH="claude/health-check-service-U3jBv"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================"
echo " Sixamo クイックデプロイ"
echo "============================================"
echo ""

# ---------------------------------------------------------------
# Step1: .env に Telegram 設定を追加
# ---------------------------------------------------------------
echo "=== [Step1] .env Telegram設定 ==="

ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "  -> .env が無いためテンプレートからコピー..."
    mkdir -p "$APP_DIR"
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
fi

# TELEGRAM_BOT_TOKEN を設定（既存値を上書き）
if grep -q "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE"; then
    sed -i 's|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=8584264439:AAEXAgDVG_Mgg4X8hlch0aTSwXCinNp1RlI|' "$ENV_FILE"
    echo "  -> TELEGRAM_BOT_TOKEN: 更新済み"
else
    echo 'TELEGRAM_BOT_TOKEN=8584264439:AAEXAgDVG_Mgg4X8hlch0aTSwXCinNp1RlI' >> "$ENV_FILE"
    echo "  -> TELEGRAM_BOT_TOKEN: 追加済み"
fi

# TELEGRAM_CHAT_ID を設定
if grep -q "^TELEGRAM_CHAT_ID=" "$ENV_FILE"; then
    sed -i 's|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=6976979859|' "$ENV_FILE"
    echo "  -> TELEGRAM_CHAT_ID: 更新済み"
else
    echo 'TELEGRAM_CHAT_ID=6976979859' >> "$ENV_FILE"
    echo "  -> TELEGRAM_CHAT_ID: 追加済み"
fi

# DRYRUN_MODE を設定（未設定の場合のみ）
if ! grep -q "^DRYRUN_MODE=" "$ENV_FILE"; then
    echo 'DRYRUN_MODE=true' >> "$ENV_FILE"
    echo "  -> DRYRUN_MODE: 追加済み (true)"
else
    echo "  -> DRYRUN_MODE: $(grep '^DRYRUN_MODE=' "$ENV_FILE" | cut -d= -f2)"
fi

# LOG_DIR を設定（未設定の場合のみ）
if ! grep -q "^LOG_DIR=" "$ENV_FILE"; then
    echo "LOG_DIR=$APP_DIR" >> "$ENV_FILE"
    echo "  -> LOG_DIR: 追加済み ($APP_DIR)"
fi

echo ""

# ---------------------------------------------------------------
# Step2: 最新コードをデプロイ
# ---------------------------------------------------------------
echo "=== [Step2] コード更新 ==="

# gitリポジトリから最新を取得
if [ -d "$REPO_DIR/.git" ]; then
    echo "  -> git pull origin $BRANCH ..."
    cd "$REPO_DIR"
    git pull origin "$BRANCH" 2>/dev/null || echo "  -> [INFO] git pull スキップ（ローカルコピーを使用）"
    cd - > /dev/null
fi

# アプリケーションファイルを配置
cp "$SCRIPT_DIR/health_app.py" "$APP_DIR/health_app.py"
echo "  -> health_app.py を配置しました"

if [ -f "$SCRIPT_DIR/test_webhook.py" ]; then
    cp "$SCRIPT_DIR/test_webhook.py" "$APP_DIR/test_webhook.py"
    echo "  -> test_webhook.py を配置しました"
fi

# systemd サービスファイルも更新
cp "$SCRIPT_DIR/sixamo-health.service" /etc/systemd/system/sixamo-health.service
systemctl daemon-reload
echo "  -> systemd サービス定義を更新しました"

chown -R www-data:www-data "$APP_DIR"
echo ""

# ---------------------------------------------------------------
# Step3: サービス再起動
# ---------------------------------------------------------------
echo "=== [Step3] サービス再起動 ==="
systemctl restart sixamo-health
sleep 2

if systemctl is-active --quiet sixamo-health; then
    echo "  -> sixamo-health: active (正常)"
else
    echo "  -> [ERROR] sixamo-health の起動に失敗しました"
    systemctl status sixamo-health --no-pager || true
    exit 1
fi

# ヘルスチェック
HEALTH=$(curl -s http://127.0.0.1:5000/health 2>/dev/null || echo '{"error":"接続失敗"}')
echo "  -> ヘルスチェック: $HEALTH"
echo ""

# ---------------------------------------------------------------
# Step4: Telegram通知確認
# ---------------------------------------------------------------
echo "=== [Step4] Telegram通知確認 ==="
echo "  -> 起動時に以下の通知がTelegramに届いているはずです:"
echo ""
echo "     🚀 サーバーが起動しました"
echo "     DRYRUNモード：ON"
echo "     テンプレート数：0件"
echo "     ワーカー数：1"
echo ""

# ログ確認
echo "=== 直近のログ ==="
if [ -f "$APP_DIR/access.log" ]; then
    echo "--- access.log (最新5行) ---"
    tail -5 "$APP_DIR/access.log"
fi
if [ -f "$APP_DIR/error.log" ]; then
    echo "--- error.log (最新5行) ---"
    tail -5 "$APP_DIR/error.log"
fi

echo ""
echo "============================================"
echo " デプロイ完了!"
echo "============================================"
echo ""
echo " 次のステップ:"
echo "   1. Telegramに🚀通知が届いたか確認"
echo "   2. Webhookテスト: cd $APP_DIR && python3 test_webhook.py all"
echo "   3. ログ監視: tail -f $APP_DIR/access.log"
echo ""
