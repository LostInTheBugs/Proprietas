"""vote par correspondance : votes reçus par résolution, résolution amendée en séance

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "votes_correspondance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ag_id", sa.Integer(), sa.ForeignKey("ags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resolution_id", sa.Integer(), sa.ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("personne_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voix", sa.String(), nullable=False, server_default=""),
        sa.Column("recu_le", sa.Date(), nullable=False),
        sa.UniqueConstraint("resolution_id", "personne_id", name="uq_votes_correspondance_res_personne"),
    )
    op.create_index("ix_votes_correspondance_ag_id", "votes_correspondance", ["ag_id"])
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("amendee", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.drop_column("amendee")
    op.drop_index("ix_votes_correspondance_ag_id", table_name="votes_correspondance")
    op.drop_table("votes_correspondance")
