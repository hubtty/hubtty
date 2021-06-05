"""Add can_push to project

Revision ID: 4a2afc48dd09
Revises: 21d691c40b39
Create Date: 2021-06-05 17:26:00.883182

"""

# revision identifiers, used by Alembic.
revision = '4a2afc48dd09'
down_revision = '21d691c40b39'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('project', sa.Column('can_push', sa.Boolean()))


def downgrade():
    pass
