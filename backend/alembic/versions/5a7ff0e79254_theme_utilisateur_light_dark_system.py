"""theme utilisateur : préférence d'affichage light | dark | system

Le rendu sombre est purement côté frontend (surcharges CSS sous html.dark) ;
la préférence est conservée par compte pour la retrouver sur tous les appareils.

Revision ID: 5a7ff0e79254
Revises: 42eefb4fae52
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5a7ff0e79254'
down_revision: Union[str, Sequence[str], None] = '42eefb4fae52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('theme', sa.String(), nullable=True))
    # Colonne ajoutée = NULL sur les lignes existantes → normaliser (le schéma
    # de sortie UserOut tolère aussi None, mais autant garder la donnée propre).
    op.execute("UPDATE users SET theme = 'system' WHERE theme IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('theme')
