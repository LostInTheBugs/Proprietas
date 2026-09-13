#!/usr/bin/env python3
"""Smoke test E2E manuel contre une instance RÉELLE (dev lab ou production).

Le parcours fonctionnel équivalent tourne en CI dans `backend/tests/`
(pytest, SQLite en mémoire) — voir `test_flux_complet.py`. Ce script garde son
utilité pour vérifier un déploiement réel de bout en bout (uvicorn, base de
données réelle, config SMTP…) :

    # instance de dev locale (après seed_demo.py) :
    uvicorn app.main:app --port 8000 &
    python scripts/smoke_e2e.py

Exige un compte `syndic@test.fr` / `test1234` (créé par seed_demo.py — compte de
démonstration, exempté de double authentification). Si le compte utilisé exige la
2FA (politique de sa copropriété), le script s'arrête proprement au login :
complétez l'enrôlement à la main ou utilisez un compte exempté.
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
TOKEN = None
FAIL = []


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        FAIL.append(f"{method} {path} -> {e.code} {e.read().decode()[:200]}")
        return None


def check(name, cond):
    print(("OK  " if cond else "FAIL") + f"  {name}")
    if not cond:
        FAIL.append(name)


# 1. Login
r = call("POST", "/api/auth/login", {"email": "syndic@test.fr", "password": "test1234"})
if r and not r.get("access_token"):
    print("  ⚠️ ce compte exige la double authentification — utilisez un compte exempté (démo) "
          "ou complétez l'enrôlement manuellement.")
TOKEN = r.get("access_token") if r else None
check("login", bool(TOKEN))

# 2. Copro (auto-création)
copro = call("GET", "/api/copro", token=TOKEN)
check("copro auto-créée", copro and copro["id"] > 0)
copro = call("PUT", "/api/copro", {"nom": "Résidence Les Lilas", "ville": "Paris"}, token=TOKEN)
check("copro mise à jour", copro and copro["nom"] == "Résidence Les Lilas")

# 3. Personnes
p1 = call("POST", "/api/personnes", {"nom": "Durand", "prenom": "Paul", "email": "paul@test.fr"}, token=TOKEN)
p2 = call("POST", "/api/personnes", {"nom": "Martin", "prenom": "Sophie"}, token=TOKEN)
p3 = call("POST", "/api/personnes", {"nom": "Bernard", "prenom": "Luc"}, token=TOKEN)
check("3 personnes créées", all([p1, p2, p3]))

# 4. Lots (4 appartements, total 1000 millièmes)
lots = []
for i, (num, tant, prop) in enumerate([("1", 280, p1), ("2", 260, p2), ("3", 240, p2), ("4", 220, p3)], 1):
    lot = call("POST", "/api/lots", {
        "numero": num, "designation": f"Appartement {num}", "type": "appartement",
        "tantiemes": tant, "proprietaire_id": prop["id"],
    }, token=TOKEN)
    lots.append(lot)
check("4 lots créés", all(lots))
check("total millièmes = 1000", sum(l["tantiemes"] for l in lots) == 1000)

# 5. Exercice + budget
ex = call("POST", "/api/exercices", {"annee": 2026}, token=TOKEN)
check("exercice 2026", ex and ex["annee"] == 2026)
b1 = call("POST", f"/api/exercices/{ex['id']}/budget", {"libelle": "Entretien courant", "montant": 2400}, token=TOKEN)
b2 = call("POST", f"/api/exercices/{ex['id']}/budget", {"libelle": "Assurance", "montant": 600}, token=TOKEN)
check("budget ajouté", b1 and b2)

# 6. Appel de fonds (total 3000, fonds travaux 5% inclus)
appel = call("POST", f"/api/exercices/{ex['id']}/appels", {
    "libelle": "Appel 1er trimestre 2026", "date_emission": "2026-01-05",
    "date_echeance": "2026-01-31", "montant_total": 3000.0, "inclut_fonds_travaux": True,
}, token=TOKEN)
check("appel créé", appel and len(appel["parts"]) == 4)
somme = sum(p["montant_charges"] for p in appel["parts"])
check(f"répartition exacte (somme={somme})", abs(somme - 3000.0) < 0.01)
ft = sum(p["montant_fonds_travaux"] for p in appel["parts"])
check(f"fonds travaux 5% (={ft})", abs(ft - 150.0) < 0.01)
# lot 1 : 280/1000 * 3000 = 840, +5% = 42
lot1_part = [p for p in appel["parts"] if p["lot_id"] == lots[0]["id"]][0]
check("part lot 1 = 840 + 42", abs(lot1_part["montant_charges"] - 840.0) < 0.01 and abs(lot1_part["montant_fonds_travaux"] - 42.0) < 0.01)

# 7. Mouvements (lot 1 paie tout, lot 2 paie partiellement)
m1 = call("POST", f"/api/exercices/{ex['id']}/mouvements", {
    "date": "2026-01-15", "libelle": "Virement lot 1", "type": "encaissement",
    "categorie": "charges", "montant": 882.0, "lot_id": lots[0]["id"],
}, token=TOKEN)
m2 = call("POST", f"/api/exercices/{ex['id']}/mouvements", {
    "date": "2026-01-20", "libelle": "Virement lot 2", "type": "encaissement",
    "categorie": "charges", "montant": 500.0, "lot_id": lots[1]["id"],
}, token=TOKEN)
d1 = call("POST", f"/api/exercices/{ex['id']}/mouvements", {
    "date": "2026-02-01", "libelle": "Facture électricité", "type": "depense",
    "categorie": "energie", "montant": 350.0,
}, token=TOKEN)
check("mouvements créés", all([m1, m2, d1]))

# 8. Récap / état daté
recap = call("GET", "/api/recap", token=TOKEN)
check("recap exercice 2026", recap and recap["annee"] == 2026)
check("recap budget 3000", abs(recap["budget_previsionnel"] - 3000.0) < 0.01)
check("recap encaissé 1382", abs(recap["encaisse"] - 1382.0) < 0.01)
check("recap dépenses 350", abs(recap["depense"] - 350.0) < 0.01)
check("fonds travaux encaissé 0 (catégorie)", recap["fonds_travaux_encaisse"] == 0.0)
solde_lot1 = [l for l in recap["lots"] if l["lot"]["id"] == lots[0]["id"]][0]
check("solde lot 1 = 0 (tout payé)", abs(solde_lot1["solde"]) < 0.01)
solde_lot2 = [l for l in recap["lots"] if l["lot"]["id"] == lots[1]["id"]][0]
check("solde lot 2 = 319 (780+39-500)", abs(solde_lot2["solde"] - 319.0) < 0.1)

# 9. AG + résolutions + votes
ag = call("POST", "/api/ag", {"date": "2026-03-10", "type_ag": "annuelle", "statut": "convoquee"}, token=TOKEN)
r1 = call("POST", f"/api/ag/{ag['id']}/resolutions", {
    "numero": 1, "libelle": "Approbation des comptes 2025", "majorite": "art25",
}, token=TOKEN)
r2 = call("POST", f"/api/ag/{ag['id']}/resolutions", {
    "numero": 2, "libelle": "Travaux de toiture", "majorite": "art26",
}, token=TOKEN)
check("résolutions créées", r1 and r2)

# votes : lot1+lot2+lot3 pour (780/1000), lot4 contre (220/1000) -> art25 adoptée
for lot in lots[:3]:
    call("POST", f"/api/resolutions/{r1['id']}/votes", {"lot_id": lot["id"], "voix": "pour"}, token=TOKEN)
call("POST", f"/api/resolutions/{r1['id']}/votes", {"lot_id": lots[3]["id"], "voix": "contre"}, token=TOKEN)
res1 = call("POST", f"/api/resolutions/{r1['id']}/calculer", token=TOKEN)
check("art25 adoptée (780 > 500)", res1 and res1["statut"] == "adoptee" and res1["resultat"]["pour"] == 780)

# art26 : lot1 pour (280) seulement -> rejetée
call("POST", f"/api/resolutions/{r2['id']}/votes", {"lot_id": lots[0]["id"], "voix": "pour"}, token=TOKEN)
call("POST", f"/api/resolutions/{r2['id']}/votes", {"lot_id": lots[1]["id"], "voix": "contre"}, token=TOKEN)
call("POST", f"/api/resolutions/{r2['id']}/votes", {"lot_id": lots[2]["id"], "voix": "abstention"}, token=TOKEN)
call("POST", f"/api/resolutions/{r2['id']}/votes", {"lot_id": lots[3]["id"], "voix": "contre"}, token=TOKEN)
res2 = call("POST", f"/api/resolutions/{r2['id']}/calculer", token=TOKEN)
check("art26 rejetée (280 < 667)", res2 and res2["statut"] == "rejetee")

# 10. Exports
req = urllib.request.Request(BASE + "/api/export/registre", headers={"Authorization": f"Bearer {TOKEN}"})
with urllib.request.urlopen(req) as r:
    csv1 = r.read().decode()
check("export registre", "Résidence Les Lilas" in csv1 and "Durand" in csv1)

# 11. Documents (upload multipart)
import uuid
boundary = uuid.uuid4().hex
body = (
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"categorie\"\r\n\r\nassurance\r\n"
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"libelle\"\r\n\r\nContrat assurance 2026\r\n"
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"fichier\"; filename=\"contrat.pdf\"\r\n"
    f"Content-Type: application/pdf\r\n\r\n%PDF-1.4 test\r\n"
    f"--{boundary}--\r\n"
).encode()
req = urllib.request.Request(BASE + "/api/documents", data=body, method="POST")
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
req.add_header("Authorization", f"Bearer {TOKEN}")
with urllib.request.urlopen(req) as r:
    doc = json.loads(r.read())
check("document uploadé", doc and doc["libelle"] == "Contrat assurance 2026")

# 12. Contacts + Contrats
ct = call("POST", "/api/contacts", {"nom": "EDF", "type": "fournisseur", "categorie": "energie", "telephone": "09 69 32 15 15"}, token=TOKEN)
ca = call("POST", "/api/contacts", {"nom": "AXA Assurance", "type": "entreprise", "categorie": "assurance"}, token=TOKEN)
check("contacts créés", ct and ca)
check("contacts listés", len(call("GET", "/api/contacts", token=TOKEN)) == 2)
from datetime import date, timedelta
d10 = (date.today() + timedelta(days=10)).isoformat()
d200 = (date.today() + timedelta(days=200)).isoformat()
k1 = call("POST", "/api/contrats", {"libelle": "Électricité PC", "type": "energie", "contact_id": ct["id"], "date_fin": d200, "montant": 1200, "periode": "annuel", "renouvellement_auto": True}, token=TOKEN)
k2 = call("POST", "/api/contrats", {"libelle": "Assurance immeuble", "type": "assurance", "contact_id": ca["id"], "date_fin": d10, "montant": 850}, token=TOKEN)
check("contrats créés", k1 and k2)
check("contrat actif (J+200)", k1["statut"] == "actif" and k1["contact_nom"] == "EDF")
check("contrat expire bientôt (J+10)", k2["statut"] == "expire_bientot" and k2["jours_restants"] == 10)
liste_contrats = call("GET", "/api/contrats", token=TOKEN)
check("tri par urgence", liste_contrats[0]["libelle"] == "Assurance immeuble")
call("DELETE", f"/api/contrats/{k2['id']}", token=TOKEN)
call("DELETE", f"/api/contrats/{k1['id']}", token=TOKEN)
call("DELETE", f"/api/contacts/{ca['id']}", token=TOKEN)
call("DELETE", f"/api/contacts/{ct['id']}", token=TOKEN)
check("nettoyage contacts/contrats", len(call("GET", "/api/contacts", token=TOKEN)) == 0 and len(call("GET", "/api/contrats", token=TOKEN)) == 0)

# 13. Sécurité : statut 2FA + journal d'audit
st = call("GET", "/api/auth/2fa/status", token=TOKEN)
check("statut 2fa", bool(st) and "enabled" in st and "policy" in st)
journal = call("GET", "/api/audit?limit=5", token=TOKEN)
check("journal d'audit accessible", isinstance(journal, list) and len(journal) >= 1)

print()
if FAIL:
    print(f"{len(FAIL)} ÉCHECS:")
    for f in FAIL:
        print(" -", f)
    raise SystemExit(1)
print("TOUS LES TESTS PASSENT ✅")
