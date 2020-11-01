"""add-checks

Revision ID: 45d33eccc7a7
Revises: 6f6183367a8f
Create Date: 2020-02-20 13:16:22.342039

"""

# revision identifiers, used by Alembic.
revision = '45d33eccc7a7'
down_revision = '6f6183367a8f'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('checker',
                    sa.Column('key', sa.Integer(), nullable=False),
                    sa.Column('uuid', sa.String(255), index=True, unique=True, nullable=False),
                    sa.Column('name', sa.String(255), nullable=False),
                    sa.Column('status', sa.String(255), nullable=False),
                    sa.Column('blocking', sa.String(255)),
                    sa.Column('description', sa.Text()),
                    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('check',
                    sa.Column('key', sa.Integer(), nullable=False),
                    sa.Column('revision_key', sa.Integer(), index=True),
                    sa.Column('checker_key', sa.Integer(), index=True),
                    sa.Column('state', sa.String(255), nullable=False),
                    sa.Column('url', sa.Text()),
                    sa.Column('message', sa.Text()),
                    sa.Column('started', sa.DateTime()),
                    sa.Column('finished', sa.DateTime()),
                    sa.Column('created', sa.DateTime(), index=True, nullable=False),
                    sa.Column('updated', sa.DateTime(), index=True, nullable=False),
                    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
