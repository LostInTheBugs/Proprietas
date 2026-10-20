"""second vote immédiat (passerelles art. 25-1 / 26-1)

Revision ID: c7a1e2b3d4f5
Revises: 840f497d9a3c
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7a1e2b3d4f5"
down_revision: Union[str, Sequence[str], None] = "840f497d9a3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("second_vote_de_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_resolutions_second_vote_de_id", "resolutions",
            ["second_vote_de_id"], ["id"], ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_resolutions_second_vote_de_id", type_="foreignkey")
        batch_op.drop_column("second_vote_de_id")
