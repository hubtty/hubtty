"""Drop sync_query table

Revision ID: 79d141409a92
Revises: 58a0f7616432
Create Date: 2021-08-10 11:37:05.887683

"""

# revision identifiers, used by Alembic.
revision = '79d141409a92'
down_revision = '58a0f7616432'

from alembic import op


def upgrade():
    op.drop_table('sync_query')
    pass


def downgrade():
    pass
