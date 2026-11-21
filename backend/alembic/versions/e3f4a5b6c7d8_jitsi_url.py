"""réunion en ligne : serveur Jitsi de la copropriété

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coproprietes") as b:
        b.add_column(sa.Column("jitsi_url", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("coproprietes") as b:
        b.drop_column("jitsi_url")
