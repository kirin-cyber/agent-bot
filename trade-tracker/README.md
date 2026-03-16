# トレード自動記録システム v3.1

LINEオープンチャットのスクショをアップロードするだけで、Claude Vision APIが自動でトレード情報を読み取り、Googleスプレッドシートに記録するシステム。

## 技術スタック

| 役割 | ツール | 備考 |
|------|--------|------|
| フロントエンド | Glide（無料プラン） | スクショアップ・確認画面・未決済リスト |
| 自動化ハブ | Make（無料プラン） | 月1,000オペレーション以内で運用 |
| AI解析 | Claude Vision API | 従量課金（1回2〜5円程度） |
| 記録先 | Google スプレッドシート | 無料 |

## ディレクトリ構成

```
trade-tracker/
├── frontend/                  # Glide連携用Webhook仕様
│   └── webhook-spec.json      # エンドポイント仕様・画面構成定義
├── make-scenarios/            # Makeシナリオ設定
│   ├── entry-scenario.json    # エントリーフロー定義
│   └── settlement-scenario.json # 決済フロー定義
├── prompts/                   # Claude APIプロンプト
│   ├── entry-prompt.txt       # エントリー用プロンプト
│   └── settlement-prompt.txt  # 決済用プロンプト
├── sheets/                    # スプレッドシート設定
│   ├── sheet-config.json      # 列構成・計算ルール定義
│   └── setup-formulas.txt     # 初期設定手順・数式
└── README.md
```

## 運用フロー

### エントリー記録
1. Glideアプリでスクショを選択（エントリータブ）
2. Make Webhookが受信 → Claude Vision APIで解析
3. 確認・修正画面でAI読み取り結果を確認
4. Google Sheetsに新規行追加（勝敗=Wait）

### 決済記録
1. 未決済リスト（D列=Wait）からポジションをタップ選択
2. 決済スクショをアップロード
3. Claude Vision APIでクローズ価格・分割/最終を判定
4. 既存行のJ列・I列を上書き更新
5. 最終決済時（is_final=true）→ 損益pipsに基づきWin/Lose/Drawを自動判定

## 構築手順

| 順 | 作業 | 参照ファイル |
|----|------|-------------|
| 1 | Google Sheets準備 | `sheets/setup-formulas.txt` |
| 2 | Claude APIキー取得 | Anthropicコンソール |
| 3 | Makeシナリオ作成 | `make-scenarios/*.json` |
| 4 | Glideアプリ作成 | `frontend/webhook-spec.json` |
| 5 | 結合テスト | 実際のLINEスクショで動作確認 |

## 損益計算ルール

| 銘柄 | 計算式 | 備考 |
|------|--------|------|
| FX（USD/JPY等） | 価格差 × 100 | 通常のpips計算 |
| ゴールド（XAU/USD） | 価格差 × 10 | 1ドル差 = 10pips |
| 仮想通貨（BTC/USD等） | 価格差 × 0.1 | 100ドル差 = 10pips |
| ナスダック（NAS100） | 価格差 × 0.1 | 10ポイント差 = 1pips |

## 勝敗判定ロジック

- エントリー時 → `Wait`
- 最終決済（is_final=true）かつ pips > 0 → `Win`
- 最終決済（is_final=true）かつ pips < 0 → `Lose`
- 最終決済（is_final=true）かつ pips = 0 → `Draw`
- 分割決済中 → `Wait`維持

※ I列（分割決済）の有無は判定条件に含まない
