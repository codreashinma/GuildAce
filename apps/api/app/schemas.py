from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from .agents import policy as agent_policy
from .agents.policy import Policy

CATEGORIES = ["web", "design", "video", "wedding", "other"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: str
    wallet_address: str
    display_name: str | None = None


class MeOut(UserOut):
    role: str | None = None  # 最後のログインで選んだ利用者種別
    human_verified_actions: list[str] = []
    is_ops: bool = False  # 運用者（OPS_ADDRESSES）。/ops/* と運用画面を使える


class AuthVerifyIn(BaseModel):
    message: str
    signature: str
    role: str | None = None  # ウォレット接続の前に選んだ利用者種別（auth.USER_ROLES のキー）


RESERVED_SUBAGENT_ROLES = {"pm", "field", "human", "worker", "reputation", "project", "www", "eth"}


class SubagentIn(BaseModel):
    """専門 AI エージェント 1 件。role は ENS の subname（<role>.<agent>）になる"""
    role: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    rules: str = Field(default="", max_length=4000)

    @field_validator("role")
    @classmethod
    def _v_role(cls, v):
        if v in RESERVED_SUBAGENT_ROLES or v.startswith("project-"):
            raise ValueError(f"Role '{v}' is reserved and cannot be used")
        return v


def _clean_subagents(v):
    if v is None:
        return None
    if not isinstance(v, list):
        raise ValueError("subagents must be an array of [{role, name, description, rules}]")
    if len(v) > 12:
        raise ValueError("Up to 12 specialist agents are allowed")
    seen = set()
    for x in v:
        r = (x.get("role") if isinstance(x, dict) else getattr(x, "role", None)) or ""
        if r in seen:
            raise ValueError(f"Role '{r}' is duplicated")
        seen.add(r)
    return v


class AgentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    label: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    description: str = ""
    category: Literal["web", "design", "video", "wedding", "other"] = "web"
    rules: str = ""
    fee_bps: int = Field(default=200, ge=0, le=5000)
    payout_address: str | None = None
    avatar: str | None = None
    parent_ens_name: str | None = Field(default=None, pattern=r"^[a-z0-9-]+\.eth$", description="A .eth name owned by the Creator. If empty, the platform parent name is used")
    subagents: list[SubagentIn] | None = Field(default=None, description="List of specialist AI agents. If omitted, the 4 defaults are used (designer / frontend / backend / qa)")
    policy: Policy | None = None  # GRD-006: スキーマ外のキーは捨てる。None = 既定の policy

    @field_validator("subagents", mode="before")
    @classmethod
    def _v_sub(cls, v):
        return _clean_subagents(v)


class AgentUpdateIn(BaseModel):
    """D4: Agent の編集。ラベル（subname）と公開先は変えられない。変更分だけ ENS の text record を再書き込みする"""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    category: Literal["web", "design", "video", "wedding", "other"] | None = None
    rules: str | None = None
    fee_bps: int | None = Field(default=None, ge=0, le=5000)
    avatar: str | None = None
    subagents: list[SubagentIn] | None = None  # 渡した一覧で丸ごと置き換える（[] で全消し）
    policy: Policy | None = None  # GRD-006。ENS には書かない（DEC-002）

    @field_validator("subagents", mode="before")
    @classmethod
    def _v_sub(cls, v):
        return _clean_subagents(v)


class AgentOut(ORM):
    id: str
    creator_id: str
    name: str
    label: str
    description: str
    category: str
    rules: str
    fee_bps: int
    payout_address: str
    ens_name: str | None
    ens_tx_hash: str | None
    parent_ens_name: str | None = None
    owner_mode: str = "platform"
    ens_subregistry: str | None = None
    status: str
    rating_avg: float
    rating_count: int
    completed_count: int
    ens_error: str | None = None
    subagents: list[dict[str, str]] = []  # None（未設定）は既定の 4 つに展開して返す
    created_at: datetime
    creator: UserOut
    policy: dict | None = None  # 保存された policy（無ければ None）

    @computed_field
    @property
    def effective_policy(self) -> dict:
        """実際に使う policy（保存された値、無ければ既定。DEC-002）"""
        return agent_policy.effective(self.policy, self.category)

    @field_validator("subagents", mode="before")
    @classmethod
    def _default_subagents(cls, v):
        if v is None:
            from .services.ens import DEFAULT_SUBAGENTS

            return [dict(x) for x in DEFAULT_SUBAGENTS]
        return v


class EarningRowOut(BaseModel):
    case_id: str
    case_title: str
    case_status: str
    task_id: str
    task_title: str
    amount: str  # PM 管理費（最小単位）
    received: str  # 実際に受け取った額。paid = amount、resolved = 裁定の pay_amount（返金なら 0）、預託中 = 0
    chain_status: str  # funded | submitted | paid | disputed | resolved
    payee: str | None
    tx_hash: str | None
    at: datetime | None
    budget: str


class AgentEarningsOut(BaseModel):
    """D3 / API-18: Creator の収益（PM 工程の Escrow 投影の集計）"""
    agent_id: str
    agent_name: str
    payout_address: str
    fee_bps: int
    paid_total: str  # paid の受取合計
    pending_total: str  # 預託中（未払い）の工程額合計
    resolved_total: str  # 裁定で受け取った額の合計（返金分は含まない）
    cases: int
    rows: list[EarningRowOut]


class AgentDetailOut(AgentOut):
    ens_records: dict[str, str] = {}
    ens_reputation_name: str | None = None  # reputation.<agent>（評価 record の置き場）
    ens_reputation_records: dict[str, str] = {}
    ens_subagents: dict[str, dict[str, str]] = {}  # designer.<agent> などの record
    ens_roles: list[dict[str, Any]] = []  # EAC の役割（オンチェーンから読んだ実データ）


class CaseCreateIn(BaseModel):
    agent_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    budget_usdc: int = Field(gt=0, le=10_000_000, description="In USDC (integer)")
    deadline: str | None = None
    approvers: list[str] = Field(default_factory=list, description="Approver addresses (if empty, the Client)")
    threshold: int = Field(default=1, ge=1, le=10)
    idkit_response: dict[str, Any] | None = None  # FR-002 依頼開始時の World 検証
    world_signal: str | None = Field(default=None, max_length=120, description="Signal for World verification (the API assigns Case IDs, so only Request start uses an ID issued by the client)")




class CompanyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ens_name: str = Field(pattern=r"^[a-z0-9-]+\.eth$")
    description: str = ""


class MemberCreateIn(BaseModel):
    label: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    name: str = Field(min_length=1, max_length=120)
    wallet_address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    role: str = ""
    skills: str = ""
    location: str = ""
    available: bool = True


class MemberUpdateIn(BaseModel):
    available: bool | None = None
    role: str | None = None
    skills: str | None = None
    location: str | None = None


class MemberOut(ORM):
    id: str
    company_id: str
    label: str
    name: str
    wallet_address: str
    ens_name: str
    role: str
    skills: str
    location: str
    available: bool
    ens_status: str
    ens_tx_hash: str | None
    rating_avg: float
    completed_count: int


class CompanyOut(ORM):
    id: str
    name: str
    ens_name: str
    description: str
    ens_verified: bool
    admin: UserOut
    members: list[MemberOut] = []


class MemberBrief(ORM):
    id: str
    name: str
    ens_name: str
    role: str
    skills: str
    location: str
    wallet_address: str


class ApprovalOut(ORM):
    id: str
    deliverable_hash: str
    created_at: datetime
    approver: UserOut


class HumanTaskOut(ORM):
    id: str
    task_id: str
    case_id: str
    title: str
    description: str
    reward: int
    status: str
    worker: UserOut | None
    submission: str | None
    ai_check: str | None
    assignee: MemberBrief | None = None
    assignment_reason: str | None = None
    created_at: datetime


class TaskOut(ORM):
    id: str
    order_no: int
    title: str
    description: str
    type: str
    role: str
    estimated_cost: int
    status: str
    assignee_name: str | None
    deliverable: str | None
    completed_at: datetime | None
    human_task: HumanTaskOut | None = None
    escrow_task_id: str | None = None
    chain_status: str = "none"
    deliverable_hash: str | None = None
    payee: str | None = None
    approval_count: int = 0
    chain_tx_hash: str | None = None
    approvals: list[ApprovalOut] = []


class CaseOut(ORM):
    id: str
    title: str
    description: str
    budget: int
    deadline: str | None
    status: str
    plan_json: dict[str, Any] | None
    escrow_case_id: str
    approvers: list[str] | None = []
    threshold: int = 1
    open_tx_hash: str | None
    project_ens_name: str | None
    project_ens_tx_hash: str | None
    error: str | None
    created_at: datetime
    client: UserOut
    agent: AgentOut
    tasks: list[TaskOut] = []


class SplitItem(BaseModel):
    address: str
    amount: str
    label: str


class CaseDetailOut(CaseOut):
    dispute_id: str | None = None
    typed_data: dict[str, Any] | None = None  # 承認用 EIP-712（承認者向け、タスクごとに API から取得）


class TxIn(BaseModel):
    """tx hash。モック（チェーン未設定）のときはフロントが `0xmock` + 58 hex を報告する"""
    tx_hash: str = Field(pattern=r"^0x([0-9a-fA-F]{64}|mock[0-9a-fA-F]{58})$")


class WorldProofIn(BaseModel):
    idkit_response: dict[str, Any] | None = None


class HumanTaskAcceptIn(WorldProofIn):
    pass


class CaseOpenedIn(TxIn):
    pass


class ApproveIn(WorldProofIn):
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]{130}$")


