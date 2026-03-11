import type { Company } from "@/types";

type Props = {
  results: Company[];
};

export default function ResultList({ results }: Props) {
  if (results.length === 0) {
    return (
      <div
        style={{
          marginTop: 24,
          padding: 24,
          backgroundColor: "#fff",
          borderRadius: 10,
          textAlign: "center",
          color: "#888",
          boxShadow: "0 1px 4px rgba(0,0,0,0.1)",
        }}
      >
        検索結果が見つかりませんでした。
      </div>
    );
  }

  return (
    <div style={{ marginTop: 24 }}>
      <p style={{ fontSize: 13, color: "#666", marginBottom: 12 }}>
        {results.length}件の結果
      </p>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 12 }}>
        {results.map((item, index) => (
          <li
            key={index}
            style={{
              backgroundColor: "#fff",
              borderRadius: 10,
              padding: "16px 20px",
              boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
              borderLeft: "4px solid #1a1a2e",
            }}
          >
            <a
              href={item.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 17,
                fontWeight: "bold",
                color: "#1a1a2e",
                textDecoration: "none",
              }}
            >
              {item.title}
            </a>
            <p
              style={{
                fontSize: 12,
                color: "#4a90d9",
                margin: "4px 0 8px",
                wordBreak: "break-all",
              }}
            >
              {item.link}
            </p>
            <p style={{ fontSize: 14, color: "#555", margin: 0, lineHeight: 1.6 }}>
              {item.snippet}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
