"use client";

import { useState } from "react";
import SearchForm from "@/components/SearchForm";
import ResultList from "@/components/ResultList";

export type SearchParams = {
  keyword: string;
  industry: string;
  region: string;
};

export type SearchResult = {
  title: string;
  link: string;
  snippet: string;
};

export default function HomePage() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = async (params: SearchParams) => {
    setLoading(true);
    setError(null);
    setSearched(true);

    try {
      const query = new URLSearchParams({
        keyword: params.keyword,
        industry: params.industry,
        region: params.region,
      });
      const res = await fetch(`/api/search?${query.toString()}`);
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "検索に失敗しました");
      }
      const data = await res.json();
      setResults(data.results);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "不明なエラーが発生しました");
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main style={{ maxWidth: 800, margin: "0 auto", padding: "32px 16px" }}>
      <h1 style={{ fontSize: 28, fontWeight: "bold", marginBottom: 8, color: "#1a1a2e" }}>
        企業検索
      </h1>
      <p style={{ color: "#555", marginBottom: 24 }}>
        キーワード・業種・地域から企業を検索できます。
      </p>

      <SearchForm onSearch={handleSearch} loading={loading} />

      {error && (
        <div
          style={{
            marginTop: 24,
            padding: "12px 16px",
            backgroundColor: "#fff0f0",
            border: "1px solid #ffcccc",
            borderRadius: 8,
            color: "#cc0000",
          }}
        >
          {error}
        </div>
      )}

      {!loading && searched && !error && (
        <ResultList results={results} />
      )}

      {loading && (
        <p style={{ marginTop: 24, color: "#888", textAlign: "center" }}>検索中...</p>
      )}
    </main>
  );
}
