"""users : prénom + fiche « Lots & occupants » liée

Comptes utilisateurs (Réglages → Comptes utilisateurs) : champ prénom, et lien
optionnel vers une fiche de « Lots & occupants » (un compte par personne).

Revision ID: 14a016b259ef
Revises: 5a7ff0e79254
Create Date: 2026-09-14 08:51:54.486330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14a016b259ef'
down_revision: Union[str, Sequence[str], None] = '5a7ff0e79254'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prenom', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('personne_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_users_personne_id', 'personnes', ['personne_id'], ['id'])
    # Colonnes ajoutées = NULL sur les lignes existantes → normaliser (le schéma
    # de sortie UserOut tolère aussi None, mais autant garder la donnée propre).
    op.execute("UPDATE users SET prenom = '' WHERE prenom IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_personne_id', type_='foreignkey')
        batch_op.drop_column('personne_id')
        batch_op.drop_column('prenom')
