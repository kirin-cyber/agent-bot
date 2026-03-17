## 決済フロー（Makeシナリオ設定手順）

### Step1: Webhookモジュール

- 種類: Custom Webhook
- 名前: `trade_close_webhook`
- 受け取るデータ:
  - `image`（Base64）— 決済スクショ画像
  - `management_id`（整数）— 未決済リストから選択された管理ID

### Step2: Claude Vision API呼び出し

- モジュール: HTTP > Make a request
- URL: `https://api.anthropic.com/v1/messages`
- Method: `POST`
- Headers:
  - `x-api-key`: `{{APIキー}}`
  - `anthropic-version`: `2023-06-01`
  - `content-type`: `application/json`
- Body:
  ```json
  {
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image",
            "source": {
              "type": "base64",
              "media_type": "{{1.image.mimeType}}",
              "data": "{{base64(1.image.data)}}"
            }
          },
          {
            "type": "text",
            "text": "{{CLOSE_PROMPT}}"
          }
        ]
      }
    ]
  }
  ```
- モデル: `claude-sonnet-4-6`（最新版を使用）
- プロンプト: `prompts/close_prompt.txt` の内容を `{{CLOSE_PROMPT}}` にセット

### Step3: JSONパース

- モジュール: JSON > Parse JSON
- 対象: Step2のレスポンスbody（`{{2.data.content[0].text}}`）
- 出力例:
  ```json
  {
    "close_price": 150.200,
    "is_final": true,
    "memo": null
  }
  ```
- 分割決済の場合:
  ```json
  {
    "close_price": 149.800,
    "is_final": false,
    "memo": "部分利確50%"
  }
  ```

### Step4: 管理IDで既存行を検索

- モジュール: Google Sheets > Search Rows
- スプレッドシート: `{{SPREADSHEET_ID}}`
- シート名: `トレード記録`
- 検索条件: A列 = `{{1.management_id}}`

### Step5: 行を更新

- モジュール: Google Sheets > Update a Row
- 対象行: Step4で見つかった行（`{{4.row_number}}`）
- 更新カラム:

| 列 | 内容 | 値 |
|----|------|-----|
| J | クローズ価格 | `{{3.json.close_price}}` で上書き |
| I | 分割メモ | `{{3.json.memo}}`（nullの場合は空白） |

- J列の更新により、L列の損益pips計算式が自動再計算される

### Step6: 勝敗判定（is_final=trueの場合のみ実行）

- モジュール: Router（条件分岐）

#### ルート1: 最終決済（`{{3.json.is_final}}` = true）

1. **L列（損益pips）を取得**
   - モジュール: Google Sheets > Get a Cell
   - セル: `L{{4.row_number}}`

2. **D列（勝敗）を更新**
   - モジュール: Google Sheets > Update a Row
   - 判定ロジック:

   | 条件 | D列の値 |
   |------|---------|
   | pips > 0 | `Win` |
   | pips < 0 | `Lose` |
   | pips = 0 | `Draw` |

   - Make式: `{{if(7.value > 0, 'Win', if(7.value < 0, 'Lose', 'Draw'))}}`

#### ルート2: 分割決済（`{{3.json.is_final}}` = false）

- 何もしない（D列は `Wait` のまま維持）
- Step5のJ列・I列更新のみで完了

> **注意**: I列（分割メモ）の有無は勝敗判定に影響しない。勝敗はL列のpips値のみで判定する。
