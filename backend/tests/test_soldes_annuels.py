"""Historique : soldes bancaires au 1er janvier de chaque année, pour trouver l'année où une
opération manque.

Demande de Fred (16/11/2026) : « avoir les comptes pour chaque 1er janvier, comme ça si j'ai raté
quelque chose, je peux voir sur quelle année j'ai oublié ».

Règles retenues :
- un solde bancaire (compte du syndicat, compte du fonds de travaux) se saisit pour un 31 décembre
  (= au 1er janvier suivant), avec ou sans état de l'historique à cette date ; s'il existe un état à
  cette date, c'est le même solde (une seule saisie, partagée) ; pas de date future ; pas d'autre jour
  que le 31/12 ;
- une ligne par 1er janvier, de la première année utile à l'année en cours ; pour chaque compte :
  * relevé saisi (ou rien),
  * opérations de l'année écoulée (encaissements, dépenses datés du 01/01 au 31/12 de l'année
    précédente),
  * solde calculé : à partir d'un point d'ancrage (solde bancaire de la base de l'historique s'il
    existe, sinon le plus ancien relevé, sinon 0) en ajoutant ou en retirant les opérations,
  * écart de l'année = (relevé − relevé de l'année d'avant) − (encaissements − dépenses de l'année),
    quand les deux relevés existent : il désigne l'année où il manque quelque chose ;
- réservé au syndic ; isolé par copropriété.
"""
from datetime import date

from app.models.mouvement import Mouvement
from tests.conftest import auth
from tests.test_reprise_historique import B, B0, Y, URL, _exercice, _ligne, _lots, _valider

U = "/api/reprise/soldes-bancaires"


def _saisir(client, token, jour, syndicat=None, fonds=None):
    return client.put(U, json={"date": jour.isoformat(), "solde_banque": syndicat, "solde_banque_fonds": fonds},
                      headers=auth(token))


def _annees(client, token):
    r = client.get("/api/reprise/soldes-annuels", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _ops(db, copro, annee, enc=0, dep=0, ft=0):
    ex = _exercice(db, copro, annee)
    for typ, cat, montant in (("encaissement", "charges", enc), ("depense", "energie", dep),
                              ("encaissement", "fonds_travaux", ft)):
        if montant:
            db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(annee, 6, 1), libelle="x",
                             type=typ, categorie=cat, montant=montant))
    db.commit()


