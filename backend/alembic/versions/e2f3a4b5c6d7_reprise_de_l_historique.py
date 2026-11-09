"""reprise de l'historique : états de fin d'exercice (31/12) et appels « Reprise de solde »

À la mise en place de l'application, le syndic saisit ce que chaque copropriétaire devait au
31 décembre d'une année (par lot et par exercice d'origine). L'état validé le plus ancien
génère les appels « Reprise de solde » (appels_fonds.reprise_etat_id) ; les plus récents
servent de points de contrôle. Colonne nullable : les appels existants ne sont pas des reprises.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etats_reprise",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("valide", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valide_le", sa.DateTime(), nullable=True),
        sa.Column("commentaire", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("copropriete_id", "date", name="uq_etats_reprise_copro_date"),
    )
    op.create_index("ix_etats_reprise_copropriete_id", "etats_reprise", ["copropriete_id"])
    op.create_table(
        "etats_reprise_lignes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("etat_id", sa.Integer(), sa.ForeignKey("etats_reprise.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("lots.id"), nullable=False),
        sa.Column("proprietaire_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("exercice_origine", sa.Integer(), nullable=False),
        sa.Column("montant_charges", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("montant_fonds_travaux", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("etat_id", "lot_id", "exercice_origine", name="uq_etats_reprise_lignes_lot_exercice"),
    )
    op.create_index("ix_etats_reprise_lignes_etat_id", "etats_reprise_lignes", ["etat_id"])
    with op.batch_alter_table("appels_fonds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reprise_etat_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_appels_fonds_reprise_etat_id", "etats_reprise",
                                    ["reprise_etat_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("appels_fonds", schema=None) as batch_op:
        batch_op.drop_constraint("fk_appels_fonds_reprise_etat_id", type_="foreignkey")
        batch_op.drop_column("reprise_etat_id")
    op.drop_index("ix_etats_reprise_lignes_etat_id", table_name="etats_reprise_lignes")
    op.drop_table("etats_reprise_lignes")
    op.drop_index("ix_etats_reprise_copropriete_id", table_name="etats_reprise")
    op.drop_table("etats_reprise")
