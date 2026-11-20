"""Corrections après l'audit du code (revue ChatGPT relayée par Fred, 20/11/2026).

- montants : une opération, un appel de fonds ont un montant positif ; une ligne de budget n'est pas négative ;
- compte de gestion : l'annexe par lot ne porte que sur l'exercice ; les impayés comptent les vendeurs ;
- adresse IP du client : CF-Connecting-IP n'est cru que si la requête vient de Cloudflare, X-Forwarded-For que
  s'il est posé par un proxy local ;
- approbation des comptes saisie à la main : tracée et distinguée d'un vote en AG.
"""
import io
from datetime import date
from types import SimpleNamespace

from pypdf import PdfReader

from app.core.audit import client_ip
from app.models.appel import AppelFonds, AppelLot
from app.models.audit import AuditLog
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from tests.conftest import _make_membre, auth

Y = date.today().year


def _ex(client, token, annee=Y):
    return client.post("/api/exercices", json={"annee": annee}, headers=auth(token)).json()["id"]


def test_montants_positifs(client, db, copro_a, syndic_a, token_a):
    ex = _ex(client, token_a)
    db.add(Lot(copropriete_id=copro_a.id, numero="1", tantiemes=1000))
    db.commit()
    for montant in (-50, 0):
        r = client.post(f"/api/exercices/{ex}/mouvements", json={"date": f"{Y}-01-10", "libelle": "X", "type": "depense",
                                                                  "categorie": "autre", "montant": montant}, headers=auth(token_a))
        assert r.status_code == 422 and "positif" in r.json()["detail"], montant
        r = client.post(f"/api/exercices/{ex}/appels", json={"libelle": "A", "date_emission": f"{Y}-01-01",
                                                             "montant_total": montant}, headers=auth(token_a))
        assert r.status_code == 422, montant
    r = client.post(f"/api/exercices/{ex}/budget", json={"libelle": "B", "montant": -10}, headers=auth(token_a))
    assert r.status_code == 422
    assert client.post(f"/api/exercices/{ex}/budget", json={"libelle": "B", "montant": 0},
                       headers=auth(token_a)).status_code == 200
    m = client.post(f"/api/exercices/{ex}/mouvements", json={"date": f"{Y}-01-10", "libelle": "X", "type": "depense",
                                                             "categorie": "autre", "montant": 12}, headers=auth(token_a))
    assert m.status_code == 200
    r = client.put(f"/api/mouvements/{m.json()['id']}", json={"date": f"{Y}-01-10", "libelle": "X", "type": "depense",
                                                               "categorie": "autre", "montant": -12}, headers=auth(token_a))
    assert r.status_code == 422
    assert db.query(Mouvement).count() == 1


def _requete(voisin, **entetes):
    return SimpleNamespace(client=SimpleNamespace(host=voisin) if voisin else None,
                           headers={k.replace("_", "-"): v for k, v in entetes.items()})


def test_adresse_ip_du_client():
    # Application exposée directement : seul le voisin compte, les en-têtes sont écrits par le client.
    assert client_ip(_requete("93.184.216.34", cf_connecting_ip="1.1.1.1", x_forwarded_for="1.2.3.4")) == "93.184.216.34"
    # Derrière le proxy local : la dernière adresse de X-Forwarded-For (celle qui s'est connectée au proxy).
    assert client_ip(_requete("172.18.0.5", x_forwarded_for="1.2.3.4, 93.184.216.34")) == "93.184.216.34"
    # Arrivée par Cloudflare : CF-Connecting-IP donne le client.
    assert client_ip(_requete("172.18.0.5", x_forwarded_for="162.158.1.1", cf_connecting_ip="203.0.113.9")) == "203.0.113.9"
    assert client_ip(_requete("172.18.0.5", x_forwarded_for="2606:4700::1", cf_connecting_ip="203.0.113.9")) == "203.0.113.9"
    # Contournement de Cloudflare : l'en-tête est ignoré.
    assert client_ip(_requete("172.18.0.5", x_forwarded_for="93.184.216.34", cf_connecting_ip="203.0.113.9")) == "93.184.216.34"
    # En-têtes illisibles : ignorés.
    assert client_ip(_requete("172.18.0.5", x_forwarded_for="162.158.1.1", cf_connecting_ip="pas-une-ip")) == "162.158.1.1"
    assert client_ip(_requete("127.0.0.1", x_forwarded_for="n'importe quoi")) == "127.0.0.1"
    assert client_ip(_requete("127.0.0.1")) == "127.0.0.1"
    assert client_ip(None) == ""


def test_compte_de_gestion_par_exercice_et_vendeurs(client, db, copro_a, syndic_a, token_a):
    paul, anne = _make_membre(db, "paul@exemple.fr", copro_a), _make_membre(db, "anne@exemple.fr", copro_a)
    lot = Lot(copropriete_id=copro_a.id, numero="7", tantiemes=1000, proprietaire_id=paul.id)
    db.add(lot)
    exs = {}
    for annee, montant in ((Y - 2, 111), (Y - 1, 222)):
        ex = Exercice(copropriete_id=copro_a.id, annee=annee)
        db.add(ex)
        db.flush()
        exs[annee] = ex.id
        a = AppelFonds(exercice_id=ex.id, libelle=f"Provision {annee}", date_emission=date(annee, 1, 1),
                       date_echeance=date(annee, 1, 1), montant_total=montant)
        db.add(a)
        db.flush()
        db.add(AppelLot(appel_id=a.id, lot_id=lot.id, montant_charges=montant))
    db.commit()
    pdf = client.get(f"/api/export/compte-gestion/{exs[Y - 1]}", headers=auth(token_a))
    assert pdf.status_code == 200, pdf.text
    texte = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    annexe = texte.split("ANNEXE")[1].split("IMPAYÉS")[0]
    assert "222" in annexe and "111" not in annexe and "333" not in annexe          # cet exercice seulement
    assert "333" in texte.split("IMPAYÉS")[1]                                       # impayés : tout le solde
    assert "ne remplace pas les documents comptables" in texte.replace("\n", " ")
    # Après la vente, le solde du vendeur reste dans les impayés.
    r = client.post("/api/mutations", json={"lot_id": lot.id, "date_acte": f"{Y - 1}-06-30", "acquereur_id": anne.id},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    texte = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(client.get(
        f"/api/export/compte-gestion/{exs[Y - 1]}", headers=auth(token_a)).content)).pages)
    impayes = texte.split("IMPAYÉS")[1].replace("\n", " ")
    assert "vendeur, vente du 30/06/" in impayes and "333" in impayes


def test_approbation_saisie_a_la_main(client, db, copro_a, syndic_a, token_a):
    ex = _ex(client, token_a, Y - 1)
    r = client.put(f"/api/exercices/{ex}", json={"annee": Y - 1, "cloture": True, "comptes_approuves_le": f"{Y}-01-15"},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert (r.json()["comptes_approuves_le"], r.json()["approbation_ag"]) == (f"{Y}-01-15", False)
    db.expire_all()
    a = db.query(AuditLog).filter(AuditLog.action == "approbation_comptes_saisie").one()
    assert f"exercice {Y - 1} : approuvé le 15/01/{Y}" in a.detail
