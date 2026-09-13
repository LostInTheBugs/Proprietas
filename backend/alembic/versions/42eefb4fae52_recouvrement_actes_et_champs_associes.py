"""recouvrement : actes de recouvrement + champs associés

- actes_recouvrement : journal additif par lot (mise en demeure, frais,
  activation de l'article 19-2, étapes amiables/judiciaires, notes) —
  le statut du dossier est calculé à la lecture, jamais stocké.
- personnes.adresse : adresse postale du copropriétaire (mentions de la
  mise en demeure — Service-Public F2603).
- coproprietes.taux_legal_retard : taux de l'intérêt légal (%) saisi par le
  syndic (arrêté semestriel), pour les intérêts de retard.

Revision ID: 42eefb4fae52
Revises: 3b9eb37eb91d
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '42eefb4fae52'
down_revision: Union[str, Sequence[str], None] = '3b9eb37eb91d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'actes_recouvrement',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('copropriete_id', sa.Integer(), nullable=False),
        sa.Column('lot_id', sa.Integer(), nullable=False),
        sa.Column('personne_id', sa.Integer(), nullable=True),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('date_acte', sa.DateTime(), nullable=True),
        sa.Column('date_envoi', sa.Date(), nullable=True),
        sa.Column('mode_envoi', sa.String(), nullable=True),
        sa.Column('reference', sa.String(), nullable=True),
        sa.Column('montant', sa.Float(), nullable=True),
        sa.Column('libelle', sa.String(), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['copropriete_id'], ['coproprietes.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], ),
        sa.ForeignKeyConstraint(['personne_id'], ['personnes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('coproprietes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('taux_legal_retard', sa.Float(), nullable=True))
    with op.batch_alter_table('personnes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('adresse', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('personnes', schema=None) as batch_op:
        batch_op.drop_column('adresse')
    with op.batch_alter_table('coproprietes', schema=None) as batch_op:
        batch_op.drop_column('taux_legal_retard')
    op.drop_table('actes_recouvrement')