def test_saisie_directe_partagee_avec_l_etat(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    r = _saisir(client, token_a, B0, "1000", "200")
    assert r.status_code == 200, r.text
    # Un état créé ensuite à la même date montre le même solde, et le modifier change la saisie commune.
    e = client.post(URL, json={"date": B0.isoformat(), "commentaire": "", "lignes": [_ligne(l1, Y - 1, 100)],
                               "solde_banque": "1000", "solde_banque_fonds": "200"}, headers=auth(token_a)).json()
    assert (e["solde_banque"], e["solde_banque_fonds"]) == (1000, 200)
    client.put(f"{URL}/{e['id']}/banque", json={"solde_banque": "1100", "solde_banque_fonds": "200"},
               headers=auth(token_a))
    lignes = {l["annee"]: l for l in _annees(client, token_a)["lignes"]}
    assert lignes[Y]["syndicat"]["releve"] == 1100           # au 1er janvier Y = au 31/12/Y-1


def test_ecart_de_l_annee_designe_l_annee_fautive(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    _saisir(client, token_a, B0, "1000")
    _ops(db, copro_a, Y, enc=650, dep=400)                    # année Y : +250 saisis
    _saisir(client, token_a, B, "1150")                       # la banque n'a pris que +150 : 100 € manquent
    d = _annees(client, token_a)
    lignes = {l["annee"]: l for l in d["lignes"]}
    assert d["ancre"] == {"date": B0.isoformat(), "source": "releve"}
    s = lignes[Y + 1]["syndicat"]                             # au 1er janvier Y+1
    assert (s["releve"], s["encaissements"], s["depenses"], s["calcule"]) == (1150, 650, 400, 1250)
    assert (s["ecart"], s["ecart_annee"]) == (-100, -100)
    assert lignes[Y]["syndicat"]["ecart_annee"] is None       # pas de relevé l'année d'avant
    assert lignes[Y]["syndicat"]["ecart"] == 0                # c'est le point d'ancrage
    # Une ligne par 1er janvier jusqu'à l'année en cours.
    assert max(lignes) == date.today().year


def test_ancrage_sur_la_base_de_l_historique(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    e = client.post(URL, json={"date": B.isoformat(), "commentaire": "", "lignes": [_ligne(l1, Y, 0)],
                               "solde_banque": "2000", "solde_banque_fonds": None}, headers=auth(token_a)).json()
    assert _valider(client, token_a, e["id"]).status_code == 200
    _saisir(client, token_a, B0, "1700")                      # relevé plus ancien que la base
    _ops(db, copro_a, Y, enc=500, dep=200)
    d = _annees(client, token_a)
    assert d["ancre"] == {"date": B.isoformat(), "source": "base"}
    lignes = {l["annee"]: l for l in d["lignes"]}
    # En remontant : 2000 − (500 − 200) = 1700 au 1er janvier Y, concordant avec le relevé.
    assert (lignes[Y]["syndicat"]["calcule"], lignes[Y]["syndicat"]["ecart"]) == (1700, 0)
    assert lignes[Y + 1]["syndicat"]["ecart_annee"] == 0


def test_fonds_de_travaux_suivi_a_part(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    _saisir(client, token_a, B0, "1000", "300")
    _ops(db, copro_a, Y, enc=100, ft=80)
    _saisir(client, token_a, B, "1100", "330")                # fonds : +30 à la banque, +80 saisis
    f = {l["annee"]: l for l in _annees(client, token_a)["lignes"]}[Y + 1]["fonds_travaux"]
    assert (f["encaissements"], f["calcule"], f["ecart_annee"]) == (80, 380, -50)


def test_sans_aucun_releve_le_calcul_part_de_zero(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    _ops(db, copro_a, Y, enc=100, dep=30)
    d = _annees(client, token_a)
    assert d["ancre"]["source"] == "zero"
    lignes = {l["annee"]: l for l in d["lignes"]}
    assert min(lignes) == Y                                   # première année : celle des opérations
    assert (lignes[Y + 1]["syndicat"]["calcule"], lignes[Y + 1]["syndicat"]["releve"]) == (70, None)


def test_saisies_refusees(client, db, copro_a, syndic_a, token_a):
    assert _saisir(client, token_a, date(Y, 6, 30), "1").status_code == 422          # pas un 31/12
    assert _saisir(client, token_a, date(date.today().year + 1, 12, 31), "1").status_code == 422   # futur
    # Effacer : les deux soldes à null.
    _saisir(client, token_a, B0, "5")
    assert _saisir(client, token_a, B0, None, None).status_code == 200
    assert all(l["syndicat"]["releve"] is None for l in _annees(client, token_a)["lignes"])


def test_reserve_au_syndic_et_isole(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    from app.core.security import create_access_token
    from tests.conftest import _make_membre
    _saisir(client, token_a, B0, "1000")
    assert all(l["syndicat"]["releve"] is None for l in _annees(client, token_b)["lignes"])
    tok = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert client.get("/api/reprise/soldes-annuels", headers=auth(tok)).status_code == 403
    assert _saisir(client, tok, B0, "1").status_code == 403


def test_ancienne_sauvegarde_soldes_dans_les_etats(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    """Sauvegarde d'avant la 2026.11.021 : les soldes étaient des colonnes des états. Ils sont repris."""
    import io
    import json
    import zipfile
    from tests.test_sauvegarde import _export, _import
    l1, _ = _lots(db, copro_a)
    client.post(URL, json={"date": B0.isoformat(), "commentaire": "", "lignes": [_ligne(l1, Y - 1, 100)]},
                headers=auth(token_a))
    z = zipfile.ZipFile(io.BytesIO(_export(client, token_a, {})))
    donnees = json.loads(z.read("donnees.json"))
    del donnees["soldes_bancaires"]
    donnees["etats_reprise"][0].update(solde_banque="1234.50", solde_banque_fonds=None)
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as z2:
        for nom in z.namelist():
            z2.writestr(nom, json.dumps(donnees) if nom == "donnees.json" else z.read(nom))
    r = _import(client, token_b, sortie.getvalue(), mot_de_passe="")
    assert r.status_code == 200, r.text
    assert not [a for a in r.json()["avertissements"] if "solde_banque" in a]
    tok = client.post(f"/api/auth/switch-copro/{r.json()['copropriete_id']}", headers=auth(token_b)).json()["access_token"]
    lignes = {l["annee"]: l for l in _annees(client, tok)["lignes"]}
    assert lignes[Y]["syndicat"]["releve"] == 1234.5
