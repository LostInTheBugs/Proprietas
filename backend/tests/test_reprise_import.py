"""Reprise de l'historique : import CSV (état au 31/12, appels, paiements).

Règles retenues :
- trois types de fichier, avec une ligne d'en-tête (ordre des colonnes libre, casse ignorée) :
  état « lot;exercice;charges;fonds_travaux » (crée un BROUILLON à la date donnée),
  appels « date;lot;libelle;charges;fonds_travaux » (une ligne par lot ; les lignes de même date et
  même libellé forment un seul appel),
  paiements « date;lot;montant;libelle » (encaissements, libellé facultatif) ;
- séparateur « ; » ou « , », montants à la française (« 1 234,50 »), dates JJ/MM/AAAA ou AAAA-MM-JJ,
  lot désigné par son numéro dans la copropriété ;
- l'exercice d'un appel ou d'un paiement est l'année de sa date (créé s'il manque) ;
- « simuler » vérifie et résume sans rien écrire ;
- refus en bloc : à la moindre erreur, rien n'est importé, et chaque erreur cite sa ligne ;
- un appel (même date, même libellé) ou un paiement (même lot, date et montant) déjà présent est
  refusé : un fichier importé deux fois ne compte jamais double ;
- le résumé indique combien d'opérations sont couvertes par la base (sans effet sur les soldes).
"""
from datetime import date

from app.models.appel import AppelFonds
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.core.security import create_access_token
from tests.conftest import _make_membre, auth

Y = date.today().year - 1
URL = "/api/reprise/import"


def _lots(db, copro):
    p1 = _make_membre(db, "un@test.fr", copro)
    p2 = _make_membre(db, "deux@test.fr", copro)
    l1 = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=p1.id)
    l2 = Lot(copropriete_id=copro.id, numero="2", tantiemes=400, proprietaire_id=p2.id)
    db.add_all([l1, l2])
    db.commit()
    return l1, l2


def _importer(client, token, type_, contenu, simuler=False, jour=None):
    corps = {"type": type_, "contenu": contenu, "simuler": simuler}
    if jour:
        corps["date"] = jour.isoformat()
    return client.post(URL, json=corps, headers=auth(token))


def _soldes(client, token):
    return {s["lot"]["numero"]: s["solde"] for s in client.get("/api/lots/soldes", headers=auth(token)).json()}


APPELS = (f"date;lot;libelle;charges;fonds_travaux\n"
          f"01/03/{Y};1;Provisions T1;600,00;30\n"
          f"01/03/{Y};2;Provisions T1;400;20\n"
          f"{Y}-06-01;1;Provisions T2;1 200,50;0\n")

PAIEMENTS = (f"date;lot;montant;libelle\n"
             f"10/03/{Y};1;630;Virement\n"
             f"12/03/{Y};2;420;\n")


