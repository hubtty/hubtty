"""Drop pending cherry-pick table

Revision ID: 58a0f7616432
Revises: 164f2a7ca2b0
Create Date: 2021-08-09 22:20:18.024213

"""

# revision identifiers, used by Alembic.
revision = '58a0f7616432'
down_revision = '164f2a7ca2b0'

from alembic import op


def upgrade():
    op.drop_table('pending_cherry_pick')


def downgrade():
    pass
