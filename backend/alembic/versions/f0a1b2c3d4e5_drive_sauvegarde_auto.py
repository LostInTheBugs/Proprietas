"""sauvegarde automatique de la copropriété sur son drive

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("drive_sauvegarde_auto", sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column("drive_sauvegarde_password", sa.String(), nullable=True, server_default=""))
        batch_op.add_column(sa.Column("drive_sauvegarde_derniere", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("drive_sauvegarde_tentative", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("drive_sauvegarde_erreur", sa.String(), nullable=True, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        for nom in ("drive_sauvegarde_erreur", "drive_sauvegarde_tentative", "drive_sauvegarde_derniere",
                    "drive_sauvegarde_password", "drive_sauvegarde_auto"):
            batch_op.drop_column(nom)
