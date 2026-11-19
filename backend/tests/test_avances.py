"""Avances : une personne paie une dépense de la copropriété (demande de Fred, 19/11/2026).

Cas d'origine : assurance et EDF impayées, réglées personnellement par le syndic bénévole. Choix de Fred :
la copropriété règle sa dette par remboursement (virement) ou en déduisant l'avance des charges de la
personne, au choix ; seuls les comptes de la copropriété peuvent faire une avance ; une avance a toujours
son justificatif (la facture).

- avance : dépense « payée par » → comptée dans les charges, pas dans la banque ;
- remboursement : dépense de catégorie « avance » → passe par la banque, n'est pas une charge ;
- déduction : encaissement sur un lot de la personne → paie ses appels, pas dans la banque ;
- jamais plus que le reste dû ; justificatif obligatoire et indélébile ; compte non supprimable tant que
  la copropriété lui doit de l'argent.
"""
from datetime import date

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app import demarrage
from app.core.security import create_access_token
from app.models.document import Document
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services.soldes import totaux_lot
from tests.conftest import _make_membre, auth

Y = date.today().year


def _base(client, db, copro, syndic, token):
    ex_id = client.post("/api/exercices", json={"annee": Y}, headers=auth(token)).json()["id"]
    membre = _make_membre(db, "voisin@test.fr", copro)
    lot_syndic = Lot(copropriete_id=copro.id, numero="1", tantiemes=600, proprietaire_id=syndic.id)
    lot_voisin = Lot(copropriete_id=copro.id, numero="2", tantiemes=400, proprietaire_id=membre.id)
    facture = Document(copropriete_id=copro.id, categorie="facture", libelle="Facture EDF", fichier="edf.pdf",
                       date_ajout=date.today())
    db.add_all([lot_syndic, lot_voisin, facture])
    db.commit()
    return ex_id, membre, lot_syndic, lot_voisin, facture


def _mouvement(client, token, ex_id, **champs):
    corps = {"date": f"{Y}-03-01", "libelle": "Facture EDF", "type": "depense", "categorie": "energie",
             "montant": 300, **champs}
    return client.post(f"/api/exercices/{ex_id}/mouvements", json=corps, headers=auth(token))


def _recap(client, token):
    r = client.get("/api/recap", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _reste(client, token, personne_id):
    etat = client.get("/api/avances", headers=auth(token)).json()
    return next((p["reste"] for p in etat if p["personne_id"] == personne_id), 0.0)


def test_avance_remboursement_deduction(client, db, copro_a, syndic_a, token_a):
    ex_id, _, lot_syndic, _, facture = _base(client, db, copro_a, syndic_a, token_a)
    r = _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id, document_id=facture.id)
    assert r.status_code == 200, r.text
    assert r.json()["hors_banque"] is True and r.json()["avance_par_nom"]
    recap = _recap(client, token_a)
    assert (recap["depense"], recap["tresorerie_syndicat"], recap["solde_caisse"]) == (300, 0, 0)  # une charge, pas en banque
    assert _reste(client, token_a, syndic_a.id) == 300

    rembourse = _mouvement(client, token_a, ex_id, libelle="Remboursement avance EDF", categorie="avance",
                           montant=100, avance_par_id=syndic_a.id)
    assert rembourse.status_code == 200, rembourse.text
    assert rembourse.json()["hors_banque"] is False
    recap = _recap(client, token_a)
    assert (recap["depense"], recap["tresorerie_syndicat"], recap["solde_caisse"]) == (300, -100, -100)  # banque, pas une charge
    assert _reste(client, token_a, syndic_a.id) == 200

    deduit = _mouvement(client, token_a, ex_id, libelle="Avance EDF déduite", type="encaissement",
                        categorie="charges", montant=150, lot_id=lot_syndic.id, avance_par_id=syndic_a.id)
    assert deduit.status_code == 200, deduit.text
    assert deduit.json()["hors_banque"] is True
    recap = _recap(client, token_a)
    assert (recap["encaisse"], recap["tresorerie_syndicat"]) == (150, -100)  # paie ses appels, rien en banque
    db.expire_all()
    assert totaux_lot(db, db.get(Lot, lot_syndic.id))["encaisse"] == 150
    [p] = client.get("/api/avances", headers=auth(token_a)).json()
    assert (p["avance"], p["rembourse"], p["deduit"], p["reste"]) == (300, 100, 150, 50)
    assert p["lots"] == [{"id": lot_syndic.id, "numero": "1"}]
    assert [m["nature"] for m in p["mouvements"]] == ["avance", "remboursement", "deduction"]

    # Jamais plus que le reste dû.
    r = _mouvement(client, token_a, ex_id, categorie="avance", montant=60, avance_par_id=syndic_a.id)
    assert r.status_code == 422 and "50" in r.json()["detail"]
    # Une avance déjà remboursée ou déduite ne se supprime pas d'abord.
    m_avance = db.query(Mouvement).filter(Mouvement.categorie == "energie").one()
    r = client.delete(f"/api/mouvements/{m_avance.id}", headers=auth(token_a))
    assert r.status_code == 409 and "remboursée ou déduite" in r.json()["detail"]
    # Réduire l'avance sous ce qui est déjà réglé : refusé aussi.
    corps = {"date": f"{Y}-03-01", "libelle": "Facture EDF", "type": "depense", "categorie": "energie",
             "montant": 200, "avance_par_id": syndic_a.id, "document_id": facture.id}
    assert client.put(f"/api/mouvements/{m_avance.id}", json=corps, headers=auth(token_a)).status_code == 422
    # Le remboursement supprimé : la dette remonte.
    assert client.delete(f"/api/mouvements/{rembourse.json()['id']}", headers=auth(token_a)).status_code == 200
    assert _reste(client, token_a, syndic_a.id) == 150


