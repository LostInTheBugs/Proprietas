"""suppression de l'ancienne table personnes (RGPD : données qui ne servaient plus)

La table « personnes » vient de l'ancien écran « Lots & occupants », remplacé par les comptes
utilisateurs (modèle « zéro fiche », 2026.09). Plus aucun code ne la lit ni ne l'écrit, mais elle gardait
des noms, e-mails, téléphones et adresses. Elle est supprimée, avec les deux colonnes qui la désignaient
encore (lots.occupant_id, users.personne_id). Le retour arrière recrée une table vide : ces données
ne reviennent pas.

Revision ID: a7b8c9d0e1f2
Revises: f0a1b2c3d4e5
Create Date: 2026-11-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# SQLite seulement : d'anciennes clés étrangères désignent encore « personnes » alors que la colonne contient
# un compte (users.id) depuis le modèle « zéro fiche » ; PostgreSQL a été repointé par les migrations d'alors.
# On les repointe vers users avant de supprimer la table (SQLite ne vérifie pas ces clés : rien ne cassait).
REPOINTER = {"lots": "proprietaire_id", "relances": "personne_id", "invitations": "personne_id",
             "actes_recouvrement": "personne_id"}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table, colonne in REPOINTER.items():
            with op.batch_alter_table(table, schema=None, recreate="always", reflect_args=[
                    sa.Column(colonne, sa.Integer(), sa.ForeignKey("users.id"), nullable=True)]):
                pass
    # PostgreSQL retire la clé étrangère avec la colonne ; SQLite (mode batch) recrée la table sans elle.
    with op.batch_alter_table("lots", schema=None) as batch_op:
        batch_op.drop_column("occupant_id")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("personne_id")
    op.drop_table("personnes")


def downgrade() -> None:
    op.create_table(
        "personnes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("copropriete_id", sa.Integer(), nullable=False),
        sa.Column("nom", sa.String(), nullable=False),
        sa.Column("prenom", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("telephone", sa.String(), nullable=True),
        sa.Column("adresse", sa.String(), nullable=True),
        sa.Column("est_proprietaire", sa.Boolean(), nullable=True),
        sa.Column("est_occupant", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["copropriete_id"], ["coproprietes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("personne_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_users_personne_id", "personnes", ["personne_id"], ["id"])
    with op.batch_alter_table("lots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("occupant_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("lots_occupant_id_fkey", "personnes", ["occupant_id"], ["id"])
