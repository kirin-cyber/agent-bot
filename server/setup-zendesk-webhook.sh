#!/bin/bash
# ============================================================
# Zendesk Webhook セットアップスクリプト
# ============================================================
# 使用方法: sudo bash setup-zendesk-webhook.sh
#
# このスクリプトは以下を実行します:
#   Step1: .env の確認・対話的設定
#   Step2: ZendeskのIPレンジ自動取得
#   Step3: サービス再起動・動作確認
#
# ※ Step2（Zendesk管理画面でのWebhook作成）と
#   Step5（トリガー設定）は手動で行う必要があります。
#   スクリプト実行後に表示されるガイドに従ってください。
# ============================================================
set -euo pipefail

APP_DIR="/opt/sixamo"
ENV_FILE="$APP_DIR/.env"
ZENDESK_SUBDOMAIN="sixamo"
SERVICE_NAME="sixamo-health"

echo "============================================"
echo " Zendesk Webhook セットアップ"
echo "============================================"
echo ""

# ============================================================
# Step1: .env の確認・更新
# ============================================================
echo "=== [Step1/3] .env の確認 ==="

if [ ! -f "$ENV_FILE" ]; then
    echo "  [エラー] $ENV_FILE が見つかりません。"
    echo "  先に deploy.sh を実行してください。"
    exit 1
fi

echo "  -> $ENV_FILE の現在の設定:"
echo ""

# 各設定値の状態を表示（値自体はマスク）
for key in ZENDESK_WEBHOOK_SECRET ZENDESK_IP_RANGES ZENDESK_SUBDOMAIN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
    VALUE=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- || true)
    if [ -z "$VALUE" ] || echo "$VALUE" | grep -qE '^(your_|123456)'; then
        echo "  -> $key: [未設定]"
    else
        # 値をマスク表示（最初の4文字のみ表示）
        MASKED="${VALUE:0:4}..."
        echo "  -> $key: ${MASKED}"
    fi
done

echo ""

