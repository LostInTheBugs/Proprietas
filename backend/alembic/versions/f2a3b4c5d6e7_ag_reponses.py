"""AG : réponse des copropriétaires (présent, absent, pouvoir à un autre copropriétaire)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ag_reponses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ag_id", sa.Integer(), sa.ForeignKey("ags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("personne_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reponse", sa.String(), nullable=False),
        sa.Column("mandataire_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("repondu_le", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("pouvoir_recu_le", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("ag_id", "personne_id", name="uq_ag_reponses_ag_personne"),
    )
    op.create_index("ix_ag_reponses_ag_id", "ag_reponses", ["ag_id"])


def downgrade() -> None:
    op.drop_index("ix_ag_reponses_ag_id", table_name="ag_reponses")
    op.drop_table("ag_reponses")
