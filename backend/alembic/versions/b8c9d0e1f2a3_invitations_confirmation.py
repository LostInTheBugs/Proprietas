"""e-mails d'information sur l'AG : lien personnel de confirmation de réception

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jeton", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("confirme_le", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_invitations_jeton", ["jeton"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.drop_index("ix_invitations_jeton")
        batch_op.drop_column("confirme_le")
        batch_op.drop_column("jeton")
