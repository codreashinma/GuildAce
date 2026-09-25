/**
 * UI 側の補助（契約条件の文言、project subname の予測、検収期限の仮計算）。
 * 候補・権限・通知は API の実データに移行済み。
 */
import type { Case, Task } from "./api";

/** FR-027: プロジェクトごとの subname */
export function projectSubname(c: Case): string {
  const n = parseInt(c.id.replace(/-/g, "").slice(0, 6), 16) % 1000;
  return `project-${n}.${c.agent.label}.choice.eth`;  // API と同じ導出（openCase 後に実発行）
}

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
