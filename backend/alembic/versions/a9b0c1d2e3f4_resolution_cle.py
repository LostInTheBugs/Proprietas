"""AG : résolution sur une clé de répartition (seuls les copropriétaires concernés votent, art. 24 dernier alinéa)

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cle_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_resolutions_cle_id", "cles_repartition", ["cle_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("resolutions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_resolutions_cle_id", type_="foreignkey")
        batch_op.drop_column("cle_id")
