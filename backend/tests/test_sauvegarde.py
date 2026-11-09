"""Sauvegarde d'une copropriété : export (archive ZIP) et import (nouvelle copropriété).

Règles retenues :
- l'export contient toutes les données de la copropriété active (et rien d'une autre), les comptes
  concernés (mot de passe haché, pas l'administration de l'instance) et les fichiers des documents ;
  ni journal d'audit, ni mot de passe SMTP ;
- l'import crée toujours une NOUVELLE copropriété ; toutes les références sont renumérotées ;
  les documents sont recopiés sous de nouveaux noms ; un compte dont l'e-mail existe est réutilisé,
  sinon il est créé et peut se connecter avec son mot de passe ; un secret 2FA qui ne se déchiffre
  pas avec la clé du serveur est désactivé ; l'importeur est rattaché à la nouvelle copropriété ;
- réservé au syndic ; un fichier qui n'est pas une sauvegarde est refusé (422).
"""
import io
import json
import zipfile
from datetime import date

import pyzipper

from app.models.ag import AG, Resolution, Vote
from app.models.appel import AppelFonds, AppelLot
from app.models.audit import AuditLog
from app.models.contrat import Contrat
from app.models.copropriete import Copropriete
from app.models.document import Document
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.reprise import EtatReprise
from app.models.user import User, UserCopro
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth

Y = date.today().year


def _copro_complete(client, db, copro, token):
    copro.smtp_password = "secret-smtp"
    martin = _make_membre(db, "martin@test.fr", copro)
    appart = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=martin.id)
    db.add(appart)
    db.flush()
    cave = Lot(copropriete_id=copro.id, numero="12", tantiemes=40, proprietaire_id=martin.id,
               lot_principal_id=appart.id)
    db.add(cave)
    contrat = Contrat(copropriete_id=copro.id, libelle="EDF", type="energie")
    db.add(contrat)
    ex = Exercice(copropriete_id=copro.id, annee=Y, cloture=False)
    db.add(ex)
    db.commit()
    doc = client.post("/api/documents", data={"categorie": "facture", "libelle": "Facture EDF"},
                      files={"fichier": ("edf.pdf", b"%PDF-1.4 facture", "application/pdf")},
                      headers=auth(token)).json()
    a = AppelFonds(exercice_id=ex.id, libelle="T1", date_emission=date(Y, 1, 5), date_echeance=date(Y, 1, 15),
                   montant_total=640)
    db.add(a)
    db.flush()
    db.add_all([AppelLot(appel_id=a.id, lot_id=appart.id, montant_charges=600, montant_fonds_travaux=0),
                AppelLot(appel_id=a.id, lot_id=cave.id, montant_charges=40, montant_fonds_travaux=0)])
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(Y, 1, 20), libelle="Virement",
                     type="encaissement", categorie="charges", montant=500, lot_id=appart.id))
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(Y, 2, 1), libelle="Facture EDF",
                     type="depense", categorie="energie", montant="123.45", contrat_id=contrat.id,
                     document_id=doc["id"]))
    ag = AG(copropriete_id=copro.id, date=date(Y, 3, 10), statut="terminee")
    db.add(ag)
    db.flush()
    r1 = Resolution(ag_id=ag.id, numero=1, libelle="Approbation", majorite="art24", exercice_id=ex.id)
    db.add(r1)
    db.flush()
    db.add(Resolution(ag_id=ag.id, numero=2, libelle="Second vote", majorite="art24", second_vote_de_id=r1.id))
    db.add(Vote(resolution_id=r1.id, lot_id=appart.id, voix="pour"))
    db.commit()
    e = client.post("/api/reprise/etats", json={"date": f"{Y - 1}-12-31", "lignes": [
        {"lot_id": appart.id, "exercice_origine": Y - 1, "montant_charges": 70}]}, headers=auth(token)).json()
    client.post(f"/api/reprise/etats/{e['id']}/valider", headers=auth(token))
    return martin, appart, cave


