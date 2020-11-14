"""add html_url for PRs

Revision ID: 175ea25b42d5
Revises: 83be31a4793a
Create Date: 2020-11-14 21:17:12.306252

"""

# revision identifiers, used by Alembic.
revision = '175ea25b42d5'
down_revision = '83be31a4793a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('change', sa.Column('html_url', sa.String(length=255), nullable=False))


def downgrade():
    pass
