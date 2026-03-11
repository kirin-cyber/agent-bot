# Agent Bot - 企業検索

Google Custom Search API を使って企業をキーワード・業種・地域で検索できるWebアプリです。

## 技術スタック

- **フレームワーク**: Next.js 14 (App Router)
- **言語**: TypeScript
- **API**: Google Custom Search API
- **デプロイ**: Vercel

## セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd agent-bot
```

### 2. 依存関係のインストール

```bash
npm install
```

### 3. 環境変数の設定

`.env.local.example` をコピーして `.env.local` を作成し、APIキーを設定します。

```bash
cp .env.local.example .env.local
```

`.env.local` を編集:

```
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_CSE_ID=your_custom_search_engine_id_here
```

#### Google APIキーの取得方法

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. プロジェクトを作成または選択
3. 「APIとサービス」→「認証情報」→「APIキーを作成」
4. 「Custom Search API」を有効化

#### Google CSE IDの取得方法

1. [Programmable Search Engine](https://programmablesearchengine.google.com/) にアクセス
2. 「新しい検索エンジンを追加」
3. 検索対象サイトに `*.co.jp` や `www.google.com` を指定（全ウェブ検索の場合は「ウェブ全体を検索」を有効化）
4. 検索エンジンIDをコピー

### 4. 開発サーバーの起動

```bash
npm run dev
```

ブラウザで [http://localhost:3000](http://localhost:3000) を開きます。

## Vercel へのデプロイ

1. [Vercel](https://vercel.com) にサインアップ・ログイン
2. このリポジトリをインポート
3. 環境変数を設定:
   - `GOOGLE_API_KEY`
   - `GOOGLE_CSE_ID`
4. デプロイ

## ファイル構成

```
agent-bot/
├── app/
│   ├── api/
│   │   └── search/
│   │       └── route.ts     # Google検索APIを呼ぶAPIルート
│   ├── layout.tsx           # アプリ全体のレイアウト
│   └── page.tsx             # 検索UIのメインページ
├── components/
│   ├── SearchForm.tsx       # キーワード・業種・地域の検索フォーム
│   └── ResultList.tsx       # 検索結果の一覧表示
├── .env.local.example       # 環境変数のサンプル
├── vercel.json              # Vercelデプロイ設定
└── README.md
```
