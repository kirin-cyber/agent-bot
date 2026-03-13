# Sixamo - Zendesk問い合わせ自動化システム

> **⚠️ テンプレート編集前に必ずバックアップを取ること：**
> ```bash
> cp templates.yaml templates_backup_$(date +%Y%m%d).yaml
> ```

## 概要

ZendeskのWebhookを受け取り、Claude AIでお問い合わせ内容を分析し、テンプレートに基づいて自動返信またはTelegram経由で担当者に転送するシステムです。

## セットアップ

### 1. リポジトリのクローンと仮想環境

```bash
git clone <repository-url>
cd agent-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して必要な値を設定してください。

### 3. 開発サーバーの起動

```bash
python main.py
```

### 4. gunicornでの起動

```bash
gunicorn --bind 127.0.0.1:5000 --timeout 60 --workers $(nproc) main:app
```

**ワーカー数の推奨計算式：** CPUコア数 × 2 + 1

```bash
# CPUコア数の確認
nproc
# 例: 2コアの場合 → 2×2+1 = 5ワーカー
```

## DRYRUNモード

DRYRUNモードでは自動返信は送信されず、Telegramに返信案のみが通知されます。

### 切り替え手順

1. `.env` の `DRYRUN_MODE` を変更
2. サービスを再起動：`sudo systemctl restart sixamo`

### DRYRUNモード活用ルール

- テンプレート変更後は一時的に `DRYRUN_MODE=true` に設定して確認すること
- 返信案の内容が適切であることを確認してから `DRYRUN_MODE=false` に切り替える

## Zendesk IPレンジの管理

ZendeskのIPレンジは `.env` の `ZENDESK_IP_RANGES` にカンマ区切りで設定します。

### 確認・更新手順

1. Zendesk公式ドキュメントでIPレンジを確認：
   https://support.zendesk.com/hc/en-us/articles/203660846
2. `.env` の `ZENDESK_IP_RANGES` を更新
3. サービスを再起動：`sudo systemctl restart sixamo`

**月1回の確認を推奨します。**

## systemd サービスの管理

### サービスの登録

```bash
sudo cp sixamo.service /etc/systemd/system/
sudo cp sixamo-summary.service /etc/systemd/system/
sudo cp sixamo-summary.timer /etc/systemd/system/
sudo cp sixamo-backup.service /etc/systemd/system/
sudo cp sixamo-backup.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now sixamo
sudo systemctl enable --now sixamo-summary.timer
sudo systemctl enable --now sixamo-backup.timer
```

### タイマーの動作確認

```bash
systemctl list-timers
```

すべてのタイマー（sixamo-summary.timer, sixamo-backup.timer）が表示されることを確認してください。

### ログの確認

```bash
# メインサーバーのログ
journalctl -u sixamo

# 週次サマリーのログ
journalctl -u sixamo-summary

# DBバックアップのログ
journalctl -u sixamo-backup

# リアルタイムでログを追跡
journalctl -u sixamo -f
```

## テスト

```bash
# 正常系：通常の問い合わせ
python test_webhook.py normal

# 異常系：不正な署名（401が返ることを確認）
python test_webhook.py invalid_sig

# 異常系：重複イベントID（スキップされることを確認）
python test_webhook.py duplicate

# 異常系：JSONパースエラーを引き起こすケース
python test_webhook.py parse_error
```

## バックアップと復旧

### DBバックアップ

- バックアップディレクトリ：`backups/`
- ファイル名：`events_backup_YYYYMMDD.db`
- 7世代保持（それ以前は自動削除）
- S3転送：`BACKUP_S3_BUCKET` が設定されている場合は自動転送

### 復旧手順

```bash
# サービスを停止
sudo systemctl stop sixamo

# バックアップから復旧
cp backups/events_backup_YYYYMMDD.db events.db

# サービスを再起動
sudo systemctl start sixamo
```

## テンプレート管理

- テンプレートは `templates.yaml` で管理
- **テンプレートは10件以内を推奨**
- サーバー起動時に一度だけ読み込まれキャッシュされます
- テンプレート変更後はサービスの再起動が必要：`sudo systemctl restart sixamo`

## ファイル構成

```
agent-bot/
├── main.py                    # メインサーバー（Flask + gunicorn）
├── summary.py                 # 週次サマリー送信スクリプト
├── backup.py                  # SQLite DBバックアップスクリプト
├── test_webhook.py            # テスト用Webhookスクリプト
├── templates.yaml             # 返信テンプレート
├── events.db                  # SQLiteデータベース（自動作成）
├── .env                       # 環境変数（Git管理外）
├── .env.example               # 環境変数のサンプル
├── requirements.txt           # Pythonパッケージ
├── sixamo.service             # gunicorn用systemdサービス
├── sixamo-summary.service     # 週次サマリー用サービス
├── sixamo-summary.timer       # 週次サマリー用タイマー（毎週月曜9:00）
├── sixamo-backup.service      # DBバックアップ用サービス
├── sixamo-backup.timer        # DBバックアップ用タイマー（毎日0:00）
└── README.md
```

## 本番移行チェックリスト

以下の全項目をチェックした後に `DRYRUN_MODE=false` に変更してください。

- [ ] 最低1週間以上DRYRUN運用した
- [ ] 自動返信案を20件以上確認した
- [ ] 担当者転送を5件以上確認した
- [ ] 返信案の内容が適切だった（おかしいものがない）
- [ ] 禁止表現が使われていなかった
- [ ] エラーが連続で発生していない
- [ ] Telegram通知が正常に届いている
- [ ] UptimeRobotの監視が正常
- [ ] `systemctl list-timers` で全タイマーが動作中
- [ ] `test_webhook.py` の全4テストケースが正常に動作した
