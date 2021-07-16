"""Drop hashtag table

Revision ID: 5c7de722e68c
Revises: 4fb888763b3b
Create Date: 2021-06-20 17:02:39.352580

"""

# revision identifiers, used by Alembic.
revision = '5c7de722e68c'
down_revision = '4fb888763b3b'

from alembic import op


def upgrade():
    op.alter_column('change', 'pending_hashtags', new_column_name='pending_labels')
    op.drop_table('hashtag')
    pass


def downgrade():
    pass
