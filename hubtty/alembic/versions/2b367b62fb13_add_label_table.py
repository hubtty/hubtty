"""Add label table

Revision ID: 2b367b62fb13
Revises: f8109f9cde46
Create Date: 2021-06-20 10:06:13.635727

"""

# revision identifiers, used by Alembic.
revision = '2b367b62fb13'
down_revision = 'f8109f9cde46'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('label',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('project_key', sa.Integer(), sa.ForeignKey('project.key'), index=True),
    sa.Column('id', sa.Integer(), nullable=False, index=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('color', sa.String(length=8), nullable=False),
    sa.Column('description', sa.Text()),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
