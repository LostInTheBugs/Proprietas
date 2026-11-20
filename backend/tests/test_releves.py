"""Relevés bancaires : import (CSV, OFX, QIF) et rapprochement proposé puis validé (demande de Fred, 20/11/2026).

- import « Vérifier » sans écriture, refus en bloc, opérations déjà importées non dupliquées ;
- propositions : même montant et même sens à 10 jours près, paiement d'un copropriétaire réparti entre
  ses lots (plusieurs encaissements, une ligne), facture à payer (payée à la date de la ligne) ;
- « sûre » : seule proposition de sa ligne et opérations proposées nulle part ailleurs ;
- opération créée depuis une ligne, ligne mise de côté, opérations absentes du relevé.
"""
from datetime import date

from decimal import Decimal as D

from app.models.lot import Lot
from app.models.mouvement import Mouvement
from tests.conftest import _make_membre, auth

Y = date.today().year

CSV = (f"Compte courant n° 12345;;;\n"
       f"Période du 01/03/{Y} au 31/03/{Y};;;\n"
       f";;;\n"
       f"Date opération;Date valeur;Libellé;Débit;Crédit\n"
       f"02/03/{Y};03/03/{Y};PRLV EDF;84,20;\n"
       f"05/03/{Y};05/03/{Y};VIR MME MARTIN;;450,00\n"
       f"10/03/{Y};10/03/{Y};FRAIS TENUE DE COMPTE;2,00;\n"
       f"10/03/{Y};10/03/{Y};FRAIS TENUE DE COMPTE;2,00;\n"
       f"20/03/{Y};20/03/{Y};CHQ 1234567 ASSURANCE;1 612,00;\n"
       f";;Solde au 31/03/{Y};;12 345,67\n")

OFX = f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
CHARSET:1252

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{Y}0302<TRNAMT>-84.20<FITID>A1<NAME>PRLV EDF</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>{Y}0305120000<TRNAMT>450,00<FITID>A2<NAME>VIR MME MARTIN<MEMO>CHARGES T1</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

QIF = f"!Type:Bank\nD02/03/{Y}\nT-84,20\nPPRLV EDF\n^\nD05/03/{Y}\nT450.00\nPVIR MARTIN\n^\n"
QIF_US = f"!Type:Bank\nD03/02/{Y}\nT-84.20\nPEDF\n^\nD03/25'{Y % 100}\nT450.00\nPVIR\n^\n"


def _envoyer(client, token, nom, contenu, simuler, compte="syndicat"):
    return client.post("/api/releves/import", files={"fichier": (nom, contenu, "application/octet-stream")},
                       data={"simuler": "true" if simuler else "false", "compte": compte}, headers=auth(token))


