"""Rename project to repository

Revision ID: 536a0daafe68
Revises: 3dbc09758351
Create Date: 2021-08-29 13:10:56.537407

"""

# revision identifiers, used by Alembic.
revision = '536a0daafe68'
down_revision = '3dbc09758351'

from alembic import op


def upgrade():
    op.rename_table('project', 'repository')
    op.rename_table('project_topic', 'repository_topic')

    op.alter_column('branch', 'project_key', new_column_name='repository_key')
    op.alter_column('label', 'project_key', new_column_name='repository_key')
    op.alter_column('pull_request', 'project_key', new_column_name='repository_key')
    op.alter_column('repository_topic', 'project_key', new_column_name='repository_key')

    # Rename indices
    op.drop_index('ix_branch_project_key')
    op.create_index(op.f('ix_branch_repository_key'), "branch", ["repository_key"], unique=False)
    op.drop_index('ix_label_project_key')
    op.create_index(op.f('ix_label_repository_key'), "label", ["repository_key"], unique=False)
    op.drop_index('ix_pull_request_project_key')
    op.create_index(op.f('ix_pull_request_repository_key'), "pull_request", ["repository_key"], unique=False)
    op.drop_index('ix_project_topic_project_key')
    op.create_index(op.f('ix_repository_topic_repository_key'), "repository_topic", ["repository_key"], unique=False)
    op.drop_index('ix_project_topic_topic_key')
    op.create_index(op.f('ix_repository_topic_topic_key'), "repository_topic", ["topic_key"], unique=False)
    op.drop_index('ix_project_subscribed')
    op.create_index(op.f('ix_repository_subscribed'), "repository", ["subscribed"], unique=False)
    op.drop_index('ix_project_name')
    op.create_index(op.f('ix_repository_name'), "repository", ["name"], unique=True)
    pass


def downgrade():
    pass
