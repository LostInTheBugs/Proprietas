"""Notifications et mises en demeure : décret n° 67-223, art. 64 à 64-4 (rédaction du décret
n° 2025-1292 du 22 décembre 2025).

- Art. 64 : la voie électronique (LRE ou prestataire qualifié) est la règle.
- Art. 64-1 : « par exception », la LRAR, lorsque le copropriétaire a demandé la voie postale.
- Art. 64-4 : la demande prend effet le 9e jour suivant sa réception par le syndic, ou le jour
  même si elle est formulée en assemblée générale. Pendant ces 9 jours, la LRE reste valable
  et la LRAR (demandée) l'est aussi.
- Art. 64-3 : la remise contre récépissé ne vaut que pour les convocations et l'avis de
  l'art. 59, PAS pour une mise en demeure. La signification par commissaire de justice reste
  toujours possible (CPC, art. 651).
- Fonds de travaux avec PPT (loi, art. 14-2-1) : au moins 2,5 % du plan ET au moins 5 % du
  budget, donc le plus élevé des deux, pas leur somme.
- Limiteur de connexion : pas d'entrée créée par une simple vérification, purge des entrées
  expirées.
"""
import time
from collections import deque
from datetime import date, timedelta

import pytest

from app.core.security import create_access_token
from app.models.recouvrement import ActeRecouvrement
from tests.conftest import auth
from tests.test_notification_pv import _item, _preparer, _saisir, seance  # noqa: F401 (fixture)
from tests.test_recouvrement import _campagne

AUJOURDHUI = date.today()


def _jour(n):
    return (AUJOURDHUI - timedelta(days=n)).isoformat()


def _demande(client, token_a, user, **corps):
    return client.put(f"/api/auth/users/{user.id}/voie-postale", json={"postale": True, **corps},
                      headers=auth(token_a))


# ---------------------------------------------------------------- art. 64-4 : date d'effet
def test_demande_recue_par_le_syndic_effet_au_neuvieme_jour(client, token_a, seance):
    r = _demande(client, token_a, seance["bernard"], recue_le=_jour(3))
    assert r.status_code == 200, r.text
    assert r.json()["notification_postale_depuis"] == (AUJOURDHUI + timedelta(days=6)).isoformat()


def test_demande_formulee_en_assemblee_effet_immediat(client, token_a, seance):
    r = _demande(client, token_a, seance["bernard"], recue_le=_jour(2), en_assemblee=True)
    assert r.status_code == 200, r.text
    assert r.json()["notification_postale_depuis"] == _jour(2)


def test_date_de_reception_future_refusee(client, token_a, seance):
    r = _demande(client, token_a, seance["bernard"], recue_le=(AUJOURDHUI + timedelta(days=1)).isoformat())
    assert r.status_code == 422


