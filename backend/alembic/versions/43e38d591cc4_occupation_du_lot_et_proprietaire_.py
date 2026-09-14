"""occupation du lot et proprietaire occupant sur le compte

L'occupation quitte les fiches personnes (cases historiques « Propriétaire /
Occupant ») pour :
- `users.est_occupant` : le compte lié déclare « occupe son logement »
  (affiché « propriétaire occupant » pour les lots dont il est propriétaire) ;
- `lots.statut_occupation` : "" | "loue" | "vacant" — jamais de nom de
  locataire stocké (RGPD).

Revision ID: 43e38d591cc4
Revises: 14a016b259ef
Create Date: 2026-09-14 11:28:43.191480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43e38d591cc4'
down_revision: Union[str, Sequence[str], None] = '14a016b259ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('lots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('statut_occupation', sa.String(),
                                      server_default='', nullable=False))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('est_occupant', sa.Boolean(),
                                      server_default=sa.text('false'), nullable=False))

    # Reprise : l'ancienne case « Occupant » de la fiche personne devient
    # « occupe son logement » sur le compte lié (COALESCE : fiche absente ou
    # colonne NULL → false, la colonne étant NOT NULL).
    op.execute(
        "UPDATE users SET est_occupant = COALESCE("
        "  (SELECT p.est_occupant FROM personnes p WHERE p.id = users.personne_id), false)"
        " WHERE users.personne_id IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('est_occupant')

    with op.batch_alter_table('lots', schema=None) as batch_op:
        batch_op.drop_column('statut_occupation')
