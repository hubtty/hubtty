"""Deduplicate checks and add unique constraint on (commit_key, name)

Revision ID: f3a1b2c4d5e6
Revises: 1e41885ea284
Create Date: 2026-06-04 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'f3a1b2c4d5e6'
down_revision = '1e41885ea284'

from alembic import op


def upgrade():
    # Step 1: Delete duplicate check rows, keeping the one with the
    # highest key (most recently inserted) for each (commit_key, name)
    # pair.
    op.execute("""
        DELETE FROM "check"
        WHERE key NOT IN (
            SELECT MAX(key)
            FROM "check"
            GROUP BY commit_key, name
        )
    """)

    # Step 2: Add unique constraint to prevent future duplicates
    with op.batch_alter_table('check') as batch_op:
        batch_op.create_unique_constraint(
            'uq_check_commit_key_name', ['commit_key', 'name']
        )


def downgrade():
    with op.batch_alter_table('check') as batch_op:
        batch_op.drop_constraint('uq_check_commit_key_name', type_='unique')
