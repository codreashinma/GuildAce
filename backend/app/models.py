from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorldIDProofUse(Base):
    __tablename__ = "world_id_proof_uses"
    __table_args__ = (
        UniqueConstraint(
            "rp_id",
            "environment",
            "action",
            "identifier",
            "nullifier",
            name="uq_world_id_proof_use_replay",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    rp_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    environment: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    identifier: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    nullifier: Mapped[Decimal] = mapped_column(
        Numeric(78, 0),
        nullable=False,
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
