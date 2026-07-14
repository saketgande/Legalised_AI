"""negotiation rounds: WITH_COUNTERPARTY/RETURNED states + round counters

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-14 12:20:00.000000

Slice 3: the loop. A request can go APPROVED -> WITH_COUNTERPARTY (their
review), come back RETURNED, and spin a fresh round (redline -> risk score ->
ladder) on the same ticket. `round` counts the cycles on both the request and
each review run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction.
    # IF NOT EXISTS keeps re-runs against a partially-migrated DB safe.
    op.execute("ALTER TYPE requeststate ADD VALUE IF NOT EXISTS 'WITH_COUNTERPARTY' AFTER 'APPROVED'")
    op.execute("ALTER TYPE requeststate ADD VALUE IF NOT EXISTS 'RETURNED' AFTER 'WITH_COUNTERPARTY'")
    op.add_column('request', sa.Column('round', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('review_run', sa.Column('round', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    # enum values are additive-only in Postgres; the columns drop cleanly
    op.drop_column('review_run', 'round')
    op.drop_column('request', 'round')
