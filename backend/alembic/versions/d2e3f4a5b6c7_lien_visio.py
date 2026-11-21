"""réunion en ligne : lien de visioconférence de l'AG

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ags") as b:
        b.add_column(sa.Column("lien_visio", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("ags") as b:
        b.drop_column("lien_visio")
