import type { SearchParams, Company } from "@/types";

// 企業名らしいキーワードが含まれているか判定
function hasCompanyKeyword(text: string): boolean {
  return /会社|株式会社|合同会社|有限会社|Corp|Inc|Ltd|Co\.|企業|法人/.test(text);
}

// 検索クエリを組み立てる純粋関数（テスト・拡張しやすい）
export function buildQuery(params: SearchParams, appendCompanyKeyword = true): string {
  const base = [params.keyword, params.industry, params.region]
    .filter(Boolean)
    .join(" ");

  if (appendCompanyKeyword && base && !hasCompanyKeyword(base)) {
    return `${base} 会社`;
  }
  return base;
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
    const apiMessage: string = err?.error?.message ?? "";
    const apiStatus: number = err?.error?.code ?? res.status;

    if (apiMessage.includes("does not have the access to Custom Search JSON API")) {
      throw new Error(
        "Google Cloud Console で Custom Search JSON API が有効化されていません。" +
        "APIライブラリから有効化してください。（GCP error: " + apiMessage + "）"
      );
    }
    if (apiStatus === 429 || apiMessage.toLowerCase().includes("quota")) {
      throw new Error("Google検索APIの1日あたりのクォータを超過しました。翌日以降に再試行してください。");
    }
    throw new Error(
      apiMessage
        ? `Google検索APIエラー (${apiStatus}): ${apiMessage}`
        : `Google検索APIでエラーが発生しました (HTTP ${res.status})`
    );
  }

  const data = await res.json();
  return (data.items ?? []).map((item: GoogleItem): Company => ({
    title: item.title ?? "",
    link: item.link ?? "",
    snippet: item.snippet ?? "",
  }));
}
