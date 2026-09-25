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
export type Me = User & { human_verified_actions: string[] };
export type Agent = {
  id: string; creator_id: string; name: string; label: string; description: string; category: string; rules: string;
  fee_bps: number; payout_address: string; ens_name: string | null; ens_tx_hash: string | null; parent_ens_name: string | null; owner_mode: "platform" | "creator"; ens_subregistry: string | null; status: string;
  rating_avg: number; rating_count: number; completed_count: number; ens_error: string | null; created_at: string; creator: User;
};
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
  summary_json: { issues?: string[]; client_position?: string; agent_position?: string; facts_to_check?: string[]; ai_note?: string; error?: string } | null;
  case: Case; votes: JuryVote[];
};
export type AppConfig = {
  chain_id: number; escrow_address: string; usdc_address: string; ens_parent_name: string; ens_universal_resolver: string;
  world_app_id: string; world_rp_id: string; mock: { chain: boolean; ens_write: boolean; world: boolean; gemini: boolean };
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
