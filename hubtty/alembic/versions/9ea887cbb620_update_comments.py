"""Update comments

Revision ID: 9ea887cbb620
Revises: fc35305967d4
Create Date: 2020-12-18 17:23:50.956084

"""

# revision identifiers, used by Alembic.
revision = '9ea887cbb620'
down_revision = 'fc35305967d4'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # TODO(mandre) add a foreign key contraint for change_key
    op.add_column('comment', sa.Column('change_key', sa.Integer(), nullable=False, index=True))
    op.add_column('comment', sa.Column('updated', sa.DateTime(), nullable=False))
    op.add_column('comment', sa.Column('commit_id', sa.String(length=255), nullable=False))
    op.add_column('comment', sa.Column('original_commit_id', sa.String(length=255), nullable=False))
    op.add_column('comment', sa.Column('original_line', sa.Integer(), nullable=False))


def downgrade():
    pass
