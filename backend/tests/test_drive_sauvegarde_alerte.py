"""Sauvegarde automatique en échec : les syndics sont prévenus par e-mail (exercice de reprise du 19/11/2026).

Constat de l'exercice : l'échec n'était visible que dans Réglages ; un syndic bénévole ne s'en apercevait pas.
Règles : un e-mail au premier échec d'une série (pas à chaque nouvel essai toutes les 6 heures), un autre
quand la sauvegarde fonctionne de nouveau ; jamais bloquant ; avec Google Drive, l'autorisation expirée est
expliquée (application Google en mode « Test » : 7 jours).
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models.copropriete import Copropriete
from app.services import drive_sauvegarde
from app.services.emailer import EmailError
from tests.test_drive import _brancher, serveur  # noqa: F401
from tests.test_drive_sauvegarde import T0, _regler


@pytest.fixture()
def boite(monkeypatch):
    envoyes = []
    monkeypatch.setattr(drive_sauvegarde, "config_smtp", lambda copro: SimpleNamespace(source="instance"))
    monkeypatch.setattr(drive_sauvegarde, "envoyer_email",
                        lambda copro, dest, sujet, corps: envoyes.append((dest, sujet, corps)))
    return envoyes


def test_premier_echec_puis_retour(client, db, copro_a, syndic_a, token_a, serveur, boite):
    _brancher(client, token_a)
    _regler(client, token_a)
    serveur.panne = True
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0)["echecs"] == 1
    assert len(boite) == 1
    dest, sujet, corps = boite[0]
    assert dest == syndic_a.email and "a échoué" in sujet and "Résidence A" in sujet
    assert "injoignable" in corps and "toutes les 6 heures" in corps and "Réglages → Sauvegarde et stockage" in corps
    # Nouvel essai 6 heures plus tard, toujours en panne : pas de deuxième e-mail.
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(hours=6))["echecs"] == 1
    assert len(boite) == 1
    serveur.panne = False
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(hours=12))["sauvegardes"] == 1
    assert len(boite) == 2 and "rétablie" in boite[1][1] and "17/11/2026 à 15:30" in boite[1][2]
    # Semaine suivante sans incident : aucun e-mail.
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(days=7, hours=12))["sauvegardes"] == 1
    assert len(boite) == 2


def test_envoi_impossible_ne_bloque_rien(client, db, copro_a, syndic_a, token_a, serveur, monkeypatch):
    _brancher(client, token_a)
    _regler(client, token_a)
    serveur.panne = True
    monkeypatch.setattr(drive_sauvegarde, "config_smtp", lambda copro: SimpleNamespace(source="instance"))

    def refus(*a):
        raise EmailError("serveur SMTP injoignable")
    monkeypatch.setattr(drive_sauvegarde, "envoyer_email", refus)
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0) == {"sauvegardes": 0, "echecs": 1}
    monkeypatch.setattr(drive_sauvegarde, "config_smtp", lambda copro: None)       # aucun réglage d'envoi
    serveur.panne = False
    assert drive_sauvegarde.run_sauvegardes_drive(db, T0 + timedelta(hours=6)) == {"sauvegardes": 1, "echecs": 0}


def test_google_autorisation_expiree_expliquee(db, copro_a):
    copro_a.drive_type = "google"
    texte = drive_sauvegarde._corps_echec(copro_a, "L'autorisation Google a expiré ou a été retirée : reconnectez "
                                                   "Google Drive dans Réglages → Sauvegarde et stockage.")
    assert "mode « Test »" in texte and "7 jours" in texte and "publier l'application" in texte
    copro_a.drive_type = "webdav"
    assert "7 jours" not in drive_sauvegarde._corps_echec(copro_a, "Drive injoignable (ConnectError).")


def test_seuls_les_syndics_de_la_copropriete(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, serveur, boite):
    from tests.conftest import _make_membre
    _make_membre(db, "proprietaire@test.fr", copro_a)
    _brancher(client, token_a)
    _regler(client, token_a)
    serveur.panne = True
    drive_sauvegarde.run_sauvegardes_drive(db, T0)
    assert [d for d, _, _ in boite] == [syndic_a.email]
