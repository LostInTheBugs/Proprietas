"""Clés de répartition : charges spéciales (loi 1965, art. 10 ; demande de Fred, 20/11/2026 ; issue #65).

Choix de Fred : un appel de provisions se répartit comme le budget, chaque part par sa clé ; un appel peut
aussi porter sur une seule clé. Cas de l'issue #65 : trois bâtiments, des charges sur tous les lots
(« quote-part générale ») et d'autres sur un seul bâtiment (« charge commune spéciale »).

Immeuble d'essai : lots 1 et 2 (bâtiment A), lot 3 (bâtiment B), 1000 tantièmes généraux (300/300/400) ;
clé « Bâtiment A » : lots 1 et 2, 500/500 ; clé « Ascenseur » : lot 2 seul.
"""
from datetime import date

import pytest

from app.models.appel import AppelLot
from app.models.lot import Lot
from app.services import cles
from tests.conftest import auth

Y = date.today().year


@pytest.fixture()
def immeuble(client, db, copro_a, syndic_a, token_a):
    lots = [Lot(copropriete_id=copro_a.id, numero=str(i), tantiemes=t) for i, t in ((1, 300), (2, 300), (3, 400))]
    db.add_all(lots)
    db.commit()
    l1, l2, l3 = lots
    r = client.post("/api/cles", json={"nom": "Bâtiment A", "lots": [{"lot_id": l1.id, "tantiemes": 500},
                                                                    {"lot_id": l2.id, "tantiemes": 500}]},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    bat_a = next(c for c in r.json() if c["nom"] == "Bâtiment A")
    r = client.post("/api/cles", json={"nom": "Ascenseur", "lots": [{"lot_id": l2.id, "tantiemes": 1000},
                                                                  {"lot_id": l3.id, "tantiemes": 0}]},
                    headers=auth(token_a))
    asc = next(c for c in r.json() if c["nom"] == "Ascenseur")
    ex_id = client.post("/api/exercices", json={"annee": Y}, headers=auth(token_a)).json()["id"]
    return {"lots": lots, "bat_a": bat_a, "asc": asc, "ex": ex_id}


def _parts(db, appel_id):
    db.expire_all()
    return {p.lot_id: (float(p.montant_charges), float(p.montant_fonds_travaux))
            for p in db.query(AppelLot).filter(AppelLot.appel_id == appel_id)}


def test_cles_et_leurs_lots(client, db, token_a, immeuble):
    bat_a, asc = immeuble["bat_a"], immeuble["asc"]
    assert (bat_a["total"], [l["tantiemes"] for l in bat_a["lots"]]) == (1000, [500, 500])
    assert [l["lot_numero"] for l in asc["lots"]] == ["2"]                    # 0 millième : lot non concerné
    # Nom réservé, en double, clé sans aucun millième.
    for corps, code in (({"nom": "Charges générales", "lots": []}, 422), ({"nom": "Ascenseur", "lots": []}, 409),
                        ({"nom": "Vide", "lots": [{"lot_id": immeuble["lots"][0].id, "tantiemes": 0}]}, 422)):
        r = client.post("/api/cles", json=corps, headers=auth(token_a))
        assert r.status_code == code, (corps, r.text)


def test_appel_reparti_comme_le_budget(client, db, token_a, immeuble):
    l1, l2, l3 = immeuble["lots"]
    ex = immeuble["ex"]
    for libelle, montant, cle in (("Entretien", 700, None), ("Ascenseur", 300, immeuble["asc"]["id"])):
        r = client.post(f"/api/exercices/{ex}/budget", json={"libelle": libelle, "montant": montant, "cle_id": cle},
                        headers=auth(token_a))
        assert r.status_code == 200 and r.json()["cle_id"] == cle
    r = client.post(f"/api/exercices/{ex}/appels", json={"libelle": "T1", "date_emission": f"{Y}-01-01",
                                                        "montant_total": 250}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    # 250 € : 175 € de charges générales (300/300/400) + 75 € d'ascenseur (lot 2 seul).
    assert _parts(db, r.json()["id"]) == {l1.id: (52.5, 0.0), l2.id: (127.5, 0.0), l3.id: (70.0, 0.0)}
    # Appel sur une seule clé : bâtiment A seulement.
    r = client.post(f"/api/exercices/{ex}/appels", json={"libelle": "Toiture A", "date_emission": f"{Y}-03-01",
                                                        "montant_total": 1000, "cle_id": immeuble["bat_a"]["id"]},
                    headers=auth(token_a))
    assert r.json()["cle_id"] == immeuble["bat_a"]["id"]
    assert _parts(db, r.json()["id"]) == {l1.id: (500.0, 0.0), l2.id: (500.0, 0.0)}


def test_fonds_de_travaux_par_les_tantiemes_generaux(client, db, copro_a, token_a, immeuble):
    l1, l2, l3 = immeuble["lots"]
    copro_a.fonds_travaux_actif, copro_a.fonds_travaux_taux_pct = True, 5
    db.commit()
    r = client.post(f"/api/exercices/{immeuble['ex']}/appels",
                    json={"libelle": "Ascenseur", "date_emission": f"{Y}-01-01", "montant_total": 1000,
                          "cle_id": immeuble["asc"]["id"], "inclut_fonds_travaux": True}, headers=auth(token_a))
    assert _parts(db, r.json()["id"]) == {l1.id: (0.0, 15.0), l2.id: (1000.0, 15.0), l3.id: (0.0, 20.0)}


def test_sans_cle_rien_ne_change(client, db, token_a, immeuble):
    l1, l2, l3 = immeuble["lots"]
    r = client.post(f"/api/exercices/{immeuble['ex']}/appels",
                    json={"libelle": "T1", "date_emission": f"{Y}-01-01", "montant_total": 100}, headers=auth(token_a))
    assert _parts(db, r.json()["id"]) == {l1.id: (30.0, 0.0), l2.id: (30.0, 0.0), l3.id: (40.0, 0.0)}


def test_regularisation_cle_par_cle(client, db, token_a, immeuble):
    from app.models.exercice import Exercice
    from app.services import regularisation
    l1, l2, l3 = immeuble["lots"]
    ex = immeuble["ex"]
    for libelle, montant, cle in (("Électricité", 100, None), ("Contrat ascenseur", 600, immeuble["asc"]["id"]),
                                  ("Ménage bâtiment A", 200, immeuble["bat_a"]["id"])):
        r = client.post(f"/api/exercices/{ex}/mouvements", json={
            "date": f"{Y}-02-01", "libelle": libelle, "type": "depense", "categorie": "charges",
            "montant": montant, "cle_id": cle}, headers=auth(token_a))
        assert r.status_code == 200, r.text
        assert r.json()["cle_nom"] == ("" if cle is None else ("Ascenseur" if cle == immeuble["asc"]["id"] else "Bâtiment A"))
    lignes = {l["lot_id"]: l["charges_reelles"] for l in regularisation.calcul(db, db.get(Exercice, ex))["lignes"]}
    # Lot 1 : 30 (général) + 100 (bâtiment A) ; lot 2 : 30 + 600 + 100 ; lot 3 : 40.
    assert lignes == {l1.id: 130, l2.id: 730, l3.id: 40}


def test_regles(client, db, token_a, immeuble):
    ex, asc = immeuble["ex"], immeuble["asc"]["id"]
    base = {"date": f"{Y}-02-01", "libelle": "x", "type": "depense", "categorie": "charges", "montant": 10}
    for champs in ({"type": "encaissement"}, {"lot_id": immeuble["lots"][0].id}):
        r = client.post(f"/api/exercices/{ex}/mouvements", json={**base, **champs, "cle_id": asc}, headers=auth(token_a))
        assert r.status_code == 422 and "dépense commune" in r.json()["detail"]
    # Une clé d'une autre copropriété, ou utilisée, ne se prend ni ne se supprime.
    assert client.post(f"/api/exercices/{ex}/budget", json={"libelle": "x", "montant": 1, "cle_id": 99999},
                       headers=auth(token_a)).status_code == 422
    client.post(f"/api/exercices/{ex}/budget", json={"libelle": "Ascenseur", "montant": 1, "cle_id": asc},
                headers=auth(token_a))
    r = client.delete(f"/api/cles/{asc}", headers=auth(token_a))
    assert r.status_code == 409 and "1 ligne(s) de budget" in r.json()["detail"]
    assert client.delete(f"/api/cles/{immeuble['bat_a']['id']}", headers=auth(token_a)).status_code == 200


def test_compte_de_gestion(client, db, token_a, immeuble):
    import io
    from pypdf import PdfReader
    ex = immeuble["ex"]
    client.post(f"/api/exercices/{ex}/budget", json={"libelle": "Ascenseur", "montant": 300,
                                                    "cle_id": immeuble["asc"]["id"]}, headers=auth(token_a))
    client.post(f"/api/exercices/{ex}/mouvements", json={"date": f"{Y}-02-01", "libelle": "Contrat ascenseur",
                "type": "depense", "categorie": "charges", "montant": 250, "cle_id": immeuble["asc"]["id"]},
                headers=auth(token_a))
    pdf = client.get(f"/api/export/compte-gestion/{ex}", headers=auth(token_a))
    assert pdf.status_code == 200
    texte = " ".join(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages).split())
    assert "RÉPARTITION PAR CLÉ" in texte and "Charges spéciales : Ascenseur" in texte


def test_lot_supprime_quitte_ses_cles(client, db, token_a, immeuble):
    l1 = immeuble["lots"][0]
    assert client.delete(f"/api/lots/{l1.id}", headers=auth(token_a)).status_code == 200
    bat_a = next(c for c in client.get("/api/cles", headers=auth(token_a)).json() if c["nom"] == "Bâtiment A")
    assert bat_a["total"] == 500


def test_lecture_pour_les_coproprietaires(client, db, copro_a, immeuble):
    from app.core.security import create_access_token
    from tests.conftest import _make_membre
    m = _make_membre(db, "m@test.fr", copro_a)
    tok = create_access_token(m.id, copro_a.id)
    assert len(client.get("/api/cles", headers=auth(tok)).json()) == 2
    assert client.post("/api/cles", json={"nom": "X", "lots": []}, headers=auth(tok)).status_code == 403


def test_migration(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from app import demarrage
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "head")
    i = inspect(create_engine(url))
    assert {"cles_repartition", "cles_lots"} <= set(i.get_table_names())
    assert all("cle_id" in [c["name"] for c in i.get_columns(t)] for t in ("budget_lines", "appels_fonds", "mouvements"))
    command.downgrade(cfg, "a3b4c5d6e7f8")
    assert "cles_lots" not in inspect(create_engine(url)).get_table_names()
    command.upgrade(cfg, "head")


def test_repartir_selon_budget_au_centime(db, copro_a, immeuble):
    from decimal import Decimal
    parts = cles.repartir_selon_budget(db, copro_a.id, immeuble["ex"], Decimal("100.01"))
    assert sum(parts.values()) == Decimal("100.01")
