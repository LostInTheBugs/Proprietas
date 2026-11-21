"""mandats du syndic bénévole et du conseil syndical

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mandats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("debut", sa.Date(), nullable=False),
        sa.Column("fin", sa.Date(), nullable=False),
        sa.Column("membres", sa.JSON(), nullable=False),
        sa.Column("ag_id", sa.Integer(), sa.ForeignKey("ags.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_id", sa.Integer(), sa.ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_mandats_copropriete_id", "mandats", ["copropriete_id"])
    op.create_index("ix_mandats_resolution_id", "mandats", ["resolution_id"])
    with op.batch_alter_table("resolutions") as b:
        b.add_column(sa.Column("mandat_mois", sa.Integer(), nullable=True))
        b.add_column(sa.Column("mandat_personnes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("resolutions") as b:
        b.drop_column("mandat_personnes")
        b.drop_column("mandat_mois")
    op.drop_index("ix_mandats_resolution_id", table_name="mandats")
    op.drop_index("ix_mandats_copropriete_id", table_name="mandats")
    op.drop_table("mandats")
