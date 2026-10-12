"""Add author_association to pull_request

Used to skip the workflow-runs API call for trusted authors
(MEMBER, COLLABORATOR, OWNER) whose workflows auto-run.

Revision ID: a7b3c9d2e1f4
Revises: efa74392eb65
Create Date: 2025-06-28 14:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'a7b3c9d2e1f4'
down_revision = 'efa74392eb65'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('pull_request') as batch_op:
        batch_op.add_column(sa.Column('author_association', sa.String(32)))


def downgrade():
    with op.batch_alter_table('pull_request') as batch_op:
        batch_op.drop_column('author_association')
