/**
 * UI 専用のモックデータ（FR-004 候補検索 / FR-006 契約 / FR-027 subname / FR-028 権限 / FR-032 通知 など）。
 * バックエンド未実装の要件を画面で表現するためのもので、API とは独立している。
 */
import type { Case, Task } from "./api";

export type Candidate = { ens: string; kind: "company" | "ai" | "human"; role: string; rating: number; reviews: number; completed: number; price: number; note: string };

const POOL: Record<string, Candidate[]> = {
  designer: [
    { ens: "alice.eth", kind: "human", role: "designer", rating: 4.8, reviews: 52, completed: 61, price: 50, note: "UI/UX・LP。Figma 納品" },
    { ens: "studio-mint.eth", kind: "company", role: "designer", rating: 4.6, reviews: 21, completed: 30, price: 80, note: "ブランド設計が得意" },
    { ens: "designer.web-pm.choice.eth", kind: "ai", role: "designer", rating: 4.5, reviews: 18, completed: 140, price: 20, note: "PM Agent 配下の専門 Agent" },
  ],
  frontend: [
    { ens: "bob.eth", kind: "human", role: "frontend", rating: 4.7, reviews: 40, completed: 48, price: 80, note: "Next.js / React" },
    { ens: "frontend.web-pm.choice.eth", kind: "ai", role: "frontend", rating: 4.4, reviews: 12, completed: 210, price: 30, note: "PM Agent 配下の専門 Agent" },
  ],
  backend: [
    { ens: "dev.xyz.eth", kind: "company", role: "backend", rating: 4.9, reviews: 77, completed: 90, price: 80, note: "API / インフラ" },
    { ens: "backend.web-pm.choice.eth", kind: "ai", role: "backend", rating: 4.3, reviews: 9, completed: 180, price: 30, note: "PM Agent 配下の専門 Agent" },
  ],
  qa: [
    { ens: "qa.web-pm.choice.eth", kind: "ai", role: "qa", rating: 4.6, reviews: 15, completed: 300, price: 30, note: "テスト観点の自動生成" },
    { ens: "carol.eth", kind: "human", role: "qa", rating: 4.5, reviews: 10, completed: 12, price: 40, note: "受け入れテスト" },
  ],
  field: [
    { ens: "dan.eth", kind: "human", role: "field", rating: 4.9, reviews: 33, completed: 35, price: 10, note: "現地撮影（都内）" },
    { ens: "human-task.choice.eth", kind: "human", role: "field", rating: 4.7, reviews: 120, completed: 400, price: 10, note: "World 認証済みの人間に公開発注" },
  ],
  pm: [],
};

/** FR-004: ENS を参照した候補検索（モック）。タスクの role ごとに候補を返す */
export function candidatesFor(role: string): Candidate[] {
  return POOL[role] ?? POOL.frontend;
}

/** FR-005: 編成されたメンバーの ENS 名（タスクの種別・役割から決める） */
export function memberEnsFor(task: Task, agentLabel: string): string {
  if (task.type === "human") return "human-task.choice.eth";
  return `${task.role}.${agentLabel}.choice.eth`;
}

/** FR-027: プロジェクトごとの subname */
export function projectSubname(c: Case): string {
  const n = parseInt(c.id.replace(/-/g, "").slice(0, 6), 16) % 1000;
  return `project-${n}.${c.agent.label}.choice.eth`;  // API と同じ導出（openCase 後に実発行）
}

/** FR-028: ENSv2 EAC の権限（モック） */
export const PERMISSIONS = [
  { role: "Creator", ens: (agent: string, creator: string) => creator, can: "すべての操作（subname 発行・レコード更新・権限付与）" },
  { role: "PM Agent", ens: (agent: string) => agent, can: "agent.endpoint / agent.status の更新" },
  { role: "Reputation", ens: () => "reputation.choice.eth", can: "agent.rating / agent.reviews の更新のみ" },
  { role: "Project Agent", ens: (agent: string) => `project-*.${agent}`, can: "project subname の作成のみ" },
];

/** FR-006: タスク別契約（モック）。API の task から契約条件を組み立てる */
export function contractFor(task: Task) {
  const status = task.status === "done" ? "納品済み" : task.status === "in_progress" ? "履行中" : "締結済み";
  return {
    id: `CT-${task.order_no + 1}`,
    status,
    terms: [`成果物: ${task.title}`, `完成条件: ${task.description || "PM Agent が定義"}`, `報酬: ${(Number(task.estimated_cost) / 1_000_000).toLocaleString()} USDC（検収承認後に Escrow から支払い）`, "期限のみでは資金は動かない"],
  };
}

/** FR-034: 検収タイムアウト（仮: 7 日）までの残り */
export function reviewDeadline(c: Case): { days: number; label: string } {
  const start = new Date(c.created_at).getTime();
  const due = start + 7 * 24 * 3600 * 1000;
  const days = Math.max(0, Math.ceil((due - Date.now()) / (24 * 3600 * 1000)));
  return { days, label: new Date(due).toLocaleDateString("ja-JP") };
}