def test_justificatif_obligatoire_et_conserve(client, db, copro_a, syndic_a, token_a):
    ex_id, _, _, _, facture = _base(client, db, copro_a, syndic_a, token_a)
    r = _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id)
    assert r.status_code == 422 and "justificatif" in r.json()["detail"]
    m = _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id, document_id=facture.id).json()
    corps = {"date": f"{Y}-03-01", "libelle": "Facture EDF", "type": "depense", "categorie": "energie",
             "montant": 300, "avance_par_id": syndic_a.id, "document_id": None}
    assert client.put(f"/api/mouvements/{m['id']}", json=corps, headers=auth(token_a)).status_code == 422
    r = client.delete(f"/api/documents/{facture.id}", headers=auth(token_a))
    assert r.status_code == 409 and "justifie l'avance" in r.json()["detail"]


def test_regles(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a):
    ex_id, membre, lot_syndic, lot_voisin, facture = _base(client, db, copro_a, syndic_a, token_a)
    _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id, document_id=facture.id)
    # Déduction sur le lot d'un autre copropriétaire.
    r = _mouvement(client, token_a, ex_id, type="encaissement", categorie="charges", montant=50,
                   lot_id=lot_voisin.id, avance_par_id=syndic_a.id)
    assert r.status_code == 422 and "un de ses lots" in r.json()["detail"]
    # Catégorie « avance » : seulement un remboursement à une personne.
    for champs in ({"categorie": "avance"}, {"type": "encaissement", "categorie": "avance", "avance_par_id": syndic_a.id,
                                             "lot_id": lot_syndic.id}):
        assert _mouvement(client, token_a, ex_id, montant=10, **champs).status_code == 422
    # Remboursement rattaché à un lot ; personne sans compte dans la copropriété.
    assert _mouvement(client, token_a, ex_id, categorie="avance", montant=10, avance_par_id=syndic_a.id,
                      lot_id=lot_syndic.id).status_code == 422
    r = _mouvement(client, token_a, ex_id, avance_par_id=syndic_b.id, document_id=facture.id)
    assert r.status_code == 422 and "n'a pas de compte" in r.json()["detail"]
    # Type ou catégorie d'une avance : pas en lot.
    ids = [m.id for m in db.query(Mouvement).all()]
    r = client.post("/api/mouvements/groupe", json={"ids": ids, "categorie": "autre"}, headers=auth(token_a))
    assert r.status_code == 422 and "un par un" in r.json()["detail"]


