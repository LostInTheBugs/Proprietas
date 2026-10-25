"""PV de consultation écrite et lisibilité de l'aperçu 19-2.

1. PV de consultation écrite (petites copropriétés, décret n° 67-223 dans sa rédaction issue du
   décret n° 2020-834) : procès-verbal établi et signé par le SYNDIC, indiquant le sens du vote
   de CHAQUE copropriétaire ; les écrits de vote sont annexés. Il n'y a ni président de séance,
   ni secrétaire, ni scrutateur : le PV d'AG ne convenait pas.
2. Aperçu 19-2 : « total nouvellement exigible » et « arriéré échu » se recouvraient (les restes
   des exercices précédents figuraient dans les deux). Le décompte est maintenant ventilé en
   quatre parts disjointes dont la somme est le solde du lot.
"""
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.models.ag import AG, Resolution, Vote
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.services.pv_pdf import generer_pv_pdf, votants_nommes
from tests.conftest import auth
from tests.test_pv_conforme import _user
from tests.test_recouvrement import AUJOURDHUI, _campagne, _md_enregistree


def _texte(buf: BytesIO) -> str:
    return " ".join((p.extract_text() or "").replace("\n", " ") for p in PdfReader(BytesIO(buf.getvalue())).pages)


def _seance(db, copro, type_ag, voix=("pour", "pour", "pour")):
    dupont, martin = _user(db, copro, "Jean", "Dupont"), _user(db, copro, "Claire", "Martin")
    lots = [Lot(copropriete_id=copro.id, numero=str(i + 1), tantiemes=t, proprietaire_id=o.id)
            for i, (t, o) in enumerate(((400, dupont), (100, dupont), (500, martin)))]
    db.add_all(lots)
    ag = AG(copropriete_id=copro.id, date=date(2026, 11, 20), type_ag=type_ag)
    db.add(ag)
    db.flush()
    r = Resolution(ag_id=ag.id, numero=1, libelle="Remplacement de la porte", majorite="unanimite")
    db.add(r)
    db.flush()
    db.add_all([Vote(resolution_id=r.id, lot_id=l.id, voix=v) for l, v in zip(lots, voix)])
    db.commit()
    db.refresh(ag)
    return ag, r, lots


# ---------------------------------------------------------------- 1. PV de consultation écrite
def test_votants_nommes_inclut_les_votes_pour(db, copro_a):
    ag, r, lots = _seance(db, copro_a, "consultation_ecrite")
    noms = votants_nommes(r, lots, db)
    assert noms["pour"] == [("Dupont Jean", ["1", "2"], 500), ("Martin Claire", ["3"], 500)]


def test_pv_consultation_nomme_chaque_vote_et_signe_par_le_syndic(db, copro_a):
    ag, r, lots = _seance(db, copro_a, "consultation_ecrite")
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "PROCÈS-VERBAL DE CONSULTATION ÉCRITE" in texte
    assert "Pour : Dupont Jean (lots 1, 2)" in texte and "Martin Claire (lot 3)" in texte
    assert "Le syndic" in texte
    assert "annexés" in texte
    assert "Le président de séance" not in texte and "scrutateur" not in texte


def test_pv_d_ag_inchange(db, copro_a):
    ag, r, lots = _seance(db, copro_a, "annuelle")
    texte = _texte(generer_pv_pdf(copro_a, ag, db))
    assert "PROCÈS-VERBAL D'ASSEMBLÉE GÉNÉRALE" in texte
    assert "Le président de séance" in texte
    assert "Pour : Dupont" not in texte          # en AG, la loi nomme opposants, abstenus, défaillants


# ---------------------------------------------------------------- 2. aperçu 19-2 ventilé
def _apercu(client, token_a, lot):
    r = client.get(f"/api/recouvrement/lot/{lot.id}/19-2", headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


def test_apercu_19_2_ventile_sans_recouvrement(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)                 # solde 550 = 200 (n-1) + 200 échu + 150 à échoir
    _md_enregistree(client, token_a, lot.id, jours_avant=45)
    b = _apercu(client, token_a, lot)
    assert (b["a_echoir"], b["precedents_approuves"], b["echu_courant"], b["precedents_non_approuves"]) \
        == (150.0, 200.0, 200.0, 0.0)
    assert b["total"] == b["a_echoir"] + b["precedents_approuves"] == 350.0
    assert b["total"] + b["echu_courant"] + b["precedents_non_approuves"] == 550.0   # = solde


def test_apercu_19_2_exercice_non_approuve(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    prev = db.query(Exercice).filter(Exercice.annee == AUJOURDHUI.year - 1).one()
    prev.comptes_approuves_le = None
    db.commit()
    _md_enregistree(client, token_a, lot.id, jours_avant=45)
    b = _apercu(client, token_a, lot)
    assert (b["precedents_approuves"], b["precedents_non_approuves"], b["total"]) == (0.0, 200.0, 150.0)
