"""Report des délais au premier jour ouvrable (code de procédure civile, art. 642).

« Le délai qui expirerait normalement un samedi, un dimanche ou un jour férié ou chômé est
prorogé jusqu'au premier jour ouvrable suivant. »

- Jours fériés légaux (code du travail, art. L3133-1) : 1er janvier, lundi de Pâques, 1er mai,
  8 mai, Ascension, lundi de Pentecôte, 14 juillet, 15 août, 1er novembre, 11 novembre,
  25 décembre. En Alsace-Moselle (Bas-Rhin 67, Haut-Rhin 68, Moselle 57) : en plus le Vendredi
  saint et le 26 décembre (art. L3134-13), déterminés par le code postal de la copropriété.
- Appliqué aux délais qui protègent le copropriétaire : fin du délai de contestation du PV
  (2 mois) et délai de 30 jours de la mise en demeure avant l'article 19-2. La date limite
  d'envoi du PV (obligation du syndic) n'est PAS reportée : on reste prudent.
"""
from datetime import date

import pytest

from tests.conftest import auth
from tests.test_notification_pv import _item, _preparer, _saisir, seance  # noqa: F401 (fixture)
from tests.test_recouvrement import _campagne


def _delais():
    from app.services import delais   # module créé par le correctif
    return delais


def test_jours_feries_2026():
    feries = _delais().jours_feries(2026)
    assert len(feries) == 11
    for d in ("2026-01-01", "2026-04-06", "2026-05-01", "2026-05-08", "2026-05-14", "2026-05-25",
              "2026-07-14", "2026-08-15", "2026-11-01", "2026-11-11", "2026-12-25"):
        assert date.fromisoformat(d) in feries


def test_jours_feries_alsace_moselle():
    feries = _delais().jours_feries(2026, alsace_moselle=True)
    assert len(feries) == 13
    assert date(2026, 4, 3) in feries and date(2026, 12, 26) in feries


@pytest.mark.parametrize("cp,attendu", [("57330", True), ("67000", True), ("68100", True),
                                        ("75011", False), ("", False), (None, False)])
def test_alsace_moselle_par_code_postal(cp, attendu):
    assert _delais().est_alsace_moselle(cp) is attendu


@pytest.mark.parametrize("echeance,attendu", [
    ("2026-10-27", "2026-10-27"),   # mardi : inchangé
    ("2026-10-31", "2026-11-02"),   # samedi → lundi (le dimanche 1er novembre est aussi férié)
    ("2026-12-25", "2026-12-28"),   # Noël (vendredi) → lundi
    ("2026-05-14", "2026-05-15"),   # Ascension (jeudi) → vendredi
    ("2026-04-04", "2026-04-07"),   # samedi → mardi (lundi de Pâques)
])
def test_report_au_premier_jour_ouvrable(echeance, attendu):
    assert _delais().reporter(date.fromisoformat(echeance)) == date.fromisoformat(attendu)


def test_vendredi_saint_reporte_en_alsace_moselle_seulement():
    d = date(2026, 4, 3)
    assert _delais().reporter(d) == d
    assert _delais().reporter(d, alsace_moselle=True) == date(2026, 4, 7)


# ---------------------------------------------------------------- intégration
def _fin_contestation(client, token_a, seance, envoi, presentation):
    martin = _item(_preparer(client, token_a, seance["ag"]), "Martin Claire")
    r = _saisir(client, token_a, martin["id"], date_envoi=envoi, date_presentation=presentation)
    assert r.status_code == 200, r.text
    return _item(r.json(), "Martin Claire")["fin_contestation"]


def test_fin_de_contestation_reportee(client, token_a, seance):
    # présentation le 31/08 → 31/10/2026 (samedi) → lundi 2 novembre
    assert _fin_contestation(client, token_a, seance, "2026-08-28", "2026-08-31") == "2026-11-02"


def test_fin_de_contestation_alsace_moselle(client, token_a, db, copro_a, seance):
    # présentation le 03/02 → 03/04/2026 : Vendredi saint en Moselle → mardi 7 avril
    copro_a.code_postal = "57330"
    db.commit()
    assert _fin_contestation(client, token_a, seance, "2026-02-02", "2026-02-03") == "2026-04-07"


def test_fin_de_contestation_hors_alsace_moselle(client, token_a, seance):
    assert _fin_contestation(client, token_a, seance, "2026-02-02", "2026-02-03") == "2026-04-03"


def test_limite_d_envoi_du_pv_non_reportee(client, token_a, db, seance):
    seance["ag"].date = date(2026, 10, 1)   # + 1 mois = dimanche 1er novembre 2026 (férié)
    db.commit()
    assert _preparer(client, token_a, seance["ag"])["limite_envoi"] == "2026-11-01"


def test_delai_19_2_reporte(client, db, copro_a, syndic_a, token_a):
    # présentée le 03/09/2026 : le délai de 30 jours finit le samedi 03/10, reporté au lundi
    # 05/10 ; l'article 19-2 devient applicable le lendemain, mardi 06/10 (au lieu du 04/10).
    lot, *_ = _campagne(db, copro_a)
    r = client.post(f"/api/recouvrement/lot/{lot.id}/acte", headers=auth(token_a), json={
        "type": "mise_en_demeure", "date_envoi": "2026-09-01", "date_reception": "2026-09-03",
        "mode_envoi": "lre", "reference": "LRE-1"})
    assert r.status_code == 200, r.text
    d = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    assert d["activable_le"] == "2026-10-06"
