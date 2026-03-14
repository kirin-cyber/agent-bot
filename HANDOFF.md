# ハンドオフ: Sixamo Zendesk自動化システム 進捗まとめ

**期間**: 2026/03/13 〜 2026/03/15
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

### 4. 本番サーバーデプロイ完了（3/15）

| 作業 | 状態 |
|---|---|
| サーバー再起動 | 完了 |
| `git clone` & ブランチ切替 | 完了（`/opt/sixamo`） |
| Python venv & `pip install` | 完了 |
| `.env` 設定（APIキー全件） | 完了 |
| `/opt/sixamo` 権限修正 (`chown www-data`) | 完了 |
| systemdサービス登録 & 起動 | 完了（`sixamo.service`, `backup.timer`, `summary.timer`） |
| Nginx リバースプロキシ設定 | 完了（80番ポート → 5000番ポート） |
| ヘルスチェック（内部・外部） | 完了（`{"status":"ok"}`） |
| Zendesk Webhook設定 | 完了（`http://133.117.75.92/webhook`, POST, JSON） |
| Zendesk トリガー設定 | **進行中** |

---

## 現在のシステム構成

```
┌─────────────────┐     Webhook      ┌──────────────────────┐
│    Zendesk       │ ───────────────→ │  Nginx (:80)         │
│  カスタマーサポート │   POST /webhook  │  → gunicorn (:5000)  │
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
                     │ 自動返信送信    │                  │ @kirin76supportbot │
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
| **所有者** | `www-data:www-data` |
| **sixamo.service** | active (running) |
| **Nginx** | active (running), 80→5000 プロキシ |
| **DRYRUN_MODE** | `true`（返信は送信されず、Telegramプレビューのみ） |
| **ヘルスチェック** | `curl http://133.117.75.92/health` → `{"status":"ok"}` |

---

## 次のステップ（未実施）

### 1. Zendeskトリガー設定

Zendesk管理画面 → オブジェクトとルール → トリガー → 追加：
- **トリガー名**: `Sixamo自動応答`
- **条件**: チケット → ステータス → 新規
- **アクション**: Webhookに通知、JSON本文:

```json
{
  "ticket_id": "{{ticket.id}}",
  "subject": "{{ticket.title}}",
  "description": "{{ticket.description}}",
  "requester_email": "{{ticket.requester.email}}",
  "requester_name": "{{ticket.requester.name}}",
  "status": "{{ticket.status}}",
  "created_at": "{{ticket.created_at}}"
}
```

### 2. テストチケットでDRYRUN動作確認

テストチケットを作成 → Telegramにプレビューが届くことを確認

### 3. DRYRUN_MODE解除

サーバーで実行:
```bash
sed -i 's/DRYRUN_MODE=true/DRYRUN_MODE=false/' /opt/sixamo/.env
systemctl restart sixamo
```

### 4. HTTPS化（任意）

SSL証明書を取得してNginxでHTTPS対応（Let's Encrypt等）

---

## 設定済みサービス情報

| サービス | 情報 |
|---|---|
| **Zendesk** | `sixamogrouplimited.zendesk.com` / `shiomi.support@sixamo.forex` |
| **Telegram Bot** | `@kirin76supportbot` / Chat ID: `6976979859` |
| **Anthropic** | claude-sonnet-4-20250514 |

---

## 注意事項

- `.env` にはAPIキー・トークンが含まれるため、Gitには含めていない（`.env.example` のみ）
- 現在 `DRYRUN_MODE=true` のため、Zendeskへの自動返信は**送信されない**（Telegramプレビューのみ）
- SSH接続はCI環境からは不可（ネットワーク制限）。手動での本番適用が必要
- `/opt/sixamo` の所有者は `www-data` に設定済み。`git pull` 後は再度 `chown -R www-data:www-data /opt/sixamo` が必要
