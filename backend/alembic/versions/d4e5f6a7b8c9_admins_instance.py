"""administrateurs de l'instance gérés dans l'application (users.is_instance_admin)

Remplace la variable COPRO_INSTANCE_ADMINS. Données : le premier compte non-démo
(celui qui a installé l'instance, cf. /api/auth/register) devient administrateur.

Revision ID: d4e5f6a7b8c9
Revises: c7a1e2b3d4f5
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c7a1e2b3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_instance_admin", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("is_demo", sa.Boolean),
                     sa.column("is_instance_admin", sa.Boolean))
    conn = op.get_bind()
    premier = conn.execute(
        sa.select(sa.func.min(users.c.id)).where(sa.or_(users.c.is_demo.is_(None), users.c.is_demo == sa.false()))
    ).scalar()
    if premier is not None:
        conn.execute(sa.update(users).where(users.c.id == premier).values(is_instance_admin=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("is_instance_admin")
