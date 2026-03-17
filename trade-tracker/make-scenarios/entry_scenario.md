## エントリーフロー（Makeシナリオ設定手順）

### Step1: Webhookモジュール

- 種類: Custom Webhook
- 名前: `trade_entry_webhook`
- 受け取るデータ:
  - `image`（Base64）— LINEスクショ画像
  - `tab`（`"entry"` 固定）— エントリー識別用

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
            "text": "{{ENTRY_PROMPT}}"
          }
        ]
      }
    ]
  }
  ```
- モデル: `claude-sonnet-4-6`（最新版を使用）
- プロンプト: `prompts/entry_prompt.txt` の内容を `{{ENTRY_PROMPT}}` にセット

### Step3: JSONパース

- モジュール: JSON > Parse JSON
- 対象: Step2のレスポンスbody（`{{2.data.content[0].text}}`）
- 出力例:
  ```json
  {
    "date": "03/17",
    "time": "14:30",
    "instructor": "よっとん",
    "result": "Wait",
    "symbol": "USD/JPY",
    "direction": "Buy",
    "entry_price": 149.500,
    "stop_loss": 149.200,
    "take_profit": 150.000,
    "message": "ドル円ロング 149.5 SL149.2 TP150.0"
  }
  ```

### Step4: Glideへレスポンス返却

- モジュール: Webhook Response
- パースしたJSONをWebhookレスポンスとして返す
- ユーザーが確認・修正できるよう全フィールドを返す
- レスポンス形式:
  ```json
  {
    "parsed_data": "{{3.json}}",
    "status": "pending_confirmation"
  }
  ```

### Step5: 確認後 → Google Sheetsへ書き込み

- モジュール: Google Sheets > Add a Row
- スプレッドシート: `{{SPREADSHEET_ID}}`
- シート名: `トレード記録`
- カラムマッピング:

| 列 | 内容 | 値 |
|----|------|-----|
| A | 管理ID | `{{既存の最終行+1}}` で自動採番 |
| B | 日付 | `{{3.json.date}}` |
| C | 講師名 | `{{3.json.instructor}}` |
| D | 勝敗 | `"Wait"` 固定 |
| E | 銘柄 | `{{3.json.symbol}}` |
| F | 売買方向 | `{{3.json.direction}}` |
| G | エントリー価格 | `{{3.json.entry_price}}` |
| H | SL | `{{3.json.stop_loss}}` |
| I | 分割メモ | （空欄） |
| J | クローズ価格 | （空欄） |
| K | TP | `{{3.json.take_profit}}` |
| L | 損益pips | （数式で自動計算） |
| M | メッセージ原文 | `{{3.json.message}}` |
