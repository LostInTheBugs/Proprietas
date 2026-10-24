"""mise en demeure : date de première présentation / avis électronique / remise

Le délai de 30 jours de l'art. 19-2 court à compter du lendemain de cette date (décret
n° 67-223, art. 64 et 64-1), et non de la date d'envoi. Colonne nullable : les mises en
demeure existantes n'ont pas cette date ; leur statut devient « date de présentation à
saisir » jusqu'à ce que le syndic la renseigne (rien n'est inventé).

Revision ID: f3a4b5c6d7e8
Revises: e7f1a2b3c4d5
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e7f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("actes_recouvrement", schema=None) as batch_op:
        batch_op.add_column(sa.Column("date_reception", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("actes_recouvrement", schema=None) as batch_op:
        batch_op.drop_column("date_reception")
