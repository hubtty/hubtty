"""rename revision to commit

Revision ID: a2974173ff5b
Revises: 862b2a89e855
Create Date: 2020-11-14 10:35:57.799486

"""

# revision identifiers, used by Alembic.
revision = 'a2974173ff5b'
down_revision = '862b2a89e855'

from alembic import op


def upgrade():
    op.rename_table('revision', 'commit')
    op.alter_column('commit', 'commit', new_column_name='sha')
    op.alter_column('file', 'revision_key', new_column_name='commit_key')
    op.alter_column('message', 'revision_key', new_column_name='commit_key')
    op.alter_column('pending_cherry_pick', 'revision_key', new_column_name='commit_key')
    op.alter_column('check', 'revision_key', new_column_name='commit_key')
    pass


def downgrade():
    pass
