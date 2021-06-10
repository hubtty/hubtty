"""Add missing indices

Revision ID: fb283799c60d
Revises: 579571523a48
Create Date: 2021-03-14 08:49:30.259012

"""

# revision identifiers, used by Alembic.
revision = 'fb283799c60d'
down_revision = '579571523a48'

from alembic import op


def upgrade():
    # Missing indices
    op.create_index(op.f('ix_approval_state'), 'approval', ['state'], unique=False)
    op.create_index(op.f('ix_branch_name'), 'branch', ['name'], unique=False)
    op.create_index(op.f('ix_change_number'), 'change', ['number'], unique=False)
    op.create_index(op.f('ix_check_name'), 'check', ['name'], unique=False)
    op.create_index(op.f('ix_comment_line'), 'comment', ['line'], unique=False)
    op.create_index(op.f('ix_comment_line_created'), 'comment', ['line', 'created'], unique=False)
    op.create_index(op.f('ix_comment_file_key'), 'comment', ['file_key'], unique=False)
    op.create_index(op.f('ix_comment_in_reply_to'), 'comment', ['in_reply_to'], unique=False)
    op.create_index(op.f('ix_file_status'), 'file', ['status'], unique=False)

    # Missing uniqueness constraints
    op.drop_index('ix_approval')
    op.create_index(op.f('ix_approval'), "approval", ["change_key", "account_key", "sha"], unique=True)
    op.drop_index('ix_change_change_id')
    op.create_index(op.f('ix_change_change_id'), "change", ["change_id"], unique=True)

    # Rename indices to match db schema
    op.drop_index('ix_change_status')
    op.create_index(op.f('ix_change_state'), 'change', ['state'], unique=False)
    op.drop_index('ix_check_revision_key')
    op.create_index(op.f('ix_check_commit_key'), 'check', ['commit_key'], unique=False)
    op.drop_index('ix_file_revision_key')
    op.create_index(op.f('ix_file_commit_key'), 'file', ['commit_key'], unique=False)
    op.drop_index('ix_message_revision_key')
    op.create_index(op.f('ix_message_commit_key'), 'message', ['commit_key'], unique=False)
    op.drop_index('ix_pending_cherry_pick_revision_key')
    op.create_index(op.f('ix_pending_cherry_pick_commit_key'), 'pending_cherry_pick', ['commit_key'], unique=False)
    op.drop_index('ix_revision_change_key')
    op.create_index(op.f('ix_commit_change_key'), 'commit', ['change_key'], unique=False)
    op.drop_index('ix_revision_commit')
    op.create_index(op.f('ix_commit_sha'), 'commit', ['sha'], unique=False)
    op.drop_index('ix_revision_parent')
    op.create_index(op.f('ix_commit_parent'), 'commit', ['parent'], unique=False)
    op.drop_index('ix_revision_pending_message')
    op.create_index(op.f('ix_commit_pending_message'), 'commit', ['pending_message'], unique=False)

    # Drop unused indices
    op.drop_index('ix_check_updated')
    op.drop_index('ix_check_created')
    op.drop_index('ix_project_updated')
    op.drop_index('ix_sync_query_updated')


def downgrade():
    pass