def test_import_etat_cree_un_brouillon(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    contenu = f"Lot;Exercice;Charges;Fonds_travaux\n1;{Y};120,50;15\n2;{Y - 1};-30;0\n"
    r = _importer(client, token_a, "etat", contenu, jour=date(Y, 12, 31))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resume"]["lignes"] == 2 and d["etat_id"] is not None
    etat = client.get(f"/api/reprise/etats/{d['etat_id']}", headers=auth(token_a)).json()
    assert etat["valide"] is False
    assert {(l["lot_numero"], l["exercice_origine"], l["montant_charges"]) for l in etat["lignes"]} == {
        ("1", Y, 120.5), ("2", Y - 1, -30)}


def test_import_appels_regroupe_par_date_et_libelle(client, db, copro_a, syndic_a, token_a):
    l1, l2 = _lots(db, copro_a)
    r = _importer(client, token_a, "appels", APPELS)
    assert r.status_code == 200, r.text
    assert r.json()["resume"]["appels"] == 2
    appels = {a.libelle: a for a in db.query(AppelFonds).all()}
    t1 = appels["Provisions T1"]
    assert t1.date_emission == date(Y, 3, 1) and t1.exercice.annee == Y
    assert float(t1.montant_total) == 1050 and float(t1.fonds_travaux_montant) == 50
    parts = {p.lot_id: p for p in t1.parts}
    assert float(parts[l1.id].montant_charges) == 600 and float(parts[l2.id].montant_fonds_travaux) == 20
    assert float(appels["Provisions T2"].parts[0].montant_charges) == 1200.5
    assert _soldes(client, token_a) == {"1": 1830.5, "2": 420}


def test_import_paiements(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    _importer(client, token_a, "appels", APPELS)
    r = _importer(client, token_a, "paiements", PAIEMENTS)
    assert r.status_code == 200, r.text
    assert r.json()["resume"]["paiements"] == 2
    m = db.query(Mouvement).filter(Mouvement.type == "encaissement").order_by(Mouvement.date).all()
    assert [(x.date, float(x.montant), x.libelle) for x in m] == [
        (date(Y, 3, 10), 630, "Virement"), (date(Y, 3, 12), 420, "Paiement importé")]
    assert all(x.exercice.annee == Y for x in m)
    assert _soldes(client, token_a) == {"1": 1200.5, "2": 0}


def test_simulation_n_ecrit_rien(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    r = _importer(client, token_a, "appels", APPELS, simuler=True)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["simulation"] is True and d["erreurs"] == []
    assert d["resume"]["appels"] == 2 and d["resume"]["lignes"] == 3
    assert db.query(AppelFonds).count() == 0
    assert db.query(Exercice).count() == 0


def test_refus_en_bloc_avec_numeros_de_ligne(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    contenu = (f"date;lot;montant\n"
               f"10/03/{Y};1;100\n"
               f"31/02/{Y};1;100\n"
               f"10/03/{Y};9;100\n"
               f"10/03/{Y};2;abc\n"
               f"10/03/{Y};2;-5\n")
    simu = _importer(client, token_a, "paiements", contenu, simuler=True).json()
    assert [e["ligne"] for e in simu["erreurs"]] == [3, 4, 5, 6]
    r = _importer(client, token_a, "paiements", contenu)
    assert r.status_code == 422
    assert "ligne 3" in r.json()["detail"]
    assert db.query(Mouvement).count() == 0


def test_colonne_manquante(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    r = _importer(client, token_a, "appels", f"date;lot;charges\n01/03/{Y};1;100\n", simuler=True)
    assert r.status_code == 200
    assert "libelle" in r.json()["erreurs"][0]["message"]


def test_separateur_virgule(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    r = _importer(client, token_a, "paiements", f"date,lot,montant\n{Y}-03-10,1,\"1 234,50\"\n")
    assert r.status_code == 200, r.text
    assert float(db.query(Mouvement).one().montant) == 1234.5


def test_un_fichier_importe_deux_fois_ne_compte_pas_double(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    assert _importer(client, token_a, "appels", APPELS).status_code == 200
    assert _importer(client, token_a, "paiements", PAIEMENTS).status_code == 200
    r = _importer(client, token_a, "appels", APPELS)
    assert r.status_code == 422 and "déjà" in r.json()["detail"]
    r = _importer(client, token_a, "paiements", PAIEMENTS)
    assert r.status_code == 422 and "déjà" in r.json()["detail"]
    assert db.query(AppelFonds).count() == 2 and db.query(Mouvement).count() == 2


def test_operations_couvertes_par_la_base_signalees(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    e = client.post("/api/reprise/etats", json={"date": f"{Y}-12-31", "lignes": [
        {"lot_id": l1.id, "exercice_origine": Y, "montant_charges": 50}]}, headers=auth(token_a)).json()
    client.post(f"/api/reprise/etats/{e['id']}/valider", headers=auth(token_a))
    d = _importer(client, token_a, "paiements", PAIEMENTS, simuler=True).json()
    assert d["resume"]["couverts_par_la_base"] == 2


def test_etat_date_invalide(client, db, copro_a, syndic_a, token_a):
    _lots(db, copro_a)
    r = _importer(client, token_a, "etat", f"lot;exercice;charges\n1;{Y};10\n", jour=date(Y, 6, 30))
    assert r.status_code == 422


def test_reserve_au_syndic(client, db, copro_a, syndic_a, token_a):
    l1, _ = _lots(db, copro_a)
    tok = create_access_token(l1.proprietaire_id, copro_a.id)
    assert _importer(client, tok, "paiements", PAIEMENTS, simuler=True).status_code == 403


def test_lots_d_une_autre_copropriete_inconnus(client, db, copro_a, copro_b, syndic_a, syndic_b, token_b):
    _lots(db, copro_a)
    d = _importer(client, token_b, "paiements", PAIEMENTS, simuler=True).json()
    assert [e["ligne"] for e in d["erreurs"]] == [2, 3]
