import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    wallet_address: Mapped[str] = mapped_column(String(42), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    world_session_id: Mapped[str | None] = mapped_column(String(160), unique=True)  # World ID 4.0 の session_id（初回の人間確認で保存。1 World ID = 1 アカウント）


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    # ENS 名は <label>.<親名> なので、一意性は (label, 親名) の組。親名 NULL（= プラットフォームの親名）は '' に寄せて比較する
    __table_args__ = (Index("uq_agents_label_parent", "label", func.coalesce(text("parent_ens_name"), ""), unique=True),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(63), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    rules: Mapped[str] = mapped_column(Text, default="")
    fee_bps: Mapped[int] = mapped_column(Integer, default=200)
    payout_address: Mapped[str] = mapped_column(String(42))
    ens_name: Mapped[str | None] = mapped_column(String(255), index=True)
    ens_tx_hash: Mapped[str | None] = mapped_column(String(66))
    parent_ens_name: Mapped[str | None] = mapped_column(String(255))  # None = プラットフォームの親名（choice.eth）
    ens_subregistry: Mapped[str | None] = mapped_column(String(42))  # Agent 配下（project subname）のサブレジストリ
    owner_mode: Mapped[str] = mapped_column(String(10), default="platform")  # platform | creator（Creator 自身の .eth の下。Creator が署名）
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 1), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    ens_error: Mapped[str | None] = mapped_column(Text)
    # 専門 AI エージェントの一覧 [{role, name, description, rules}]。所有者が追加・削除・編集。None は既定の 4 つ。rules は ENS に書かない
    subagents: Mapped[list | None] = mapped_column(JSON)
    policy: Mapped[dict | None] = mapped_column(JSON)  # PM Agent の進め方（WP-009 / GRD-006）。None = 既定の policy（DEC-002）

    creator: Mapped[User] = relationship()


class Case(TimestampMixin, Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[int] = mapped_column(Numeric(78, 0))  # USDC 最小単位 (6 decimals)
    deadline: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    plan_json: Mapped[dict | None] = mapped_column(JSON)
    escrow_case_id: Mapped[str] = mapped_column(String(66))
    approvers: Mapped[list | None] = mapped_column(JSON, default=list)  # 承認者アドレス（openCase で固定）
    threshold: Mapped[int] = mapped_column(Integer, default=1)
    open_tx_hash: Mapped[str | None] = mapped_column(String(66))  # 発注者が送った openCase
    project_ens_name: Mapped[str | None] = mapped_column(String(255))  # project-<n>.<agent>.choice.eth
    project_ens_tx_hash: Mapped[str | None] = mapped_column(String(66))
    request_nullifier: Mapped[str | None] = mapped_column(String(160))  # 依頼開始時の World 検証
    error: Mapped[str | None] = mapped_column(Text)

    client: Mapped[User] = relationship()
    agent: Mapped[Agent] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="case", order_by="Task.order_no")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    order_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(10))  # ai | human
    role: Mapped[str] = mapped_column(String(40))
    estimated_cost: Mapped[int] = mapped_column(Numeric(78, 0), default=0)
    status: Mapped[str] = mapped_column(String(20), default="todo", index=True)
    assignee_name: Mapped[str | None] = mapped_column(String(120))
    deliverable: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- オンチェーン（Escrow）の投影。正本はコントラクト（ADR-001）
    escrow_task_id: Mapped[str | None] = mapped_column(String(66))
    chain_status: Mapped[str] = mapped_column(String(20), default="none")  # none|funded|submitted|paid|disputed|resolved
    deliverable_hash: Mapped[str | None] = mapped_column(String(66))
    payee: Mapped[str | None] = mapped_column(String(42))
    approval_count: Mapped[int] = mapped_column(Integer, default=0)
    chain_tx_hash: Mapped[str | None] = mapped_column(String(66))

    case: Mapped[Case] = relationship(back_populates="tasks")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="task")
    human_task: Mapped["HumanTask | None"] = relationship(back_populates="task", uselist=False)


