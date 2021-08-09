"""Remove commit pending_message

Revision ID: 32e7026ffef6
Revises: 2862256bd583
Create Date: 2021-08-09 17:14:18.557118

"""

# revision identifiers, used by Alembic.
revision = '32e7026ffef6'
down_revision = '2862256bd583'

from alembic import op

from hubtty.dbsupport import sqlite_drop_columns


def upgrade():
    op.drop_index(op.f('ix_commit_pending_message'), table_name='commit')
    sqlite_drop_columns('commit', ['pending_message'])
    pass


def downgrade():
    pass
