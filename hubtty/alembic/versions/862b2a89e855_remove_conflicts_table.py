"""remove conflicts table

Revision ID: 862b2a89e855
Revises: 175ea25b42d5
Create Date: 2020-11-14 10:07:35.141272

"""

# revision identifiers, used by Alembic.
revision = '862b2a89e855'
down_revision = '175ea25b42d5'

from alembic import op


def upgrade():
    op.drop_table('change_conflict')


def downgrade():
    pass
