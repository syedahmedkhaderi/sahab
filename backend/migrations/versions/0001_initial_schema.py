"""Initial schema — all tables from blueprint §12.

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="student"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("credit_balance", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # gpu_inventory
    op.create_table(
        "gpu_inventory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gpu_uuid", sa.String(256), nullable=False, unique=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("vram_mb", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="free"),
    )
    op.create_index("ix_gpu_inventory_gpu_uuid", "gpu_inventory", ["gpu_uuid"])

    # images
    op.create_table(
        "images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("docker_ref", sa.Text, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
    )

    # rates
    op.create_table(
        "rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource_type", sa.String(64), nullable=False, unique=True),
        sa.Column("credits_per_minute", sa.Numeric(18, 6), nullable=False),
    )
    op.create_index("ix_rates_resource_type", "rates", ["resource_type"])

    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("image_id", sa.String(36), sa.ForeignKey("images.id"), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="requested"),
        sa.Column("queue_pos", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_metered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_state", "sessions", ["state"])

    # gpu_leases
    op.create_table(
        "gpu_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("gpu_uuid", sa.String(256), sa.ForeignKey("gpu_inventory.gpu_uuid"), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gpu_leases_session_id", "gpu_leases", ["session_id"])

    # credit_ledger
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delta", sa.Numeric(18, 6), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("balance_after", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])

    # transactions
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_qar", sa.Numeric(18, 2), nullable=True),
        sa.Column("credits", sa.Numeric(18, 4), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("provider_ref", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])

    # audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(256), nullable=False),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("transactions")
    op.drop_table("credit_ledger")
    op.drop_table("gpu_leases")
    op.drop_table("sessions")
    op.drop_table("rates")
    op.drop_table("images")
    op.drop_table("gpu_inventory")
    op.drop_table("users")
