"""float_to_numeric_monetary

Revision ID: 840f497d9a3c
Revises: 8f2c41d0b7a9
Create Date: 2026-10-17 21:54:22.821026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '840f497d9a3c'
down_revision: Union[str, Sequence[str], None] = '8f2c41d0b7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE actes_recouvrement SET montant = ROUND(CAST(montant AS NUMERIC), 2)")
    with op.batch_alter_table('actes_recouvrement', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE appels_fonds SET montant_total = ROUND(CAST(montant_total AS NUMERIC), 2), fonds_travaux_montant = ROUND(CAST(fonds_travaux_montant AS NUMERIC), 2)")
    with op.batch_alter_table('appels_fonds', schema=None) as batch_op:
        batch_op.alter_column('montant_total',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)
        batch_op.alter_column('fonds_travaux_montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE appels_lots SET montant_charges = ROUND(CAST(montant_charges AS NUMERIC), 2), montant_fonds_travaux = ROUND(CAST(montant_fonds_travaux AS NUMERIC), 2)")
    with op.batch_alter_table('appels_lots', schema=None) as batch_op:
        batch_op.alter_column('montant_charges',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)
        batch_op.alter_column('montant_fonds_travaux',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE budget_lines SET montant = ROUND(CAST(montant AS NUMERIC), 2)")
    with op.batch_alter_table('budget_lines', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE carnet_entretien SET cout = ROUND(CAST(cout AS NUMERIC), 2)")
    with op.batch_alter_table('carnet_entretien', schema=None) as batch_op:
        batch_op.alter_column('cout',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE contrats SET montant = ROUND(CAST(montant AS NUMERIC), 2)")
    with op.batch_alter_table('contrats', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE coproprietes SET fonds_travaux_taux_pct = ROUND(CAST(fonds_travaux_taux_pct AS NUMERIC), 4), relance_minimum = ROUND(CAST(relance_minimum AS NUMERIC), 2), taux_legal_retard = ROUND(CAST(taux_legal_retard AS NUMERIC), 4)")
    with op.batch_alter_table('coproprietes', schema=None) as batch_op:
        batch_op.alter_column('fonds_travaux_taux_pct',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=7, scale=4),
               existing_nullable=True)
        batch_op.alter_column('relance_minimum',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)
        batch_op.alter_column('taux_legal_retard',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=7, scale=4),
               existing_nullable=True)

    op.execute("UPDATE mouvements SET montant = ROUND(CAST(montant AS NUMERIC), 2)")
    with op.batch_alter_table('mouvements', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE relances SET montant_du = ROUND(CAST(montant_du AS NUMERIC), 2)")
    with op.batch_alter_table('relances', schema=None) as batch_op:
        batch_op.alter_column('montant_du',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)

    op.execute("UPDATE travaux SET montant = ROUND(CAST(montant AS NUMERIC), 2)")
    with op.batch_alter_table('travaux', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.FLOAT(),
               type_=sa.Numeric(precision=12, scale=2),
               existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('travaux', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('relances', schema=None) as batch_op:
        batch_op.alter_column('montant_du',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('mouvements', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('coproprietes', schema=None) as batch_op:
        batch_op.alter_column('taux_legal_retard',
               existing_type=sa.Numeric(precision=7, scale=4),
               type_=sa.FLOAT(),
               existing_nullable=True)
        batch_op.alter_column('relance_minimum',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)
        batch_op.alter_column('fonds_travaux_taux_pct',
               existing_type=sa.Numeric(precision=7, scale=4),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('contrats', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('carnet_entretien', schema=None) as batch_op:
        batch_op.alter_column('cout',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('budget_lines', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('appels_lots', schema=None) as batch_op:
        batch_op.alter_column('montant_fonds_travaux',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)
        batch_op.alter_column('montant_charges',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('appels_fonds', schema=None) as batch_op:
        batch_op.alter_column('fonds_travaux_montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)
        batch_op.alter_column('montant_total',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)

    with op.batch_alter_table('actes_recouvrement', schema=None) as batch_op:
        batch_op.alter_column('montant',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.FLOAT(),
               existing_nullable=True)
