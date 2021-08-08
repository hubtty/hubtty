"""Remove pending_starred

Revision ID: 2862256bd583
Revises: 5c7de722e68c
Create Date: 2021-08-08 15:21:14.983712

"""

# revision identifiers, used by Alembic.
revision = '2862256bd583'
down_revision = '5c7de722e68c'

from alembic import op

from hubtty.dbsupport import sqlite_drop_columns

def upgrade():
    op.drop_index(op.f('ix_change_pending_starred'), table_name='change')
    sqlite_drop_columns('change', ['pending_starred'])
    pass


def downgrade():
    pass
