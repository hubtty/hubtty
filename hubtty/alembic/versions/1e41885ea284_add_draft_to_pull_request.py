"""Add draft to pull-request

Revision ID: 1e41885ea284
Revises: a2af1e2e44ee
Create Date: 2022-01-21 10:07:48.605105

"""

# revision identifiers, used by Alembic.
revision = '1e41885ea284'
down_revision = 'a2af1e2e44ee'

from alembic import op
import sqlalchemy as sa

import warnings

from hubtty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('pull_request', sa.Column('draft', sa.Boolean()))

    connection = op.get_bind()
    pr = sa.sql.table('pull_request',
            sa.sql.column('draft', sa.Boolean()))
    connection.execute(pr.update().values({'draft':False}))

    sqlite_alter_columns('pull_request', [
        sa.Column('draft', sa.Boolean(), index=True, nullable=False),
        ])


def downgrade():
    pass
