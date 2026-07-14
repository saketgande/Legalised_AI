"""contract lifecycle: executed_at, expires_at, renewed_from_id on request

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-14 05:10:00.000000

The CLM half: once an NDA is executed it becomes a tracked contract. These
columns carry the executed date and the derived expiry so the registry can
surface renewal posture. Backfill reads the executed date from the append-only
audit ledger (the same immutable source the SLA clock uses), so already-filed
contracts get correct expiry without a re-execution pass.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('request', sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('request', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('request', sa.Column('renewed_from_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_request_renewed_from', 'request', 'request', ['renewed_from_id'], ['id']
    )

    # backfill executed_at from the earliest execution event in the immutable ledger
    op.execute(
        """
        UPDATE request AS r SET executed_at = sub.ts
        FROM (
            SELECT resource_id, MIN(created_at) AS ts
            FROM audit_event
            WHERE resource_type = 'Request'
              AND action IN ('request.executed', 'request.filed')
            GROUP BY resource_id
        ) AS sub
        WHERE sub.resource_id = r.id AND r.executed_at IS NULL
        """
    )
    # fallback for executed/filed rows with no ledger event (e.g. legacy data)
    op.execute(
        """
        UPDATE request SET executed_at = updated_at
        WHERE executed_at IS NULL AND state IN ('EXECUTED', 'FILED')
        """
    )
    # derive expiry = executed_at + term_months (month-correct interval)
    op.execute(
        """
        UPDATE request SET expires_at = executed_at + make_interval(months => term_months)
        WHERE executed_at IS NOT NULL AND expires_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint('fk_request_renewed_from', 'request', type_='foreignkey')
    op.drop_column('request', 'renewed_from_id')
    op.drop_column('request', 'expires_at')
    op.drop_column('request', 'executed_at')
