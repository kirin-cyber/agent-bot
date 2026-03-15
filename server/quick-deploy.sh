#!/bin/bash
# Sixamo クイックデプロイ（コード更新 + .env設定 + 再起動）
# 使用方法: sudo bash quick-deploy.sh
#
# 本番構成:
#   sixamo.service (gunicorn + main.py) → ポート5000
#   sixamo-health.service は不使用（停止・無効化する）
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
# Step0: sixamo-health.service を停止・無効化
# ---------------------------------------------------------------
echo "=== [Step0] sixamo-health.service 停止 ==="
if systemctl is-active --quiet sixamo-health 2>/dev/null; then
    systemctl stop sixamo-health
    echo "  -> sixamo-health を停止しました"
else
    echo "  -> sixamo-health は既に停止済み"
fi
if systemctl is-enabled --quiet sixamo-health 2>/dev/null; then
    systemctl disable sixamo-health
    echo "  -> sixamo-health を無効化しました"
else
    echo "  -> sixamo-health は既に無効化済み"
fi
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

cp "$SCRIPT_DIR/main.py" "$APP_DIR/main.py"
echo "  -> main.py を配置しました"

if [ -f "$SCRIPT_DIR/test_webhook.py" ]; then
    cp "$SCRIPT_DIR/test_webhook.py" "$APP_DIR/test_webhook.py"
    echo "  -> test_webhook.py を配置しました"
fi

# sixamo.service を更新（既存がなければ新規配置）
if [ -f "$SCRIPT_DIR/sixamo.service" ]; then
    cp "$SCRIPT_DIR/sixamo.service" /etc/systemd/system/sixamo.service
    systemctl daemon-reload
    echo "  -> sixamo.service を更新しました"
fi

chown -R www-data:www-data "$APP_DIR"
echo ""

# ---------------------------------------------------------------
# Step3: sixamo.service を再起動
# ---------------------------------------------------------------
echo "=== [Step3] sixamo.service 再起動 ==="
systemctl restart sixamo
sleep 3

if systemctl is-active --quiet sixamo; then
    echo "  -> sixamo: active (正常)"
else
    echo "  -> [ERROR] sixamo の起動に失敗しました"
    systemctl status sixamo --no-pager || true
    echo ""
    echo "  -> journalctl で詳細を確認:"
    journalctl -u sixamo --no-pager -n 20 || true
    exit 1
fi

# ヘルスチェック
sleep 1
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
echo "     ワーカー数：2"
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
echo " サービス状態:"
echo "   sixamo:        $(systemctl is-active sixamo 2>/dev/null || echo 'unknown')"
echo "   sixamo-health: $(systemctl is-active sixamo-health 2>/dev/null || echo 'inactive')"
echo "   nginx:         $(systemctl is-active nginx 2>/dev/null || echo 'unknown')"
echo ""
echo " 次のステップ:"
echo "   1. Telegramに🚀通知が届いたか確認"
echo "   2. Webhookテスト: cd $APP_DIR && python3 test_webhook.py all"
echo "   3. ログ監視: tail -f $APP_DIR/access.log"
echo ""
