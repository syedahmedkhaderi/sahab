"""Let a corrected GPU UUID cascade to its lease history.

A host rebuild reissues the physical GPUs new UUIDs. The inventory row has to be
corrected in place — deleting and re-inserting it would orphan the gpu_leases
rows that reference it — so the foreign key needs ON UPDATE CASCADE.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "gpu_leases_gpu_uuid_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "gpu_leases", type_="foreignkey")
    op.create_foreign_key(
        _FK, "gpu_leases", "gpu_inventory", ["gpu_uuid"], ["gpu_uuid"], onupdate="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "gpu_leases", type_="foreignkey")
    op.create_foreign_key(_FK, "gpu_leases", "gpu_inventory", ["gpu_uuid"], ["gpu_uuid"])
