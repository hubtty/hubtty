"""Rename change pending_status to pending_edit

Revision ID: 164f2a7ca2b0
Revises: 32e7026ffef6
Create Date: 2021-08-09 19:39:58.483315

"""

# revision identifiers, used by Alembic.
revision = '164f2a7ca2b0'
down_revision = '32e7026ffef6'

from alembic import op


def upgrade():
    op.alter_column('change', 'pending_status', new_column_name='pending_edit')
    op.alter_column('change', 'pending_status_message', new_column_name='pending_edit_message')
    op.drop_index('ix_change_pending_status')
    op.create_index(op.f('ix_change_pending_edit'), 'change', ['pending_edit'], unique=False)
    pass


def downgrade():
    pass
