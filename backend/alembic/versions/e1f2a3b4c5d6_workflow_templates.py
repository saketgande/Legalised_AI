"""workflow templates: the ladder as versioned data

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-14 12:40:00.000000

Slice 4: per-contract-type workflow blueprints (pinned/always/conditional
rungs, versioned, one active default per type) + the instantiated snapshot
pinned onto each request at creation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workflow_template',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('org_id', sa.String(), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('type_key', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('rungs', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index(
        'uq_workflow_active_default', 'workflow_template', ['org_id', 'type_key'],
        unique=True, postgresql_where=sa.text('active'),
    )
    op.add_column('request', sa.Column('workflow_template_id', sa.String(),
                                       sa.ForeignKey('workflow_template.id'), nullable=True))
    op.add_column('request', sa.Column('workflow_version', sa.Integer(), nullable=True))
    op.add_column('request', sa.Column('workflow_rungs', sa.JSON(), nullable=False,
                                       server_default='[]'))


def downgrade() -> None:
    op.drop_column('request', 'workflow_rungs')
    op.drop_column('request', 'workflow_version')
    op.drop_column('request', 'workflow_template_id')
    op.drop_index('uq_workflow_active_default', table_name='workflow_template')
    op.drop_table('workflow_template')
