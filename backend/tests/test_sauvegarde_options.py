"""Sauvegarde : mot de passe, données personnelles, comptes à compléter.

Règles retenues :
- par défaut (aucune option) : SANS données personnelles et SANS fichiers des documents ; les comptes
  deviennent « Compte 1 », « Compte 2 »… (e-mail @anonyme.invalid, ni mot de passe, ni téléphone, ni
  adresse) et les champs qui décrivent des personnes sont vidés ; les fiches des documents restent ;
- mot de passe : archive ZIP chiffrée AES-256 ; 10 caractères minimum ;
- données personnelles ou fichiers sans mot de passe : refusé (422) ;
- import d'une sauvegarde protégée : sans mot de passe ou avec un mauvais → 422 ;
- import sans données personnelles : les comptes « Compte N » sont créés (adresse propre à chaque
  import) et listés « à compléter » ; les compléter remet nom, e-mail, téléphone, adresse et mot de
  passe ; un e-mail déjà connu du serveur fusionne le compte anonyme dans le compte existant.
"""
import io
import json
import zipfile

import pyzipper
import pytest

from app.models.lot import Lot
from app.models.user import User, UserCopro
from tests.conftest import auth
from tests.test_sauvegarde import MDP, _copro_complete, _export, _import

URL = "/api/sauvegarde/comptes-a-completer"


def test_par_defaut_sans_donnees_personnelles_ni_fichiers(client, db, copro_a, syndic_a, token_a):
    martin, appart, cave = _copro_complete(client, db, copro_a, token_a)
    appart.notes = "Occupé par M. Martin, 06 12 34 56 78"
    copro_a.smtp_user = "syndic.perso@gmail.com"
    db.commit()
    contenu = _export(client, token_a, {})
    z = zipfile.ZipFile(io.BytesIO(contenu))               # pas de mot de passe : lisible tel quel
    manifest = json.loads(z.read("manifest.json"))
    assert (manifest["donnees_personnelles"], manifest["fichiers_documents"], manifest["protegee"]) == (False, False, False)
    donnees = json.loads(z.read("donnees.json"))
    texte = json.dumps(donnees, ensure_ascii=False)
    for perso in ("martin@test.fr", "syndic.a@test.fr", "06 12 34 56 78", "syndic.perso@gmail.com"):
        assert perso not in texte
    assert sorted(u["nom"] for u in donnees["users"]) == ["Compte 1", "Compte 2"]
    assert all(u["email"].endswith("@anonyme.invalid") and u["password_hash"] == "" for u in donnees["users"])
    # Les comptes restent liés à leurs lots : le décompte de chacun est intact.
    lots = {l["numero"]: l for l in donnees["lots"]}
    assert lots["1"]["proprietaire_id"] == lots["12"]["proprietaire_id"] == martin.id
    # Fiches des documents gardées, fichiers non.
    assert [d["fichier"] for d in donnees["documents"]] == [""]
    assert not [n for n in z.namelist() if n.startswith("documents/")]


@pytest.mark.parametrize("options, message", [
    ({"donnees_personnelles": True}, "mot de passe"),
    ({"fichiers": True}, "mot de passe"),
    ({"mot_de_passe": "court", "donnees_personnelles": True}, "10 caractères"),
])
def test_donnees_personnelles_exigent_un_mot_de_passe(client, db, copro_a, syndic_a, token_a, options, message):
    r = client.post("/api/sauvegarde/export", json=options, headers=auth(token_a))
    assert r.status_code == 422 and message in r.json()["detail"]


