"""factures à payer : dépense saisie avant d'être réglée, échéance, date de paiement, rappels

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("a_payer", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("echeance", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("paye_le", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("rappel_avant_le", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("rappel_retard_le", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        for col in ("rappel_retard_le", "rappel_avant_le", "paye_le", "echeance", "a_payer"):
            batch_op.drop_column(col)
