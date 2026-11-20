"""annexes comptables : catégorie de charges des lignes de budget (comparaison budget / réalisé)

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("budget_lines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("categorie", sa.String(), nullable=False, server_default="charges"))


def downgrade() -> None:
    with op.batch_alter_table("budget_lines", schema=None) as batch_op:
        batch_op.drop_column("categorie")
