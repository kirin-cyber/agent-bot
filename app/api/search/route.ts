import { NextRequest, NextResponse } from "next/server";
import { searchCompanies } from "@/lib/search";
import type { SearchParams } from "@/types";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const params: SearchParams = {
    keyword: searchParams.get("keyword") ?? "",
    industry: searchParams.get("industry") ?? "",
    region: searchParams.get("region") ?? "",
  };

  try {
    const { results, source } = await searchCompanies(params);
    return NextResponse.json({ results, source });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "不明なエラーが発生しました";
    const status = message.includes("APIキーが設定されていません") ? 500 : 400;
    return NextResponse.json({ error: message }, { status });
  }
}