MDP = "motdepasse-solide"
COMPLETE = {"mot_de_passe": MDP, "donnees_personnelles": True, "fichiers": True}


def _export(client, token, options=COMPLETE):
    """Sauvegarde complète (données personnelles et fichiers, donc protégée) sauf options contraires."""
    r = client.post("/api/sauvegarde/export", json=options, headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return r.content


def _import(client, token, contenu, mot_de_passe=MDP):
    return client.post("/api/sauvegarde/import", files={"fichier": ("sauvegarde.zip", contenu, "application/zip")},
                       data={"mot_de_passe": mot_de_passe}, headers=auth(token))


def _ouvrir(contenu, mot_de_passe=MDP):
    z = pyzipper.AESZipFile(io.BytesIO(contenu))
    z.setpassword(mot_de_passe.encode())
    return z


def _soldes(client, token):
    return {s["lot"]["numero"]: s["solde"] for s in client.get("/api/lots/soldes", headers=auth(token)).json()}


def test_contenu_de_l_export(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a):
    _copro_complete(client, db, copro_a, token_a)
    db.add(Lot(copropriete_id=copro_b.id, numero="B1", tantiemes=1))
    db.commit()
    z = _ouvrir(_export(client, token_a))
    manifest = json.loads(z.read("manifest.json"))
    donnees = json.loads(z.read("donnees.json"))
    assert manifest["format"] == "proprietas-copropriete" and manifest["copropriete"] == copro_a.nom
    assert [c["id"] for c in donnees["coproprietes"]] == [copro_a.id]
    assert "smtp_password" not in donnees["coproprietes"][0]
    assert {l["numero"] for l in donnees["lots"]} == {"1", "12"}          # rien de la copropriété B
    emails = {u["email"] for u in donnees["users"]}
    assert emails == {"syndic.a@test.fr", "martin@test.fr"}
    assert all("password_hash" in u and "is_instance_admin" not in u for u in donnees["users"])
    assert "audit_logs" not in donnees
    [doc] = donnees["documents"]
    assert z.read(f"documents/{doc['fichier']}") == b"%PDF-1.4 facture"
    assert db.query(AuditLog).filter(AuditLog.action == "sauvegarde_export").count() == 1


def test_import_cree_une_nouvelle_copropriete_identique(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                         token_a, token_b):
    _copro_complete(client, db, copro_a, token_a)
    avant = _soldes(client, token_a)
    r = _import(client, token_b, _export(client, token_a))
    assert r.status_code == 200, r.text
    res = r.json()
    nid = res["copropriete_id"]
    assert nid not in (copro_a.id, copro_b.id)
    # Même instance : les deux comptes existent déjà, ils sont réutilisés et non dupliqués.
    assert (res["comptes_crees"], res["comptes_existants"], res["documents"]) == (0, 2, 1)
    assert db.query(User).filter(User.email == "martin@test.fr").count() == 1
    # Le syndic B est rattaché à la nouvelle copropriété et y retrouve les mêmes soldes.
    tok = client.post(f"/api/auth/switch-copro/{nid}", headers=auth(token_b)).json()["access_token"]
    assert _soldes(client, tok) == avant
    db.expire_all()
    nouveaux = {l.numero: l for l in db.query(Lot).filter(Lot.copropriete_id == nid)}
    assert nouveaux["12"].lot_principal_id == nouveaux["1"].id                 # auto-référence renumérotée
    m = db.query(Mouvement).filter(Mouvement.copropriete_id == nid, Mouvement.type == "depense").one()
    assert float(m.montant) == 123.45
    assert db.get(Contrat, m.contrat_id).copropriete_id == nid
    doc = db.get(Document, m.document_id)
    assert doc.copropriete_id == nid
    assert client.get(f"/api/documents/{doc.id}/download", headers=auth(tok)).content == b"%PDF-1.4 facture"
    ag = db.query(AG).filter(AG.copropriete_id == nid).one()
    r1, r2 = sorted(db.query(Resolution).filter(Resolution.ag_id == ag.id), key=lambda r: r.numero)
    assert r2.second_vote_de_id == r1.id and db.get(Exercice, r1.exercice_id).copropriete_id == nid
    assert db.query(Vote).filter(Vote.resolution_id == r1.id).one().lot_id == nouveaux["1"].id
    etat = db.query(EtatReprise).filter(EtatReprise.copropriete_id == nid).one()
    assert etat.valide is True
    assert db.get(Copropriete, nid).smtp_password == ""
    # La copropriété d'origine n'a pas bougé.
    assert db.query(Lot).filter(Lot.copropriete_id == copro_a.id).count() == 2


def test_import_sur_une_autre_instance_cree_les_comptes(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                          token_a, token_b):
    _copro_complete(client, db, copro_a, token_a)
    contenu = _export(client, token_a)
    # Simule une instance neuve : des e-mails inconnus ; un secret 2FA chiffré avec une autre clé.
    z = _ouvrir(contenu)
    donnees = json.loads(z.read("donnees.json"))
    for u in donnees["users"]:
        u["email"] = "nouveau." + u["email"]
        if u["email"].startswith("nouveau.martin"):
            u["totp_secret"], u["totp_enabled"] = "gAAAAA-chiffre-ailleurs", True
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as z2:
        for nom in z.namelist():
            z2.writestr(nom, json.dumps(donnees) if nom == "donnees.json" else z.read(nom))
    r = _import(client, token_b, sortie.getvalue(), mot_de_passe="")     # archive réécrite sans mot de passe
    assert r.status_code == 200, r.text
    assert (r.json()["comptes_crees"], r.json()["deuxfa_desactivee"]) == (2, 1)
    # Le copropriétaire se connecte avec son mot de passe d'origine.
    login = client.post("/api/auth/login", json={"email": "nouveau.martin@test.fr", "password": "test1234"})
    assert login.status_code == 200, login.text
    martin = db.query(User).filter(User.email == "nouveau.martin@test.fr").one()
    assert martin.totp_enabled is False and martin.is_instance_admin is False
    assert db.query(UserCopro).filter(UserCopro.user_id == martin.id,
                                      UserCopro.copropriete_id == r.json()["copropriete_id"]).count() == 1


def test_fichier_qui_n_est_pas_une_sauvegarde(client, db, copro_a, syndic_a, token_a):
    assert _import(client, token_a, b"pas un zip").status_code == 422
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "autre"}))
        z.writestr("donnees.json", "{}")
    assert _import(client, token_a, sortie.getvalue()).status_code == 422


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    membre = _make_membre(db, "m@test.fr", copro_a)
    tok = create_access_token(membre.id, copro_a.id)
    assert client.post("/api/sauvegarde/export", json={}, headers=auth(tok)).status_code == 403
    assert _import(client, tok, b"x").status_code == 403


def test_toutes_les_tables_de_la_copropriete_sont_couvertes():
    """Garde-fou : une nouvelle table liée à une copropriété doit être ajoutée à la sauvegarde."""
    from app.core.database import Base
    from app.services.sauvegarde import TABLES, TABLES_IGNOREES

    hors_copro = {"audit_logs", "instance_state"}   # journal et état propres à l'instance
    oubliees = [n for n in Base.metadata.tables if n not in TABLES and n not in TABLES_IGNOREES and n not in hors_copro]
    assert oubliees == []


def test_nom_distingue_si_deja_pris(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    r = _import(client, token_b, _export(client, token_a))
    assert r.status_code == 200, r.text
    assert r.json()["nom"].startswith(f"{copro_a.nom} (importée le ")
    assert db.get(Copropriete, r.json()["copropriete_id"]).nom == r.json()["nom"]
