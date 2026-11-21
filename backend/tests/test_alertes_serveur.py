"""Alertes de supervision par e-mail aux administrateurs de l'instance (demande de Fred, 22/11/2026).

Après chaque relevé (toutes les 5 minutes), l'application vérifie :
- disque à 90 % ou plus ; mémoire à 95 % ou plus sur les 3 derniers relevés ; processeur à 90 % ou plus en
  moyenne sur les 3 derniers relevés ; 10 erreurs serveur (5xx) ou plus en 5 minutes ;
- applicateur des mises à jour arrêté (installé, mais muet depuis plus de 15 minutes) ;
- sauvegarde automatique sur le drive en échec dans une copropriété.
Un problème ouvre un incident et envoie un e-mail ; rappel au plus une fois par 24 h tant qu'il dure ;
e-mail « résolu » quand il disparaît. Les incidents des 7 derniers jours sont listés dans « État du serveur ».
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from tests.conftest import auth


@pytest.fixture()
def boite(monkeypatch, tmp_path):
    from app.services import emailer
    envois = []
    monkeypatch.setattr(emailer, "envoyer_email", lambda copro, dest, sujet, corps: envois.append((dest, sujet, corps)))
    monkeypatch.setattr(get_settings(), "update_dir", str(tmp_path / "updates"))
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.exemple.fr")
    monkeypatch.setattr(get_settings(), "email_expediteur", "proprietas@exemple.fr")
    (tmp_path / "updates").mkdir()
    return envois


def _admin(db, user):
    user.is_instance_admin = True
    db.commit()


def _mesure(db, il_y_a_min=0, **valeurs):
    from app.models.supervision import MesureServeur
    m = MesureServeur(instant=datetime.now() - timedelta(minutes=il_y_a_min), source="hote",
                      **{"cpu_pct": 10, "memoire_pct": 40, "disque_pct": 50, "requetes": 5, "erreurs_5xx": 0, **valeurs})
    db.add(m)
    db.commit()
    return m


def _incidents(db, ouverts=True):
    from app.models.supervision import Incident
    q = db.query(Incident)
    return {i.code for i in (q.filter(Incident.fin.is_(None)) if ouverts else q)}


def test_disque_ouvre_rappelle_puis_resout(db, syndic_a, boite):
    from app.models.supervision import Incident
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db, disque_pct=93.5)
    alertes_serveur.verifier(db)
    assert _incidents(db) == {"disque"}
    assert len(boite) == 1 and boite[0][0] == syndic_a.email and "disque" in boite[0][1].lower()
    assert "93,5 %" in boite[0][2]
    alertes_serveur.verifier(db)                           # toujours plein : pas de nouvel e-mail
    assert len(boite) == 1
    inc = db.query(Incident).one()
    inc.dernier_envoi = datetime.now() - timedelta(hours=25)
    db.commit()
    alertes_serveur.verifier(db)                           # 24 h plus tard : rappel
    assert len(boite) == 2 and "rappel" in boite[1][1].lower()
    _mesure(db, disque_pct=60)
    alertes_serveur.verifier(db)
    assert _incidents(db) == set() and db.query(Incident).one().fin is not None
    assert len(boite) == 3 and "résolu" in boite[2][1].lower()


def test_memoire_et_processeur_sur_15_minutes(db, syndic_a, boite):
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db, 10, memoire_pct=97, cpu_pct=95)
    _mesure(db, 5, memoire_pct=97, cpu_pct=95)
    alertes_serveur.verifier(db)
    assert _incidents(db) == set()                         # deux relevés seulement : un pic passager
    _mesure(db, 0, memoire_pct=96, cpu_pct=92)
    alertes_serveur.verifier(db)
    assert _incidents(db) == {"memoire", "cpu"} and len(boite) == 2


def test_erreurs_serveur(db, syndic_a, boite):
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db, erreurs_5xx=12, requetes=40)
    alertes_serveur.verifier(db)
    assert _incidents(db) == {"erreurs"} and "12 erreurs" in boite[0][2]


def test_applicateur_arrete(db, syndic_a, boite, tmp_path):
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db)
    statut = Path(get_settings().update_dir) / "update-applier.json"
    alertes_serveur.verifier(db)
    assert _incidents(db) == set()                         # pas d'applicateur installé : rien à signaler
    statut.write_text(json.dumps({"seen_at": time.time() - 3600}), encoding="utf-8")
    alertes_serveur.verifier(db)
    assert _incidents(db) == {"applicateur"}
    statut.write_text(json.dumps({"seen_at": time.time()}), encoding="utf-8")
    alertes_serveur.verifier(db)
    assert _incidents(db) == set()


def test_sauvegarde_drive_en_echec(db, copro_a, syndic_a, boite):
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db)
    copro_a.drive_sauvegarde_erreur = "21/11/2026 03:00 : drive injoignable"
    db.commit()
    alertes_serveur.verifier(db)
    assert _incidents(db) == {"sauvegarde"} and copro_a.nom in boite[0][2]


def test_sans_administrateur_ni_smtp_aucune_erreur(db, syndic_a, boite, monkeypatch):
    from app.services import alertes_serveur
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    _mesure(db, disque_pct=99)
    alertes_serveur.verifier(db)                           # personne à prévenir : l'incident est quand même noté
    assert _incidents(db) == {"disque"} and boite == []


def test_incidents_dans_l_historique(client, db, syndic_a, token_a, boite):
    from app.services import alertes_serveur
    _admin(db, syndic_a)
    _mesure(db, disque_pct=95)
    alertes_serveur.verifier(db)
    d = client.get("/api/instance/supervision?heures=24", headers=auth(token_a)).json()
    assert [(i["code"], i["en_cours"]) for i in d["incidents"]] == [("disque", True)]
    assert "95" in d["incidents"][0]["detail"]
