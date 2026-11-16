"""SMTP de l'instance (PR #70 et issue #69 de zorglube).

Besoin : régler le serveur d'envoi une fois pour toute l'instance, hors de l'application (rotation des
secrets sans se connecter à Proprietas), et ne plus envoyer l'adresse de la démo dans les e-mails.

Règles :
- variables d'instance : COPRO_SMTP_HOST, COPRO_SMTP_PORT (587), COPRO_SMTP_USER, COPRO_SMTP_PASSWORD,
  COPRO_EMAIL_EXPEDITEUR, COPRO_FRONTEND_URL ;
- une copropriété qui a saisi un serveur SMTP utilise SES réglages, en entier (jamais de mélange :
  pas le serveur de l'un avec le mot de passe ou l'expéditeur de l'autre) ; s'ils sont incomplets,
  l'envoi est refusé comme avant ;
- une copropriété sans serveur SMTP utilise ceux de l'instance s'ils sont complets (serveur + expéditeur) ;
- sinon : « Configuration SMTP incomplète », comme avant ;
- adresse publique dans les e-mails : celle de la copropriété, sinon celle de l'instance, sinon AUCUN
  lien (plus d'adresse de démo codée en dur) ;
- le syndic voit dans Réglages si le serveur de l'instance est utilisé (serveur, expéditeur) ; le mot
  de passe de l'instance ne sort jamais de l'API ;
- les alertes de sécurité suivent la même règle.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.services import alertes, emailer
from app.services.emailer import EmailError, config_smtp, convocation_texte, envoyer_email
from tests.conftest import _make_membre, auth


class FauxSMTP:
    envois = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.login_ = host, port, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        self.login_ = (user, password)

    def send_message(self, msg):
        FauxSMTP.envois.append({"host": self.host, "port": self.port, "login": self.login_,
                                "de": msg["From"], "a": msg["To"]})


@pytest.fixture()
def smtp(monkeypatch):
    FauxSMTP.envois = []
    monkeypatch.setattr(emailer.smtplib, "SMTP", FauxSMTP)
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FauxSMTP)
    return FauxSMTP.envois


@pytest.fixture()
def instance(monkeypatch):
    s = get_settings()
    for cle, valeur in (("smtp_host", "smtp.instance.fr"), ("smtp_port", 587), ("smtp_user", "robot"),
                        ("smtp_password", "secret-instance"), ("email_expediteur", "noreply@instance.fr"),
                        ("frontend_url", "https://copro.instance.fr")):
        monkeypatch.setattr(s, cle, valeur)
    return s


def _copro_smtp(db, copro, **champs):
    for k, v in {"smtp_host": "smtp.copro.fr", "smtp_port": 465, "smtp_user": "syndic", "smtp_password": "secret-copro",
                 "email_expediteur": "syndic@copro.fr", **champs}.items():
        setattr(copro, k, v)
    db.commit()


def test_variables_d_environnement(monkeypatch):
    for cle, valeur in (("COPRO_SMTP_HOST", "smtp.env.fr"), ("COPRO_SMTP_PORT", "2525"), ("COPRO_SMTP_USER", "u"),
                        ("COPRO_SMTP_PASSWORD", "p"), ("COPRO_EMAIL_EXPEDITEUR", "e@env.fr"),
                        ("COPRO_FRONTEND_URL", "https://env.fr")):
        monkeypatch.setenv(cle, valeur)
    s = Settings(_env_file=None)
    assert (s.smtp_host, s.smtp_port, s.smtp_user, s.smtp_password, s.email_expediteur, s.frontend_url) == \
        ("smtp.env.fr", 2525, "u", "p", "e@env.fr", "https://env.fr")


def test_sans_aucun_reglage_l_envoi_est_refuse(db, copro_a, smtp):
    assert config_smtp(copro_a) is None
    with pytest.raises(EmailError, match="incomplète"):
        envoyer_email(copro_a, "a@test.fr", "s", "c")
    assert smtp == []


def test_copropriete_sans_serveur_utilise_l_instance(db, copro_a, smtp, instance):
    cfg = config_smtp(copro_a)
    assert (cfg.source, cfg.smtp_host, cfg.email_expediteur) == ("instance", "smtp.instance.fr", "noreply@instance.fr")
    envoyer_email(copro_a, "a@test.fr", "s", "c")
    assert smtp == [{"host": "smtp.instance.fr", "port": 587, "login": ("robot", "secret-instance"),
                     "de": "noreply@instance.fr", "a": "a@test.fr"}]


def test_copropriete_configuree_garde_ses_reglages(db, copro_a, smtp, instance):
    _copro_smtp(db, copro_a)
    assert config_smtp(copro_a).source == "copropriete"
    envoyer_email(copro_a, "a@test.fr", "s", "c")
    assert smtp == [{"host": "smtp.copro.fr", "port": 465, "login": ("syndic", "secret-copro"),
                     "de": "syndic@copro.fr", "a": "a@test.fr"}]


def test_jamais_de_melange(db, copro_a, smtp, instance):
    # Serveur saisi sans expéditeur : refus, on ne complète pas avec l'instance.
    _copro_smtp(db, copro_a, email_expediteur="")
    with pytest.raises(EmailError, match="incomplète"):
        envoyer_email(copro_a, "a@test.fr", "s", "c")
    # Expéditeur seul, sans serveur : c'est l'instance, en entier (son expéditeur à elle).
    _copro_smtp(db, copro_a, smtp_host="", email_expediteur="syndic@copro.fr")
    envoyer_email(copro_a, "a@test.fr", "s", "c")
    assert smtp == [{"host": "smtp.instance.fr", "port": 587, "login": ("robot", "secret-instance"),
                     "de": "noreply@instance.fr", "a": "a@test.fr"}]


def test_instance_incomplete_ne_sert_pas(db, copro_a, smtp, instance, monkeypatch):
    monkeypatch.setattr(instance, "email_expediteur", "")
    assert config_smtp(copro_a) is None


def _ag():
    return SimpleNamespace(type_ag="annuelle", date=date(2027, 3, 15), heure="18:00", lieu="Hall")


def test_adresse_publique_dans_la_convocation(db, copro_a, monkeypatch):
    # Rien de réglé : aucun lien, et surtout pas l'adresse de la démo.
    texte = convocation_texte(copro_a, _ag(), [], "Le syndic")
    assert "http" not in texte and "consulter les détails" not in texte
    monkeypatch.setattr(get_settings(), "frontend_url", "https://copro.instance.fr")
    texte = convocation_texte(copro_a, _ag(), [], "Le syndic")
    assert "consulter les détails" in texte and "https://copro.instance.fr" in texte
    copro_a.frontend_url = "https://ma-copro.fr"
    texte = convocation_texte(copro_a, _ag(), [], "Le syndic")
    assert "https://ma-copro.fr" in texte and "instance.fr" not in texte


def test_reglages_affiche_le_serveur_de_l_instance(client, db, copro_a, syndic_a, token_a, instance):
    r = client.get("/api/smtp/instance", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json() == {"configure": True, "utilise": True, "serveur": "smtp.instance.fr", "port": 587,
                        "expediteur": "noreply@instance.fr", "adresse_publique": "https://copro.instance.fr"}
    assert "secret-instance" not in r.text
    _copro_smtp(db, copro_a)
    assert client.get("/api/smtp/instance", headers=auth(token_a)).json()["utilise"] is False
    membre = create_access_token(_make_membre(db, "m@test.fr", copro_a).id, copro_a.id)
    assert client.get("/api/smtp/instance", headers=auth(membre)).status_code == 403


def test_reglages_sans_instance(client, db, copro_a, syndic_a, token_a):
    assert client.get("/api/smtp/instance", headers=auth(token_a)).json() == {
        "configure": False, "utilise": False, "serveur": "", "port": 587, "expediteur": "", "adresse_publique": ""}


def test_email_de_test_avec_le_serveur_de_l_instance(client, db, copro_a, syndic_a, token_a, smtp, instance):
    r = client.post("/api/smtp/test", json={}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and "instance" in r.json()["detail"]
    assert [(e["host"], e["a"]) for e in smtp] == [("smtp.instance.fr", "noreply@instance.fr")]


def test_email_de_test_sans_rien(client, db, copro_a, syndic_a, token_a, smtp):
    assert client.post("/api/smtp/test", json={}, headers=auth(token_a)).status_code == 400
    assert smtp == []


def test_alertes_de_securite_avec_l_instance(db, copro_a, syndic_a, instance):
    copro = alertes._copro_smtp(db, syndic_a)
    assert copro is not None and copro.id == copro_a.id
    cfg = alertes._cfg_smtp(copro)
    assert isinstance(cfg, SimpleNamespace)                        # rien de SQLAlchemy dans le thread
    assert (cfg.smtp_host, cfg.smtp_password, cfg.email_expediteur) == \
        ("smtp.instance.fr", "secret-instance", "noreply@instance.fr")


def test_alertes_de_securite_sans_rien(db, copro_a, syndic_a):
    assert alertes._copro_smtp(db, syndic_a) is None
