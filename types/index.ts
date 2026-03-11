// フェーズ1: 企業検索の基本型
export type SearchParams = {
  keyword: string;
  industry: string;
  region: string;
};

export type Company = {
  title: string;
  link: string;
  snippet: string;
};

// フェーズ2以降: AI分析・営業リスト用に拡張予定
// export type CompanyAnalysis = {
//   company: Company;
//   score: number;          // AIによる営業優先度スコア
//   summary: string;        // AI生成の企業サマリー
//   contactInfo?: string;   // 抽出された連絡先
// };
//
// export type SalesLead = {
//   company: Company;
//   status: "new" | "contacted" | "in_progress" | "closed";
//   addedAt: string;
//   notes?: string;
// };
