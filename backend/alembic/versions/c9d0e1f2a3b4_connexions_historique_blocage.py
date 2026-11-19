"""connexions : historique activable et blocage des comptes après des échecs

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-19

Les copropriétés existantes gardent l'historique complet des connexions (le journal d'audit
les enregistrait déjà toutes) ; les nouvelles ne gardent que la dernière connexion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connexions_historique", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("verrouillage_actif", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("verrouillage_seuil", sa.Integer(), nullable=False, server_default=sa.text("5")))
        batch_op.add_column(sa.Column("verrouillage_minutes", sa.Integer(), nullable=False, server_default=sa.text("15")))
        batch_op.add_column(sa.Column("verrouillage_seuil_definitif", sa.Integer(), nullable=False, server_default=sa.text("10")))
        batch_op.add_column(sa.Column("verrouillage_avec_2fa", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("echecs_connexion", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("dernier_echec_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("bloque_jusqua", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("bloque_definitif_le", sa.DateTime(), nullable=True))
    op.execute(sa.text("UPDATE coproprietes SET connexions_historique = true"))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("bloque_definitif_le")
        batch_op.drop_column("bloque_jusqua")
        batch_op.drop_column("dernier_echec_at")
        batch_op.drop_column("echecs_connexion")
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        batch_op.drop_column("verrouillage_avec_2fa")
        batch_op.drop_column("verrouillage_seuil_definitif")
        batch_op.drop_column("verrouillage_minutes")
        batch_op.drop_column("verrouillage_seuil")
        batch_op.drop_column("verrouillage_actif")
        batch_op.drop_column("connexions_historique")
