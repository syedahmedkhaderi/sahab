"""SQLAlchemy ORM models for every table in the Sahab schema (blueprint §12).

UUID primary keys, proper enums/constraints, and timestamps throughout.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRole(str, enum.Enum):
    student = "student"
    researcher = "researcher"
    professor = "professor"
    admin = "admin"


class UserStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    disabled = "disabled"


class GpuStatus(str, enum.Enum):
    free = "free"
    leased = "leased"
    disabled = "disabled"


class ImageKind(str, enum.Enum):
    gpu = "gpu"
    cpu = "cpu"


class SessionState(str, enum.Enum):
    requested = "requested"
    queued = "queued"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    stopped = "stopped"
    failed = "failed"


class LedgerReason(str, enum.Enum):
    grant = "grant"
    metering = "metering"
    refund = "refund"
    adjustment = "adjustment"


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"


class ResourceType(str, enum.Enum):
    l4_gpu = "l4_gpu"
    cpu = "cpu"


# ---------------------------------------------------------------------------
# Helper: UUID default + now()
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.student,
    )
    status: Mapped[str] = mapped_column(
        Enum(UserStatus, name="user_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserStatus.pending,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    credit_balance: Mapped[float] = mapped_column(Numeric(precision=18, scale=4), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # relationships
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", lazy="select")
    ledger_entries: Mapped[list["CreditLedger"]] = relationship(
        "CreditLedger", back_populates="user", lazy="select"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="user", lazy="select"
    )


class GpuInventory(Base):
    __tablename__ = "gpu_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    gpu_uuid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    vram_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(GpuStatus, name="gpu_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GpuStatus.free,
    )

    leases: Mapped[list["GpuLease"]] = relationship("GpuLease", back_populates="gpu", lazy="select")


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    docker_ref: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(ImageKind, name="image_kind", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="image", lazy="select")


class Rate(Base):
    __tablename__ = "rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resource_type: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    credits_per_minute: Mapped[float] = mapped_column(Numeric(precision=18, scale=6), nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    image_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("images.id"), nullable=True)
    resource_type: Mapped[str] = mapped_column(
        Enum(ResourceType, name="resource_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        Enum(SessionState, name="session_state", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=SessionState.requested,
        index=True,
    )
    queue_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions", lazy="select")
    image: Mapped["Image | None"] = relationship("Image", back_populates="sessions", lazy="select")
    gpu_leases: Mapped[list["GpuLease"]] = relationship(
        "GpuLease", back_populates="session", lazy="select"
    )
    ledger_entries: Mapped[list["CreditLedger"]] = relationship(
        "CreditLedger", back_populates="session", lazy="select"
    )


class GpuLease(Base):
    __tablename__ = "gpu_leases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    # ON UPDATE CASCADE: a host rebuild gives the physical GPUs new UUIDs, and the
    # inventory row is corrected in place so the lease history survives the change.
    gpu_uuid: Mapped[str] = mapped_column(
        String(256),
        ForeignKey("gpu_inventory.gpu_uuid", onupdate="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["Session"] = relationship("Session", back_populates="gpu_leases", lazy="select")
    gpu: Mapped["GpuInventory"] = relationship("GpuInventory", back_populates="leases", lazy="select")


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    delta: Mapped[float] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    reason: Mapped[str] = mapped_column(
        Enum(LedgerReason, name="ledger_reason", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=True)
    balance_after: Mapped[float] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="ledger_entries", lazy="select")
    session: Mapped["Session | None"] = relationship("Session", back_populates="ledger_entries", lazy="select")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    amount_qar: Mapped[float | None] = mapped_column(Numeric(precision=18, scale=2), nullable=True)
    credits: Mapped[float | None] = mapped_column(Numeric(precision=18, scale=4), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(TransactionStatus, name="transaction_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TransactionStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="transactions", lazy="select")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(256), nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Use Text for SQLite compat; JSONB used in Postgres via Alembic migration
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
