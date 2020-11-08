"""add columns to change

Revision ID: 83be31a4793a
Revises: 12554687e95c
Create Date: 2020-11-08 18:57:59.752450

"""

# revision identifiers, used by Alembic.
revision = '83be31a4793a'
down_revision = '12554687e95c'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.alter_column('change', 'subject', new_column_name='title')
    op.add_column('change', sa.Column('body', sa.Text(), nullable=False))
    op.add_column('change', sa.Column('additions', sa.Integer(), nullable=False))
    op.add_column('change', sa.Column('deletions', sa.Integer(), nullable=False))


def downgrade():
    pass
