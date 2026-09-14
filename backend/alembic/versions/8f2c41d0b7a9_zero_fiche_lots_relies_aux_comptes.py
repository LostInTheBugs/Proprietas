"""zero fiche — les lots (et l'historique) se relient aux comptes utilisateurs

Le modèle « Lots & occupants » passe des fiches `personnes` aux COMPTES
utilisateurs :

- `users.adresse` / `users.telephone` : coordonnées du copropriétaire
  (modifiables par lui-même : Réglages → Mes informations) ;
- les propriétaires de lots SANS compte sont convertis en comptes (email de la
  fiche, sinon `<ficheN>@proprietas.local` ; mot de passe aléatoire inconnu —
  le syndic en définit un depuis Réglages → Comptes) ;
- `lots.proprietaire_id`, `relances.personne_id`, `invitations.personne_id` et
  `actes_recouvrement.personne_id` gardent leur nom mais pointent désormais
  `users.id` (valeurs remappées, FK retirées/recréées) ;
- `lots.statut_occupation` accepte « occupant » : l'ancienne case
  `users.est_occupant` devient l'état du lot (migration de reprise) ;
- la table `personnes` N'EST PAS supprimée (migrations additives) : plus aucun
  code applicatif ne la lit.

Revision ID: 8f2c41d0b7a9
Revises: 29d4b23cc786
Create Date: 2026-09-14 12:30:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f2c41d0b7a9'
down_revision: Union[str, Sequence[str], None] = '29d4b23cc786'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table → colonne des références « personne » repointées vers users.id
REFERENCES = [
    ("lots", "proprietaire_id"),
    ("relances", "personne_id"),
    ("invitations", "personne_id"),
    ("actes_recouvrement", "personne_id"),
]


def _fk_vers_personnes(conn, table: str, column: str) -> str | None:
    """Nom de la contrainte FK (table, colonne) en PostgreSQL, si elle existe."""
    row = conn.execute(sa.text("""
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f' AND t.relname = :t AND a.attname = :col
    """), {"t": table, "col": column}).first()
    return row[0] if row else None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # 1. Coordonnées du copropriétaire sur le compte.
    op.add_column("users", sa.Column("adresse", sa.String(), nullable=True, server_default=""))
    op.add_column("users", sa.Column("telephone", sa.String(), nullable=True, server_default=""))

    # En PostgreSQL, retirer D'ABORD les FK vers `personnes` (sinon les
    # remappages ci-dessous violeraient la contrainte). SQLite ne contrôle pas
    # les FK et les bases dev sont reconstruites depuis les migrations.
    if dialect == "postgresql":
        for table, column in REFERENCES:
            name = _fk_vers_personnes(conn, table, column)
            if name:
                op.drop_constraint(name, table, type_="foreignkey")

    # 2. Comptes pour les propriétaires de lots sans compte.
    from app.core.security import hash_password  # import local (bcrypt)
    hash_aleatoire = hash_password(uuid.uuid4().hex)
    conn.execute(sa.text("""
        INSERT INTO users (email, password_hash, prenom, nom, adresse, telephone, role,
                           is_demo, est_occupant, totp_secret, totp_enabled, recovery_hashes,
                           token_version, theme, personne_id, copropriete_id)
        SELECT CASE WHEN TRIM(COALESCE(p.email, '')) <> '' THEN LOWER(TRIM(p.email))
                    ELSE 'fiche' || CAST(p.id AS TEXT) || '@proprietas.local' END,
               :hash, COALESCE(p.prenom, ''), p.nom, COALESCE(p.adresse, ''), COALESCE(p.telephone, ''),
               'membre', false, false, '', false, '[]', 0, 'system', p.id, p.copropriete_id
        FROM personnes p
        WHERE p.id IN (SELECT proprietaire_id FROM lots WHERE proprietaire_id IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.personne_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM users u2
                          WHERE TRIM(COALESCE(p.email, '')) <> ''
                            AND LOWER(TRIM(u2.email)) = LOWER(TRIM(p.email)))
    """), {"hash": hash_aleatoire})

    # 3. Liaisons copropriété des comptes convertis (l'app liste via user_coproprietes).
    conn.execute(sa.text("""
        INSERT INTO user_coproprietes (user_id, copropriete_id, principale)
        SELECT u.id, u.copropriete_id, true
        FROM users u
        WHERE u.personne_id IS NOT NULL AND u.copropriete_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM user_coproprietes uc
                          WHERE uc.user_id = u.id AND uc.copropriete_id = u.copropriete_id)
    """))

    # 4. Remappage fiche → compte, puis nettoyage des références orphelines
    #    (fiche sans compte, ex. email en collision) → NULL, détaché et visible.
    for table, column in REFERENCES:
        conn.execute(sa.text(f"""
            UPDATE {table} SET {column} = (SELECT u.id FROM users u WHERE u.personne_id = {table}.{column})
            WHERE {column} IS NOT NULL
              AND EXISTS (SELECT 1 FROM users u2 WHERE u2.personne_id = {table}.{column})
        """))
        conn.execute(sa.text(f"""
            UPDATE {table} SET {column} = NULL
            WHERE {column} IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM users u3 WHERE u3.id = {table}.{column})
        """))

    # 5. Occupation : l'ancienne case « occupe son logement » du compte devient
    #    l'état du lot (le choix vit désormais lot par lot).
    conn.execute(sa.text("""
        UPDATE lots SET statut_occupation = 'occupant'
        WHERE statut_occupation = ''
          AND proprietaire_id IN (SELECT id FROM users WHERE est_occupant = true)
    """))

    # 6. Nouvelles FK → users.id (PostgreSQL).
    if dialect == "postgresql":
        for table, column in REFERENCES:
            op.create_foreign_key(f"{table}_{column}_fkey", table, "users", [column], ["id"])


def downgrade() -> None:
    raise RuntimeError(
        "Migration 8f2c41d0b7a9 (conversion fiches → comptes, « zéro fiche ») : "
        "transformation de données irréversible.\n"
        "Restaurer une sauvegarde de la base plutôt qu'un downgrade Alembic."
    )