class Company(TimestampMixin, Base):
    """受注側の会社。独自の .eth を所有し、その下に人員の subname を発行する"""
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    admin_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ens_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ens_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    admin: Mapped[User] = relationship()
    members: Mapped[list["Member"]] = relationship(back_populates="company", order_by="Member.created_at")


class Member(TimestampMixin, Base):
    """会社の人員。ENS 名 = <label>.<company ens>。record は DB にキャッシュ"""
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("company_id", "label", name="uq_members_company_label"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    label: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(String(120))
    wallet_address: Mapped[str] = mapped_column(String(42), index=True)
    ens_name: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(60), default="")
    skills: Mapped[str] = mapped_column(Text, default="")  # カンマ区切り
    location: Mapped[str] = mapped_column(String(120), default="")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    ens_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | written
    ens_tx_hash: Mapped[str | None] = mapped_column(String(66))
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 1), default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)

    company: Mapped[Company] = relationship(back_populates="members")


class HumanTask(TimestampMixin, Base):
    __tablename__ = "human_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    reward: Mapped[int] = mapped_column(Numeric(78, 0), default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # assigned | open | accepted | submitted | done
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submission: Mapped[str | None] = mapped_column(Text)
    ai_check: Mapped[str | None] = mapped_column(Text)
    assignee_member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"))
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    declined_member_ids: Mapped[list | None] = mapped_column(JSON, default=list)

    task: Mapped[Task] = relationship(back_populates="human_task")
    case: Mapped[Case] = relationship()
    worker: Mapped[User | None] = relationship()
    assignee: Mapped[Member | None] = relationship()


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String(10))  # agent | user
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    nullifier: Mapped[str] = mapped_column(String(160))

    reviewer: Mapped[User] = relationship()
    case: Mapped[Case] = relationship()


class Dispute(TimestampMixin, Base):
    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    outcome: Mapped[str | None] = mapped_column(String(10))
    resolve_tx_hash: Mapped[str | None] = mapped_column(String(66))
    required_votes: Mapped[int] = mapped_column(Integer, default=3)

    case: Mapped[Case] = relationship()
    votes: Mapped[list["JuryVote"]] = relationship(back_populates="dispute")