def _etat(client, token, compte="syndicat"):
    r = client.get(f"/api/releves?compte={compte}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _ex(client, token):
    return client.post("/api/exercices", json={"annee": Y}, headers=auth(token)).json()["id"]


def _mvt(client, token, ex_id, **champs):
    corps = {"date": f"{Y}-03-01", "libelle": "EDF", "type": "depense", "categorie": "energie", "montant": 84.2, **champs}
    r = client.post(f"/api/exercices/{ex_id}/mouvements", json=corps, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _releves():
    from app.services import releves          # importé ici : sans le code, les tests échouent un par un
    return releves


def _lignes(db):
    from app.models.releve import LigneReleve
    return db.query(LigneReleve)


def test_lecture_des_trois_formats():
    releves = _releves()
    ops, err = releves.lire("releve.csv", CSV.encode("cp1252"))
    assert err == []
    assert [(o["date"], o["libelle"], o["montant"]) for o in ops][:2] == [
        (date(Y, 3, 2), "PRLV EDF", D("-84.20")), (date(Y, 3, 5), "VIR MME MARTIN", D("450.00"))]
    assert ops[-1]["montant"] == D("-1612.00") and len(ops) == 5        # ligne de solde passée
    ops, err = releves.lire("releve.ofx", OFX.encode())
    assert err == [] and [(o["date"], o["montant"], o["fitid"], o["libelle"]) for o in ops] == [
        (date(Y, 3, 2), D("-84.20"), "A1", "PRLV EDF"),
        (date(Y, 3, 5), D("450.00"), "A2", "VIR MME MARTIN CHARGES T1")]
    ops, err = releves.lire("releve.qif", QIF.encode())
    assert err == [] and [(o["date"], o["montant"]) for o in ops] == [(date(Y, 3, 2), D("-84.20")),
                                                                      (date(Y, 3, 5), D("450.00"))]
    ops, err = releves.lire("releve.qif", QIF_US.encode())          # 25 n'est pas un mois : fichier en MM/JJ
    assert err == [] and [o["date"] for o in ops] == [date(Y, 3, 2), date(Y, 3, 25)]
    for texte, attendu in (("1 234,56", "1234.56"), ("-12,30", "-12.30"), ("1.234,56", "1234.56"),
                           ("1,234.56", "1234.56"), ("12,30 €", "12.30"), ("+5", "5"), ("12,30-", "-12.30")):
        assert releves.montant(texte) == D(attendu), texte


def test_importer_verifier_puis_reimporter(client, db, copro_a, syndic_a, token_a):
    r = _envoyer(client, token_a, "mars.csv", CSV.encode(), True)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("operations", "nouvelles", "deja_importees", "du", "au", "credits", "debits")} == {
        "operations": 5, "nouvelles": 5, "deja_importees": 0, "du": f"{Y}-03-02", "au": f"{Y}-03-20",
        "credits": 450.0, "debits": 1700.2}
    assert _lignes(db).count() == 0                                    # simulation : rien d'écrit
    assert _envoyer(client, token_a, "mars.csv", CSV.encode(), False).status_code == 200
    assert _lignes(db).count() == 5                                    # les deux frais de 2 € gardés
    r = _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    assert (r.json()["nouvelles"], r.json()["deja_importees"]) == (0, 5)
    assert _lignes(db).count() == 5
    # Autre compte : les mêmes opérations sont d'autres lignes.
    assert _envoyer(client, token_a, "mars.csv", CSV.encode(), True, compte="fonds_travaux").json()["nouvelles"] == 5


def test_erreurs_refus_en_bloc_et_droits(client, db, copro_a, syndic_a, token_a):
    mauvais = "Date;Libellé;Montant\n02/03/2026;EDF;-84,20\n31/02/2026;X;12\n05/03/2026;Y;douze\n"
    r = _envoyer(client, token_a, "x.csv", mauvais.encode(), True)
    assert r.json()["erreurs"] == ["Ligne 3 : date « 31/02/2026 » illisible (attendu : JJ/MM/AAAA).",
                                   "Ligne 4 : montant « douze » illisible."]
    r = _envoyer(client, token_a, "x.csv", mauvais.encode(), False)
    assert r.status_code == 422 and "rien n'a été importé" in r.json()["detail"]
    assert _lignes(db).count() == 0
    assert "En-tête introuvable" in _envoyer(client, token_a, "x.csv", b"a;b\n1;2\n", True).json()["erreurs"][0]
    assert _envoyer(client, token_a, "x.pdf", b"%PDF", True).status_code == 422
    assert _envoyer(client, token_a, "x.csv", CSV.encode(), True, compte="livret").status_code == 422
    membre = _make_membre(db, "m@exemple.fr", copro_a)
    from app.core.security import create_access_token
    t = create_access_token(membre.id, copro_a.id)
    assert _envoyer(client, t, "x.csv", CSV.encode(), True).status_code == 403
    assert client.get("/api/releves", headers=auth(t)).status_code == 403


def test_propositions_sures_validees(client, db, copro_a, syndic_a, token_a):
    ex = _ex(client, token_a)
    edf = _mvt(client, token_a, ex)                                              # 01/03 : prélevé le 02/03
    assur = _mvt(client, token_a, ex, libelle="Assurance", categorie="assurance", montant=1612, date=f"{Y}-03-15",
                 a_payer=True)
    loin = _mvt(client, token_a, ex, libelle="Frais", categorie="autre", montant=2, date=f"{Y}-01-10")  # trop tôt
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    e = _etat(client, token_a)
    par_lib = {l["libelle"]: l for l in e["lignes"]}
    assert par_lib["PRLV EDF"]["statut"] == "proposee"
    assert [c["mouvements"][0]["id"] for c in par_lib["PRLV EDF"]["candidats"]] == [edf["id"]]
    assert par_lib["PRLV EDF"]["candidats"][0]["sure"] is True
    assert par_lib["CHQ 1234567 ASSURANCE"]["candidats"][0]["mouvements"][0]["id"] == assur["id"]
    assert all(l["statut"] == "a_traiter" for l in e["lignes"] if l["libelle"].startswith("FRAIS"))
    assert e["resume"]["surs"] == 2
    r = client.post("/api/releves/pointer-surs?compte=syndicat", headers=auth(token_a))
    assert r.json() == {"pointees": 2}
    e = _etat(client, token_a)
    assert e["resume"]["pointees"] == 2
    db.expire_all()
    a = db.get(Mouvement, assur["id"])
    assert (a.a_payer, a.paye_le) == (False, date(Y, 3, 20))                    # payée à la date de la ligne
    assert db.get(Mouvement, loin["id"]).releve_ligne_id is None


def test_deux_propositions_ne_sont_pas_sures(client, db, copro_a, syndic_a, token_a):
    ex = _ex(client, token_a)
    _mvt(client, token_a, ex, libelle="Frais A", categorie="autre", montant=2, date=f"{Y}-03-10")
    _mvt(client, token_a, ex, libelle="Frais B", categorie="autre", montant=2, date=f"{Y}-03-10")
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    frais = [l for l in _etat(client, token_a)["lignes"] if l["libelle"].startswith("FRAIS")]
    assert all(l["statut"] == "proposee" and len(l["candidats"]) == 2 for l in frais)
    assert not any(c["sure"] for l in frais for c in l["candidats"])
    # Le syndic choisit : une opération par ligne ; la même opération sur deux lignes est refusée.
    a, b = frais[0]["candidats"][0]["mouvements"][0]["id"], frais[0]["candidats"][1]["mouvements"][0]["id"]
    assert client.post(f"/api/releves/{frais[0]['id']}/pointer", json={"mouvement_ids": [a]},
                       headers=auth(token_a)).status_code == 200
    r = client.post(f"/api/releves/{frais[1]['id']}/pointer", json={"mouvement_ids": [a]}, headers=auth(token_a))
    assert r.status_code == 409
    r = client.post(f"/api/releves/{frais[1]['id']}/pointer", json={"mouvement_ids": [a, b]}, headers=auth(token_a))
    assert r.status_code == 409
    e = _etat(client, token_a)
    restant = next(l for l in e["lignes"] if l["id"] == frais[1]["id"])
    assert [c["mouvements"][0]["id"] for c in restant["candidats"]] == [b] and restant["candidats"][0]["sure"]


def test_paiement_reparti_entre_lots_et_montant_different(client, db, copro_a, syndic_a, token_a):
    marie = _make_membre(db, "marie@exemple.fr", copro_a)
    for n in ("1", "2"):
        db.add(Lot(copropriete_id=copro_a.id, numero=n, tantiemes=500, proprietaire_id=marie.id))
    db.commit()
    lots = sorted(l.id for l in db.query(Lot))
    r = client.post("/api/paiements", json={
        "proprietaire_id": marie.id, "date": f"{Y}-03-04", "montant": 450, "libelle": "Virement Martin",
        "repartition": [{"lot_id": lots[0], "montant": 300}, {"lot_id": lots[1], "montant": 150}]}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    ids = sorted(m["id"] for m in r.json())
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    vir = next(l for l in _etat(client, token_a)["lignes"] if l["libelle"] == "VIR MME MARTIN")
    assert [sorted(m["id"] for m in c["mouvements"]) for c in vir["candidats"]] == [ids]
    r = client.post(f"/api/releves/{vir['id']}/pointer", json={"mouvement_ids": ids[:1]}, headers=auth(token_a))
    assert r.status_code == 422 and "300,00 €" in r.json()["detail"] and "450,00 €" in r.json()["detail"]
    assert client.post(f"/api/releves/{vir['id']}/pointer", json={"mouvement_ids": ids},
                       headers=auth(token_a)).status_code == 200
    vir = next(l for l in _etat(client, token_a)["lignes"] if l["id"] == vir["id"])
    assert vir["statut"] == "pointee" and len(vir["mouvements"]) == 2
    # Une opération pointée qu'on modifie : la ligne passe en écart.
    m = db.get(Mouvement, ids[0])
    m.montant = 299
    db.commit()
    vir = next(l for l in _etat(client, token_a)["lignes"] if l["id"] == vir["id"])
    assert (vir["statut"], vir["ecart"]) == ("ecart", 1.0)
    assert client.post(f"/api/releves/{vir['id']}/depointer", headers=auth(token_a)).status_code == 200
    db.expire_all()
    assert db.get(Mouvement, ids[0]).releve_ligne_id is None


def test_creer_ignorer_supprimer_et_absentes(client, db, copro_a, syndic_a, token_a):
    ex = _ex(client, token_a)
    absente = _mvt(client, token_a, ex, libelle="Ménage", categorie="entretien", montant=60, date=f"{Y}-03-12")
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    e = _etat(client, token_a)
    assert [m["id"] for m in e["absentes"]] == [absente["id"]]
    frais = [l for l in e["lignes"] if l["libelle"].startswith("FRAIS")]
    r = client.post(f"/api/releves/{frais[0]['id']}/creer", json={"categorie": "autre", "libelle": "Frais bancaires"},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    m = db.get(Mouvement, r.json()["mouvement_id"])
    assert (m.type, m.montant, m.date, m.categorie, m.releve_ligne_id) == (
        "depense", D("2.00"), date(Y, 3, 10), "autre", frais[0]["id"])
    # La catégorie doit suivre le compte.
    r = client.post(f"/api/releves/{frais[1]['id']}/creer", json={"categorie": "fonds_travaux"}, headers=auth(token_a))
    assert r.status_code == 422
    assert client.post(f"/api/releves/{frais[1]['id']}/ignorer", json={"ignoree": True},
                       headers=auth(token_a)).status_code == 200
    e = _etat(client, token_a)
    assert next(l for l in e["lignes"] if l["id"] == frais[1]["id"])["statut"] == "ignoree"
    assert client.post(f"/api/releves/{frais[1]['id']}/creer", json={"categorie": "autre"},
                       headers=auth(token_a)).status_code == 409
    # Supprimer : refusé pour une ligne pointée, accepté sinon.
    assert client.delete(f"/api/releves/{frais[0]['id']}", headers=auth(token_a)).status_code == 409
    assert client.delete(f"/api/releves/{frais[1]['id']}", headers=auth(token_a)).status_code == 200
    # Une autre copropriété ne voit pas ces lignes.
    assert client.post(f"/api/releves/{frais[0]['id']}/depointer", headers=auth(token_a)).status_code == 200


def test_isolation_entre_coproprietes(client, db, copro_a, syndic_a, token_a, copro_b, syndic_b, token_b):
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    lid = _lignes(db).first().id
    assert _etat(client, token_b)["lignes"] == []
    assert client.post(f"/api/releves/{lid}/ignorer", json={"ignoree": True}, headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/releves/{lid}", headers=auth(token_b)).status_code == 404


def test_sauvegarde_garde_les_lignes_et_le_pointage(client, db, copro_a, syndic_a, token_a, copro_b, syndic_b, token_b):
    from app.models.releve import LigneReleve
    ex = _ex(client, token_a)
    edf = _mvt(client, token_a, ex)
    _envoyer(client, token_a, "mars.csv", CSV.encode(), False)
    assert client.post("/api/releves/pointer-surs?compte=syndicat", headers=auth(token_a)).json() == {"pointees": 1}
    mdp = "sauvegarde-releves-88"
    r = client.post("/api/sauvegarde/export", json={"mot_de_passe": mdp, "donnees_personnelles": True},
                    headers=auth(token_a))
    assert r.status_code == 200, r.text
    r = client.post("/api/sauvegarde/import", files={"fichier": ("s.zip", r.content, "application/zip")},
                    data={"mot_de_passe": mdp}, headers=auth(token_b))
    assert r.status_code == 200, r.text
    nid = r.json()["copropriete_id"]
    lignes = db.query(LigneReleve).filter(LigneReleve.copropriete_id == nid).all()
    assert len(lignes) == 5
    m = db.query(Mouvement).filter(Mouvement.copropriete_id == nid, Mouvement.libelle == edf["libelle"]).one()
    assert db.get(LigneReleve, m.releve_ligne_id).copropriete_id == nid and m.releve_ligne_id != edf["id"]
