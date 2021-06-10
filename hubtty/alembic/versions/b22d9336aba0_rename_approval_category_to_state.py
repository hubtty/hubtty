"""Rename approval category to state

Revision ID: b22d9336aba0
Revises: c61a3925cedb
Create Date: 2021-03-13 12:13:12.199620

"""

# revision identifiers, used by Alembic.
revision = 'b22d9336aba0'
down_revision = 'c61a3925cedb'

from alembic import op


def upgrade():
    op.alter_column('approval', 'category', new_column_name='state')
    pass


def downgrade():
    pass
