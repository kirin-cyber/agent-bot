"use client";

import { useState } from "react";
import type { SearchParams } from "@/app/page";

type Props = {
  onSearch: (params: SearchParams) => void;
  loading: boolean;
};

const INDUSTRIES = [
  "",
  "IT・ソフトウェア",
  "製造業",
  "小売業",
  "金融・保険",
  "不動産",
  "医療・福祉",
  "教育",
  "物流・運輸",
  "建設",
  "飲食・サービス",
  "その他",
];

const REGIONS = [
  "",
  "北海道",
  "東北",
  "関東",
  "中部",
  "近畿",
  "中国",
  "四国",
  "九州・沖縄",
];

export default function SearchForm({ onSearch, loading }: Props) {
  const [keyword, setKeyword] = useState("");
  const [industry, setIndustry] = useState("");
  const [region, setRegion] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch({ keyword, industry, region });
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    fontSize: 15,
    border: "1px solid #ccc",
    borderRadius: 6,
    boxSizing: "border-box",
    outline: "none",
  };

  const labelStyle: React.CSSProperties = {
    display: "block",
    marginBottom: 4,
    fontSize: 13,
    fontWeight: "bold",
    color: "#333",
  };

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        backgroundColor: "#fff",
        borderRadius: 10,
        padding: 24,
        boxShadow: "0 1px 4px rgba(0,0,0,0.1)",
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>キーワード</label>
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="例: 株式会社、ECサイト、DX推進"
          style={inputStyle}
        />
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>業種</label>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            style={{ ...inputStyle, backgroundColor: "#fff" }}
          >
            {INDUSTRIES.map((ind) => (
              <option key={ind} value={ind}>
                {ind || "すべての業種"}
              </option>
            ))}
          </select>
        </div>

        <div style={{ flex: 1 }}>
          <label style={labelStyle}>地域</label>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            style={{ ...inputStyle, backgroundColor: "#fff" }}
          >
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r || "すべての地域"}
              </option>
            ))}
          </select>
        </div>
      </div>

      <button
        type="submit"
        disabled={loading || (!keyword && !industry && !region)}
        style={{
          width: "100%",
          padding: "12px 0",
          fontSize: 16,
          fontWeight: "bold",
          backgroundColor: loading || (!keyword && !industry && !region) ? "#aaa" : "#1a1a2e",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          cursor: loading || (!keyword && !industry && !region) ? "not-allowed" : "pointer",
          transition: "background-color 0.2s",
        }}
      >
        {loading ? "検索中..." : "検索する"}
      </button>
    </form>
  );
}
