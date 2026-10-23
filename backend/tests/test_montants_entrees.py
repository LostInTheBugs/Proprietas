"""Montants SAISIS (corps des requêtes) : arrondis, bornés et finis AVANT l'écriture en base.

Pourquoi : les schémas d'entrée étaient en `float`. Sous PostgreSQL, Numeric(12,2) arrondit
à l'écriture ; sous SQLite (version de bureau, tests), la valeur brute est stockée telle
quelle (10.005 reste 10.005) et les sommes SQL divergent. NaN / Infinity passent la
validation float et font planter les calculs Decimal (500), et un montant énorme dépasse
Numeric(12,2) (erreur PostgreSQL = 500).
Règle : arrondi comptable ROUND_HALF_UP à 2 décimales (taux : 4 décimales) dès la
validation ; non fini ou hors limites → 422 ; les réponses restent des nombres JSON.
"""
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.lot import Lot
from app.schemas import AppelIn, CoproUpdate, MouvementIn
from tests.conftest import auth


@pytest.fixture()
def ex(client, token_a):
    r = client.post("/api/exercices", json={"annee": 2026}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


def _mouvement(client, token_a, ex, montant, raw=False):
    corps = {"date": "2026-03-01", "libelle": "Test", "type": "depense", "montant": montant}
    if raw:   # JSON écrit à la main : NaN / Infinity ne sont pas du JSON standard
        import json
        return client.post(f"/api/exercices/{ex['id']}/mouvements", content=json.dumps(corps),
                           headers={**auth(token_a), "Content-Type": "application/json"})
    return client.post(f"/api/exercices/{ex['id']}/mouvements", json=corps, headers=auth(token_a))


# ---------------------------------------------------------------- schémas
def test_schema_arrondit_au_centime_half_up():
    m = MouvementIn(date="2026-03-01", libelle="x", type="depense", montant=10.005)
    assert m.montant == Decimal("10.01")
    assert MouvementIn(date="2026-03-01", libelle="x", type="depense", montant="-2.345").montant == Decimal("-2.35")


def test_schema_taux_a_4_decimales():
    c = CoproUpdate(fonds_travaux_taux_pct=5.12345, taux_legal_retard=3.5, relance_minimum=12.345)
    assert c.fonds_travaux_taux_pct == Decimal("5.1235")
    assert c.taux_legal_retard == Decimal("3.5000")
    assert c.relance_minimum == Decimal("12.35")
    assert CoproUpdate().fonds_travaux_taux_pct is None        # champ optionnel non fourni


@pytest.mark.parametrize("valeur", ["NaN", "Infinity", "-Infinity", "abc", True, 1e10, -1e10])
def test_schema_refuse_non_fini_texte_booleen_et_hors_limites(valeur):
    with pytest.raises(ValueError):
        AppelIn(libelle="x", date_emission="2026-01-01", montant_total=valeur)


# ---------------------------------------------------------------- API
def test_mouvement_stocke_arrondi_en_base(client, token_a, ex, db):
    r = _mouvement(client, token_a, ex, 10.005)
    assert r.status_code == 200, r.text
    assert r.json()["montant"] == 10.01                        # la réponse reste un nombre JSON
    brut = db.execute(text("SELECT montant FROM mouvements WHERE id = :i"), {"i": r.json()["id"]}).scalar()
    assert Decimal(str(brut)) == Decimal("10.01")              # et non 10.005 sous SQLite


@pytest.mark.parametrize("valeur", ["NaN", "Infinity"])
def test_mouvement_non_fini_refuse_422(client, token_a, ex, valeur):
    r = _mouvement(client, token_a, ex, float(valeur), raw=True)
    assert r.status_code == 422, r.text


def test_mouvement_hors_limites_refuse_422(client, token_a, ex):
    assert _mouvement(client, token_a, ex, 1e12).status_code == 422


def test_appel_total_egal_a_la_somme_des_parts(client, token_a, ex, db, copro_a):
    db.add_all([Lot(copropriete_id=copro_a.id, numero=str(i), tantiemes=t)
                for i, t in ((1, 333), (2, 333), (3, 334))])
    db.commit()
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "T1", "date_emission": "2026-01-05", "montant_total": 1000.005}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = r.json()
    assert appel["montant_total"] == 1000.01
    parts = sum(Decimal(str(p["montant_charges"])) for p in appel["parts"])
    assert parts == Decimal("1000.01")
    brut = db.execute(text("SELECT montant_total FROM appels_fonds WHERE id = :i"), {"i": appel["id"]}).scalar()
    assert Decimal(str(brut)) == Decimal("1000.01")


def test_reglages_copro_arrondis_en_base(client, token_a, db, copro_a):
    r = client.put("/api/copro", json={"fonds_travaux_taux_pct": 5.12345, "relance_minimum": 12.345},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["fonds_travaux_taux_pct"] == 5.1235 and r.json()["relance_minimum"] == 12.35
    taux, mini = db.execute(text("SELECT fonds_travaux_taux_pct, relance_minimum FROM coproprietes WHERE id = :i"),
                            {"i": copro_a.id}).one()
    assert Decimal(str(taux)) == Decimal("5.1235") and Decimal(str(mini)) == Decimal("12.35")


@pytest.mark.parametrize("route,table,champ,corps", [
    ("/api/contrats", "contrats", "montant", {"libelle": "Assurance", "montant": 99.999}),
    ("/api/travaux", "travaux", "montant", {"libelle": "Toiture", "annee": 2026, "montant": 99.999}),
    ("/api/carnet", "carnet_entretien", "cout", {"date": "2026-01-01", "type_intervention": "Visite", "cout": 99.999}),
])
def test_autres_saisies_arrondies_en_base(client, token_a, db, route, table, champ, corps):
    # La réponse était déjà arrondie (relecture Numeric) : c'est la valeur STOCKÉE qu'on vérifie.
    r = client.post(route, json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()[champ] == 100.0
    brut = db.execute(text(f"SELECT {champ} FROM {table} WHERE id = :i"), {"i": r.json()["id"]}).scalar()
    assert Decimal(str(brut)) == Decimal("100.00")
