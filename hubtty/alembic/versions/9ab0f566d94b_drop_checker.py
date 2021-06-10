"""Drop checker

Revision ID: 9ab0f566d94b
Revises: 3f3f38356cbc
Create Date: 2021-02-20 17:55:52.587428

"""

# revision identifiers, used by Alembic.
revision = '9ab0f566d94b'
down_revision = '3f3f38356cbc'

from alembic import op
import sqlalchemy as sa

from hubtty.dbsupport import sqlite_drop_columns


def upgrade():
    sqlite_drop_columns('check', ['checker_key'])

    op.drop_table('checker')
    op.add_column('check', sa.Column('name', sa.String(255)))


def downgrade():
    pass
