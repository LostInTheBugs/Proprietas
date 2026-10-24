"""Convocations et PV : délai légal et nature des e-mails.

- Décret n° 67-223, art. 9 : la convocation est notifiée au moins VINGT ET UN jours avant
  l'AG (sauf urgence ou délai plus long du règlement). L'application annonçait 15 jours et
  envoyait l'e-mail automatique 15 jours avant par défaut.
- Décret n° 2025-1292 du 22/12/2025 (art. 64 et s. du décret de 1967) : une notification
  électronique passe par une lettre recommandée électronique ou un prestataire de confiance
  qualifié ; sinon LRAR ou, pour la convocation, remise contre récépissé. Un e-mail simple
  n'est qu'une INFORMATION : l'application ne doit pas le présenter comme une convocation
  ou une notification.
- Le délai de contestation (2 mois) court à compter de la notification du PV (loi 1965,
  art. 42 al. 2) — l'ancien e-mail citait à tort « art. 17, deux mois depuis l'AG ».
"""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.ag import AG
from app.models.copropriete import Copropriete
from app.schemas import AGIn
from app.services.emailer import convocation_sujet, convocation_texte, pv_email_texte
from tests.conftest import auth


def test_envoi_automatique_par_defaut_21_jours(client, token_a):
    r = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=60))}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["rappel_jours"] == 21


@pytest.mark.parametrize("jours", [1, 15, 20])
def test_envoi_automatique_moins_de_21_jours_refuse(jours):
    with pytest.raises(ValidationError, match="21 jours"):
        AGIn(date=date.today(), rappel_jours=jours)


@pytest.mark.parametrize("jours", [0, 21, 45, 90])
def test_envoi_automatique_valeurs_acceptees(jours):
    assert AGIn(date=date.today(), rappel_jours=jours).rappel_jours == jours


def test_api_refuse_15_jours(client, token_a):
    r = client.post("/api/ag", json={"date": str(date.today() + timedelta(days=60)), "rappel_jours": 15},
                    headers=auth(token_a))
    assert r.status_code == 422


def _ag():
    return AG(date=date(2026, 12, 15), heure="18:30", type_ag="annuelle", lieu="Salle", resolutions=[])


def test_email_de_convocation_presente_comme_information():
    copro = Copropriete(nom="Les Tilleuls")
    texte = convocation_texte(copro, _ag(), [], "Le syndic")
    assert "Vous êtes convoqué" not in texte
    assert "ne remplace pas la convocation" in texte
    assert "art. 9 et 64" in texte
    assert convocation_sujet(copro, _ag()).startswith("Information")


def test_email_du_pv_cite_l_article_42_et_plus_l_article_17():
    texte = pv_email_texte(Copropriete(nom="Les Tilleuls"), _ag(), "Le syndic")
    assert "article 17" not in texte
    assert "deux mois à compter de l'assemblée" not in texte
    assert "42" in texte and "ne vaut pas notification" in texte
