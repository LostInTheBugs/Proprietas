"""exercices : date d'approbation des comptes ; résolutions : exercice approuvé

Art. 19-2 de la loi du 10 juillet 1965 : les restes dus des exercices précédents ne deviennent
exigibles qu'« après approbation des comptes ». La clôture d'un exercice ne vaut pas approbation.
Colonnes nullables : aucune approbation n'est inventée pour les exercices existants ; le syndic
saisit la date de l'AG (page Comptes) ou elle est reportée par une résolution adoptée.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exercices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("comptes_approuves_le", sa.Date(), nullable=True))
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("exercice_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_resolutions_exercice_id", "exercices",
            ["exercice_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_resolutions_exercice_id", type_="foreignkey")
        batch_op.drop_column("exercice_id")
    with op.batch_alter_table("exercices", schema=None) as batch_op:
        batch_op.drop_column("comptes_approuves_le")
