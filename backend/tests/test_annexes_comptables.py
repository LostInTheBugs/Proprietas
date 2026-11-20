"""Annexes comptables (demande de Fred, 20/11/2026) : état financier, compte de gestion général, opérations courantes
par catégorie (réalisé N-1, budget N, réalisé N, budget N+1), travaux, opérations non clôturées."""
import io
from datetime import date

from pypdf import PdfReader

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import BudgetLine, Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.travaux import Travaux
from tests.conftest import _make_membre, auth

A = date.today().year - 1


def _copro(db, copro):
    paul = _make_membre(db, "paul@exemple.fr", copro)
    lot = Lot(copropriete_id=copro.id, numero="1", tantiemes=1000, proprietaire_id=paul.id)
    db.add(lot)
    exs = {}
    for annee in (A - 1, A, A + 1):
        ex = Exercice(copropriete_id=copro.id, annee=annee)
        db.add(ex)
        db.flush()
        exs[annee] = ex
    db.add_all([BudgetLine(exercice_id=exs[A].id, libelle="EDF", montant=1000, categorie="energie"),
                BudgetLine(exercice_id=exs[A].id, libelle="Assurance", montant=600, categorie="assurance"),
                BudgetLine(exercice_id=exs[A + 1].id, libelle="EDF", montant=1100, categorie="energie")])
    a = AppelFonds(exercice_id=exs[A].id, libelle="Provisions", date_emission=date(A, 1, 1), date_echeance=date(A, 1, 1),
                   montant_total=1600)
    db.add(a)
    db.flush()
    db.add(AppelLot(appel_id=a.id, lot_id=lot.id, montant_charges=1600, montant_fonds_travaux=80))
    d = lambda ex, j, lib, cat, mt, **k: Mouvement(copropriete_id=copro.id, exercice_id=exs[ex].id, date=j,  # noqa: E731
                                                   libelle=lib, type="depense", categorie=cat, montant=mt, **k)
    db.add_all([d(A - 1, date(A - 1, 3, 1), "EDF", "energie", 900),
                d(A, date(A, 3, 1), "EDF", "energie", 950),
                d(A, date(A, 6, 1), "Assurance", "assurance", 610, a_payer=True),
                d(A, date(A, 9, 1), "Toiture", "travaux", 2000),
                Mouvement(copropriete_id=copro.id, exercice_id=exs[A].id, date=date(A, 2, 1), libelle="Virement",
                          type="encaissement", categorie="charges", montant=1000, lot_id=lot.id)])
    db.add(Travaux(copropriete_id=copro.id, libelle="Ravalement", categorie="facade", annee=A, montant=30000,
                   statut="planifie"))
    db.commit()
    return exs


def test_annexes(client, db, copro_a, syndic_a, token_a):
    from app.services import annexes_comptables as svc
    exs = _copro(db, copro_a)
    a = svc.annexes(db, copro_a, exs[A])
    l = {x["groupe"]: x for x in a["courantes"]}
    assert (l["energie"]["realise_prec"], l["energie"]["budget"], l["energie"]["realise"], l["energie"]["budget_suiv"]) == (
        900, 1000, 950, 1100)
    assert (l["assurance"]["budget"], l["assurance"]["realise"]) == (600, 610)       # facture reçue non réglée comprise
    assert a["totaux_courantes"]["realise"] == 1560 and a["travaux"][A]["travaux"] == 2000
    assert (a["produits"][A]["provisions"], a["produits"][A]["fonds_travaux"]) == (1600, 80)
    ef = a["etat_financier"]
    actif, passif = dict(ef["actif"]), dict(ef["passif"])
    assert actif["Copropriétaires débiteurs"] == 680                                    # 1 680 appelés − 1 000 reçus
    assert passif["Fournisseurs : factures reçues non réglées"] == 610
    assert ef["total_actif"] == ef["total_passif"]
    assert [x["libelle"] for x in a["en_cours"]] == ["Ravalement"]
    r = client.get(f"/api/export/annexes-comptables/{exs[A].id}", headers=auth(token_a))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    t = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages).replace("\n", " ")
    for n in range(1, 6):
        assert f"ANNEXE {n}" in t
    assert "Ravalement" in t and "1 100,00 €" in t
    assert client.get("/api/export/annexes-comptables/99999", headers=auth(token_a)).status_code == 404


def test_categorie_des_lignes_de_budget(client, db, copro_a, syndic_a, token_a):
    ex = client.post("/api/exercices", json={"annee": A}, headers=auth(token_a)).json()["id"]
    r = client.post(f"/api/exercices/{ex}/budget", json={"libelle": "EDF", "montant": 100, "categorie": "energie"},
                    headers=auth(token_a))
    assert r.status_code == 200 and r.json()["categorie"] == "energie"
    r = client.post(f"/api/exercices/{ex}/budget", json={"libelle": "X", "montant": 100}, headers=auth(token_a))
    assert r.json()["categorie"] == "charges"
    assert client.post(f"/api/exercices/{ex}/budget", json={"libelle": "X", "montant": 1, "categorie": "chateau"},
                       headers=auth(token_a)).status_code == 422
