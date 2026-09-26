export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function token(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem("choice.token");
  } catch {
    return null;
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, body, cache: "no-store" });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- types (API の schemas.py に対応) ----
export type User = { id: string; wallet_address: string; display_name: string | null };
export type Me = User & { human_verified_actions: string[]; is_ops?: boolean };
export type Agent = {
  id: string; creator_id: string; name: string; label: string; description: string; category: string; rules: string;
  fee_bps: number; payout_address: string; ens_name: string | null; ens_tx_hash: string | null; parent_ens_name: string | null; owner_mode: "platform" | "creator"; ens_subregistry: string | null; status: string;
  rating_avg: number; rating_count: number; completed_count: number; ens_error: string | null; subagents: Subagent[]; created_at: string; creator: User;
  policy: Policy | null; effective_policy: Policy; // policy = 保存された値（無ければ null）、effective_policy = 無ければ既定（WP-009）
};
/** PM Agent の進め方（codrea.agent.policy のスキーマ。GRD-006: 変えられるのは工程と人間の使い方だけ） */
export type HumanRole = { role: "approver" | "reviewer" | "juror"; world_verified: boolean; min_count: number };
export type Policy = { version: 1; domain: string; workflow: { phases: { key: string; title: string }[] }; human_roles: HumanRole[] };
export type Subagent = { role: string; name: string; description: string; rules: string };
/** 既定の専門エージェント（API の DEFAULT_SUBAGENTS と同じ）。所有者が追加・削除・編集できる */
export const DEFAULT_SUBAGENTS: Subagent[] = [
  { role: "designer", name: "Designer Agent", description: "画面構成・ワイヤーフレーム・デザイン方針", rules: "" },
  { role: "frontend", name: "Frontend Agent", description: "画面の実装方針とコンポーネント設計", rules: "" },
  { role: "backend", name: "Backend Agent", description: "API 設計とデータモデル", rules: "" },
  { role: "qa", name: "QA Agent", description: "受け入れテストの観点と結果", rules: "" },
];
export type EnsRole = { role: string; account?: string | null; where?: string; can?: string; cannot?: string; subregistry?: string | null; verified?: boolean; checks?: Record<string, boolean | null>; error?: string };
export type TeamCandidate = { ens_name: string; kind: "ai" | "human"; name: string; role: string; skills: string; location: string; available: boolean; company: string | null; chosen: boolean; declined: boolean; records: Record<string, string> };
export type TeamTask = { task_id: string; title: string; kind: "ai" | "human"; role: string; amount: number; assignee_ens: string | null; assignee_name: string | null; assignee_records: Record<string, string>; assignment_reason: string | null; candidates: TeamCandidate[] };
export type AgentDetail = Agent & { ens_records: Record<string, string>; ens_reputation_name: string | null; ens_reputation_records: Record<string, string>; ens_subagents: Record<string, Record<string, string>>; ens_roles: EnsRole[] };
export type MemberBrief = { id: string; name: string; ens_name: string; role: string; skills: string; location: string; wallet_address: string };
export type Member = MemberBrief & { company_id: string; label: string; available: boolean; ens_status: string; ens_tx_hash: string | null; rating_avg: number; completed_count: number };
export type Company = { id: string; name: string; ens_name: string; description: string; ens_verified: boolean; admin: User; members: Member[] };
export type HumanTask = {
  id: string; task_id: string; case_id: string; title: string; description: string; reward: number; status: string;
  worker: User | null; submission: string | null; ai_check: string | null; assignee: MemberBrief | null; assignment_reason: string | null; created_at: string;
};
export type Approval = { id: string; deliverable_hash: string; created_at: string; approver: User };
export type ChainStatus = "none" | "funded" | "submitted" | "paid" | "disputed" | "resolved";
export type Task = {
  id: string; order_no: number; title: string; description: string; type: "ai" | "human"; role: string; estimated_cost: number;
  status: string; assignee_name: string | null; deliverable: string | null; completed_at: string | null; human_task: HumanTask | null;
  escrow_task_id: string | null; chain_status: ChainStatus; deliverable_hash: string | null; payee: string | null; approval_count: number; chain_tx_hash: string | null; approvals: Approval[];
};
export type Case = {
  id: string; title: string; description: string; budget: number; deadline: string | null; status: string;
  plan_json: { summary?: string; team?: { name: string; role: string; kind: string }[] } | null;
  escrow_case_id: string; approvers: string[]; threshold: number; open_tx_hash: string | null; project_ens_name: string | null; project_ens_tx_hash: string | null;
  error: string | null; created_at: string; client: User; agent: Agent; tasks: Task[];
};
export type CaseDetail = Case & { dispute_id: string | null };
export type PendingApproval = { case_id: string; case_title: string; task_id: string; task_title: string; task_type: string; amount: number; approval_count: number; threshold: number; payee: string | null; deliverable_hash: string | null };
export type Notice = { id: string; kind: "approve" | "assigned" | "deliver" | "pay" | "dispute" | "info"; title: string; body: string; href: string; urgent: boolean };
export type TypedData = { types: Record<string, { name: string; type: string }[]>; primaryType: string; domain: Record<string, unknown>; message: Record<string, string> };
export type Review = { id: string; case_id: string; rating: number; comment: string; target_type: string; target_id: string; created_at: string; reviewer: User };
export type JuryVote = { id: string; vote: "release" | "refund"; created_at: string; voter: User };
export type Dispute = {
  id: string; case_id: string; reason: string; status: string; outcome: string | null; resolve_tx_hash: string | null; required_votes: number; created_at: string;
  summary_json: DisputeSummary | null;
  case: Case; votes: JuryVote[];
};
/** AG-004 の争点（agent-definitions AG-004 の「出力」）。結論の項目は持たない */
export type DisputeIssue = { title: string; requester_position: string; provider_position: string; evidence_refs: string[] };
/** 論点サマリー。source = "agents" は AG-001 → AG-004 経由（WP-019）、無ければ旧 summarize_dispute の形。resolve_jobs は裁定で足される */
export type DisputeSummary =
  | { source: "agents"; version: number | null; issues: DisputeIssue[]; no_issues: boolean; no_issues_reason: string | null; ref_labels: Record<string, string>; resolve_jobs?: string[] }
  | { source?: undefined; issues?: string[]; client_position?: string; agent_position?: string; facts_to_check?: string[]; ai_note?: string; error?: string; resolve_jobs?: string[] };
