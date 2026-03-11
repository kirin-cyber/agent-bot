import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "企業検索 | Agent Bot",
  description: "キーワード・業種・地域から企業を検索するツール",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body style={{ margin: 0, fontFamily: "sans-serif", backgroundColor: "#f5f5f5" }}>
        {children}
      </body>
    </html>
  );
}
