"""Add pending_merge table

Revision ID: f8109f9cde46
Revises: 439753e172a0
Create Date: 2021-06-12 15:51:10.914705

"""

# revision identifiers, used by Alembic.
revision = 'f8109f9cde46'
down_revision = '439753e172a0'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('pending_merge',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('change_key', sa.Integer(), sa.ForeignKey('change.key'), index=True, nullable=False),
    sa.Column('commit_title', sa.String(length=255)),
    sa.Column('commit_message', sa.Text()),
    sa.Column('sha', sa.String(length=255), nullable=False),
    sa.Column('merge_method', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
