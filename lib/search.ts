import type { SearchParams, Company } from "@/types";

// 企業名らしいキーワードが含まれているか判定
function hasCompanyKeyword(text: string): boolean {
  return /会社|株式会社|合同会社|有限会社|Corp|Inc|Ltd|Co\.|企業|法人/.test(text);
}

// 検索クエリを組み立てる純粋関数
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

// DuckDuckGo Instant Answer API のレスポンス型
type DDGRelatedTopic = {
  Text?: string;
  FirstURL?: string;
  Topics?: DDGRelatedTopic[]; // カテゴリグループの場合
};

type DDGResponse = {
  Abstract?: string;
  AbstractURL?: string;
  AbstractSource?: string;
  RelatedTopics?: DDGRelatedTopic[];
};

// Google CSE で検索（失敗時は Error をスロー）
async function searchWithGoogle(query: string): Promise<Company[]> {
  const apiKey = process.env.GOOGLE_API_KEY;
  const cseId = process.env.GOOGLE_CSE_ID;

  if (!apiKey || !cseId) {
    throw new Error("GOOGLE_API_KEY_MISSING");
  }

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

    // フォールバック対象エラー（API未有効・403）
    if (
      apiStatus === 403 ||
      apiMessage.includes("does not have the access to Custom Search JSON API")
    ) {
      throw new Error("GOOGLE_FALLBACK");
    }
    if (apiStatus === 429 || apiMessage.toLowerCase().includes("quota")) {
      throw new Error("GOOGLE_FALLBACK");
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

// DuckDuckGo Instant Answer API で検索（APIキー不要・完全無料）
async function searchWithDuckDuckGo(query: string): Promise<Company[]> {
  const url = new URL("https://api.duckduckgo.com/");
  url.searchParams.set("q", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("no_html", "1");
  url.searchParams.set("skip_disambig", "1");
  url.searchParams.set("no_redirect", "1");

  const res = await fetch(url.toString(), {
    headers: {
      "Accept-Language": "ja",
      "User-Agent": "Mozilla/5.0 (compatible; agent-bot/1.0)",
    },
    redirect: "follow",
  });
  if (!res.ok) {
    throw new Error(`DuckDuckGo APIエラー (HTTP ${res.status})`);
  }

  const text = await res.text();
  if (!text || text.trim() === "") return [];

  let data: DDGResponse;
  try {
    data = JSON.parse(text) as DDGResponse;
  } catch {
    return [];
  }
  const results: Company[] = [];

  // Abstract（要約）があれば先頭に追加
  if (data.Abstract && data.AbstractURL) {
    results.push({
      title: data.AbstractSource ?? query,
      link: data.AbstractURL,
      snippet: data.Abstract,
    });
  }

  // RelatedTopics を展開（ネストしたカテゴリも含む）
  const topics: DDGRelatedTopic[] = [];
  for (const t of data.RelatedTopics ?? []) {
    if (t.Topics) {
      topics.push(...t.Topics);
    } else {
      topics.push(t);
    }
  }

  for (const topic of topics) {
    if (topic.FirstURL && topic.Text) {
      results.push({
        title: topic.Text.split(" - ")[0] ?? topic.Text,
        link: topic.FirstURL,
        snippet: topic.Text,
      });
    }
    if (results.length >= 10) break;
  }

  return results;
}

export type SearchSource = "google" | "duckduckgo";

// Google を試み、フォールバック条件のエラーなら DuckDuckGo へ切り替え
export async function searchCompanies(
  params: SearchParams
): Promise<{ results: Company[]; source: SearchSource }> {
  const query = buildQuery(params);
  if (!query) throw new Error("検索キーワードを入力してください");

  const hasGoogleConfig =
    !!process.env.GOOGLE_API_KEY && !!process.env.GOOGLE_CSE_ID;

  if (hasGoogleConfig) {
    try {
      const results = await searchWithGoogle(query);
      return { results, source: "google" };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      // フォールバック対象以外のエラーはそのままスロー
      if (msg !== "GOOGLE_FALLBACK") throw err;
    }
  }

  // DuckDuckGo フォールバック
  const results = await searchWithDuckDuckGo(query);
  return { results, source: "duckduckgo" };
}
