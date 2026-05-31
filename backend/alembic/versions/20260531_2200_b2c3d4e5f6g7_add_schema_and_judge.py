"""add schema and judge columns

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31 22:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # We use IF NOT EXISTS just to be safe if the user added it via clear_db.py
    op.execute('ALTER TABLE challenges ADD COLUMN IF NOT EXISTS schema JSONB;')
    op.execute("ALTER TABLE challenges ADD COLUMN IF NOT EXISTS judge VARCHAR(50) DEFAULT 'exact' NOT NULL;")


def downgrade() -> None:
    op.drop_column('challenges', 'schema')
    op.drop_column('challenges', 'judge')
