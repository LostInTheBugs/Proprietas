"""Flux complet de bout en bout (conversion de l'ancien test_e2e.py).

Le smoke test manuel contre une instance réelle vit désormais dans
`backend/scripts/smoke_e2e.py` (voir README). Ici, le même parcours tourne
en CI sur SQLite en mémoire : register → copro → personnes → lots → exercice
→ budget → appel → mouvements → récap → AG/votes → exports → documents →
contacts/contrats.
"""
from datetime import date, timedelta

from tests.conftest import auth

PASSWORD = "test1234"


def test_flux_complet(client):
    # 1. Register (premier compte)
    r = client.post("/api/auth/register", json={
        "email": "syndic@test.fr", "password": PASSWORD, "nom": "Syndic"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = auth(token)

    # 2. Copro (auto-création au premier appel) + mise à jour
    r = client.get("/api/copro", headers=h)
    assert r.status_code == 200
    copro = r.json()
    assert copro["id"] > 0
    r = client.put("/api/copro", json={"nom": "Résidence Les Lilas", "ville": "Paris"}, headers=h)
    assert r.status_code == 200
    assert r.json()["nom"] == "Résidence Les Lilas"

    # 3. Comptes copropriétaires (« zéro fiche » : le compte EST la personne)
    p1 = client.post("/api/auth/users", json={"email": "paul@test.fr", "password": "test1234",
                     "nom": "Durand", "prenom": "Paul", "role": "membre"}, headers=h).json()
    p2 = client.post("/api/auth/users", json={"email": "sophie@test.fr", "password": "test1234",
                     "nom": "Martin", "prenom": "Sophie", "role": "membre"}, headers=h).json()
    p3 = client.post("/api/auth/users", json={"email": "luc@test.fr", "password": "test1234",
                     "nom": "Bernard", "prenom": "Luc", "role": "membre"}, headers=h).json()
    assert all([p1, p2, p3])

    # 4. Lots (total 1000 millièmes)
    lots = []
    for i, (num, tant, prop) in enumerate([("1", 280, p1), ("2", 260, p2), ("3", 240, p2), ("4", 220, p3)], 1):
        lot = client.post("/api/lots", json={
            "numero": num, "designation": f"Appartement {num}", "type": "appartement",
            "tantiemes": tant, "proprietaire_id": prop["id"],
        }, headers=h).json()
        lots.append(lot)
    assert sum(l["tantiemes"] for l in lots) == 1000

    # 5. Exercice + budget
    ex = client.post("/api/exercices", json={"annee": 2026}, headers=h).json()
    b1 = client.post(f"/api/exercices/{ex['id']}/budget", json={"libelle": "Entretien courant", "montant": 2400}, headers=h)
    b2 = client.post(f"/api/exercices/{ex['id']}/budget", json={"libelle": "Assurance", "montant": 600}, headers=h)
    assert b1.status_code == 200 and b2.status_code == 200

    # 6. Appel de fonds (3000 €, fonds travaux 5 %)
    r = client.post(f"/api/exercices/{ex['id']}/appels", json={
        "libelle": "Appel 1er trimestre 2026", "date_emission": "2026-01-05",
        "date_echeance": "2026-01-31", "montant_total": 3000.0, "inclut_fonds_travaux": True,
    }, headers=h)
    assert r.status_code == 200, r.text
    appel = r.json()
    assert len(appel["parts"]) == 4
    somme = sum(p["montant_charges"] for p in appel["parts"])
    assert abs(somme - 3000.0) < 0.01, f"répartition inexacte : {somme}"
    ft = sum(p["montant_fonds_travaux"] for p in appel["parts"])
    assert abs(ft - 150.0) < 0.01
    lot1_part = [p for p in appel["parts"] if p["lot_id"] == lots[0]["id"]][0]
    assert abs(lot1_part["montant_charges"] - 840.0) < 0.01
    assert abs(lot1_part["montant_fonds_travaux"] - 42.0) < 0.01

    # 7. Mouvements (lot 1 paie tout, lot 2 paie partiellement)
    m1 = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-01-15", "libelle": "Virement lot 1", "type": "encaissement",
        "categorie": "charges", "montant": 882.0, "lot_id": lots[0]["id"],
    }, headers=h)
    m2 = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-01-20", "libelle": "Virement lot 2", "type": "encaissement",
        "categorie": "charges", "montant": 500.0, "lot_id": lots[1]["id"],
    }, headers=h)
    d1 = client.post(f"/api/exercices/{ex['id']}/mouvements", json={
        "date": "2026-02-01", "libelle": "Facture électricité", "type": "depense",
        "categorie": "energie", "montant": 350.0,
    }, headers=h)
    assert all(r.status_code == 200 for r in (m1, m2, d1))

    # 8. Récap / état daté
    recap = client.get("/api/recap", headers=h).json()
    assert recap["annee"] == 2026
    assert abs(recap["budget_previsionnel"] - 3000.0) < 0.01
    assert abs(recap["encaisse"] - 1382.0) < 0.01
    assert abs(recap["depense"] - 350.0) < 0.01
    solde_lot1 = [l for l in recap["lots"] if l["lot"]["id"] == lots[0]["id"]][0]
    assert abs(solde_lot1["solde"]) < 0.01
    solde_lot2 = [l for l in recap["lots"] if l["lot"]["id"] == lots[1]["id"]][0]
    assert abs(solde_lot2["solde"] - 319.0) < 0.1

    # 9. AG + résolutions + votes
    ag = client.post("/api/ag", json={"date": "2026-03-10", "type_ag": "annuelle", "statut": "convoquee"}, headers=h).json()
    r1 = client.post(f"/api/ag/{ag['id']}/resolutions", json={
        "numero": 1, "libelle": "Approbation des comptes 2025", "majorite": "art25"}, headers=h).json()
    r2 = client.post(f"/api/ag/{ag['id']}/resolutions", json={
        "numero": 2, "libelle": "Travaux de toiture", "majorite": "art26"}, headers=h).json()
    for lot in lots[:3]:
        client.post(f"/api/resolutions/{r1['id']}/votes", json={"lot_id": lot["id"], "voix": "pour"}, headers=h)
    client.post(f"/api/resolutions/{r1['id']}/votes", json={"lot_id": lots[3]["id"], "voix": "contre"}, headers=h)
    res1 = client.post(f"/api/resolutions/{r1['id']}/calculer", headers=h).json()
    assert res1["statut"] == "adoptee" and res1["resultat"]["pour"] == 780
    # art26 : lot 1 pour seulement → rejetée
    client.post(f"/api/resolutions/{r2['id']}/votes", json={"lot_id": lots[0]["id"], "voix": "pour"}, headers=h)
    client.post(f"/api/resolutions/{r2['id']}/votes", json={"lot_id": lots[1]["id"], "voix": "contre"}, headers=h)
    client.post(f"/api/resolutions/{r2['id']}/votes", json={"lot_id": lots[2]["id"], "voix": "abstention"}, headers=h)
    client.post(f"/api/resolutions/{r2['id']}/votes", json={"lot_id": lots[3]["id"], "voix": "contre"}, headers=h)
    res2 = client.post(f"/api/resolutions/{r2['id']}/calculer", headers=h).json()
    assert res2["statut"] == "rejetee"

    # 10. Export registre (CSV)
    r = client.get("/api/export/registre", headers=h)
    assert r.status_code == 200
    csv1 = r.text
    assert "Résidence Les Lilas" in csv1 and "Durand" in csv1

    # 11. Documents (upload multipart + download)
    files = {"fichier": ("contrat.pdf", b"%PDF-1.4 test", "application/pdf")}
    r = client.post("/api/documents", data={"categorie": "assurance", "libelle": "Contrat assurance 2026"},
                    files=files, headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["libelle"] == "Contrat assurance 2026"
    r = client.get(f"/api/documents/{doc['id']}/download", headers=h)
    assert r.status_code == 200 and r.content == b"%PDF-1.4 test"

    # 12. Contacts + contrats
    ct = client.post("/api/contacts", json={"nom": "EDF", "type": "fournisseur", "categorie": "energie", "telephone": "09 69 32 15 15"}, headers=h).json()
    ca = client.post("/api/contacts", json={"nom": "AXA Assurance", "type": "entreprise", "categorie": "assurance"}, headers=h).json()
    assert len(client.get("/api/contacts", headers=h).json()) == 2
    d10 = (date.today() + timedelta(days=10)).isoformat()
    d200 = (date.today() + timedelta(days=200)).isoformat()
    k1 = client.post("/api/contrats", json={"libelle": "Électricité PC", "type": "energie", "contact_id": ct["id"], "date_fin": d200, "montant": 1200, "periode": "annuel", "renouvellement_auto": True}, headers=h).json()
    k2 = client.post("/api/contrats", json={"libelle": "Assurance immeuble", "type": "assurance", "contact_id": ca["id"], "date_fin": d10, "montant": 850}, headers=h).json()
    assert k1["statut"] == "actif" and k1["contact_nom"] == "EDF"
    assert k2["statut"] == "expire_bientot" and k2["jours_restants"] == 10
    liste = client.get("/api/contrats", headers=h).json()
    assert liste[0]["libelle"] == "Assurance immeuble"  # tri par urgence
    client.delete(f"/api/contrats/{k2['id']}", headers=h)
    client.delete(f"/api/contrats/{k1['id']}", headers=h)
    client.delete(f"/api/contacts/{ca['id']}", headers=h)
    client.delete(f"/api/contacts/{ct['id']}", headers=h)
    assert len(client.get("/api/contacts", headers=h).json()) == 0
