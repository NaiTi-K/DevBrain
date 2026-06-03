"""initial migration

Revision ID: 99503ee30569
Revises: 0b98706c2cc4
Create Date: 2026-05-29 09:23:49.854866+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "99503ee30569"
down_revision: Union[str, None] = "0b98706c2cc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("challenges", sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("challenges", sa.Column("examples", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("challenges", sa.Column("starter_code", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("challenges", "starter_code")
    op.drop_column("challenges", "examples")
    op.drop_column("challenges", "constraints")
