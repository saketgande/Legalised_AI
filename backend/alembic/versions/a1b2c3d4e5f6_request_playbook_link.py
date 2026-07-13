"""request playbook link

Records which playbook a request was drafted/reviewed against, so multi-playbook
orgs have a defensibility answer to "which standard did we apply".

Revision ID: a1b2c3d4e5f6
Revises: 76632dab1ed8
Create Date: 2026-07-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '76632dab1ed8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('request', sa.Column('playbook_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_request_playbook_id', 'request', 'playbook', ['playbook_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_request_playbook_id', 'request', type_='foreignkey')
    op.drop_column('request', 'playbook_id')
