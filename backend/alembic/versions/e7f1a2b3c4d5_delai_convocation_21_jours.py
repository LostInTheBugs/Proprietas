"""délai de convocation : envoi automatique au moins 21 jours avant l'AG

Décret n° 67-223 du 17 mars 1967, art. 9 : la convocation est notifiée au moins 21 jours
avant l'assemblée. L'envoi automatique était réglé à 15 jours par défaut : les AG encore
à venir et non convoquées avec un réglage de 1 à 20 jours passent à 21. Le réglage 0
(désactivé) et les AG déjà convoquées ne sont pas modifiés.

Revision ID: e7f1a2b3c4d5
Revises: d4e5f6a7b8c9
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ags = sa.table("ags", sa.column("rappel_jours", sa.Integer),
                   sa.column("convocation_envoyee", sa.Boolean))
    op.execute(
        sa.update(ags)
        .where(ags.c.rappel_jours.between(1, 20))
        .where(sa.or_(ags.c.convocation_envoyee.is_(None), ags.c.convocation_envoyee == sa.false()))
        .values(rappel_jours=21)
    )


def downgrade() -> None:
    # Donnée corrigée (non réversible de façon fiable) : rien à défaire.
    pass