def test_droits(client, db, copro_a, syndic_a, token_a):
    ex_id, membre, lot_syndic, lot_voisin, facture = _base(client, db, copro_a, syndic_a, token_a)
    _mouvement(client, token_a, ex_id, avance_par_id=membre.id, document_id=facture.id, montant=80)
    tok_membre = create_access_token(membre.id, copro_a.id)
    assert client.get("/api/avances", headers=auth(tok_membre)).status_code == 403
    [moi] = client.get("/api/avances/moi", headers=auth(tok_membre)).json()
    assert (moi["nom"], moi["reste"]) == ("Membre voisin@test.fr", 80)
    assert client.get("/api/avances/moi", headers=auth(token_a)).json() == []


def test_compte_supprime_seulement_une_fois_rembourse(client, db, copro_a, syndic_a, token_a):
    ex_id, membre, _, lot_voisin, facture = _base(client, db, copro_a, syndic_a, token_a)
    _mouvement(client, token_a, ex_id, avance_par_id=membre.id, document_id=facture.id, montant=80)
    r = client.delete(f"/api/auth/users/{membre.id}", headers=auth(token_a))
    assert r.status_code == 409 and "avances" in r.json()["detail"]
    _mouvement(client, token_a, ex_id, type="encaissement", categorie="charges", montant=80, lot_id=lot_voisin.id,
               avance_par_id=membre.id)
    tresorerie = _recap(client, token_a)["tresorerie_syndicat"]
    assert client.delete(f"/api/auth/users/{membre.id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    assert db.query(Mouvement).filter(Mouvement.avance_par_id.isnot(None)).count() == 0
    assert _recap(client, token_a)["tresorerie_syndicat"] == tresorerie            # la banque ne change pas


def test_grand_livre(client, db, copro_a, syndic_a, token_a):
    ex_id, _, lot_syndic, _, facture = _base(client, db, copro_a, syndic_a, token_a)
    _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id, document_id=facture.id)
    _mouvement(client, token_a, ex_id, categorie="avance", montant=100, avance_par_id=syndic_a.id,
               libelle="Remboursement")
    r = client.get("/api/export/compte-gestion", headers=auth(token_a))
    assert r.status_code == 200
    texte = r.content.decode("utf-8-sig")
    assert "payée par" in texte and "(hors banque)" in texte and "remboursement d'avance à" in texte


def test_regularisation_ignore_les_remboursements(client, db, copro_a, syndic_a, token_a):
    from app.models.exercice import Exercice
    from app.services import regularisation
    ex_id, _, _, _, facture = _base(client, db, copro_a, syndic_a, token_a)
    _mouvement(client, token_a, ex_id, avance_par_id=syndic_a.id, document_id=facture.id)
    _mouvement(client, token_a, ex_id, categorie="avance", montant=100, avance_par_id=syndic_a.id)
    calcul = regularisation.calcul(db, db.get(Exercice, ex_id))
    assert calcul["total_charges_reelles"] == 300


def test_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "d0e1f2a3b4c5")
    with create_engine(url).begin() as c:
        c.execute(text("insert into coproprietes (id, nom) values (1, 'R')"))
        c.execute(text("insert into exercices (id, copropriete_id, annee) values (1, 1, 2026)"))
        c.execute(text("insert into mouvements (id, copropriete_id, exercice_id, date, libelle, type, montant) "
                       "values (1, 1, 1, '2026-03-01', 'EDF', 'depense', 300)"))
    command.upgrade(cfg, "head")
    with create_engine(url).connect() as c:
        assert c.execute(text("select avance_par_id, hors_banque from mouvements")).one() == (None, 0)
    command.downgrade(cfg, "d0e1f2a3b4c5")
    assert "hors_banque" not in [x["name"] for x in inspect(create_engine(url)).get_columns("mouvements")]
    command.upgrade(cfg, "head")
