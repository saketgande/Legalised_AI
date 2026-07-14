"""unique obligation per (request, kind)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-14 09:00:00.000000

Closes the concurrent backfill-on-read race: two simultaneous readers of a
pre-obligations contract could both pass the read-then-insert guard and write
duplicate rows. The unique index makes the database the arbiter; the service
catches IntegrityError and yields to the winner. Dedupes any existing
duplicates first (keeps the oldest row per (request, kind)).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM obligation o USING obligation keep
        WHERE o.request_id = keep.request_id AND o.kind = keep.kind
          AND o.created_at > keep.created_at
        """
    )
    op.create_index(
        'uq_obligation_request_kind', 'obligation', ['request_id', 'kind'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_obligation_request_kind', table_name='obligation')
