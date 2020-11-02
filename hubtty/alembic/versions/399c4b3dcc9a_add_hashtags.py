"""add_hashtags

Revision ID: 399c4b3dcc9a
Revises: 7ef7dfa2ca3a
Create Date: 2019-08-24 15:54:05.934760

"""

# revision identifiers, used by Alembic.
revision = '399c4b3dcc9a'
down_revision = '7ef7dfa2ca3a'

import warnings

from alembic import op
import sqlalchemy as sa

from hubtty.dbsupport import sqlite_alter_columns


def upgrade():
    op.create_table('hashtag',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('change_key', sa.Integer(), sa.ForeignKey('change.key'), index=True),
    sa.Column('name', sa.String(length=255), index=True, nullable=False),
    sa.PrimaryKeyConstraint('key')
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('pending_hashtags', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('pending_hashtags', sa.Boolean()))
    connection.execute(change.update().values({'pending_hashtags':False}))

    sqlite_alter_columns('change', [
        sa.Column('pending_hashtags', sa.Boolean(), index=True, nullable=False),
    ])


def downgrade():
    pass
