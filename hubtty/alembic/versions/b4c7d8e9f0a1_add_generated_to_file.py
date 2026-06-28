"""Drop generated column from file table (if present)

The generated-file status is now computed dynamically at view time
using ``GeneratedFileFilter`` instead of being cached in the DB.

Revision ID: b4c7d8e9f0a1
Revises: f3a1b2c4d5e6
Create Date: 2026-06-28 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'b4c7d8e9f0a1'
down_revision = 'f3a1b2c4d5e6'

from alembic import op
import sqlalchemy as sa


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('file')]
    if 'generated' in columns:
        with op.batch_alter_table('file') as batch_op:
            batch_op.drop_column('generated')


def downgrade():
    with op.batch_alter_table('file') as batch_op:
        batch_op.add_column(
            sa.Column('generated', sa.Boolean(), nullable=False,
                      server_default=sa.text('0')))
