"""supervision : incidents (alertes par e-mail)

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-11-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, Sequence[str], None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents_serveur",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("debut", sa.DateTime(), nullable=False),
        sa.Column("fin", sa.DateTime(), nullable=True),
        sa.Column("detail", sa.String(), nullable=False, server_default=""),
        sa.Column("dernier_envoi", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_incidents_serveur_code", "incidents_serveur", ["code"])


def downgrade() -> None:
    op.drop_index("ix_incidents_serveur_code", table_name="incidents_serveur")
    op.drop_table("incidents_serveur")
