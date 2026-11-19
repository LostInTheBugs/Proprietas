"""Résolutions types d'une AG annuelle (demande de Fred, 20/11/2026).

Pré-cochées : bureau (président, scrutateurs, secrétaire), approbation des comptes de l'exercice écoulé (reliée à
l'exercice), quitus, budget de l'exercice suivant (montant repris), cotisation au fonds de travaux (art. 25).
À cocher si besoin : ajustement du budget en cours, syndic bénévole, conseil syndical, seuils de l'art. 21, PPT.
"""
from datetime import date

from app.models.ag import Resolution
from tests.conftest import auth

AN = date.today().year
JOUR = date(AN, 6, 15)


def _exercices(client, token):
    ids = {}
    for a in (AN - 1, AN + 1):
        ids[a] = client.post("/api/exercices", json={"annee": a}, headers=auth(token)).json()["id"]
    client.post(f"/api/exercices/{ids[AN + 1]}/budget", json={"libelle": "Entretien", "montant": 12000},
                headers=auth(token))
    return ids


def test_modele_et_creation(client, db, copro_a, syndic_a, token_a):
    ids = _exercices(client, token_a)
    copro_a.fonds_travaux_taux_pct = 5
    db.commit()
    r = client.get(f"/api/ag/modele-annuelle?jour={JOUR}", headers=auth(token_a))
    assert r.status_code == 200, r.text
    modele = {m["code"]: m for m in r.json()}
    assert [c for c, m in modele.items() if m["coche"]] == ["president", "scrutateurs", "secretaire", "comptes",
                                                           "quitus", "budget", "fonds_travaux"]
    assert modele["comptes"]["exercice_id"] == ids[AN - 1] and modele["comptes"]["nature"] == "approbation_comptes"
    assert "12 000,00 €" in modele["budget"]["texte"] and modele["budget"]["nature"] == "budget"
    assert "600,00 €" in modele["fonds_travaux"]["texte"] and modele["fonds_travaux"]["majorite"] == "art25"
    assert modele["syndic"]["majorite"] == "art25" and syndic_a.nom in modele["syndic"]["texte"]
    ag = client.post("/api/ag", json={"date": str(JOUR), "type_ag": "annuelle"}, headers=auth(token_a)).json()
    client.post(f"/api/ag/{ag['id']}/resolutions", json={"numero": 1, "libelle": "Déjà là"}, headers=auth(token_a))
    r = client.post(f"/api/ag/{ag['id']}/resolutions-types",
                    json={"codes": ["budget", "president", "comptes", "syndic"]}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert [(x["numero"], x["libelle"].split(" ")[0]) for x in r.json()] == \
        [(2, "Élection"), (3, "Approbation"), (4, "Vote"), (5, "Désignation")]           # ordre du modèle
    comptes = db.query(Resolution).filter(Resolution.nature == "approbation_comptes").one()
    assert comptes.exercice_id == ids[AN - 1]


def test_sans_exercice_ecoule(client, db, copro_a, syndic_a, token_a):
    m = {x["code"]: x for x in client.get(f"/api/ag/modele-annuelle?jour={JOUR}", headers=auth(token_a)).json()}
    assert m["comptes"]["coche"] is False and "créez-le" in m["comptes"]["remarque"]
    assert "……" in m["budget"]["texte"] and m["budget"]["remarque"]
    ag = client.post("/api/ag", json={"date": str(JOUR)}, headers=auth(token_a)).json()
    r = client.post(f"/api/ag/{ag['id']}/resolutions-types", json={"codes": ["comptes"]}, headers=auth(token_a))
    assert r.status_code == 422 and "créez-le" in r.json()["detail"]
    r = client.post(f"/api/ag/{ag['id']}/resolutions-types", json={"codes": ["inexistant"]}, headers=auth(token_a))
    assert r.status_code == 422


def test_pas_en_consultation_ecrite_ni_pour_un_copropriétaire(client, db, copro_a, syndic_a, token_a, monkeypatch):
    from app.core.security import create_access_token
    from app.models.ag import AG
    from tests.conftest import _make_membre
    ag = AG(copropriete_id=copro_a.id, date=JOUR, type_ag="consultation_ecrite")
    db.add(ag)
    db.commit()
    r = client.post(f"/api/ag/{ag.id}/resolutions-types", json={"codes": ["president"]}, headers=auth(token_a))
    assert r.status_code == 422
    m = _make_membre(db, "m@test.fr", copro_a)
    assert client.get(f"/api/ag/modele-annuelle?jour={JOUR}",
                      headers=auth(create_access_token(m.id, copro_a.id))).status_code == 403
