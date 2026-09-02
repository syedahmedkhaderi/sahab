"""Teach the schema about the machine a GPU lives in.

Before this, gpu_inventory held a bare GPU UUID with no notion of a host, so the
scheduler could only ever be right about one machine. Adding nodes lets a lease
name both the GPU and the VM it is in, which is what the spawner needs to start
the container in the right place.

The existing inventory is backfilled onto a seeded manager node — the VM running
the control plane — so a single-machine deployment carries on unchanged.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import os
import socket
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NODE_STATUS = sa.Enum(
    "pending", "enrolling", "ready", "unreachable", "draining", "disabled",
    name="node_status",
)
_NODE_AUTH_KIND = sa.Enum("password", "key", name="node_auth_kind")
_ENROLLMENT_STATUS = sa.Enum(
    "issued", "running", "completed", "failed", "expired", name="enrollment_status"
)


def _manager_name() -> str:
    """Same resolution the app uses: MANAGER_NODE_NAME, else this host's name."""
    return os.environ.get("MANAGER_NODE_NAME") or socket.gethostname()


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(253), nullable=False, unique=True),
        sa.Column("display_name", sa.String(253), nullable=True),
        sa.Column("address", sa.String(253), nullable=False, server_default=""),
        sa.Column("docker_port", sa.Integer, nullable=False, server_default="2376"),
        sa.Column("metrics_url", sa.Text, nullable=True),
        sa.Column("status", _NODE_STATUS, nullable=False, server_default="pending"),
        sa.Column("is_manager", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("driver_version", sa.String(64), nullable=True),
        sa.Column("docker_version", sa.String(64), nullable=True),
        sa.Column("ssh_host", sa.String(253), nullable=True),
        sa.Column("ssh_port", sa.Integer, nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(64), nullable=True),
        sa.Column("ssh_auth_kind", _NODE_AUTH_KIND, nullable=True),
        sa.Column("ssh_secret_enc", sa.Text, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unreachable_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_nodes_name", "nodes", ["name"], unique=True)
    op.create_index("ix_nodes_status", "nodes", ["status"])

    op.create_table(
        "node_enrollments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "node_id",
            sa.String(36),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", _ENROLLMENT_STATUS, nullable=False, server_default="issued"),
        sa.Column("log", sa.Text, nullable=False, server_default=""),
        sa.Column("reported_gpus", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_node_enrollments_node_id", "node_enrollments", ["node_id"])
    op.create_index(
        "ix_node_enrollments_token_hash", "node_enrollments", ["token_hash"], unique=True
    )

    # Seed the control-plane VM as the first node. Its empty address is the signal
    # that its containers go through the local Docker socket.
    manager_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO nodes (id, name, display_name, address, docker_port, status,"
            " is_manager, enrolled_at, last_seen_at, created_at)"
            " VALUES (:id, :name, :display, '', 2376, 'ready', true, now(), now(), now())"
        ).bindparams(id=manager_id, name=_manager_name(), display="Control plane")
    )

    # Nullable first so the backfill has somewhere to land, then locked down.
    op.add_column("gpu_inventory", sa.Column("node_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE gpu_inventory SET node_id = :id").bindparams(id=manager_id))
    op.alter_column("gpu_inventory", "node_id", nullable=False)
    op.create_foreign_key(
        "gpu_inventory_node_id_fkey",
        "gpu_inventory",
        "nodes",
        ["node_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_gpu_inventory_node_id", "gpu_inventory", ["node_id"])

    # Sessions record where they were placed. Left nullable: queued and CPU
    # sessions have no node, and history from before this migration has none.
    op.add_column("sessions", sa.Column("node_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "sessions_node_id_fkey", "sessions", "nodes", ["node_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sessions_node_id", "sessions", ["node_id"])

    del bind


def downgrade() -> None:
    op.drop_index("ix_sessions_node_id", table_name="sessions")
    op.drop_constraint("sessions_node_id_fkey", "sessions", type_="foreignkey")
    op.drop_column("sessions", "node_id")

    op.drop_index("ix_gpu_inventory_node_id", table_name="gpu_inventory")
    op.drop_constraint("gpu_inventory_node_id_fkey", "gpu_inventory", type_="foreignkey")
    op.drop_column("gpu_inventory", "node_id")

    op.drop_index("ix_node_enrollments_token_hash", table_name="node_enrollments")
    op.drop_index("ix_node_enrollments_node_id", table_name="node_enrollments")
    op.drop_table("node_enrollments")

    op.drop_index("ix_nodes_status", table_name="nodes")
    op.drop_index("ix_nodes_name", table_name="nodes")
    op.drop_table("nodes")

    bind = op.get_bind()
    for enum in (_ENROLLMENT_STATUS, _NODE_AUTH_KIND, _NODE_STATUS):
        enum.drop(bind, checkfirst=True)
