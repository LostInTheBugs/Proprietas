"""drive de la copropriété (WebDAV) et emplacement des documents

Une copropriété peut ranger ses fichiers sur un drive WebDAV (Nextcloud, ownCloud, Synology…).
`documents.emplacement` : "" = stockage de l'instance (tous les documents existants), "drive".

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLONNES = ("drive_type", "drive_url", "drive_user", "drive_password", "drive_dossier")


def upgrade() -> None:
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        for nom in COLONNES:
            batch_op.add_column(sa.Column(nom, sa.String(), nullable=True, server_default=""))
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("emplacement", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    # Les fichiers restés sur un drive ne sont plus atteignables par l'ancienne version :
    # leurs fiches sont gardées, sans fichier.
    op.execute("UPDATE documents SET fichier = '' WHERE emplacement = 'drive'")
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("emplacement")
    with op.batch_alter_table("coproprietes", schema=None) as batch_op:
        for nom in reversed(COLONNES):
            batch_op.drop_column(nom)
