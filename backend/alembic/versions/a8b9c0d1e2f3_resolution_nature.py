"""résolutions : nature de la décision (autre | budget | approbation_comptes)

Consultation écrite (art. 41-12 de la loi du 10 juillet 1965) : le vote du budget prévisionnel
et l'approbation des comptes en sont exclus. Les résolutions existantes reçoivent « autre » :
rien n'est deviné à partir du libellé.

Revision ID: a8b9c0d1e2f3
Revises: f3a4b5c6d7e8
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nature", sa.String(), nullable=False, server_default="autre"))


def downgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.drop_column("nature")
