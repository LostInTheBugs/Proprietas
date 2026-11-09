"""états de reprise : soldes bancaires (compte du syndicat, compte du fonds de travaux)

Facultatifs (NULL = non saisi) : rien ne change pour les états existants.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("etats_reprise", schema=None) as batch_op:
        batch_op.add_column(sa.Column("solde_banque", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("solde_banque_fonds", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("etats_reprise", schema=None) as batch_op:
        batch_op.drop_column("solde_banque_fonds")
        batch_op.drop_column("solde_banque")
