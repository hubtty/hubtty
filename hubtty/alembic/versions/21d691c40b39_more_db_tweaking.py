"""More DB tweaking

Revision ID: 21d691c40b39
Revises: fb283799c60d
Create Date: 2021-03-14 15:51:16.535981

"""

# revision identifiers, used by Alembic.
revision = '21d691c40b39'
down_revision = 'fb283799c60d'

import sqlalchemy as sa

from hubtty.dbsupport import sqlite_alter_columns
from hubtty.dbsupport import sqlite_drop_columns

def upgrade():
    sqlite_alter_columns('approval', [
        sa.Column('state', sa.String(32), index=True, nullable=False),
        sa.Column('sha', sa.String(64), nullable=False),
        ])

    sqlite_alter_columns('change', [
        sa.Column('id', sa.Integer, index=True, nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('html_url', sa.Text, nullable=False),
        ])

    sqlite_alter_columns('check', [
        sa.Column('state', sa.String(16), nullable=False),
        ])

    sqlite_alter_columns('comment', [
        sa.Column('id', sa.Integer, index=True),
        sa.Column('in_reply_to', sa.Integer),
        sa.Column('commit_id', sa.String(64), nullable=False),
        sa.Column('original_commit_id', sa.String(64), nullable=False),
        ])
    sqlite_drop_columns('comment', ['robot_id', 'robot_run_id'])

    sqlite_alter_columns('commit', [
        sa.Column('sha', sa.String(64), index=True, nullable=False),
        sa.Column('parent', sa.String(64), index=True, nullable=False),
        ])

    sqlite_alter_columns('file', [
        sa.Column('status', sa.String(16), index=True, nullable=False),
        ])

    sqlite_alter_columns('message', [
        sa.Column('id', sa.Integer, index=True),
        ])

def downgrade():
    pass