class HumanTaskSubmitIn(BaseModel):
    submission: str = Field(min_length=1)


class ReviewCreateIn(WorldProofIn):
    case_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class ReviewOut(ORM):
    id: str
    case_id: str
    rating: int
    comment: str
    target_type: str
    target_id: str
    created_at: datetime
    reviewer: UserOut


class DisputeCreateIn(BaseModel):
    reason: str = Field(min_length=1)


class JuryVoteIn(WorldProofIn):
    vote: Literal["release", "refund"]


class JuryVoteOut(ORM):
    id: str
    vote: str
    created_at: datetime
    voter: UserOut


class DisputeOut(ORM):
    id: str
    case_id: str
    reason: str
    summary_json: dict[str, Any] | None
    status: str
    outcome: str | None
    resolve_tx_hash: str | None
    required_votes: int
    created_at: datetime
    case: CaseOut
    votes: list[JuryVoteOut] = []


class PendingApprovalOut(BaseModel):
    case_id: str
    case_title: str
    task_id: str
    task_title: str
    task_type: str
    amount: int
    approval_count: int
    threshold: int
    payee: str | None
    deliverable_hash: str | None


class NoticeOut(BaseModel):
    id: str
    kind: str  # approve | assigned | deliver | pay | dispute | info
    title: str
    body: str
    href: str
    urgent: bool = False


class TeamCandidateOut(BaseModel):
    ens_name: str
    kind: str  # ai | human
    name: str
    role: str
    skills: str = ""
    location: str = ""
    available: bool = True
    company: str | None = None
    chosen: bool = False
    declined: bool = False
    records: dict[str, str] = {}


class TeamTaskOut(BaseModel):
    task_id: str
    title: str
    kind: str
    role: str
    amount: int
    assignee_ens: str | None
    assignee_name: str | None
    assignee_records: dict[str, str] = {}
    assignment_reason: str | None = None
    candidates: list[TeamCandidateOut] = []


class ConfigOut(BaseModel):
    chain_id: int
    escrow_address: str
    usdc_address: str
    ens_parent_name: str
    ens_universal_resolver: str
    world_app_id: str
    world_rp_id: str
    ens_roles: dict  # owner / reputation / project のアドレスと separated（役割鍵が揃っているか）
    mock: dict[str, bool]
