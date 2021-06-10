"""remove topic from change

Revision ID: 12554687e95c
Revises: 45d33eccc7a7
Create Date: 2020-11-07 18:02:27.380801

"""

# revision identifiers, used by Alembic.
revision = '12554687e95c'
down_revision = '45d33eccc7a7'

from alembic import op

from hubtty.dbsupport import sqlite_drop_columns

def upgrade():
    op.drop_index(op.f('ix_change_topic'), table_name='change')
    op.drop_index(op.f('ix_change_pending_topic'), table_name='change')
    sqlite_drop_columns('change', ['topic', 'pending_topic'])


def downgrade():
    pass
