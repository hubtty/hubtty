"""Drop commit can_submit

Revision ID: 439753e172a0
Revises: 4a2afc48dd09
Create Date: 2021-06-05 22:21:24.537412

"""

from hubtty.dbsupport import sqlite_drop_columns

# revision identifiers, used by Alembic.
revision = '439753e172a0'
down_revision = '4a2afc48dd09'


def upgrade():
    sqlite_drop_columns('commit', ['can_submit'])


def downgrade():
    pass
