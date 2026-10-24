"""RGPD : écarts relevés dans docs/rgpd.md § 8 (tâche 22b).

1. Mot de passe SMTP : chiffré en base (clé dérivée de COPRO_SECRET_KEY, préfixe « enc:v1: »).
   Un ancien mot de passe en clair reste lisible, puis est rechiffré au démarrage.
2. Journaux : purge automatique du journal d'audit et des informations de dernière connexion
   (IP, navigateur) au-delà de COPRO_RETENTION_JOURNAL_MOIS (12 par défaut, 0 = jamais).
3. Droit d'accès (RGPD art. 15) : export « mes données » en JSON, limité à la personne.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core import crypto
from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.lot import Lot
from app.models.user import User
from tests.conftest import _make_membre, auth

MOT_DE_PASSE = "Sm7p-tres-secret!"


def _brut(db, copro):
    return db.execute(text("SELECT smtp_password FROM coproprietes WHERE id = :i"), {"i": copro.id}).scalar()


# ---------------------------------------------------------------- 1. SMTP chiffré
def test_mot_de_passe_smtp_chiffre_en_base(client, token_a, db, copro_a):
    r = client.put("/api/smtp/config", json={"smtp_host": "smtp.test", "smtp_user": "u",
                                             "smtp_password": MOT_DE_PASSE}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    brut = _brut(db, copro_a)
    assert brut.startswith("enc:v1:") and MOT_DE_PASSE not in brut
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).smtp_password == MOT_DE_PASSE   # relu en clair par l'ORM


def test_ancien_mot_de_passe_en_clair_lisible_puis_rechiffre(db, copro_a):
    db.execute(text("UPDATE coproprietes SET smtp_password = :p WHERE id = :i"),
               {"p": MOT_DE_PASSE, "i": copro_a.id})
    db.commit()
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).smtp_password == MOT_DE_PASSE   # rien n'est cassé
    assert crypto.rechiffrer_secrets_smtp(db) == 1
    assert _brut(db, copro_a).startswith("enc:v1:")
    db.expire_all()
    assert db.get(Copropriete, copro_a.id).smtp_password == MOT_DE_PASSE
    assert crypto.rechiffrer_secrets_smtp(db) == 0                          # idempotent


def test_mot_de_passe_vide_reste_vide(db, copro_a):
    copro_a.smtp_password = ""
    db.commit()
    assert _brut(db, copro_a) == ""


def test_cle_changee_mot_de_passe_illisible(monkeypatch):
    jeton = crypto.chiffrer_texte(MOT_DE_PASSE)
    monkeypatch.setattr(get_settings(), "secret_key", "une-autre-cle")
    assert crypto.dechiffrer_texte(jeton) == ""                              # à ressaisir, pas de 500


# ---------------------------------------------------------------- 2. purge des journaux
def _retention():
    from app.services import retention      # importé ici : le module n'existe pas avant le correctif
    return retention


def test_purge_du_journal_d_audit(db):
    maintenant = datetime(2026, 10, 24, 12, 0)
    db.add_all([AuditLog(action="login", created_at=maintenant - timedelta(days=400)),
                AuditLog(action="login", created_at=maintenant - timedelta(days=30))])
    db.commit()
    stats = _retention().purger_journaux(db, maintenant=maintenant, mois=12)
    assert stats["audit"] == 1
    assert [a.created_at for a in db.query(AuditLog).all()] == [maintenant - timedelta(days=30)]


def test_purge_des_infos_de_connexion(db, copro_a):
    maintenant = datetime(2026, 10, 24, 12, 0)
    ancien = _make_membre(db, "ancien@test.fr", copro_a)
    recent = _make_membre(db, "recent@test.fr", copro_a)
    ancien.last_login_at, ancien.last_login_ip, ancien.last_login_ua = maintenant - timedelta(days=400), "1.2.3.4", "Firefox"
    recent.last_login_at, recent.last_login_ip, recent.last_login_ua = maintenant - timedelta(days=3), "5.6.7.8", "Chrome"
    db.commit()
    assert _retention().purger_journaux(db, maintenant=maintenant, mois=12)["connexions"] == 1
    db.refresh(ancien)
    db.refresh(recent)
    assert (ancien.last_login_ip, ancien.last_login_ua) == ("", "")
    assert ancien.last_login_at is not None                                  # la date seule reste
    assert recent.last_login_ip == "5.6.7.8"


def test_purge_desactivee(db):
    db.add(AuditLog(action="login", created_at=datetime(2000, 1, 1)))
    db.commit()
    assert _retention().purger_journaux(db, mois=0) == {"audit": 0, "connexions": 0}
    assert db.query(AuditLog).count() == 1


def test_duree_par_defaut_12_mois():
    assert get_settings().retention_journal_mois == 12


# ---------------------------------------------------------------- 3. export « mes données »
def test_export_mes_donnees(client, db, copro_a, copro_b, syndic_b):
    from app.core.security import create_access_token
    membre = _make_membre(db, "marie@test.fr", copro_a)
    membre.prenom, membre.telephone = "Marie", "0600000000"
    autre = _make_membre(db, "voisin@test.fr", copro_a)
    db.add_all([Lot(copropriete_id=copro_a.id, numero="12", tantiemes=100, proprietaire_id=membre.id,
                    statut_occupation="occupant"),
                Lot(copropriete_id=copro_a.id, numero="13", tantiemes=100, proprietaire_id=autre.id)])
    db.commit()
    r = client.get("/api/auth/me/export", headers=auth(create_access_token(membre.id, copro_a.id)))
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    d = r.json()
    assert d["profil"]["email"] == "marie@test.fr" and d["profil"]["telephone"] == "0600000000"
    assert [l["numero"] for l in d["lots"]] == ["12"]
    assert d["lots"][0]["statut_occupation"] == "occupant"
    for cle in ("coproprietes", "decomptes", "votes", "convocations", "relances", "actes_recouvrement", "journal"):
        assert cle in d
    brut = json.dumps(d)
    assert "voisin@test.fr" not in brut and "syndic.b@test.fr" not in brut  # rien sur les autres
    assert "password_hash" not in brut and "totp_secret" not in brut         # jamais de secret


def test_export_trace_dans_le_journal(client, db, copro_a, token_a, syndic_a):
    client.get("/api/auth/me/export", headers=auth(token_a))
    assert db.query(AuditLog).filter(AuditLog.action == "export_donnees_personnelles",
                                     AuditLog.user_id == syndic_a.id).count() == 1


def test_export_exige_une_connexion(client):
    assert client.get("/api/auth/me/export").status_code == 401
