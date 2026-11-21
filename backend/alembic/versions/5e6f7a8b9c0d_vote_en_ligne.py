"""vote en direct pendant l'AG

Revision ID: 5e6f7a8b9c0d
Revises: e3f4a5b6c7d8
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5e6f7a8b9c0d"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("resolutions") as b:
        b.add_column(sa.Column("vote_ouvert_le", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("vote_clos_le", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("resolutions") as b:
        b.drop_column("vote_clos_le")
        b.drop_column("vote_ouvert_le")
