"""robot-comments

Revision ID: 6f6183367a8f
Revises: a18731009699
Create Date: 2020-02-20 10:11:56.409361

"""

# revision identifiers, used by Alembic.
revision = '6f6183367a8f'
down_revision = 'a18731009699'

import warnings

from alembic import op
import sqlalchemy as sa


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('comment', sa.Column('robot_id', sa.String(255)))
        op.add_column('comment', sa.Column('robot_run_id', sa.String(255)))
        op.add_column('comment', sa.Column('url', sa.Text()))


def downgrade():
    pass
