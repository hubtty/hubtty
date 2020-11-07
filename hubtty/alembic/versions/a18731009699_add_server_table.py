"""add_server_table

Revision ID: a18731009699
Revises: 399c4b3dcc9a
Create Date: 2019-08-28 14:12:22.657691

"""

# revision identifiers, used by Alembic.
revision = 'a18731009699'
down_revision = '399c4b3dcc9a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('server',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('own_account_key', sa.Integer(), sa.ForeignKey('account.key'), index=True),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
