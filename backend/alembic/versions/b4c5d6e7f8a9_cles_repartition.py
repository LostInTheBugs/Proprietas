"""clés de répartition (charges spéciales) : clés, millièmes des lots, clé des lignes de budget, appels et dépenses

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES_CLE = ("budget_lines", "appels_fonds", "mouvements")


def upgrade() -> None:
    op.create_table(
        "cles_repartition",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("nom", sa.String(), nullable=False),
        sa.UniqueConstraint("copropriete_id", "nom", name="uq_cles_repartition_copro_nom"),
    )
    op.create_index("ix_cles_repartition_copropriete_id", "cles_repartition", ["copropriete_id"])
    op.create_table(
        "cles_lots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cle_id", sa.Integer(), sa.ForeignKey("cles_repartition.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("lots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tantiemes", sa.Integer(), nullable=False),
        sa.UniqueConstraint("cle_id", "lot_id", name="uq_cles_lots_cle_lot"),
    )
    op.create_index("ix_cles_lots_cle_id", "cles_lots", ["cle_id"])
    for table in TABLES_CLE:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("cle_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(f"fk_{table}_cle_id", "cles_repartition", ["cle_id"], ["id"])


def downgrade() -> None:
    for table in TABLES_CLE:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_cle_id", type_="foreignkey")
            batch_op.drop_column("cle_id")
    op.drop_index("ix_cles_lots_cle_id", table_name="cles_lots")
    op.drop_table("cles_lots")
    op.drop_index("ix_cles_repartition_copropriete_id", table_name="cles_repartition")
    op.drop_table("cles_repartition")
