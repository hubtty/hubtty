"""Add run_id to check

Stores the workflow run ID for checks needing manual approval.

Revision ID: efa74392eb65
Revises: d4f8a1c6e2b9
Create Date: 2026-10-12 17:30:04.039983

"""

# revision identifiers, used by Alembic.
revision = 'efa74392eb65'
down_revision = 'd4f8a1c6e2b9'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('check') as batch_op:
        batch_op.add_column(sa.Column('run_id', sa.BigInteger()))


def downgrade():
    with op.batch_alter_table('check') as batch_op:
        batch_op.drop_column('run_id')
