"""intake platform: request types, routing rules, obligations, queue ops, playbook ladder

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-14 07:00:00.000000

The breadth slice: Frontdoor stops being NDA-only.
- request_type: the catalog of things the front door accepts (CONTRACT vs ADVICE engine)
- routing_rule: admin-editable WHEN->THEN rows evaluated after classification
- obligation: post-signature commitments extracted at execution
- request: assignment/priority/SLA-override/snooze/advice fields
- playbook_rule: fallback positions + walk-away line (the Ivo-style ladder)

All additive. Native PG enums for the new enum types; request.priority defaults
NORMAL on existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: the types are created explicitly (checkfirst) in upgrade();
# without it, each column reference would try CREATE TYPE again and collide.
requestcategory = postgresql.ENUM('CONTRACT', 'ADVICE', name='requestcategory', create_type=False)
requestpriority = postgresql.ENUM('LOW', 'NORMAL', 'HIGH', 'URGENT', name='requestpriority', create_type=False)
obligationkind = postgresql.ENUM('RENEWAL', 'SURVIVAL', 'RETURN_DESTRUCTION', 'NOTICE', 'OTHER', name='obligationkind', create_type=False)
obligationstatus = postgresql.ENUM('OPEN', 'DONE', 'WAIVED', name='obligationstatus', create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    requestcategory.create(bind, checkfirst=True)
    requestpriority.create(bind, checkfirst=True)
    obligationkind.create(bind, checkfirst=True)
    obligationstatus.create(bind, checkfirst=True)

    op.create_table(
        'request_type',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('org_id', sa.String(), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('category', requestcategory, nullable=False, server_default='ADVICE'),
        sa.Column('default_sla_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('ordinal', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'key', name='uq_request_type_org_key'),
    )

    op.create_table(
        'routing_rule',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('org_id', sa.String(), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('stop_on_match', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('match_type_key', sa.String(), nullable=True),
        sa.Column('match_direction', sa.String(), nullable=True),
        sa.Column('match_keyword', sa.String(), nullable=True),
        sa.Column('match_jurisdiction', sa.String(), nullable=True),
        sa.Column('set_assignee_user_id', sa.String(), sa.ForeignKey('app_user.id'), nullable=True),
        sa.Column('set_priority', sa.String(), nullable=True),
        sa.Column('set_sla_hours', sa.Integer(), nullable=True),
        sa.Column('escalate', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'obligation',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('org_id', sa.String(), sa.ForeignKey('organization.id'), nullable=False),
        sa.Column('request_id', sa.String(), sa.ForeignKey('request.id'), nullable=False),
        sa.Column('kind', obligationkind, nullable=False, server_default='OTHER'),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default=''),
        sa.Column('status', obligationstatus, nullable=False, server_default='OPEN'),
        sa.Column('resolved_by', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_obligation_request', 'obligation', ['request_id'])

    op.add_column('request', sa.Column('assigned_to_user_id', sa.String(), sa.ForeignKey('app_user.id'), nullable=True))
    op.add_column('request', sa.Column('priority', requestpriority, nullable=False, server_default='NORMAL'))
    op.add_column('request', sa.Column('sla_target_hours', sa.Integer(), nullable=True))
    op.add_column('request', sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('request', sa.Column('resolution_note', sa.Text(), nullable=True))
    op.add_column('request', sa.Column('resolution_draft', sa.Text(), nullable=True))
    op.add_column('request', sa.Column('details', sa.Text(), nullable=True))

    op.add_column('playbook_rule', sa.Column('fallbacks', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('playbook_rule', sa.Column('walk_away_text', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('playbook_rule', 'walk_away_text')
    op.drop_column('playbook_rule', 'fallbacks')
    for col in ('details', 'resolution_draft', 'resolution_note', 'snoozed_until', 'sla_target_hours', 'priority', 'assigned_to_user_id'):
        op.drop_column('request', col)
    op.drop_index('ix_obligation_request', table_name='obligation')
    op.drop_table('obligation')
    op.drop_table('routing_rule')
    op.drop_table('request_type')
    bind = op.get_bind()
    for e in (obligationstatus, obligationkind, requestpriority, requestcategory):
        e.drop(bind, checkfirst=True)
