"""Add change_label table

Revision ID: 4fb888763b3b
Revises: 2b367b62fb13
Create Date: 2021-06-20 13:23:37.038252

"""

# revision identifiers, used by Alembic.
revision = '4fb888763b3b'
down_revision = '2b367b62fb13'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('change_label',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('change_key', sa.Integer(), sa.ForeignKey('change.key'), index=True),
    sa.Column('label_key', sa.Integer(), sa.ForeignKey('label.key'), index=True),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
