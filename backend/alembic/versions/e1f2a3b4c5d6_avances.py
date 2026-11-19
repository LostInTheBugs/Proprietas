"""avances : une personne paie une dépense de la copropriété, remboursée ou déduite de ses charges

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avance_par_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("hors_banque", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.create_index("ix_mouvements_avance_par_id", ["avance_par_id"])
        batch_op.create_foreign_key("fk_mouvements_avance_par_id_users", "users", ["avance_par_id"], ["id"],
                                    ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("mouvements", schema=None) as batch_op:
        batch_op.drop_constraint("fk_mouvements_avance_par_id_users", type_="foreignkey")
        batch_op.drop_index("ix_mouvements_avance_par_id")
        batch_op.drop_column("hors_banque")
        batch_op.drop_column("avance_par_id")
