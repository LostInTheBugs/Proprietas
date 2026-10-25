"""appels de fonds : régularisation des charges d'un exercice approuvé

Loi n° 65-557, art. 14-1 ; décret n° 67-223, art. 6-2, 3° : après l'approbation des comptes, le
trop ou moins perçu sur provisions est porté au crédit ou au débit du copropriétaire. L'appel de
régularisation désigne l'exercice régularisé (une seule régularisation par exercice).
Colonne nullable : les appels existants ne sont pas des régularisations.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("appels_fonds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("regularisation_de_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_appels_fonds_regularisation_de_id", "exercices",
            ["regularisation_de_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("appels_fonds", schema=None) as batch_op:
        batch_op.drop_constraint("fk_appels_fonds_regularisation_de_id", type_="foreignkey")
        batch_op.drop_column("regularisation_de_id")
