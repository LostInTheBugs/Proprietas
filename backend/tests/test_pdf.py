"""Génération PDF — chaque service produit un PDF non vide + régression 2338e58
(la liste `story` du compte de gestion était réinitialisée, la section entière
disparaissait du rapport annuel)."""
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from tests.conftest import auth
from app.services.compte_gestion import story_compte_gestion
from app.services.compte_gestion import generer_compte_gestion_pdf
from app.services.pv_pdf import generer_pv_pdf
from app.services.quittances import generer_quittances_pdf
from app.services.rapport_annuel import generer_rapport_annuel_pdf
from app.models.exercice import Exercice, BudgetLine
from app.models.ag import AG
from app.services.pdf_base import register_fonts


def _pdf_non_vide(buf: BytesIO) -> bytes:
    data = buf.getvalue()
    assert len(data) > 1000, "PDF trop petit (probablement vide)"
    assert data[:5] == b"%PDF-", "ce n'est pas un PDF"
    return data


def _texte_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _setup(client, token_a, db, copro_a):
    """Copro avec exercice, budget, lots, mouvements, AG + résolution."""
    h = auth(token_a)
    r = client.post("/api/auth/users", json={"email": "durand@test.fr", "password": "test1234",
                                             "nom": "Durand", "prenom": "Paul", "role": "membre"}, headers=h)
    p = r.json()
    r = client.post("/api/lots", json={"numero": "1", "designation": "Appartement 1",
                                       "tantiemes": 1000, "proprietaire_id": p["id"]},
                    headers=h)
    lot = r.json()
    r = client.post("/api/exercices", json={"annee": 2026}, headers=h)
    ex = r.json()
    r = client.post(f"/api/exercices/{ex['id']}/budget", json={
        "libelle": "Entretien courant", "montant": 2400.0}, headers=h)
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "Appel Q1", "date_emission": "2026-01-05", "montant_total": 3000.0},
        headers=h)
    appel = r.json()
    r = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-01-15", "libelle": "Virement lot 1", "type": "encaissement",
        "categorie": "charges", "montant": 882.0, "lot_id": lot["id"]}, headers=h)
    r = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-02-01", "libelle": "Facture électricité", "type": "depense",
        "categorie": "energie", "montant": 350.0}, headers=h)
    r = client.post("/api/ag", json={"date": "2026-03-10", "type_ag": "annuelle"}, headers=h)
    ag = r.json()
    r = client.post(f"/api/ag/{ag['id']}/resolutions", json={
        "numero": 1, "libelle": "Approbation des comptes", "majorite": "art25"}, headers=h)
    res = r.json()
    return p, lot, ex, appel, ag, res


def test_compte_gestion_story_non_reinitialise(db, copro_a):
    """Régression 2338e58 : story_compte_gestion doit AJOUTER au story existant."""
    ex = Exercice(copropriete_id=copro_a.id, annee=2026)
    db.add(ex)
    db.flush()  # ex.id nécessaire pour la ligne de budget
    db.add(BudgetLine(exercice_id=ex.id, libelle="Entretien courant", montant=2400.0))
    db.commit()
    db.refresh(ex)

    el = []  # story existant (dans le rapport annuel, il contient déjà des éléments)
    register_fonts()  # nécessaire hors des générateurs (ils l'appellent eux-mêmes)
    story_compte_gestion(copro_a, ex, db, el)
    assert len(el) > 0, "le story est vide : la section compte de gestion a été perdue"
    # La section (titre + synthèse avec le budget) doit apparaître
    texte = " ".join(str(x) for x in el)
    assert "COMPTE DE GESTION DE L'EXERCICE" in texte
    assert "2 400,00" in texte


def test_rapport_annuel_pdf(client, token_a, db, copro_a):
    _setup(client, token_a, db, copro_a)
    ex = db.query(Exercice).first()
    pdf = generer_rapport_annuel_pdf(copro_a, ex, db)
    data = _pdf_non_vide(pdf)
    texte = _texte_pdf(data)
    # La section compte de gestion (régression 2338e58 : story réinitialisé,
    # section entière perdue) est bien présente dans le rapport annuel
    assert "COMPTE DE GESTION DE L'EXERCICE" in texte
    assert "2 400,00" in texte  # budget prévisionnel visible


def test_compte_gestion_pdf(client, token_a, db, copro_a):
    _setup(client, token_a, db, copro_a)
    ex = db.query(Exercice).first()
    _pdf_non_vide(generer_compte_gestion_pdf(copro_a, ex, db))


def test_pv_pdf(client, token_a, db, copro_a):
    _setup(client, token_a, db, copro_a)
    ag = db.query(AG).first()
    data = _pdf_non_vide(generer_pv_pdf(copro_a, ag, db))
    assert "Résolution" in _texte_pdf(data) or "APPROBATION" in _texte_pdf(data).upper()


def test_quittances_pdf(client, token_a, db, copro_a):
    _setup(client, token_a, db, copro_a)
    ex = db.query(Exercice).first()
    _pdf_non_vide(generer_quittances_pdf(copro_a, ex, db))
