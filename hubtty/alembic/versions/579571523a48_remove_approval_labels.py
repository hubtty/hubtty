"""Remove approval labels

Revision ID: 579571523a48
Revises: b22d9336aba0
Create Date: 2021-03-13 13:43:35.020143

"""

# revision identifiers, used by Alembic.
revision = '579571523a48'
down_revision = 'b22d9336aba0'

from alembic import op


def upgrade():
    op.drop_table('label')
    op.drop_table('permitted_label')


def downgrade():
    pass
