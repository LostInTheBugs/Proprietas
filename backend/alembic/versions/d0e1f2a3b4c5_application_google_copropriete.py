"""drive : application Google (identifiant et code secret) saisie par copropriété

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-19

Vides : l'application Google de l'instance (COPRO_GOOGLE_CLIENT_ID / _SECRET dans le .env) sert, comme avant.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("google_client_id", sa.String(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("google_client_secret", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        batch_op.drop_column("google_client_secret")
        batch_op.drop_column("google_client_id")