def test_demande_du_coproprietaire_lui_meme_effet_au_neuvieme_jour(client, copro_a, seance):
    tok = create_access_token(seance["bernard"].id, copro_a.id)
    r = client.put("/api/auth/me/voie-postale", json={"postale": True}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["notification_postale_depuis"] == (AUJOURDHUI + timedelta(days=9)).isoformat()


# ---------------------------------------------------------------- notification du PV
def test_pv_lrar_refusee_sans_demande(client, token_a, seance):
    martin = _item(_preparer(client, token_a, seance["ag"]), "Martin Claire")
    r = _saisir(client, token_a, martin["id"], mode="lrar", date_envoi=AUJOURDHUI.isoformat())
    assert r.status_code == 422
    assert "électronique" in r.json()["detail"]


def test_pv_pendant_le_delai_de_neuf_jours_les_deux_modes(client, token_a, seance):
    assert _demande(client, token_a, seance["bernard"], recue_le=_jour(2)).status_code == 200
    bernard = _item(_preparer(client, token_a, seance["ag"]), "Bernard Luc")
    assert _saisir(client, token_a, bernard["id"], mode="lre").status_code == 200
    assert _saisir(client, token_a, bernard["id"], mode="lrar").status_code == 200


def test_pv_lre_refusee_une_fois_la_demande_en_vigueur(client, token_a, seance):
    assert _demande(client, token_a, seance["bernard"], recue_le=_jour(10)).status_code == 200
    bernard = _item(_preparer(client, token_a, seance["ag"]), "Bernard Luc")
    r = _saisir(client, token_a, bernard["id"], mode="lre", date_envoi=AUJOURDHUI.isoformat())
    assert r.status_code == 422
    assert "voie postale" in r.json()["detail"]


# ---------------------------------------------------------------- mise en demeure
def _md(client, token, lot_id, **champs):
    corps = {"type": "mise_en_demeure", "date_envoi": AUJOURDHUI.isoformat(), "mode_envoi": "lre",
             "reference": "LRE-1"}
    corps.update(champs)
    return client.post(f"/api/recouvrement/lot/{lot_id}/acte", json=corps, headers=auth(token))


def test_md_lrar_refusee_sans_demande(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    r = _md(client, token_a, lot.id, mode_envoi="lrar", reference="AR-1")
    assert r.status_code == 422
    assert "électronique" in r.json()["detail"]


def test_md_lre_refusee_si_voie_postale_en_vigueur(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    from app.models.user import User
    p = db.get(User, lot.proprietaire_id)
    p.notification_postale, p.notification_postale_depuis = True, AUJOURDHUI - timedelta(days=1)
    db.commit()
    assert _md(client, token_a, lot.id, mode_envoi="lre").status_code == 422
    assert _md(client, token_a, lot.id, mode_envoi="lrar", reference="AR-1").status_code == 200


def test_md_remise_contre_recepisse_refusee(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    r = _md(client, token_a, lot.id, mode_envoi="remise", reference="Récépissé", date_reception=_jour(0))
    assert r.status_code == 422
    assert "64-3" in r.json()["detail"]


@pytest.mark.parametrize("champs,attendu", [
    ({"reference": "Acte n° 12", "date_reception": _jour(0)}, 200),
    ({"reference": "", "date_reception": _jour(0)}, 422),
    ({"reference": "Acte n° 12", "date_reception": None}, 422),
])
def test_md_signification_par_commissaire_de_justice(client, db, copro_a, syndic_a, token_a, champs, attendu):
    lot, *_ = _campagne(db, copro_a)
    assert _md(client, token_a, lot.id, mode_envoi="signification", **champs).status_code == attendu


def test_ancienne_md_par_remise_ne_fait_pas_courir_le_delai(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    db.add(ActeRecouvrement(copropriete_id=copro_a.id, lot_id=lot.id, type="mise_en_demeure",
                            date_envoi=AUJOURDHUI - timedelta(days=90), mode_envoi="remise",
                            date_reception=AUJOURDHUI - timedelta(days=90), montant=400))
    db.commit()
    d = client.get(f"/api/recouvrement/lot/{lot.id}", headers=auth(token_a)).json()
    assert d["statut"] == "en_retard"


# ---------------------------------------------------------------- fonds de travaux (art. 14-2-1)
def test_fonds_de_travaux_avec_ppt_le_plus_eleve_pas_la_somme():
    from app.services.country_rules import regles_fonds_travaux
    texte = regles_fonds_travaux(None)["texte"]
    assert "+ 5 %" not in texte
    assert "le plus élevé" in texte


# ---------------------------------------------------------------- limiteur de connexion
def test_limiteur_ne_cree_pas_d_entree_et_purge_les_expirees():
    from app.core import rate_limit
    rate_limit._failures.clear()
    try:
        for i in range(50):
            rate_limit.check_login_allowed(f"inconnu{i}@test.fr", "10.0.0.1")
        assert len(rate_limit._failures) == 0
        rate_limit._failures["ancien@test.fr|10.0.0.2"] = deque(
            [time.monotonic() - rate_limit.WINDOW_SECONDS - 1])
        rate_limit._derniere_purge = 0.0
        rate_limit.record_failure("nouveau@test.fr", "10.0.0.3")
        assert list(rate_limit._failures) == ["nouveau@test.fr|10.0.0.3"]
    finally:
        rate_limit._failures.clear()
