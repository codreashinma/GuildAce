import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
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


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    rules: Mapped[str] = mapped_column(Text, default="")
    fee_bps: Mapped[int] = mapped_column(Integer, default=200)
    payout_address: Mapped[str] = mapped_column(String(42))
    ens_name: Mapped[str | None] = mapped_column(String(255), index=True)
    ens_tx_hash: Mapped[str | None] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 1), default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    ens_error: Mapped[str | None] = mapped_column(Text)

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
    deposit_tx_hash: Mapped[str | None] = mapped_column(String(66))
    release_tx_hash: Mapped[str | None] = mapped_column(String(66))
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

    case: Mapped[Case] = relationship(back_populates="tasks")
    human_task: Mapped["HumanTask | None"] = relationship(back_populates="task", uselist=False)


class HumanTask(TimestampMixin, Base):
    __tablename__ = "human_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    reward: Mapped[int] = mapped_column(Numeric(78, 0), default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submission: Mapped[str | None] = mapped_column(Text)
    ai_check: Mapped[str | None] = mapped_column(Text)

    task: Mapped[Task] = relationship(back_populates="human_task")
    case: Mapped[Case] = relationship()
    worker: Mapped[User | None] = relationship()


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String(10))  # agent | user
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    nullifier: Mapped[str] = mapped_column(String(80))

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
    nullifier: Mapped[str] = mapped_column(String(80))

    dispute: Mapped[Dispute] = relationship(back_populates="votes")
    voter: Mapped[User] = relationship()


class WorldVerification(TimestampMixin, Base):
    __tablename__ = "world_verifications"
    __table_args__ = (UniqueConstraint("action", "signal", "nullifier", name="uq_world_action_signal_nullifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    signal: Mapped[str] = mapped_column(String(120))
    nullifier: Mapped[str] = mapped_column(String(80))
