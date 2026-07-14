"""playbooks scoped to a contract type

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-14 11:00:00.000000

Phase 2 (second CONTRACT engine): a playbook now belongs to a contract type
("nda", "dpa", ...). The resolver picks the active playbook FOR THAT TYPE, so
an org can hold one default per contract type simultaneously. All existing
playbooks are NDA playbooks — backfilled via the server default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'playbook',
        sa.Column('contract_type_key', sa.String(), nullable=False, server_default='nda'),
    )
    op.create_index('ix_playbook_org_type', 'playbook', ['org_id', 'contract_type_key'])
    # "one active default per (org, contract type)" is load-bearing for the
    # resolver; the activate endpoint's read-then-write can race, so the schema
    # backs the invariant. Deterministic pre-clean: if duplicates somehow exist,
    # keep the oldest active per (org, type) — the same one the resolver's
    # created_at ASC ordering already picks — and deactivate the rest.
    op.execute(
        """
        UPDATE playbook SET active = FALSE
        WHERE active AND id NOT IN (
            SELECT DISTINCT ON (org_id, contract_type_key) id
            FROM playbook WHERE active
            ORDER BY org_id, contract_type_key, created_at ASC
        )
        """
    )
    op.create_index(
        'uq_playbook_active_default', 'playbook', ['org_id', 'contract_type_key'],
        unique=True, postgresql_where=sa.text('active'),
    )


def downgrade() -> None:
    op.drop_index('uq_playbook_active_default', table_name='playbook')
    op.drop_index('ix_playbook_org_type', table_name='playbook')
    op.drop_column('playbook', 'contract_type_key')
