"""messages groupés du syndic aux copropriétaires (historique)

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("auteur_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("envoye_le", sa.DateTime(), nullable=False),
        sa.Column("sujet", sa.String(), nullable=False),
        sa.Column("corps", sa.Text(), nullable=False, server_default=""),
        sa.Column("cible", sa.String(), nullable=False, server_default="tous"),
        sa.Column("cle_nom", sa.String(), nullable=False, server_default=""),
        sa.Column("destinataires", sa.Text(), nullable=False, server_default=""),
        sa.Column("nb_envoyes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("erreurs", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_messages_copropriete_id", "messages", ["copropriete_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_copropriete_id", table_name="messages")
    op.drop_table("messages")
