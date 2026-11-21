"""supervision : relevés de l'état du serveur

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-11-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, Sequence[str], None] = "5e6f7a8b9c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mesures_serveur",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instant", sa.DateTime(), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("memoire_pct", sa.Float(), nullable=True),
        sa.Column("disque_pct", sa.Float(), nullable=True),
        sa.Column("requetes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("erreurs_5xx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latence_moy_ms", sa.Float(), nullable=True),
        sa.Column("latence_p95_ms", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="application"),
    )
    op.create_index("ix_mesures_serveur_instant", "mesures_serveur", ["instant"])


def downgrade() -> None:
    op.drop_index("ix_mesures_serveur_instant", table_name="mesures_serveur")
    op.drop_table("mesures_serveur")
