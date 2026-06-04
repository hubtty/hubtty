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


def upgrade():
    with op.batch_alter_table('pull_request') as batch_op:
        batch_op.add_column(
            sa.Column('draft', sa.Boolean(), nullable=False,
                      server_default=sa.text('0')))
        batch_op.create_index(op.f('ix_pull_request_draft'), ['draft'])


def downgrade():
    pass
