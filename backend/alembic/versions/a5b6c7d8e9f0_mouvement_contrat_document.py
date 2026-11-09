"""mouvements : contrat et facture (document) rattachés

Un mouvement peut porter un contrat et un document (la facture). Supprimer le contrat ou le
document délie le mouvement (SET NULL). Colonnes nullables : rien ne change pour l'existant.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contrat_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("document_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_mouvements_contrat_id", "contrats", ["contrat_id"], ["id"],
                                    ondelete="SET NULL")
        batch_op.create_foreign_key("fk_mouvements_document_id", "documents", ["document_id"], ["id"],
                                    ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.drop_constraint("fk_mouvements_document_id", type_="foreignkey")
        batch_op.drop_constraint("fk_mouvements_contrat_id", type_="foreignkey")
        batch_op.drop_column("document_id")
        batch_op.drop_column("contrat_id")
