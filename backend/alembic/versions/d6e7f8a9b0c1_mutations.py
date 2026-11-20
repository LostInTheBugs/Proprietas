"""vente d'un lot : mutations (vendeur, acquéreur, notification, avis de mutation) et encaissements du solde du vendeur

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mutations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date_acte", sa.Date(), nullable=False),
        sa.Column("vendeur_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("acquereur_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendeur_nom", sa.String(), nullable=False, server_default=""),
        sa.Column("acquereur_nom", sa.String(), nullable=False, server_default=""),
        sa.Column("notaire", sa.String(), nullable=False, server_default=""),
        sa.Column("notifiee_le", sa.Date(), nullable=True),
        sa.Column("avis_mutation_le", sa.Date(), nullable=True),
        sa.Column("opposition_le", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(), nullable=False, server_default=""),
        sa.Column("creee_le", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mutations_copropriete_id", "mutations", ["copropriete_id"])
    op.create_index("ix_mutations_lot_id", "mutations", ["lot_id"])
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mutation_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_mouvements_mutation_id", "mutations", ["mutation_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_mouvements_mutation_id", ["mutation_id"])


def downgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.drop_index("ix_mouvements_mutation_id")
        batch_op.drop_constraint("fk_mouvements_mutation_id", type_="foreignkey")
        batch_op.drop_column("mutation_id")
    op.drop_index("ix_mutations_lot_id", table_name="mutations")
    op.drop_index("ix_mutations_copropriete_id", table_name="mutations")
    op.drop_table("mutations")
