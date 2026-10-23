"""Calcul des tantièmes et appels de fonds — répartition par millièmes.

Couvre le cas « total ≠ 1000 » (commit b3f542b : le total réel sert de base de
répartition) et les arrondis : la somme des quotes-parts doit égaler le montant
appelé au centime près.
"""
from decimal import Decimal as D
from app.models.lot import Lot
from app.services.country_rules import repartir_par_tantiemes
from app.core.money import somme
from tests.conftest import auth


def _lot(id_, tantiemes):
    return Lot(id=id_, numero=str(id_), tantiemes=tantiemes)


# ---------- Unité : répartition par millièmes ----------
def test_repartition_total_1000():
    lots = [_lot(1, 280), _lot(2, 260), _lot(3, 240), _lot(4, 220)]
    parts = repartir_par_tantiemes(D(3000), lots)
    assert [p["montant_charges"] for p in parts] == [D("840.00"), D("780.00"), D("720.00"), D("660.00")]
    assert somme(p["montant_charges"] for p in parts) == D("3000.00")


def test_repartition_total_1000_avec_fonds_travaux():
    lots = [_lot(1, 280), _lot(2, 260), _lot(3, 240), _lot(4, 220)]
    parts = repartir_par_tantiemes(D(3000), lots, fonds_travaux_taux=D(5))
    # lot 1 : 840 + 5 % = 42
    assert parts[0]["montant_fonds_travaux"] == D("42.00")
    assert somme(p["montant_fonds_travaux"] for p in parts) == D("150.00")
    # total charges + fonds = 3150
    total = somme(p["montant_charges"] + p["montant_fonds_travaux"] for p in parts)
    assert total == D("3150.00")


# ---------- Cas total ≠ 1000 (b3f542b) ----------
def test_repartition_total_non_1000():
    """Total réel 900 : les parts sont proportionnelles à 900, pas à 1000."""
    lots = [_lot(1, 450), _lot(2, 450)]
    parts = repartir_par_tantiemes(D(900), lots)
    assert [p["montant_charges"] for p in parts] == [D("450.00"), D("450.00")]
    assert somme(p["montant_charges"] for p in parts) == D("900.00")


def test_repartition_total_non_1000_desequilibre():
    lots = [_lot(1, 600), _lot(2, 200), _lot(3, 100)]  # total 900
    parts = repartir_par_tantiemes(D(900), lots)
    # 600/900 = 2/3 → 600 ; 200/900 → 200 ; 100/900 → 100
    assert [p["montant_charges"] for p in parts] == [D("600.00"), D("200.00"), D("100.00")]


# ---------- Arrondis ----------
def test_arrondi_reste_impute_au_premier_lot():
    """123,45 € répartis sur 3 lots égaux : 41,15 × 3 = 123,45 (reste imputé)."""
    lots = [_lot(1, 333), _lot(2, 333), _lot(3, 334)]
    parts = repartir_par_tantiemes(D(123.45), lots)
    assert somme(p["montant_charges"] for p in parts) == D("123.45")


def test_arrondi_somme_tombe_juste_au_centime():
    """Propriété générale : somme(parts) == montant appelé, quel que soit le découpage."""
    for montant in (D("0.01"), D("1.00"), D("100.00"), D("3000.00"), D("1234.56"), D("9999.99")):
        lots = [_lot(1, 137), _lot(2, 246), _lot(3, 358), _lot(4, 259)]  # total 1000
        parts = repartir_par_tantiemes(montant, lots)
        s = somme(p["montant_charges"] for p in parts)
        assert abs(s - montant) < D("0.005"), f"{montant} -> {s}"


def test_arrondi_fonds_travaux_inclus():
    """Avec fonds travaux : charges + fonds == montant × 1,05 (au centime près)."""
    lots = [_lot(1, 137), _lot(2, 246), _lot(3, 358), _lot(4, 259)]
    parts = repartir_par_tantiemes(D(3000), lots, fonds_travaux_taux=D(5))
    total = somme(p["montant_charges"] + p["montant_fonds_travaux"] for p in parts)
    assert total == D("3150.00")


def test_repartition_sans_lots_renvoie_vide():
    assert repartir_par_tantiemes(D(100), []) == []


# ---------- Via l'API : create_appel ----------
def test_api_appel_repartition_exacte(client, token_a):
    from tests.conftest import auth
    # 4 lots, total 1000
    for num, tant in (("1", 280), ("2", 260), ("3", 240), ("4", 220)):
        r = client.post("/api/lots", json={"numero": num, "tantiemes": tant}, headers=auth(token_a))
        assert r.status_code == 200, r.text
    r = client.post("/api/exercices", json={"annee": 2026}, headers=auth(token_a))
    ex = r.json()
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "Appel Q1", "date_emission": "2026-01-05", "montant_total": 3000.0,
        "inclut_fonds_travaux": True,
    }, headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = r.json()
    parts = appel["parts"]
    assert len(parts) == 4
    # La somme des quotes-parts tombe juste (au centime près)
    somme = round(sum(p["montant_charges"] for p in parts), 2)
    assert abs(somme - 3000.0) < 0.01
    # Fonds travaux 5 % inclus
    ft = round(sum(p["montant_fonds_travaux"] for p in parts), 2)
    assert abs(ft - 150.0) < 0.01
    assert abs(appel["fonds_travaux_montant"] - 150.0) < 0.01


def test_api_appel_total_non_1000(client, token_a):
    """Cas b3f542b via l'API : lots totalisant 900 millièmes."""
    from tests.conftest import auth
    for num, tant in (("1", 450), ("2", 450)):
        r = client.post("/api/lots", json={"numero": num, "tantiemes": tant}, headers=auth(token_a))
        assert r.status_code == 200, r.text
    r = client.post("/api/exercices", json={"annee": 2027}, headers=auth(token_a))
    ex = r.json()
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "Appel 900", "date_emission": "2027-01-05", "montant_total": 900.0,
    }, headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = r.json()
    # 450/900 et 450/900 → moitié-moitié
    assert [p["montant_charges"] for p in appel["parts"]] == [450.0, 450.0]
