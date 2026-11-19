"""Suppression de l'ancienne table « personnes » (RGPD, migration a7b8c9d0e1f2, 19/11/2026).

Table de l'ancien écran « Lots & occupants », remplacée par les comptes (modèle « zéro fiche ») : plus aucun
code ne la lisait, mais elle gardait noms, e-mails, téléphones et adresses (8 fiches sur l'instance de Fred).
- la table et les colonnes qui la désignaient (lots.occupant_id, users.personne_id) disparaissent ;
- lots, comptes et le reste sont intacts ; sous SQLite, les clés étrangères restées vers « personnes »
  (lots.proprietaire_id, relances, invitations, actes de recouvrement) désignent désormais users ;
- le retour arrière recrée une table vide ;
- une sauvegarde d'avant (avec occupant_id, personne_id) s'importe toujours.
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app import demarrage


def _colonnes(moteur, table):
    return [c["name"] for c in inspect(moteur).get_columns(table)]


def test_table_personnes_supprimee(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "f0a1b2c3d4e5")
    moteur = create_engine(url)
    with moteur.begin() as c:
        c.execute(text("insert into coproprietes (id, nom) values (1, 'R')"))
        c.execute(text("insert into personnes (id, copropriete_id, nom, email, telephone) "
                       "values (1, 1, 'Dupont', 'dupont@exemple.fr', '0600000000')"))
        c.execute(text("insert into users (id, email, password_hash, nom, role, personne_id) "
                       "values (1, 'syndic@exemple.fr', 'h', 'Syndic', 'syndic', 1)"))
        c.execute(text("insert into lots (id, copropriete_id, numero, tantiemes, occupant_id, proprietaire_id) "
                       "values (1, 1, '1', 1000, 1, 1)"))
    command.upgrade(cfg, "head")
    moteur = create_engine(url)
    assert "personnes" not in inspect(moteur).get_table_names()
    assert "occupant_id" not in _colonnes(moteur, "lots") and "personne_id" not in _colonnes(moteur, "users")
    with moteur.connect() as c:
        assert c.execute(text("select numero, tantiemes, proprietaire_id from lots")).one() == ("1", 1000, 1)
        assert c.execute(text("select email from users")).scalar() == "syndic@exemple.fr"
    for table in ("lots", "relances", "invitations", "actes_recouvrement"):
        cibles = {fk["referred_table"] for fk in inspect(moteur).get_foreign_keys(table)}
        assert "personnes" not in cibles, table
    command.downgrade(cfg, "-1")
    moteur = create_engine(url)
    assert "personnes" in inspect(moteur).get_table_names()
    with moteur.connect() as c:
        assert c.execute(text("select count(*) from personnes")).scalar() == 0        # rien ne revient
    command.upgrade(cfg, "head")


def test_sauvegarde_d_avant_importee_sans_avertissement(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                         token_a, token_b):
    """Les sauvegardes d'avant la suppression contiennent lots.occupant_id : ignoré en silence."""
    import io
    import json
    import pyzipper
    from tests.conftest import auth
    from tests.test_sauvegarde import MDP, _export, _import
    assert client.post("/api/lots", json={"numero": "7", "tantiemes": 100}, headers=auth(token_a)).status_code in (200, 201)
    contenu = _export(client, token_a)
    entree, sortie = pyzipper.AESZipFile(io.BytesIO(contenu)), io.BytesIO()
    entree.setpassword(MDP.encode())
    with pyzipper.AESZipFile(sortie, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as z:
        z.setpassword(MDP.encode())
        for nom in entree.namelist():
            brut = entree.read(nom)
            if nom == "donnees.json":
                donnees = json.loads(brut)
                for lot in donnees["lots"]:
                    lot["occupant_id"] = 1
                brut = json.dumps(donnees).encode()
            z.writestr(nom, brut)
    r = _import(client, token_b, sortie.getvalue())
    assert r.status_code == 200, r.text
    assert not any("occupant_id" in a for a in r.json().get("avertissements", []))
