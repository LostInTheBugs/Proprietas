"""relevés bancaires : lignes importées et rapprochement des opérations (mouvements.releve_ligne_id)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "releve_lignes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("copropriete_id", sa.Integer(), sa.ForeignKey("coproprietes.id"), nullable=False),
        sa.Column("compte", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("libelle", sa.String(), nullable=False, server_default=""),
        sa.Column("montant", sa.Numeric(12, 2), nullable=False),
        sa.Column("empreinte", sa.String(), nullable=False),
        sa.Column("fichier", sa.String(), nullable=False, server_default=""),
        sa.Column("importe_le", sa.DateTime(), nullable=False),
        sa.Column("ignoree", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("copropriete_id", "compte", "empreinte", name="uq_releve_lignes_empreinte"),
    )
    op.create_index("ix_releve_lignes_copropriete_id", "releve_lignes", ["copropriete_id"])
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("releve_ligne_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_mouvements_releve_ligne_id", "releve_lignes", ["releve_ligne_id"], ["id"],
                                    ondelete="SET NULL")
        batch_op.create_index("ix_mouvements_releve_ligne_id", ["releve_ligne_id"])


def downgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.drop_index("ix_mouvements_releve_ligne_id")
        batch_op.drop_constraint("fk_mouvements_releve_ligne_id", type_="foreignkey")
        batch_op.drop_column("releve_ligne_id")
    op.drop_index("ix_releve_lignes_copropriete_id", table_name="releve_lignes")
    op.drop_table("releve_lignes")
