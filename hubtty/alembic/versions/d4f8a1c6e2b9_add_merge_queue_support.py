"""Add merge-queue and merge-method support

Adds the repository-level allowed-merge-method flags
(allow_merge_commit/allow_squash_merge/allow_rebase_merge/allow_auto_merge),
the pull-request-level node_id (GraphQL global id), and the
branch-level merge_queue_required/merge_queue_method columns used to
make the merge dialog dynamic.

Revision ID: d4f8a1c6e2b9
Revises: b4c7d8e9f0a1
Create Date: 2026-10-12 06:09:04.000000

"""

# revision identifiers, used by Alembic.
revision = 'd4f8a1c6e2b9'
down_revision = 'b4c7d8e9f0a1'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('repository') as batch_op:
        batch_op.add_column(
            sa.Column('allow_merge_commit', sa.Boolean(), nullable=False,
                      server_default=sa.text('1')))
        batch_op.add_column(
            sa.Column('allow_squash_merge', sa.Boolean(), nullable=False,
                      server_default=sa.text('1')))
        batch_op.add_column(
            sa.Column('allow_rebase_merge', sa.Boolean(), nullable=False,
                      server_default=sa.text('1')))
        batch_op.add_column(
            sa.Column('allow_auto_merge', sa.Boolean(), nullable=False,
                      server_default=sa.text('0')))

    with op.batch_alter_table('pull_request') as batch_op:
        batch_op.add_column(sa.Column('node_id', sa.String(length=255)))
        batch_op.create_index(op.f('ix_pull_request_node_id'), ['node_id'])

    with op.batch_alter_table('branch') as batch_op:
        batch_op.add_column(
            sa.Column('merge_queue_required', sa.Boolean(), nullable=False,
                      server_default=sa.text('0')))
        batch_op.add_column(sa.Column('merge_queue_method', sa.String(length=32)))


def downgrade():
    with op.batch_alter_table('branch') as batch_op:
        batch_op.drop_column('merge_queue_method')
        batch_op.drop_column('merge_queue_required')

    with op.batch_alter_table('pull_request') as batch_op:
        batch_op.drop_index(op.f('ix_pull_request_node_id'))
        batch_op.drop_column('node_id')

    with op.batch_alter_table('repository') as batch_op:
        batch_op.drop_column('allow_auto_merge')
        batch_op.drop_column('allow_rebase_merge')
        batch_op.drop_column('allow_squash_merge')
        batch_op.drop_column('allow_merge_commit')
