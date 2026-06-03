"""add summary to skill profiles

Revision ID: 1a2b3c4d5e6f
Revises: 99503ee30569
Create Date: 2026-05-29 17:47:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "99503ee30569"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skill_profiles", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_profiles", "summary")
