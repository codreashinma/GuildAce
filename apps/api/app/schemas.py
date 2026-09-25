from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = ["web", "design", "video", "wedding", "other"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: str
    wallet_address: str
    display_name: str | None = None


class MeOut(UserOut):
    human_verified_actions: list[str] = []


class AuthVerifyIn(BaseModel):
    message: str
    signature: str


class AgentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    label: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    description: str = ""
    category: Literal["web", "design", "video", "wedding", "other"] = "web"
    rules: str = ""
    fee_bps: int = Field(default=200, ge=0, le=5000)
    payout_address: str | None = None
    avatar: str | None = None


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
    status: str
    rating_avg: float
    rating_count: int
    completed_count: int
    ens_error: str | None = None
    created_at: datetime
    creator: UserOut


class AgentDetailOut(AgentOut):
    ens_records: dict[str, str] = {}


class CaseCreateIn(BaseModel):
    agent_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    budget_usdc: int = Field(gt=0, le=10_000_000, description="USDC 単位（整数）")
    deadline: str | None = None


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


class CaseOut(ORM):
    id: str
    title: str
    description: str
    budget: int
    deadline: str | None
    status: str
    plan_json: dict[str, Any] | None
    escrow_case_id: str
    deposit_tx_hash: str | None
    release_tx_hash: str | None
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
    split: list[SplitItem] = []
    dispute_id: str | None = None


class TxIn(BaseModel):
    tx_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")


class WorldProofIn(BaseModel):
    idkit_response: dict[str, Any] | None = None


class HumanTaskAcceptIn(WorldProofIn):
    pass


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


class ConfigOut(BaseModel):
    chain_id: int
    escrow_address: str
    usdc_address: str
    ens_parent_name: str
    ens_universal_resolver: str
    world_app_id: str
    world_rp_id: str
    mock: dict[str, bool]
