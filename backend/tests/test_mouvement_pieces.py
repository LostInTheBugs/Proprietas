"""Rattacher un mouvement à un contrat et/ou à une facture (document).

Règles retenues :
- un mouvement peut porter un contrat (`contrat_id`) et un document (`document_id`, la facture) de la
  copropriété, à la création comme en modification ; un contrat ou un document d'une autre
  copropriété est refusé (422) ;
- supprimer le contrat ou le document délie le mouvement, qui reste ;
- la liste des contrats indique, pour chacun, le nombre de mouvements rattachés et le total des
  dépenses rattachées de l'année en cours.
"""
from datetime import date

from app.models.contrat import Contrat
from app.models.document import Document
from app.models.mouvement import Mouvement
from tests.conftest import auth

Y = date.today().year


def _base(client, db, copro, token):
    ex_id = client.post("/api/exercices", json={"annee": Y}, headers=auth(token)).json()["id"]
    contrat = Contrat(copropriete_id=copro.id, libelle="EDF parties communes", type="energie")
    facture = Document(copropriete_id=copro.id, categorie="facture", libelle="Facture EDF janvier",
                       fichier="x.pdf", date_ajout=date.today())
    db.add_all([contrat, facture])
    db.commit()
    return ex_id, contrat, facture


def _corps(**champs):
    return {"date": f"{Y}-02-01", "libelle": "Facture EDF janvier", "type": "depense", "categorie": "energie",
            "montant": 120, **champs}


def test_creer_un_mouvement_rattache(client, db, copro_a, syndic_a, token_a):
    ex_id, contrat, facture = _base(client, db, copro_a, token_a)
    r = client.post(f"/api/exercices/{ex_id}/mouvements",
                    json=_corps(contrat_id=contrat.id, document_id=facture.id), headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["contrat_id"], r.json()["document_id"]) == (contrat.id, facture.id)
    [m] = client.get(f"/api/exercices/{ex_id}/mouvements", headers=auth(token_a)).json()
    assert (m["contrat_id"], m["document_id"]) == (contrat.id, facture.id)


def test_rattacher_en_modification(client, db, copro_a, syndic_a, token_a):
    ex_id, contrat, facture = _base(client, db, copro_a, token_a)
    m = client.post(f"/api/exercices/{ex_id}/mouvements", json=_corps(), headers=auth(token_a)).json()
    r = client.put(f"/api/mouvements/{m['id']}", json=_corps(contrat_id=contrat.id), headers=auth(token_a))
    assert r.status_code == 200 and r.json()["contrat_id"] == contrat.id and r.json()["document_id"] is None
    r = client.put(f"/api/mouvements/{m['id']}", json=_corps(document_id=facture.id), headers=auth(token_a))
    assert r.json()["contrat_id"] is None and r.json()["document_id"] == facture.id


def test_contrat_ou_document_d_une_autre_copropriete(client, db, copro_a, copro_b, syndic_a, token_a):
    ex_id, _, _ = _base(client, db, copro_a, token_a)
    c_b = Contrat(copropriete_id=copro_b.id, libelle="Autre")
    d_b = Document(copropriete_id=copro_b.id, libelle="Autre", fichier="y.pdf", date_ajout=date.today())
    db.add_all([c_b, d_b])
    db.commit()
    url = f"/api/exercices/{ex_id}/mouvements"
    assert client.post(url, json=_corps(contrat_id=c_b.id), headers=auth(token_a)).status_code == 422
    assert client.post(url, json=_corps(document_id=d_b.id), headers=auth(token_a)).status_code == 422
    assert db.query(Mouvement).count() == 0


def test_supprimer_le_contrat_ou_le_document_delie(client, db, copro_a, syndic_a, token_a):
    ex_id, contrat, facture = _base(client, db, copro_a, token_a)
    client.post(f"/api/exercices/{ex_id}/mouvements",
                json=_corps(contrat_id=contrat.id, document_id=facture.id), headers=auth(token_a))
    assert client.delete(f"/api/contrats/{contrat.id}", headers=auth(token_a)).status_code == 200
    assert client.delete(f"/api/documents/{facture.id}", headers=auth(token_a)).status_code == 200
    [m] = client.get(f"/api/exercices/{ex_id}/mouvements", headers=auth(token_a)).json()
    assert (m["contrat_id"], m["document_id"], m["montant"]) == (None, None, 120)


def test_contrats_avec_total_des_depenses(client, db, copro_a, syndic_a, token_a):
    ex_id, contrat, _ = _base(client, db, copro_a, token_a)
    url = f"/api/exercices/{ex_id}/mouvements"
    client.post(url, json=_corps(contrat_id=contrat.id), headers=auth(token_a))
    client.post(url, json=_corps(contrat_id=contrat.id, montant=80.5, date=f"{Y}-03-01"), headers=auth(token_a))
    # Une dépense d'une autre année compte dans le nombre, pas dans le total de l'année.
    client.post(url, json=_corps(contrat_id=contrat.id, montant=999, date=f"{Y - 1}-12-01"), headers=auth(token_a))
    [c] = client.get("/api/contrats", headers=auth(token_a)).json()
    assert (c["nb_mouvements"], c["depenses_annee"]) == (3, 200.5)
