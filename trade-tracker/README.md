# トレード自動記録システム v3.1

## 概要

LINEオープンチャットのスクショをアップロードするだけで、
Claude Vision APIがトレード情報を読み取りGoogleスプレッドシートに自動記録するシステム。

## 技術スタック

| サービス | 用途 | コスト |
|---------|------|--------|
| Glide | フロントエンド | 無料プラン |
| Make | 自動化（Webhook → API → Sheets） | 無料プラン・月1,000オペレーション以内 |
| Claude Vision API | スクショからトレード情報を読み取り | 従量課金・1回2〜5円 |
| Google スプレッドシート | トレード記録の保存先 | 無料 |

## フォルダ構成

```
trade-tracker/
├── README.md              ← このファイル
├── TEST_CHECKLIST.md      ← 結合テストチェックリスト
├── frontend/
│   ├── glide_screens.md   ← Glide画面仕様（4画面）
│   └── webhook-spec.json  ← Webhook API仕様
├── make-scenarios/
│   ├── entry_scenario.md  ← エントリーフロー設定手順
│   ├── entry-scenario.json
│   ├── close_scenario.md  ← 決済フロー設定手順
│   └── close-scenario.json
├── prompts/
│   ├── entry_prompt.txt   ← エントリー読み取りプロンプト
│   └── close_prompt.txt   ← 決済読み取りプロンプト
└── sheets/
    └── sheet-config.json  ← スプレッドシート列構成・計算式
```

## 構築手順

1. **Google Sheets** — 列構成・計算式の設定（`sheets/sheet-config.json` 参照）
2. **Anthropic Console** — APIキー発行
3. **Make** — シナリオ2本作成（`make-scenarios/entry_scenario.md` / `close_scenario.md` 参照）
4. **Glide** — アプリ4画面作成（`frontend/glide_screens.md` 参照）
5. **結合テスト** — 全項目チェック（`TEST_CHECKLIST.md` 参照）

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
- 分割決済中 → `Wait` 維持

※ I列（分割決済）の有無は判定条件に含まない

## 運用上の注意

- スクショは1講師・1トレードが明確に見える状態でアップロードする
- APIキーはMakeのシナリオ内にのみ設定し外部に漏らさない
- Makeの月間オペレーション数を1,000以内に収める（1トレード=エントリー+決済で約6〜8オペレーション）

## Makeのリクエスト本文の修正手順

1. trade_entry_scenarioを開く
2. 編集をクリック
3. HTTPモジュール（2番）をダブルクリック
4. リクエスト本文の内容を全て削除
5. entry_http_body.json の内容をコピペ
6. 保存してシナリオをオンにする