export type AuditActor = { address: string; name: string | null; source: string | null; verified: boolean; roles: string[] };
export type AuditEvent = {
  seq: number; kind: string; label: string; task_id: string | null; task_title: string | null; actor: string | null; actor_role: string;
  tx_hash: string | null; mock: boolean; status: string; at: string | null; detail: Record<string, unknown>;
};
export type CaseAudit = {
  case_id: string; title: string; status: string; escrow_case_id: string; approvers: string[]; threshold: number; project_ens_name: string | null; agent_ens_name: string | null;
  events: AuditEvent[]; actors: Record<string, AuditActor>; counts: { events: number; onchain: number; mock: number; failed: number; named_actors: number };
};
export type MeSummary = {
  user: { id: string; wallet_address: string; display_name: string | null; created_at: string };
  primary_ens: MeEnsName | null; ens_names: MeEnsName[];
  world_actions: { action: string; label: string; count: number; last_at: string | null }[];
  companies: { id: string; name: string; ens_name: string; ens_verified: boolean; relation: "admin" | "member"; member_name: string | null; member_ens: string | null; available: boolean | null }[];
  agents: { id: string; name: string; status: string; ens_name: string | null; owner_mode: string; rating_avg: number; rating_count: number; completed_count: number }[];
  cases: { as_client: number; as_approver: number; as_worker: number; as_jury: number };
  earnings: { case_id: string; case_title: string; task_id: string; task_title: string; role: "pm" | "human" | "ai"; amount: string; chain_status: string; tx_hash: string | null; at: string | null }[];
  earnings_total: string; reviews_received: { count: number; avg: number | null };
};
export type MeEnsName = { name: string; kind: "person" | "agent-payout" | "company-admin"; verified: boolean; tx_hash: string | null; link: string; note: string | null };
export type EarningRow = { case_id: string; case_title: string; case_status: string; task_id: string; task_title: string; amount: string; received: string; chain_status: ChainStatus; payee: string | null; tx_hash: string | null; at: string | null; budget: string };
export type AgentEarnings = { agent_id: string; agent_name: string; payout_address: string; fee_bps: number; paid_total: string; pending_total: string; resolved_total: string; cases: number; rows: EarningRow[] };
export type ChainJobStatus = "queued" | "running" | "retry" | "done" | "failed";
export type ChainJob = {
  id: string; kind: string; label: string; idempotency_key: string; status: ChainJobStatus; attempts: number; max_attempts: number; tx_hash: string | null; error: string | null;
  next_attempt_at: string | null; finished_at: string | null; created_at: string; updated_at: string;
  case_id: string | null; case_title: string | null; task_id: string | null; task_title: string | null; agent_id: string | null; agent_name: string | null; amount: string | null; href: string | null; retryable: boolean;
};
export type OpsJobs = { counts: Record<ChainJobStatus, number>; kinds: string[]; worker_alive: boolean; jobs: ChainJob[] };
export type AppConfig = {
  chain_id: number; escrow_address: string; usdc_address: string; ens_parent_name: string; ens_universal_resolver: string;
  world_app_id: string; world_rp_id: string;
  ens_roles: { owner: string | null; reputation: string | null; project: string | null; separated: boolean; reputation_resolver: string | null; project_resolver: string | null };
  mock: { chain: boolean; ens_write: boolean; ens_roles: boolean; world: boolean; gemini: boolean };
};
export type RpContext = { rp_id: string; nonce: string; created_at: number; expires_at: number; signature: string };

export const USDC = 1_000_000;
export const usdc = (n: number | string) => (Number(n) / USDC).toLocaleString("en-US", { maximumFractionDigits: 2 });
export const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;
export const etherscanTx = (h: string) => (h.startsWith("0xmock") ? null : `https://sepolia.etherscan.io/tx/${h}`);
export const CATEGORY_LABEL: Record<string, string> = { web: "Web開発", design: "デザイン", video: "動画制作", wedding: "Wedding", other: "その他" };
export const STATUS_LABEL: Record<string, string> = {
  "chain:none": "未預託", "chain:funded": "預託済", "chain:submitted": "提出済（承認待ち）", "chain:paid": "支払済", "chain:disputed": "保留（紛争）", "chain:resolved": "裁定済",
  draft: "下書き", planning: "計画中", planning_failed: "計画失敗", awaiting_approval: "承認待ち", funded: "入金済み", in_progress: "進行中",
  delivered: "納品済み（検収待ち）", completed: "完了", disputed: "紛争中", resolved: "仲裁で解決",
  publishing: "ENS に公開中", published: "公開中", publish_failed: "公開失敗",
  assigned: "指名中", open: "募集中", accepted: "受注済み", submitted: "提出済み", done: "完了", todo: "未着手",
};