# --- ZENDESK_SUBDOMAIN ---
CURRENT_SUBDOMAIN=$(grep "^ZENDESK_SUBDOMAIN=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
if [ -z "$CURRENT_SUBDOMAIN" ]; then
    # ZENDESK_SUBDOMAIN が .env にない場合、追加
    echo "ZENDESK_SUBDOMAIN=$ZENDESK_SUBDOMAIN" >> "$ENV_FILE"
    echo "  -> ZENDESK_SUBDOMAIN=$ZENDESK_SUBDOMAIN を追加しました"
fi

# ============================================================
# Step2: Zendesk IPレンジの自動取得
# ============================================================
echo ""
echo "=== [Step2/3] Zendesk IPレンジ取得 ==="

ZENDESK_IPS_URL="https://${ZENDESK_SUBDOMAIN}.zendesk.com/ips"
echo "  -> $ZENDESK_IPS_URL からIPレンジを取得中..."

IP_RESPONSE=$(curl -s --max-time 15 "$ZENDESK_IPS_URL" 2>/dev/null || true)

if [ -n "$IP_RESPONSE" ] && echo "$IP_RESPONSE" | grep -q "egress"; then
    # jq がある場合は使用、なければ python で解析
    if command -v jq &>/dev/null; then
        EGRESS_IPS=$(echo "$IP_RESPONSE" | jq -r '.egress.all[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    elif command -v python3 &>/dev/null; then
        EGRESS_IPS=$(echo "$IP_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ips = data.get('egress', {}).get('all', [])
print(','.join(ips))
" 2>/dev/null || true)
    fi

    if [ -n "$EGRESS_IPS" ]; then
        echo "  -> 取得成功: $EGRESS_IPS"

        # .env の ZENDESK_IP_RANGES を更新
        if grep -q "^ZENDESK_IP_RANGES=" "$ENV_FILE"; then
            sed -i "s|^ZENDESK_IP_RANGES=.*|ZENDESK_IP_RANGES=$EGRESS_IPS|" "$ENV_FILE"
        else
            echo "ZENDESK_IP_RANGES=$EGRESS_IPS" >> "$ENV_FILE"
        fi
        echo "  -> .env の ZENDESK_IP_RANGES を更新しました"
    else
        echo "  -> [警告] IPレンジの解析に失敗しました"
        echo "  -> デフォルト値 (216.198.0.0/18) を使用します"
        FALLBACK_IP="216.198.0.0/18"
        if grep -q "^ZENDESK_IP_RANGES=" "$ENV_FILE"; then
            sed -i "s|^ZENDESK_IP_RANGES=.*|ZENDESK_IP_RANGES=$FALLBACK_IP|" "$ENV_FILE"
        else
            echo "ZENDESK_IP_RANGES=$FALLBACK_IP" >> "$ENV_FILE"
        fi
    fi
else
    echo "  -> [警告] Zendesk IPs API にアクセスできませんでした"
    echo "  -> デフォルト値 (216.198.0.0/18) を使用します"
    echo ""
    echo "  手動確認: curl $ZENDESK_IPS_URL"
    FALLBACK_IP="216.198.0.0/18"
    if grep -q "^ZENDESK_IP_RANGES=" "$ENV_FILE"; then
        sed -i "s|^ZENDESK_IP_RANGES=.*|ZENDESK_IP_RANGES=$FALLBACK_IP|" "$ENV_FILE"
    else
        echo "ZENDESK_IP_RANGES=$FALLBACK_IP" >> "$ENV_FILE"
    fi
fi

# --- Webhook Secret の確認 ---
echo ""
CURRENT_SECRET=$(grep "^ZENDESK_WEBHOOK_SECRET=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
if [ -z "$CURRENT_SECRET" ] || echo "$CURRENT_SECRET" | grep -q "your_"; then
    echo "  ┌─────────────────────────────────────────┐"
    echo "  │  ZENDESK_WEBHOOK_SECRET が未設定です     │"
    echo "  │                                         │"
    echo "  │  Zendesk管理画面でWebhookを作成し、     │"
    echo "  │  署名シークレットを取得してください。    │"
    echo "  │  (詳細は下記ガイド参照)                 │"
    echo "  └─────────────────────────────────────────┘"
    echo ""
    read -rp "  署名シークレットを入力 (後で設定する場合はEnter): " INPUT_SECRET
    if [ -n "$INPUT_SECRET" ]; then
        sed -i "s|^ZENDESK_WEBHOOK_SECRET=.*|ZENDESK_WEBHOOK_SECRET=$INPUT_SECRET|" "$ENV_FILE"
        echo "  -> ZENDESK_WEBHOOK_SECRET を設定しました"
    else
        echo "  -> スキップしました。後で以下を実行して設定してください:"
        echo "     nano $ENV_FILE"
    fi
fi

# ============================================================
# Step3: サービス再起動・動作確認
# ============================================================
echo ""
echo "=== [Step3/3] サービス再起動・動作確認 ==="

echo "  -> $SERVICE_NAME を再起動..."
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "  -> ステータス: active (正常)"
else
    echo "  -> [エラー] サービスの起動に失敗しました"
    systemctl status "$SERVICE_NAME" --no-pager || true
    exit 1
fi

echo ""
echo "  -> ヘルスチェック:"
HEALTH=$(curl -s --max-time 10 http://127.0.0.1:5000/health 2>/dev/null || echo "接続失敗")
echo "     $HEALTH"

# zendesk_webhook の設定状態を確認
if echo "$HEALTH" | grep -q '"configured"'; then
    echo ""
    echo "  ✓ Webhook 設定済み"
else
    echo ""
    echo "  [情報] ZENDESK_WEBHOOK_SECRET を設定後、再度このスクリプトを実行してください"
fi

# ============================================================
# Zendesk管理画面での手動設定ガイド
# ============================================================
echo ""
echo "============================================"
echo " Zendesk管理画面での手動設定ガイド"
echo "============================================"
echo ""
echo " ■ Webhook作成 (Zendesk管理画面)"
echo "   1. https://${ZENDESK_SUBDOMAIN}.zendesk.com/admin にログイン"
echo "   2. 左メニュー → 「オブジェクトとルール」→「Webhook」"
echo "   3. 「Webhookを作成」をクリック"
echo "   4. 以下を入力:"
echo "      - 名前: sixamo-automation"

# ドメイン名を検出（SSL証明書の存在で判断）
WEBHOOK_DOMAIN=""
for d in support.sixamo.forex sixamo.forex api.sixamo.forex; do
    if [ -d "/etc/letsencrypt/live/$d" ]; then
        WEBHOOK_DOMAIN="$d"
        break
    fi
done

if [ -n "$WEBHOOK_DOMAIN" ]; then
    echo "      - エンドポイントURL: https://${WEBHOOK_DOMAIN}/webhook"
else
    echo "      - エンドポイントURL: https://<ドメイン名>/webhook"
    echo "        (SSL設定したドメインに置き換えてください)"
fi

echo "      - リクエストメソッド: POST"
echo "      - リクエスト形式: JSON"
echo "   5. 「署名シークレット」を有効化"
echo "      → 表示されたシークレットをコピー"
echo ""
echo "   シークレットの設定:"
echo "     nano $ENV_FILE"
echo "     ZENDESK_WEBHOOK_SECRET=<コピーしたシークレット>"
echo "     sudo systemctl restart $SERVICE_NAME"
echo ""
echo " ■ トリガー設定 (Zendesk管理画面)"
echo "   1. 管理画面 →「ビジネスルール」→「トリガー」"
echo "   2. 「トリガーを作成」をクリック"
echo "   3. 以下を設定:"
echo "      - トリガー名: 自動返信Webhook"
echo "      - 条件: チケットが作成された"
echo "      - アクション: Webhookを呼び出す → sixamo-automation を選択"
echo ""
echo " ■ 動作確認"
echo "   Zendeskの「テスト送信」機能で Webhook をテスト"
echo "   → Telegram に通知が届けば成功"
echo ""
