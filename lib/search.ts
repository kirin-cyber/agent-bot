import type { SearchParams, Company } from "@/types";

// 検索クエリを組み立てる純粋関数（テスト・拡張しやすい）
export function buildQuery(params: SearchParams): string {
  return [params.keyword, params.industry, params.region]
    .filter(Boolean)
    .join(" ");
}

// Google Custom Search API のレスポンス型
type GoogleItem = {
  title?: string;
  link?: string;
  snippet?: string;
};

// Google CSE を呼び出す関数（フェーズ2でAI分析と組み合わせる想定）
export async function searchCompanies(params: SearchParams): Promise<Company[]> {
  const apiKey = process.env.GOOGLE_API_KEY;
  const cseId = process.env.GOOGLE_CSE_ID;

  if (!apiKey || !cseId) {
    throw new Error("サーバー設定エラー: APIキーが設定されていません");
  }

  const query = buildQuery(params);
  if (!query) throw new Error("検索キーワードを入力してください");

  const url = new URL("https://www.googleapis.com/customsearch/v1");
  url.searchParams.set("key", apiKey);
  url.searchParams.set("cx", cseId);
  url.searchParams.set("q", query);
  url.searchParams.set("num", "10");

  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || "Google検索APIでエラーが発生しました");
  }

  const data = await res.json();
  return (data.items ?? []).map((item: GoogleItem): Company => ({
    title: item.title ?? "",
    link: item.link ?? "",
    snippet: item.snippet ?? "",
  }));
}
