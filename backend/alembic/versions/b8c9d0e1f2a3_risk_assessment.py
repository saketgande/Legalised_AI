"""risk assessment per (request, round)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-14 12:00:00.000000

Slice 1 of the score-driven workflow engine: every drafted/redlined round gets
a RiskAssessment — deterministic factor core + optional AI adjustment that can
only raise severity. The band (LOW/MEDIUM/HIGH/CRITICAL) is what slice 2 uses
to pick the approval ladder.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

riskband = postgresql.ENUM('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='riskband', create_type=False)


def upgrade() -> None:
    riskband.create(op.get_bind(), checkfirst=True)
    op.create_table(
        'risk_assessment',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('request_id', sa.String(), sa.ForeignKey('request.id'), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('review_run_id', sa.String(), sa.ForeignKey('review_run.id'), nullable=True),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('band', riskband, nullable=False),
        sa.Column('factors', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('ai_adjustment', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ai_note', sa.Text(), nullable=False, server_default=''),
        sa.Column('model', sa.String(), nullable=False, server_default='deterministic'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.UniqueConstraint('request_id', 'round', name='uq_risk_request_round'),
    )
    op.create_index('ix_risk_request', 'risk_assessment', ['request_id'])


def downgrade() -> None:
    op.drop_index('ix_risk_request', table_name='risk_assessment')
    op.drop_table('risk_assessment')
    riskband.drop(op.get_bind(), checkfirst=True)
