"""Unused commit fields

Revision ID: c61a3925cedb
Revises: 48a75819ec1d
Create Date: 2021-03-06 11:58:51.626667

"""

# revision identifiers, used by Alembic.
revision = 'c61a3925cedb'
down_revision = 'f3ceef330b1b'

from hubtty.dbsupport import sqlite_drop_columns


def upgrade():
    sqlite_drop_columns('commit', ['number', 'fetch_auth', 'fetch_ref'])


def downgrade():
    pass
