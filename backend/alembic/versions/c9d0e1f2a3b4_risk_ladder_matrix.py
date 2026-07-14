"""risk-band -> approval-ladder matrix on request_type

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-14 12:10:00.000000

Slice 2: the ladder is derived from the risk band via a per-type matrix.
Column is nullable; startup backfills category defaults so existing rows get
the canonical matrices without a data migration here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('request_type', sa.Column('risk_ladders', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('request_type', 'risk_ladders')
