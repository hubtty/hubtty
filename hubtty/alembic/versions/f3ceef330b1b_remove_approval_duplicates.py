"""Remove approval duplicates

Revision ID: f3ceef330b1b
Revises: 9ab0f566d94b
Create Date: 2021-03-05 09:50:46.558386

"""

# revision identifiers, used by Alembic.
revision = 'f3ceef330b1b'
down_revision = '9ab0f566d94b'

from alembic import op


def upgrade():
    connection = op.get_bind()
    connection.execute('delete from approval where key not in (select max(key) from approval group by change_key,account_key,sha)')

    op.create_index(op.f('ix_approval'), "approval", ["change_key", "account_key", "sha"])

def downgrade():
    pass
