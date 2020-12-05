"""add merge to PRs

Revision ID: fc35305967d4
Revises: a2974173ff5b
Create Date: 2020-12-05 11:51:08.819068

"""

# revision identifiers, used by Alembic.
revision = 'fc35305967d4'
down_revision = 'a2974173ff5b'

import warnings

from alembic import op
import sqlalchemy as sa

from hubtty.dbsupport import sqlite_alter_columns


def upgrade():
    op.alter_column('change', 'status', new_column_name='state')

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('merged', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('merged', sa.Boolean()))
    connection.execute(change.update().values({'merged':False}))

    sqlite_alter_columns('change', [
        sa.Column('merged', sa.Boolean(), index=True, nullable=False),
        ])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('mergeable', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('mergeable', sa.Boolean()))
    connection.execute(change.update().values({'mergeable':False}))

    sqlite_alter_columns('change', [
        sa.Column('mergeable', sa.Boolean(), index=True, nullable=False),
        ])

def downgrade():
    pass
