"""Test API tresorerie : retourne des nombres, pas des chaînes."""


from tests.conftest import auth


def test_tresorerie_rend_float_exact(client):
    """GET /api/copro/tresorerie renvoie solde_compte et fonds_travaux_solde
    comme nombres JSON (int ou float), avec la valeur exacte."""
    # 1. Login
    r = client.post("/api/auth/register", json={
        "email": "syndic@test.fr", "password": "test1234", "nom": "Syndic"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = auth(token)

    # 2. Créer un mouvement encaissement
    r = client.post("/api/exercices", json={"annee": 2026}, headers=h)
    assert r.status_code == 200
    exercice = r.json()

    r = client.post(f"/api/exercices/{exercice['id']}/mouvements", json={
        "date": "2026-01-10", "libelle": "Cotisation", "type": "encaissement",
        "categorie": "charges", "montant": 1500.50,
    }, headers=h)
    assert r.status_code == 200

    r = client.post(f"/api/exercices/{exercice['id']}/mouvements", json={
        "date": "2026-01-15", "libelle": "Facture eau", "type": "depense",
        "categorie": "energie", "montant": 230.75,
    }, headers=h)
    assert r.status_code == 200

    # 3. Appel tresorerie
    r = client.get("/api/copro/tresorerie", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()

    # 4. Vérifier le type : float ou int, pas str
    solde = data["solde_compte"]
    assert isinstance(solde, (int, float)), f"solde_compte est {type(solde).__name__}, pas un nombre"

    # 5. Vérifier la valeur exacte : 1500.50 - 230.75 = 1269.75
    assert solde == 1269.75, f"solde inattendu : {solde}"

    # 6. Vérifier fonds_travaux_solde (aucun mouvement FT → 0)
    ft_solde = data["fonds_travaux_solde"]
    assert isinstance(ft_solde, (int, float)), f"fonds_travaux_solde est {type(ft_solde).__name__}"
    assert ft_solde == 0.0
