"""Non-régression IDOR : isolation multi-copropriétés.

Deux copropriétés A et B, chacune avec un syndic. Tout objet créé dans A
doit être inaccessible (404) au syndic de B sur GET / PUT / DELETE par id,
et rester accessible au syndic de A (pas de régression).
"""
from datetime import date, datetime

from app.models.document import Document
from tests.conftest import auth


def _membre_a(client, token_a):
    """Compte copropriétaire de A (modèle « zéro fiche » : le compte EST la personne)."""
    r = client.post("/api/auth/users", json={
        "email": "durand.a@test.fr", "password": "test1234", "nom": "Durand",
        "prenom": "Paul", "role": "membre"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


def _lot_a(client, token_a, proprietaire=None):
    data = {"numero": "1", "designation": "Appartement 1", "tantiemes": 1000}
    if proprietaire:
        data["proprietaire_id"] = proprietaire["id"]
    r = client.post("/api/lots", json=data, headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


def _exercice_a(client, token_a, annee=2026):
    r = client.post("/api/exercices", json={"annee": annee}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


def _ag_a(client, token_a):
    r = client.post("/api/ag", json={"date": "2026-03-10", "type_ag": "annuelle"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Comptes copropriétaires ----------
def test_compte_isole(client, token_a, token_b):
    """B ne voit ni ne modifie le compte de A (404) ; A le gère normalement."""
    u = _membre_a(client, token_a)
    payload = {"email": "durand.a@test.fr", "nom": "Piraté", "prenom": "Paul", "role": "membre"}
    assert client.put(f"/api/auth/users/{u['id']}", json=payload, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/auth/users/{u['id']}", headers=auth(token_b)).status_code == 404
    # A y accède normalement
    r = client.put(f"/api/auth/users/{u['id']}", json={
        "email": "durand.a@test.fr", "nom": "Durand", "prenom": "Paul",
        "role": "membre", "adresse": "1 rue A"}, headers=auth(token_a))
    assert r.status_code == 200
    assert r.json()["nom"] == "Durand"
    assert r.json()["adresse"] == "1 rue A"


# ---------- Lots ----------
def test_lot_isole(client, token_a, token_b):
    lot = _lot_a(client, token_a)
    assert client.put(f"/api/lots/{lot['id']}", json={"numero": "X"}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/lots/{lot['id']}", headers=auth(token_b)).status_code == 404
    r = client.put(f"/api/lots/{lot['id']}", json={"numero": "1", "tantiemes": 1000}, headers=auth(token_a))
    assert r.status_code == 200
    assert r.json()["numero"] == "1"


# ---------- Documents ----------
def test_document_isole(client, token_a, token_b):
    files = {"fichier": ("contrat.pdf", b"%PDF-1.4 test", "application/pdf")}
    r = client.post(
        "/api/documents",
        data={"categorie": "assurance", "libelle": "Contrat assurance 2026"},
        files=files,
        headers=auth(token_a),
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    # B ne peut ni télécharger ni supprimer le document de A
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(token_b)).status_code == 404
    # A télécharge toujours
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 test"


def test_document_nom_telechargement_assaini(client, token_a):
    """Pas d'injection d'en-tête via le libellé dans Content-Disposition."""
    libelle = 'Contrat "bidon"\r\nX-Evil: 1'
    files = {"fichier": ("contrat.pdf", b"%PDF-1.4 test", "application/pdf")}
    r = client.post(
        "/api/documents",
        data={"categorie": "assurance", "libelle": libelle},
        files=files,
        headers=auth(token_a),
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    # Le CR/LF a été retiré du libellé : aucune injection d'en-tête possible.
    assert "\r" not in cd and "\n" not in cd


def test_document_fichier_confinement(client, db, copro_a, token_a):
    """doc.fichier ne peut pas sortir de upload_dir (traversal)."""
    doc = Document(
        copropriete_id=copro_a.id,
        categorie="autre",
        libelle="Évasion",
        fichier="../../etc/passwd",
        date_ajout=date.today(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    assert client.get(f"/api/documents/{doc.id}/download", headers=auth(token_a)).status_code == 404


# ---------- AG / résolutions / créneaux (chaîne) ----------
def test_ag_resolution_creneau_chain_isole(client, token_a, token_b):
    ag = _ag_a(client, token_a)
    r = client.post(f"/api/ag/{ag['id']}/resolutions", json={"numero": 1, "libelle": "Approbation", "majorite": "art24"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    res = r.json()
    # Créneau dans A
    debut = datetime(2026, 3, 10, 18, 30).isoformat()
    r = client.post(f"/api/ag/{ag['id']}/creneaux", json={"debut": debut, "fin": None}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    creneau = r.json()

    # B : tout est 404 sur la chaîne AG → résolution → créneau
    assert client.put(f"/api/ag/{ag['id']}", json={"date": "2026-01-01"}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/ag/{ag['id']}", headers=auth(token_b)).status_code == 404
    assert client.put(f"/api/resolutions/{res['id']}", json={"numero": 9, "libelle": "Piraté"}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/resolutions/{res['id']}", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/creneaux/{creneau['id']}", headers=auth(token_b)).status_code == 404
    # POST chaînés sur les objets de A
    assert client.post(f"/api/ag/{ag['id']}/resolutions", json={"numero": 2, "libelle": "X"}, headers=auth(token_b)).status_code == 404
    assert client.post(f"/api/ag/{ag['id']}/creneaux", json={"debut": debut, "fin": None}, headers=auth(token_b)).status_code == 404
    assert client.post(f"/api/resolutions/{res['id']}/votes", json={"lot_id": 1, "voix": "pour"}, headers=auth(token_b)).status_code == 404
    assert client.post(f"/api/resolutions/{res['id']}/calculer", headers=auth(token_b)).status_code == 404
    assert client.post(f"/api/ag/{ag['id']}/choisir-creneau/{creneau['id']}", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/ag/{ag['id']}/creneaux", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/ag/{ag['id']}/pv", headers=auth(token_b)).status_code == 404

    # A : accès normal
    r = client.put(f"/api/ag/{ag['id']}", json={"date": "2026-03-10", "type_ag": "annuelle", "lieu": "Salle 1"}, headers=auth(token_a))
    assert r.status_code == 200
    assert r.json()["lieu"] == "Salle 1"
    r = client.put(f"/api/resolutions/{res['id']}", json={"numero": 1, "libelle": "Approbation", "majorite": "art24"}, headers=auth(token_a))
    assert r.status_code == 200


def test_vote_lot_autre_copro_refuse(client, db, copro_a, copro_b, token_a, token_b):
    """Un vote avec le lot d'une autre copro est refusé (chaîne complète)."""
    ag = _ag_a(client, token_a)
    r = client.post(f"/api/ag/{ag['id']}/resolutions", json={"numero": 1, "libelle": "Approbation", "majorite": "art24"}, headers=auth(token_a))
    res = r.json()
    # Lot de B (créé côté B), token B
    r = client.post("/api/lots", json={"numero": "B1", "tantiemes": 1000}, headers=auth(token_b))
    assert r.status_code == 200
    lot_b = r.json()
    # B ne peut pas voter avec son propre lot sur une résolution de A
    assert client.post(f"/api/resolutions/{res['id']}/votes", json={"lot_id": lot_b["id"], "voix": "pour"}, headers=auth(token_b)).status_code == 404
    # A peut voter avec un lot de A
    lot_a = _lot_a(client, token_a)
    r = client.post(f"/api/resolutions/{res['id']}/votes", json={"lot_id": lot_a["id"], "voix": "pour"}, headers=auth(token_a))
    assert r.status_code == 200, r.text


# ---------- Mouvements ----------
def test_mouvement_isole(client, token_a, token_b):
    ex = _exercice_a(client, token_a)
    r = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-01-15", "libelle": "Virement", "type": "encaissement",
        "categorie": "charges", "montant": 100.0,
    }, headers=auth(token_a))
    assert r.status_code == 200, r.text
    m = r.json()
    assert client.delete(f"/api/mouvements/{m['id']}", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/mouvements/{m['id']}", headers=auth(token_a)).status_code == 200


# ---------- Contacts ----------
def test_contact_isole(client, token_a, token_b):
    r = client.post("/api/contacts", json={"nom": "EDF", "type": "fournisseur", "categorie": "energie"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.put(f"/api/contacts/{c['id']}", json={"nom": "Piraté"}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/contacts/{c['id']}", headers=auth(token_b)).status_code == 404
    r = client.put(f"/api/contacts/{c['id']}", json={"nom": "EDF", "type": "fournisseur", "categorie": "energie"}, headers=auth(token_a))
    assert r.status_code == 200


# ---------- Contrats ----------
def test_contrat_isole(client, token_a, token_b):
    r = client.post("/api/contrats", json={"libelle": "Électricité PC", "type": "energie", "montant": 1200}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    c = r.json()
    assert client.put(f"/api/contrats/{c['id']}", json={"libelle": "Piraté"}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/contrats/{c['id']}", headers=auth(token_b)).status_code == 404
    r = client.put(f"/api/contrats/{c['id']}", json={"libelle": "Électricité PC", "type": "energie", "montant": 1200}, headers=auth(token_a))
    assert r.status_code == 200


# ---------- Entretiens (carnet) ----------
def test_entretien_isole(client, token_a, token_b):
    r = client.post("/api/carnet", json={"date": "2026-02-01", "type_intervention": "Chaudière", "cout": 500.0}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    e = r.json()
    assert client.put(f"/api/carnet/{e['id']}", json={"date": "2026-02-01", "cout": 1.0}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/carnet/{e['id']}", headers=auth(token_b)).status_code == 404
    r = client.put(f"/api/carnet/{e['id']}", json={"date": "2026-02-01", "type_intervention": "Chaudière", "cout": 500.0}, headers=auth(token_a))
    assert r.status_code == 200


# ---------- Travaux ----------
def test_travaux_isole(client, token_a, token_b):
    r = client.post("/api/travaux", json={"libelle": "Toiture", "annee": 2026, "montant": 8000.0}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    t = r.json()
    assert client.put(f"/api/travaux/{t['id']}", json={"libelle": "Piraté", "annee": 2026}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/travaux/{t['id']}", headers=auth(token_b)).status_code == 404
    r = client.put(f"/api/travaux/{t['id']}", json={"libelle": "Toiture", "annee": 2026, "montant": 8000.0}, headers=auth(token_a))
    assert r.status_code == 200


# ---------- Exercices / budget / appels ----------
def test_exercice_budget_appel_isoles(client, token_a, token_b):
    ex = _exercice_a(client, token_a)
    # Budget line dans A
    r = client.post(f"/api/exercices/{ex['id']}/budget", json={"libelle": "Entretien", "montant": 2400.0}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    line = r.json()
    # Lot + appel de fonds dans A
    lot = _lot_a(client, token_a)
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "Appel Q1", "date_emission": "2026-01-05", "montant_total": 3000.0,
    }, headers=auth(token_a))
    assert r.status_code == 200, r.text
    appel = r.json()

    # B : 404 sur tous les accès par id
    assert client.put(f"/api/exercices/{ex['id']}", json={"annee": 1999}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/exercices/{ex['id']}", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/exercices/{ex['id']}/budget", headers=auth(token_b)).status_code == 404
    assert client.get(f"/api/exercices/{ex['id']}/appels", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/budget/{line['id']}", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/appels/{appel['id']}", headers=auth(token_b)).status_code == 404

    # A : accès normal (liste budget + appel, modification exercice)
    assert client.get(f"/api/exercices/{ex['id']}/budget", headers=auth(token_a)).status_code == 200
    assert client.get(f"/api/exercices/{ex['id']}/appels", headers=auth(token_a)).status_code == 200
    r = client.put(f"/api/exercices/{ex['id']}", json={"annee": 2026, "cloture": True}, headers=auth(token_a))
    assert r.status_code == 200
    assert r.json()["cloture"] is True
