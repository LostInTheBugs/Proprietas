"""Mise en demeure (art. 19-2 de la loi de 1965) : notification valable et point de départ.

- Modes valables : lettre recommandée électronique (LRE), LRAR si le copropriétaire a demandé la
  voie postale, signification par commissaire de justice. La remise contre récépissé ne vaut
  pas pour une mise en demeure (décret, art. 64-3).
  Un e-mail simple ne vaut pas mise en demeure (décret 67-223, art. 64 et s., rédaction
  du décret n° 2025-1292).
- Le délai de 30 jours court à compter du LENDEMAIN de la première présentation (LRAR), de
  l'avis électronique du prestataire (LRE) ou de la signification : il faut saisir cette date.
  Avant, il partait de la date d'ENVOI, donc trop tôt.
- Signification : date de l'acte et référence obligatoires.
- Les intérêts au taux légal courent aussi à partir de cette date.
- Le PDF mentionne les cotisations du fonds de travaux (art. 19-2, dernier alinéa).
"""
from datetime import date, timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.models.recouvrement import ActeRecouvrement
from tests.conftest import auth
from tests.test_recouvrement import AUJOURDHUI, _campagne


def _md(client, token, lot_id, **champs):
    corps = {"type": "mise_en_demeure", "date_envoi": AUJOURDHUI.isoformat(), "mode_envoi": "lre",
             "reference": "LRE-1"}
    corps.update(champs)
    return client.post(f"/api/recouvrement/lot/{lot_id}/acte", json=corps, headers=auth(token))


def _statut(client, token, lot_id):
    return client.get(f"/api/recouvrement/lot/{lot_id}", headers=auth(token)).json()


def _jour(n):
    return (AUJOURDHUI - timedelta(days=n)).isoformat()


def test_email_ne_vaut_pas_mise_en_demeure(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    r = _md(client, token_a, lot.id, mode_envoi="email")
    assert r.status_code == 422
    assert "ne vaut pas mise en demeure" in r.json()["detail"]


@pytest.mark.parametrize("champs", [{"reference": ""}, {"date_reception": None}])
def test_signification_exige_reference_et_date(client, db, copro_a, syndic_a, token_a, champs):
    lot, *_ = _campagne(db, copro_a)
    corps = {"mode_envoi": "signification", "reference": "Acte n° 12", "date_reception": _jour(0)}
    corps.update(champs)
    assert _md(client, token_a, lot.id, **corps).status_code == 422


def test_sans_date_de_reception_le_delai_ne_court_pas(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    assert _md(client, token_a, lot.id, date_envoi=_jour(60)).status_code == 200
    d = _statut(client, token_a, lot.id)
    assert d["statut"] == "mise_en_demeure_attente"
    assert d["jours_restants"] is None
    assert d["interets"] == 0.0
    # envoyée il y a 60 jours, mais présentation inconnue : pas d'article 19-2
    assert client.post(f"/api/recouvrement/lot/{lot.id}/19-2", headers=auth(token_a)).status_code == 400


def test_saisie_ulterieure_de_la_date_de_reception(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    acte = _md(client, token_a, lot.id, date_envoi=_jour(3)).json()
    r = client.put(f"/api/recouvrement/acte/{acte['id']}/reception",
                   json={"date_reception": _jour(1)}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["date_reception"] == _jour(1)
    d = _statut(client, token_a, lot.id)
    assert d["statut"] == "mise_en_demeure" and d["jours_restants"] == 30
    assert d["md_reception"] == _jour(1)


@pytest.mark.parametrize("jours,statut,activable", [
    (30, "mise_en_demeure", False),       # J+30 : dernier jour du délai
    (31, "delai_19_2_depasse", True),     # J+31 : délai expiré
])
def test_limite_du_delai_de_30_jours(client, db, copro_a, syndic_a, token_a, jours, statut, activable):
    lot, *_ = _campagne(db, copro_a)
    _md(client, token_a, lot.id, date_envoi=_jour(jours + 2), date_reception=_jour(jours))
    assert _statut(client, token_a, lot.id)["statut"] == statut
    r = client.get(f"/api/recouvrement/lot/{lot.id}/19-2", headers=auth(token_a))
    assert (r.status_code == 200) is activable


@pytest.mark.parametrize("reception", ["avant_envoi", "future"])
def test_date_de_reception_incoherente_refusee(client, db, copro_a, syndic_a, token_a, reception):
    lot, *_ = _campagne(db, copro_a)
    valeur = _jour(10) if reception == "avant_envoi" else (AUJOURDHUI + timedelta(days=1)).isoformat()
    assert _md(client, token_a, lot.id, date_envoi=_jour(5), date_reception=valeur).status_code == 422


def test_ancienne_md_par_email_ignoree(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    db.add(ActeRecouvrement(copropriete_id=copro_a.id, lot_id=lot.id, type="mise_en_demeure",
                            date_envoi=date.today() - timedelta(days=90), mode_envoi="email", montant=400))
    db.commit()
    assert _statut(client, token_a, lot.id)["statut"] == "en_retard"


def test_pdf_fonds_de_travaux_et_point_de_depart(client, db, copro_a, syndic_a, token_a):
    lot, *_ = _campagne(db, copro_a)
    r = client.get(f"/api/recouvrement/lot/{lot.id}/mise-en-demeure.pdf", headers=auth(token_a))
    texte = " ".join((p.extract_text() or "") for p in PdfReader(BytesIO(r.content)).pages).replace("\n", " ")
    assert "cotisations du fonds de travaux" in texte
    assert "à compter du lendemain" in texte
    assert "à compter de la présente" not in texte
