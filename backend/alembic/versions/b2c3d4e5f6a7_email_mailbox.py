"""email mailbox (polled intake inbox)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-13 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_mailbox',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('imap_host', sa.String(), nullable=False),
        sa.Column('imap_port', sa.Integer(), nullable=False, server_default='993'),
        sa.Column('use_ssl', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('secret_enc', sa.Text(), nullable=False),
        sa.Column('folder', sa.String(), nullable=False, server_default='INBOX'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('default_playbook_id', sa.String(), nullable=True),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_result', sa.JSON(), nullable=True),
        sa.Column('ingested_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id']),
        sa.ForeignKeyConstraint(['default_playbook_id'], ['playbook.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', name='uq_email_mailbox_org'),
    )


def downgrade() -> None:
    op.drop_table('email_mailbox')