def test_sauvegarde_protegee(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    _copro_complete(client, db, copro_a, token_a)
    contenu = _export(client, token_a)
    z = pyzipper.AESZipFile(io.BytesIO(contenu))
    assert all(i.flag_bits & 1 for i in z.infolist())          # chaque fichier est chiffré
    with pytest.raises(RuntimeError):
        z.read("donnees.json")
    r = _import(client, token_b, contenu, mot_de_passe="")
    assert r.status_code == 422 and "protégée" in r.json()["detail"]
    r = _import(client, token_b, contenu, mot_de_passe="mauvais-mot-de-passe")
    assert r.status_code == 422 and "incorrect" in r.json()["detail"]
    assert _import(client, token_b, contenu).status_code == 200


def test_sans_donnees_personnelles_mais_protegee(client, db, copro_a, syndic_a, token_a):
    _copro_complete(client, db, copro_a, token_a)
    contenu = _export(client, token_a, {"mot_de_passe": MDP})
    z = pyzipper.AESZipFile(io.BytesIO(contenu))
    z.setpassword(MDP.encode())
    assert json.loads(z.read("manifest.json"))["donnees_personnelles"] is False


def _import_anonyme(client, db, copro_a, copro_b, token_a, token_b):
    _copro_complete(client, db, copro_a, token_a)
    r = _import(client, token_b, _export(client, token_a, {}), mot_de_passe="")
    assert r.status_code == 200, r.text
    nid = r.json()["copropriete_id"]
    tok = client.post(f"/api/auth/switch-copro/{nid}", headers=auth(token_b)).json()["access_token"]
    return r.json(), nid, tok


def test_import_anonyme_comptes_a_completer(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    res, nid, tok = _import_anonyme(client, db, copro_a, copro_b, token_a, token_b)
    assert (res["comptes_crees"], res["comptes_existants"], res["comptes_a_completer"]) == (2, 0, 2)
    liste = client.get(URL, headers=auth(tok)).json()
    assert sorted(c["nom"] for c in liste) == ["Compte 1", "Compte 2"]
    assert sorted(c["lots"] for c in liste) == [[], ["1", "12"]]
    # Un compte anonyme ne peut pas se connecter.
    anonyme = db.get(User, liste[0]["id"])
    assert client.post("/api/auth/login", json={"email": anonyme.email, "password": ""}).status_code in (401, 422)
    # Un second import de la même sauvegarde ne se mélange pas au premier.
    r = _import(client, token_b, _export(client, token_a, {}), mot_de_passe="")
    assert r.status_code == 200 and r.json()["comptes_crees"] == 2


def test_completer_un_compte(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    _, nid, tok = _import_anonyme(client, db, copro_a, copro_b, token_a, token_b)
    martin = next(c for c in client.get(URL, headers=auth(tok)).json() if c["lots"])
    r = client.put(f"{URL}/{martin['id']}", json={"email": "jean.martin@exemple.fr", "nom": "Martin", "prenom": "Jean",
                                                  "telephone": "0600000000", "password": "nouveau-mdp"},
                   headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json() == {"fusionne": False, "user_id": martin["id"]}
    assert client.post("/api/auth/login", json={"email": "jean.martin@exemple.fr",
                                                "password": "nouveau-mdp"}).status_code == 200
    assert len(client.get(URL, headers=auth(tok)).json()) == 1


def test_completer_avec_un_compte_existant_fusionne(client, db, copro_a, copro_b, syndic_a, syndic_b,
                                                    token_a, token_b):
    _, nid, tok = _import_anonyme(client, db, copro_a, copro_b, token_a, token_b)
    martin_anonyme = next(c for c in client.get(URL, headers=auth(tok)).json() if c["lots"])
    # Ce copropriétaire a déjà un compte sur ce serveur (même e-mail) : le compte anonyme y est fusionné.
    r = client.put(f"{URL}/{martin_anonyme['id']}", json={"email": "Martin@test.fr", "nom": "Martin"},
                   headers=auth(tok))
    assert r.status_code == 200, r.text
    existant = db.query(User).filter(User.email == "martin@test.fr").one()
    assert r.json() == {"fusionne": True, "user_id": existant.id}
    db.expire_all()
    assert db.get(User, martin_anonyme["id"]) is None
    lots = db.query(Lot).filter(Lot.copropriete_id == nid).all()
    assert {l.numero: l.proprietaire_id for l in lots if l.numero in ("1", "12")} == {"1": existant.id, "12": existant.id}
    assert db.query(UserCopro).filter(UserCopro.user_id == existant.id, UserCopro.copropriete_id == nid).count() == 1


def test_completer_refuse(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    _, nid, tok = _import_anonyme(client, db, copro_a, copro_b, token_a, token_b)
    c = client.get(URL, headers=auth(tok)).json()[0]
    # Adresse encore anonyme, ou compte qui n'est pas à compléter.
    assert client.put(f"{URL}/{c['id']}", json={"email": "x@anonyme.invalid", "nom": "X"},
                      headers=auth(tok)).status_code == 422
    assert client.put(f"{URL}/{syndic_b.id}", json={"email": "y@test.fr", "nom": "Y"},
                      headers=auth(tok)).status_code == 404