class JuryVote(TimestampMixin, Base):
    __tablename__ = "jury_votes"
    __table_args__ = (UniqueConstraint("dispute_id", "voter_id", name="uq_jury_votes_dispute_voter"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("disputes.id"), index=True)
    voter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    vote: Mapped[str] = mapped_column(String(10))  # release | refund
    nullifier: Mapped[str] = mapped_column(String(160))

    dispute: Mapped[Dispute] = relationship(back_populates="votes")
    voter: Mapped[User] = relationship()


class WorldVerification(TimestampMixin, Base):
    __tablename__ = "world_verifications"
    __table_args__ = (UniqueConstraint("action", "signal", "nullifier", name="uq_world_action_signal_nullifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    signal: Mapped[str] = mapped_column(String(120))
    nullifier: Mapped[str] = mapped_column(String(160))  # 同じ人間を表すキー。World ID 4.0 では session_id（モック時は mock:...）
    proof_nullifier: Mapped[str | None] = mapped_column(String(80), unique=True)  # proof ごとの session_nullifier（リプレイ防止）


class Approval(TimestampMixin, Base):
    """承認者の承認（World 検証 + EIP-712 署名）。オンチェーンへは worker が中継する"""
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("task_id", "approver_id", "deliverable_hash", name="uq_approvals_task_approver_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    deliverable_hash: Mapped[str] = mapped_column(String(66))
    signature: Mapped[str] = mapped_column(Text)
    nullifier: Mapped[str] = mapped_column(String(160))

    task: Mapped[Task] = relationship(back_populates="approvals")
    approver: Mapped[User] = relationship()


class ChainJob(TimestampMixin, Base):
    """チェーン連携ワーカーのジョブ（ADR-006）。冪等キーで二重送信を防ぐ"""
    __tablename__ = "chain_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|retry|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 再送の待ち時間（他のジョブをブロックしない）


# ---------------------------------------------------------------- エージェントの実行記録（WP-005 / INF-008 の代替。DEC-010）


class AgentRun(TimestampMixin, Base):
    """エージェント 1 回の実行（agent-orchestration 12-1）。依頼文や主張の全文は入れず、長さと先頭だけを残す（12-2）"""
    __tablename__ = "agent_runs"
    # 1 案件 1 実行（agent-infra 5 章・WP-017）: AG-001 の待ち・実行中は、同じ案件・紛争・モードで 1 件だけ
    __table_args__ = (Index("uq_agent_runs_one_active", func.coalesce(text("case_id"), ""), func.coalesce(text("dispute_id"), ""), "mode",
                            unique=True, postgresql_where=text("agent_id = 'AG-001' AND status IN ('queued', 'running')")),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(10), index=True)  # AG-001〜AG-004
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)  # 委譲元の実行
    mode: Mapped[str | None] = mapped_column(String(30))  # decompose | form_team | analyze_dispute など
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), index=True)
    dispute_id: Mapped[str | None] = mapped_column(ForeignKey("disputes.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)  # running | done | failed | stopped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_summary: Mapped[str | None] = mapped_column(Text)
    iterations: Mapped[int] = mapped_column(Integer, default=0)  # LLM の呼び出し回数（再試行を含む）
    retries: Mapped[int] = mapped_column(Integer, default=0)  # 検証失敗による再試行の回数
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    validation_failures: Mapped[list | None] = mapped_column(JSON, default=list)  # 検証で違反した項目（モデルの出力は入れない）
    truncations: Mapped[list | None] = mapped_column(JSON, default=list)  # コンテキストの切り詰め（agent-context 6 章）
    error: Mapped[str | None] = mapped_column(Text)


class AgentToolCall(TimestampMixin, Base):
    """ツール呼び出しの履歴（12-1: TOOL-ID・成否・所要時間）。許可されていない呼び出しも拒否として残す（GRD-001）"""
    __tablename__ = "agent_tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_id: Mapped[str] = mapped_column(String(10), index=True)  # TOOL-001〜TOOL-009
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    validation: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class AgentOutput(TimestampMixin, Base):
    """エージェントの構造化出力の保存先（TOOL-004 / 005 / 007）。冪等キー = (種類, 対象 ID, 版番号)。同じキーは上書き"""
    __tablename__ = "agent_outputs"
    __table_args__ = (UniqueConstraint("kind", "target_id", "revision", name="uq_agent_outputs_kind_target_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # task_plan | team_proposal | dispute_summary
    target_id: Mapped[str] = mapped_column(String(36), index=True)  # 案件 ID または紛争 ID
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))


class AgentControl(TimestampMixin, Base):
    """エージェントの停止と再開の操作（WP-007 / GRD-007・OPS-001〜003）。
    操作を 1 行ずつ積み上げる。範囲（scope）ごとの最新の行が現在の状態で、それ以前の行が操作の記録になる"""
    __tablename__ = "agent_controls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(50), index=True)  # "global" または "case:<案件 ID>"
    action: Mapped[str] = mapped_column(String(10))  # stop | resume
    reason: Mapped[str] = mapped_column(Text, default="")
    operator: Mapped[str] = mapped_column(String(120), default="")


class FundingGrant(TimestampMixin, Base):
    """送金操作権限（WP-020 / GRD-010・OPS-001）。案件単位で発行し、期限・停止・案件の完了で失効する。
    行は消さずに残し（失効は revoked_at を埋める）、操作の記録を兼ねる"""
    __tablename__ = "funding_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 発行 + funding_grant_days（DEC-012）
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
