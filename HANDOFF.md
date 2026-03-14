# ハンドオフ: Sixamo Zendesk自動化システム 進捗まとめ

**期間**: 2026/03/13 〜 2026/03/14
**ブランチ**: `claude/zendesk-automation-system-WBDN5`
**リポジトリ**: `kirin-cyber/agent-bot`

---

## 完了済みタスク

### 1. Zendesk問い合わせ自動化システムの実装（3/13）

| コンポーネント | ファイル | 内容 |
|---|---|---|
| **Webhookサーバー** | `main.py` (655行) | Zendesk Webhook受信 → Claude AI分析 → 自動返信 or Telegram転送 |
| **応答テンプレート** | `templates.yaml` | ログイン・出金・入金等10カテゴリの定型返信 |
| **週次レポート** | `summary.py` | 毎週月曜09:00 JSTに自動返信/転送/エラー件数をTelegram送信 |
| **DBバックアップ** | `backup.py` | 毎日00:00 JST、7世代管理、S3オプション対応 |
| **テスト** | `test_webhook.py` | Webhook受信・署名検証・AI分析のユニットテスト |
| **systemd定義** | `sixamo*.service/timer` (5ファイル) | gunicornサーバー + タイマー2本 |
| **環境設定** | `.env.example`, `requirements.txt` | Zendesk/Anthropic/Telegram各種キー、Python依存パッケージ |

### 2. 既存Next.jsアプリのリファクタリング（3/13）

| ファイル | 内容 |
|---|---|
| `lib/search.ts` | 検索ロジックをサービス層に分離 |
| `types/index.ts` | 共通型定義を追加 |
| `app/api/search/route.ts` | API routeの簡素化 |

### 3. sixamo.service起動失敗の修正（3/14）

| 問題 | 原因 | 修正 |
|---|---|---|
| exit-code 2 | `Type=notify`（gunicorn非対応） | `Type=exec` に変更 |
| exit-code 2 | `${GUNICORN_WORKERS}`がExecStart内で未展開 | `bash -c` でラップ、デフォルト値4 |

---

## 現在のシステム構成

```
┌─────────────────┐     Webhook      ┌──────────────────────┐
│    Zendesk       │ ───────────────→ │  Flask (gunicorn)    │
│  カスタマーサポート │   POST /webhook  │  main.py :5000       │
└─────────────────┘                  │                      │
                                     │  ┌─ Claude AI 分析    │
                                     │  ├─ テンプレート照合    │
                                     │  └─ SQLite 記録       │
                                     └──────┬───────┬───────┘
                                            │       │
                              ┌─────────────┘       └──────────────┐
                              ▼                                    ▼
                     ┌────────────────┐                  ┌─────────────────┐
                     │ Zendesk API    │                  │ Telegram Bot    │
                     │ 自動返信送信    │                  │ スタッフ転送/通知 │
                     └────────────────┘                  └─────────────────┘

     ┌─────────────────────┐     ┌──────────────────────┐
     │ sixamo-backup.timer │     │ sixamo-summary.timer  │
     │ 毎日 00:00 JST      │     │ 毎週月曜 09:00 JST    │
     │ → DB 7世代バックアップ│     │ → 週次統計レポート     │
     └─────────────────────┘     └──────────────────────┘
```

---

## 本番サーバーの状態

| 項目 | 状態 |
|---|---|
| **サーバー** | `133.117.75.92` (root) |
| **デプロイ先** | `/opt/sixamo` |
| **DRYRUN_MODE** | `true`（返信は送信されず、Telegramプレビューのみ） |
| **sixamo.service** | 修正済み（要 `git pull` & `systemctl restart`） |

---

## 次のステップ（未実施）

### 1. 本番サーバーで修正版を適用

```bash
cd /opt/sixamo && git pull origin claude/zendesk-automation-system-WBDN5
cp sixamo.service /etc/systemd/system/
systemctl daemon-reload && systemctl restart sixamo
systemctl status sixamo
```

### 2. 動作確認

```bash
curl http://127.0.0.1:5000/health
```

### 3. Zendesk側のWebhook設定

- Webhook URL: `https://<ドメイン>/webhook`
- `ZENDESK_WEBHOOK_SECRET` を `.env` に設定
- `ZENDESK_IP_RANGES` にZendesk IPレンジを設定

### 4. DRYRUN_MODE解除

`.env` で `DRYRUN_MODE=false` に変更して本番稼働開始

### 5. Nginx/リバースプロキシ設定

外部からのHTTPS受信用（未構築）

---

## 注意事項

- `.env` にはAPIキー・トークンが含まれるため、Gitには含めていない（`.env.example` のみ）
- 現在 `DRYRUN_MODE=true` のため、Zendeskへの自動返信は**送信されない**（Telegramプレビューのみ）
- SSH接続はCI環境からは不可（ネットワーク制限）。手動での本番適用が必要
