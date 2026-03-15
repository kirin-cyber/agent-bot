#!/bin/bash
# ============================================================
# Zendesk Webhook テストスクリプト
# ============================================================
# 使用方法:
#   bash test-webhook.sh                   # ローカルテスト (署名なし)
#   bash test-webhook.sh local             # ローカルテスト (署名なし)
#   bash test-webhook.sh signed            # ローカルテスト (署名付き)
#   bash test-webhook.sh remote <ドメイン> # リモートHTTPSテスト
# ============================================================
set -euo pipefail

MODE="${1:-local}"
DOMAIN="${2:-}"
APP_DIR="/opt/sixamo"
ENV_FILE="$APP_DIR/.env"

# テスト用ペイロード
PAYLOAD='{
  "ticket": {
    "id": 99999,
    "subject": "[テスト] Webhook動作確認",
    "status": "new",
    "priority": "high",
    "requester": {
      "name": "テストユーザー"
    },
    "description": "これはWebhook設定の動作確認テストです。Telegramに通知が届けば成功です。"
  }
}'

echo "============================================"
echo " Zendesk Webhook テスト"
echo " モード: $MODE"
echo "============================================"
echo ""

case "$MODE" in
    local)
        # --- ローカルテスト（署名なし、IP制限スキップ用にX-Real-IPなし） ---
        echo "=== ローカルテスト (http://127.0.0.1:5000/webhook) ==="
        echo ""
        echo "リクエスト送信中..."
        RESPONSE=$(curl -s -w "\n%{http_code}" \
            -X POST http://127.0.0.1:5000/webhook \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD" 2>/dev/null || echo -e "\n000")

        HTTP_CODE=$(echo "$RESPONSE" | tail -1)
        BODY=$(echo "$RESPONSE" | head -n -1)

        echo "  HTTP Status: $HTTP_CODE"
        echo "  Response: $BODY"
        echo ""

        if [ "$HTTP_CODE" = "200" ]; then
            echo "✓ 成功: Webhookが正常に処理されました"
            echo "  → Telegramに通知が届いているか確認してください"
        elif [ "$HTTP_CODE" = "403" ]; then
            echo "[情報] IP制限により拒否されました (正常動作)"
            echo "  ローカルIPがZendeskのIPレンジに含まれていないためです。"
            echo "  署名付きテストを試してください: bash test-webhook.sh signed"
        elif [ "$HTTP_CODE" = "401" ]; then
            echo "[情報] 署名検証に失敗しました"
            echo "  署名付きテストを試してください: bash test-webhook.sh signed"
        else
            echo "[エラー] 予期しないレスポンスです"
        fi
        ;;

    signed)
        # --- 署名付きテスト ---
        echo "=== 署名付きテスト (http://127.0.0.1:5000/webhook) ==="
        echo ""

        # .env からシークレットを読み取り
        if [ -f "$ENV_FILE" ]; then
            SECRET=$(grep "^ZENDESK_WEBHOOK_SECRET=" "$ENV_FILE" | cut -d'=' -f2- | tr -d "'" | tr -d '"')
        else
            SECRET=""
        fi

        if [ -z "$SECRET" ] || echo "$SECRET" | grep -q "your_"; then
            echo "[エラー] ZENDESK_WEBHOOK_SECRET が設定されていません"
            echo "  $ENV_FILE を確認してください"
            exit 1
        fi

        # 署名を計算
        TIMESTAMP=$(date +%s)
        SIGN_PAYLOAD="${TIMESTAMP}${PAYLOAD}"

        if command -v python3 &>/dev/null; then
            SIGNATURE=$(python3 -c "
import base64, hashlib, hmac
secret = '$SECRET'.encode()
payload = '${SIGN_PAYLOAD}'.encode()
sig = base64.b64encode(hmac.new(secret, payload, hashlib.sha256).digest()).decode()
print(sig)
")
        else
            echo "[エラー] python3 が必要です"
            exit 1
        fi

        echo "  Timestamp: $TIMESTAMP"
        echo "  Signature: ${SIGNATURE:0:10}..."
        echo ""
        echo "リクエスト送信中..."

        RESPONSE=$(curl -s -w "\n%{http_code}" \
            -X POST http://127.0.0.1:5000/webhook \
            -H "Content-Type: application/json" \
            -H "X-Zendesk-Webhook-Signature: $SIGNATURE" \
            -H "X-Zendesk-Webhook-Signature-Timestamp: $TIMESTAMP" \
            -d "$PAYLOAD" 2>/dev/null || echo -e "\n000")

        HTTP_CODE=$(echo "$RESPONSE" | tail -1)
        BODY=$(echo "$RESPONSE" | head -n -1)

        echo "  HTTP Status: $HTTP_CODE"
        echo "  Response: $BODY"
        echo ""

        if [ "$HTTP_CODE" = "200" ]; then
            echo "✓ 成功: 署名検証OK、Webhookが正常に処理されました"
            echo "  → Telegramに通知が届いているか確認してください"
        elif [ "$HTTP_CODE" = "403" ]; then
            echo "[情報] IP制限により拒否されました"
            echo "  テスト時はIPレンジを一時的に緩和することを検討してください"
        elif [ "$HTTP_CODE" = "401" ]; then
            echo "[エラー] 署名検証に失敗しました"
            echo "  .env の ZENDESK_WEBHOOK_SECRET が正しいか確認してください"
        else
            echo "[エラー] 予期しないレスポンスです"
        fi
        ;;

    remote)
        # --- リモートHTTPSテスト ---
        if [ -z "$DOMAIN" ]; then
            echo "[エラー] ドメイン名を指定してください"
            echo "  使用方法: bash test-webhook.sh remote support.sixamo.forex"
            exit 1
        fi

        echo "=== リモートHTTPSテスト (https://$DOMAIN/webhook) ==="
        echo ""

        # まずヘルスチェック
        echo "  -> ヘルスチェック..."
        HEALTH=$(curl -s --max-time 10 "https://$DOMAIN/health" 2>/dev/null || echo "接続失敗")
        echo "     $HEALTH"
        echo ""

        echo "  -> Webhook テスト送信..."
        RESPONSE=$(curl -s -w "\n%{http_code}" \
            --max-time 15 \
            -X POST "https://$DOMAIN/webhook" \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD" 2>/dev/null || echo -e "\n000")

        HTTP_CODE=$(echo "$RESPONSE" | tail -1)
        BODY=$(echo "$RESPONSE" | head -n -1)

        echo "  HTTP Status: $HTTP_CODE"
        echo "  Response: $BODY"
        echo ""

        case "$HTTP_CODE" in
            200) echo "✓ 成功: Telegram通知を確認してください" ;;
            403) echo "[正常] IP制限が機能しています (Zendesk以外のIPを拒否)" ;;
            401) echo "[正常] 署名検証が機能しています (署名なしリクエストを拒否)" ;;
            000) echo "[エラー] 接続できませんでした。SSL設定を確認してください" ;;
            *)   echo "[情報] HTTP $HTTP_CODE が返されました" ;;
        esac
        ;;

    *)
        echo "使用方法:"
        echo "  bash test-webhook.sh              # ローカルテスト"
        echo "  bash test-webhook.sh local         # ローカルテスト"
        echo "  bash test-webhook.sh signed        # 署名付きテスト"
        echo "  bash test-webhook.sh remote <ドメイン>  # リモートHTTPSテスト"
        exit 1
        ;;
esac

echo ""
