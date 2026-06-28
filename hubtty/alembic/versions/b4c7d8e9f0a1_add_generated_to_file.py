"""Add generated column to file table

Revision ID: b4c7d8e9f0a1
Revises: f3a1b2c4d5e6
Create Date: 2026-06-28 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'b4c7d8e9f0a1'
down_revision = 'f3a1b2c4d5e6'

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('file') as batch_op:
        batch_op.add_column(
            sa.Column('generated', sa.Boolean(), nullable=False,
                      server_default=sa.text('0')))

    # Backfill existing rows: mark files whose path matches a built-in
    # generated-file pattern.  Only built-in heuristics are applied
    # here (no .gitattributes or user config available at migration
    # time); newly synced files will pick up all sources at sync time.
    from hubtty.generated import BUILTIN_GENERATED_PATTERNS, _match_pattern

    conn = op.get_bind()
    result = conn.execute(sa.text('SELECT key, path FROM file'))

    keys_to_update = []
    while True:
        rows = result.fetchmany(1000)
        if not rows:
            break
        for key, path in rows:
            for pattern in BUILTIN_GENERATED_PATTERNS:
                if _match_pattern(pattern, path):
                    keys_to_update.append(int(key))
                    break

    # Batch UPDATE to avoid overly large statements.
    batch_size = 500
    for i in range(0, len(keys_to_update), batch_size):
        chunk = keys_to_update[i:i + batch_size]
        conn.execute(
            sa.text('UPDATE file SET generated = 1 WHERE key IN :keys').bindparams(
                sa.bindparam('keys', value=chunk, expanding=True)
            )
        )


def downgrade():
    with op.batch_alter_table('file') as batch_op:
        batch_op.drop_column('generated')
