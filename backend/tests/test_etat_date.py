"""Documents de la vente d'un lot : pré-état daté, état daté, projet d'opposition (demande de Fred, 20/11/2026)."""
import io
from datetime import date, timedelta

from pypdf import PdfReader

from app.models.exercice import BudgetLine
from tests.conftest import auth
from tests.test_mutations import A, _immeuble


def _texte(contenu: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(contenu)).pages).replace("\n", " ")


def _budget(db, ex, montant=2400):
    db.add(BudgetLine(exercice_id=ex.id, libelle="Charges courantes", montant=montant))
    db.commit()


def test_situation_au_jour(db, copro_a, syndic_a):
    from app.services import etat_date      # importé ici : sans le code, les tests échouent un par un
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    _budget(db, ex)
    s = etat_date.situation(db, copro_a, l12, date(A, 5, 15))          # par l'annexe : tout l'ensemble
    assert s["libelle_lots"] == "Lot 1 (avec lot 12)" and s["proprietaire"] == (paul.nom_complet or paul.email)
    assert s["du"] == 320 and [l["libelle"] for l in s["dus"]] == ["Provision 4 — lot 1", "Provision 4 — lot 12"]
    assert s["futurs_total"] == 640                                     # juillet et octobre, à l'acquéreur
    # Quote-part du budget : 2 400 € × 640 / 1 000 = 1 536 € ; 4 × 320 déjà appelés → 256 € pas encore appelés.
    assert s["reste_budget"] == 256
    assert s["impayes_copro"] == 960 and s["dettes_fournisseurs"] == 0
    assert [(p["annee"], p["existe"]) for p in s["precedents"]] == [(A - 1, False), (A - 2, False)]


def test_pre_etat_date_et_etat_date(client, db, copro_a, syndic_a, token_a):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    _budget(db, ex)
    r = client.get(f"/api/mutations/documents/pre-etat-date.pdf?lot_id={l1.id}&jour={A}-05-15", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    t = _texte(r.content)
    assert "PRÉ-ÉTAT DATÉ" in t and "L721-2" in t and "Lot 1 (avec lot 12)" in t and "256,00 €" in t
    r = client.get(f"/api/mutations/documents/etat-date.pdf?lot_id={l1.id}&jour={A}-05-15"
                   "&procedures=Aucune", headers=auth(token_a))
    assert r.status_code == 200, r.text
    t = _texte(r.content)
    assert "ÉTAT DATÉ" in t and "1re partie" in t and "3e partie" in t and "320,00 €" in t and "640" not in t.split("1re partie")[0]
    assert "Provision 7" in t.split("3e partie")[1]
    # Date future, lot d'une autre copropriété, compte non syndic.
    futur = date.today() + timedelta(days=2)
    assert client.get(f"/api/mutations/documents/etat-date.pdf?lot_id={l1.id}&jour={futur}",
                      headers=auth(token_a)).status_code == 422
    assert client.get("/api/mutations/documents/etat-date.pdf?lot_id=99999", headers=auth(token_a)).status_code == 404
    from app.core.security import create_access_token
    t_paul = create_access_token(paul.id, copro_a.id)
    assert client.get(f"/api/mutations/documents/etat-date.pdf?lot_id={l1.id}", headers=auth(t_paul)).status_code == 403


def test_projet_d_opposition(client, db, copro_a, syndic_a, token_a):
    paul, anne, l1, l12, ex = _immeuble(db, copro_a)
    r = client.post("/api/mutations", json={"lot_id": l1.id, "date_acte": f"{A}-05-15", "acquereur_id": anne.id,
                                            "notaire": "Me Durand", "avis_mutation_le": f"{A}-05-20"},
                    headers=auth(token_a))
    mid = r.json()["id"]
    r = client.get(f"/api/mutations/{mid}/opposition.pdf", headers=auth(token_a))
    assert r.status_code == 200, r.text
    t = _texte(r.content)
    assert "OPPOSITION" in t and "Me Durand" in t and f"04/06/{A}" in t
    assert "Année courante et deux dernières années échues : 320,00 €" in t and "Total réclamé : 320,00 €" in t


def test_categories_art_5_1():
    from app.services import etat_date
    l = lambda annee, m: {"exercice": annee, "restant_du": m}           # noqa: E731
    cats = etat_date.categories_opposition(date(2026, 5, 1), [l(2026, 10), l(2024, 20), l(2023, 30), l(2022, 40),
                                                               l(2021, 50)])
    assert [c["total"] for c in cats] == [30, 70, 50]
