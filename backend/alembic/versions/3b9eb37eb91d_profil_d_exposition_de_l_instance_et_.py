"""profil d'exposition de l'instance + révocation de sessions

- instance_state : ligne unique (mode local|vps|maison, URL publique, détection
  de la 1re requête externe, dernier diagnostic d'exposition).
- users.token_version : « déconnecter tous mes appareils » — les JWT portent la
  version et sont refusés dès qu'elle ne correspond plus au compte.

Revision ID: 3b9eb37eb91d
Revises: 8b15b63bec49
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b9eb37eb91d'
down_revision: Union[str, Sequence[str], None] = '8b15b63bec49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "instance_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("public_url", sa.String(), nullable=True),
        sa.Column("first_external_at", sa.DateTime(), nullable=True),
        sa.Column("last_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_check_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "token_version")
    op.drop_table("instance_state")
