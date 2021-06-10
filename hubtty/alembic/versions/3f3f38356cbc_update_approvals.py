"""Update approvals

Revision ID: 3f3f38356cbc
Revises: 9ea887cbb620
Create Date: 2020-12-23 21:41:55.052531

"""

# revision identifiers, used by Alembic.
revision = '3f3f38356cbc'
down_revision = '9ea887cbb620'

from alembic import op
import sqlalchemy as sa

from hubtty.dbsupport import sqlite_drop_columns

def upgrade():
    sqlite_drop_columns('approval', ['value'])
    op.add_column('approval', sa.Column('sha', sa.String(length=255), nullable=False))


def downgrade():
    pass
