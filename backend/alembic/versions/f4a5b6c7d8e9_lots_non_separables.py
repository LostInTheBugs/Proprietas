"""lots non séparables : lot annexe rattaché à un lot principal

Un lot annexe (cave, garage…) rattaché à un lot principal est vendu et suivi avec lui :
décompte, recouvrement, relances, tableau de bord et quittances par ensemble.
Colonne nullable : les lots existants restent séparés.

Revision ID: f4a5b6c7d8e9
Revises: e2f3a4b5c6d7
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("lots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lot_principal_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_lots_lot_principal_id", "lots", ["lot_principal_id"], ["id"],
                                    ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("lots", schema=None) as batch_op:
        batch_op.drop_constraint("fk_lots_lot_principal_id", type_="foreignkey")
        batch_op.drop_column("lot_principal_id")
