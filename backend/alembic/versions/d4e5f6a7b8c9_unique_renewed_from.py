"""unique renewed_from_id: one renewal per contract

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-14 05:40:00.000000

Enforces the renewal idempotency guarantee at the database level: a given
contract can be renewed at most once. Partial unique index (NULLs excluded)
so unrenewed contracts are unconstrained. Combined with setting the link at
renewal-creation time, this closes the concurrent-double-renew race.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_request_renewed_from', 'request', ['renewed_from_id'], unique=True,
        postgresql_where=sa.text('renewed_from_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_request_renewed_from', table_name='request')
