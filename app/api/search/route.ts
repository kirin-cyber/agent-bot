import { NextRequest, NextResponse } from "next/server";

const GOOGLE_API_KEY = process.env.GOOGLE_API_KEY;
const GOOGLE_CSE_ID = process.env.GOOGLE_CSE_ID;

export async function GET(request: NextRequest) {
  if (!GOOGLE_API_KEY || !GOOGLE_CSE_ID) {
    return NextResponse.json(
      { error: "サーバー設定エラー: APIキーが設定されていません" },
      { status: 500 }
    );
  }

  const { searchParams } = new URL(request.url);
  const keyword = searchParams.get("keyword") || "";
  const industry = searchParams.get("industry") || "";
  const region = searchParams.get("region") || "";

  const queryParts = [keyword, industry, region].filter(Boolean);
  if (queryParts.length === 0) {
    return NextResponse.json(
      { error: "検索キーワードを入力してください" },
      { status: 400 }
    );
  }

  const query = queryParts.join(" ");

  const url = new URL("https://www.googleapis.com/customsearch/v1");
  url.searchParams.set("key", GOOGLE_API_KEY);
  url.searchParams.set("cx", GOOGLE_CSE_ID);
  url.searchParams.set("q", query);
  url.searchParams.set("num", "10");

  const res = await fetch(url.toString());
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    const message = errorData?.error?.message || "Google検索APIでエラーが発生しました";
    return NextResponse.json({ error: message }, { status: res.status });
  }

  const data = await res.json();

  type GoogleSearchItem = {
    title?: string;
    link?: string;
    snippet?: string;
  };

  const results = (data.items || []).map((item: GoogleSearchItem) => ({
    title: item.title || "",
    link: item.link || "",
    snippet: item.snippet || "",
  }));

  return NextResponse.json({ results });
}
