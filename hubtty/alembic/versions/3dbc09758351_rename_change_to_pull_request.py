"""Rename change to pull request

Revision ID: 3dbc09758351
Revises: 79d141409a92
Create Date: 2021-08-28 16:03:43.802026

"""

# revision identifiers, used by Alembic.
revision = '3dbc09758351'
down_revision = '79d141409a92'

from alembic import op


def upgrade():
    op.rename_table('change', 'pull_request')
    op.rename_table('change_label', 'pull_request_label')

    op.alter_column('commit', 'change_key', new_column_name='pr_key')
    op.alter_column('message', 'change_key', new_column_name='pr_key')
    op.alter_column('approval', 'change_key', new_column_name='pr_key')
    op.alter_column('pending_merge', 'change_key', new_column_name='pr_key')
    op.alter_column('pull_request_label', 'change_key', new_column_name='pr_key')

    op.alter_column('pull_request', 'change_id', new_column_name='pr_id')

    # Rename indices
    op.drop_index('ix_change_account_key')
    op.create_index(op.f('ix_pull_request_account_key'), "pull_request", ["account_key"], unique=False)
    op.drop_index('ix_change_branch')
    op.create_index(op.f('ix_pull_request_branch'), "pull_request", ["branch"], unique=False)
    op.drop_index('ix_change_change_id')
    op.create_index(op.f('ix_pull_request_pr_id'), "pull_request", ["pr_id"], unique=True)
    op.drop_index('ix_change_created')
    op.create_index(op.f('ix_pull_request_created'), "pull_request", ["created"], unique=False)
    op.drop_index('ix_change_held')
    op.create_index(op.f('ix_pull_request_held'), "pull_request", ["held"], unique=False)
    op.drop_index('ix_change_hidden')
    op.create_index(op.f('ix_pull_request_hidden'), "pull_request", ["hidden"], unique=False)
    op.drop_index('ix_change_id')
    op.create_index(op.f('ix_pull_request_id'), "pull_request", ["id"], unique=False)
    op.drop_index('ix_change_last_seen')
    op.create_index(op.f('ix_pull_request_last_seen'), "pull_request", ["last_seen"], unique=False)
    op.drop_index('ix_change_mergeable')
    op.create_index(op.f('ix_pull_request_mergeable'), "pull_request", ["mergeable"], unique=False)
    op.drop_index('ix_change_merged')
    op.create_index(op.f('ix_pull_request_merged'), "pull_request", ["merged"], unique=False)
    op.drop_index('ix_change_number')
    op.create_index(op.f('ix_pull_request_number'), "pull_request", ["number"], unique=False)
    op.drop_index('ix_change_outdated')
    op.create_index(op.f('ix_pull_request_outdated'), "pull_request", ["outdated"], unique=False)
    op.drop_index('ix_change_pending_edit')
    op.create_index(op.f('ix_pull_request_pending_edit'), "pull_request", ["pending_edit"], unique=False)
    op.drop_index('ix_change_pending_hashtags')
    op.create_index(op.f('ix_pull_request_pending_labels'), "pull_request", ["pending_labels"], unique=False)
    op.drop_index('ix_change_pending_rebase')
    op.create_index(op.f('ix_pull_request_pending_rebase'), "pull_request", ["pending_rebase"], unique=False)
    op.drop_index('ix_change_project_key')
    op.create_index(op.f('ix_pull_request_project_key'), "pull_request", ["project_key"], unique=False)
    op.drop_index('ix_change_reviewed')
    op.create_index(op.f('ix_pull_request_reviewed'), "pull_request", ["reviewed"], unique=False)
    op.drop_index('ix_change_starred')
    op.create_index(op.f('ix_pull_request_starred'), "pull_request", ["starred"], unique=False)
    op.drop_index('ix_change_state')
    op.create_index(op.f('ix_pull_request_state'), "pull_request", ["state"], unique=False)
    op.drop_index('ix_change_updated')
    op.create_index(op.f('ix_pull_request_updated'), "pull_request", ["updated"], unique=False)
    op.drop_index('ix_change_label_change_key')
    op.create_index(op.f('ix_pull_request_label_pr_key'), "pull_request_label", ["pr_key"], unique=False)
    op.drop_index('ix_change_label_label_key')
    op.create_index(op.f('ix_pull_request_label_label_key'), "pull_request_label", ["label_key"], unique=False)
    op.drop_index('ix_approval_change_key')
    op.create_index(op.f('ix_approval_pr_key'), "approval", ["pr_key"], unique=False)
    op.drop_index('ix_commit_change_key')
    op.create_index(op.f('ix_commit_pr_key'), "commit", ["pr_key"], unique=False)
    op.drop_index('ix_message_change_key')
    op.create_index(op.f('ix_message_pr_key'), "message", ["pr_key"], unique=False)
    op.drop_index('ix_pending_merge_change_key')
    op.create_index(op.f('ix_pending_merge_pr_key'), "pending_merge", ["pr_key"], unique=False)
    pass


def downgrade():
    pass
