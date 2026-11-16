"""soldes bancaires au 31 décembre dans leur propre table (au lieu de colonnes des états de reprise)

Un solde bancaire se saisit désormais pour un 31 décembre, avec ou sans état de l'historique à cette
date (tableau des soldes au 1er janvier). Les soldes déjà saisis sur des états y sont recopiés.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soldes_bancaires",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("solde_syndicat", sa.Numeric(12, 2), nullable=True),
        sa.Column("solde_fonds", sa.Numeric(12, 2), nullable=True),
        sa.UniqueConstraint("copropriete_id", "date", name="uq_soldes_bancaires_copro_date"),
    )
    op.create_index("ix_soldes_bancaires_copropriete_id", "soldes_bancaires", ["copropriete_id"])
    op.execute(
        "INSERT INTO soldes_bancaires (copropriete_id, date, solde_syndicat, solde_fonds) "
        "SELECT copropriete_id, date, solde_banque, solde_banque_fonds FROM etats_reprise "
        "WHERE solde_banque IS NOT NULL OR solde_banque_fonds IS NOT NULL")
    with op.batch_alter_table("etats_reprise", schema=None) as batch_op:
        batch_op.drop_column("solde_banque_fonds")
        batch_op.drop_column("solde_banque")


def downgrade() -> None:
    with op.batch_alter_table("etats_reprise", schema=None) as batch_op:
        batch_op.add_column(sa.Column("solde_banque", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("solde_banque_fonds", sa.Numeric(12, 2), nullable=True))
    # Seuls les soldes à la date d'un état y retournent (ceux saisis sans état sont perdus).
    op.execute(
        "UPDATE etats_reprise SET "
        "solde_banque = (SELECT s.solde_syndicat FROM soldes_bancaires s "
        "  WHERE s.copropriete_id = etats_reprise.copropriete_id AND s.date = etats_reprise.date), "
        "solde_banque_fonds = (SELECT s.solde_fonds FROM soldes_bancaires s "
        "  WHERE s.copropriete_id = etats_reprise.copropriete_id AND s.date = etats_reprise.date)")
    op.drop_index("ix_soldes_bancaires_copropriete_id", table_name="soldes_bancaires")
    op.drop_table("soldes_bancaires")
