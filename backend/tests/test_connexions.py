"""Connexions : historique activable et blocage des comptes après des échecs (demande de Fred, 19/11/2026).

- par défaut, seules la dernière connexion et le dernier échec sont gardés, sur le compte ;
- historique activé (par copropriété) : connexions réussies, ratées et refusées dans le journal ;
- blocage (par copropriété, désactivé par défaut) : temporaire au seuil (5 → 15 min), définitif au
  seuil définitif (10) jusqu'au déblocage par un syndic ou l'administrateur de l'instance ;
- les comptes avec double authentification n'y sont soumis que si la copropriété le demande ;
  les comptes de démonstration jamais ; un compte de plusieurs copros suit la règle la plus stricte ;
- commande serveur de secours : python -m app.cli.debloquer.
"""
from datetime import datetime, timedelta

from alembic import command
from sqlalchemy import create_engine, text

from app import demarrage
from app.core.security import create_access_token
from app.models.audit import AuditLog
from app.models.user import UserCopro
from tests.conftest import _make_membre, _make_syndic, auth

_n = [0]


def _essai(client, email, mdp):
    """Une tentative depuis une IP différente à chaque fois : le limiteur par (e-mail, IP) n'intervient pas."""
    _n[0] += 1
    return client.post("/api/auth/login", json={"email": email, "password": mdp},
                       headers={"x-forwarded-for": f"203.0.113.{_n[0] % 250 + 1}"})


def _actions(db, user):
    db.expire_all()
    return [a.action for a in db.query(AuditLog).filter(AuditLog.user_id == user.id).order_by(AuditLog.id)]


def _regler(db, copro, **valeurs):
    for k, v in valeurs.items():
        setattr(copro, k, v)
    db.commit()


# ---------------------------------------------------------------- historique
def test_par_defaut_seulement_la_derniere_connexion(client, db, copro_a, syndic_a):
    membre = _make_membre(db, "m@test.fr", copro_a)
    assert _essai(client, "m@test.fr", "mauvais").status_code == 401
    assert _essai(client, "m@test.fr", "test1234").status_code == 200
    assert _actions(db, membre) == []                      # rien dans le journal
    db.refresh(membre)
    assert membre.last_login_at and membre.dernier_echec_at and membre.echecs_connexion == 0
    r = client.get("/api/auth/me/connexions", headers=auth(create_access_token(membre.id, copro_a.id)))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["historique"] is False and j["entrees"] == []
    assert j["derniere_connexion"] and j["dernier_echec"] and j["bloque"] == ""


def test_adresse_inconnue_rien_n_est_garde(client, db, copro_a, syndic_a):
    _regler(db, copro_a, connexions_historique=True)
    assert _essai(client, "personne@test.fr", "x").status_code == 401
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "login_failed").count() == 0


def test_historique_active(client, db, copro_a, syndic_a):
    _regler(db, copro_a, connexions_historique=True)
    membre = _make_membre(db, "m@test.fr", copro_a)
    _essai(client, "m@test.fr", "mauvais")
    _essai(client, "m@test.fr", "test1234")
    assert _actions(db, membre) == ["login_failed", "login"]
    r = client.get(f"/api/auth/users/{membre.id}/connexions",
                   headers=auth(create_access_token(syndic_a.id, copro_a.id)))
    assert r.status_code == 200, r.text
    entrees = r.json()["entrees"]
    assert [e["action"] for e in entrees] == ["login", "login_failed"]       # le plus récent d'abord
    assert entrees[1]["detail"] == "mot de passe incorrect" and entrees[0]["ip"].startswith("203.0.113.")


# ---------------------------------------------------------------- blocage
def test_blocage_temporaire(client, db, copro_a, syndic_a):
    _regler(db, copro_a, verrouillage_actif=True, verrouillage_seuil=3, verrouillage_minutes=15,
            verrouillage_seuil_definitif=0)
    membre = _make_membre(db, "m@test.fr", copro_a)
    for _ in range(3):
        assert _essai(client, "m@test.fr", "mauvais").status_code == 401
    r = _essai(client, "m@test.fr", "test1234")                  # bon mot de passe : refusé quand même
    assert r.status_code == 423 and "réessayez après" in r.json()["detail"]
    assert "account_locked" in _actions(db, membre)              # toujours journalisé
    db.refresh(membre)
    assert membre.bloque == "temporaire"
    membre.bloque_jusqua = datetime.now() - timedelta(minutes=1)   # 15 minutes plus tard
    db.commit()
    assert _essai(client, "m@test.fr", "test1234").status_code == 200
    db.refresh(membre)
    assert membre.echecs_connexion == 0 and membre.bloque == ""


def test_blocage_definitif_puis_deblocage_par_le_syndic(client, db, copro_a, syndic_a):
    _regler(db, copro_a, verrouillage_actif=True, verrouillage_seuil=2, verrouillage_seuil_definitif=4)
    membre = _make_membre(db, "m@test.fr", copro_a)
    for _ in range(2):
        _essai(client, "m@test.fr", "mauvais")
    membre.bloque_jusqua = None                                    # attente du blocage temporaire
    db.commit()
    for _ in range(2):
        _essai(client, "m@test.fr", "mauvais")
    db.refresh(membre)
    assert membre.bloque == "definitif" and membre.echecs_connexion == 4
    r = _essai(client, "m@test.fr", "test1234")
    assert r.status_code == 423 and "débloquer" in r.json()["detail"]
    tok = create_access_token(syndic_a.id, copro_a.id)
    liste = client.get("/api/auth/users", headers=auth(tok)).json()
    assert next(u for u in liste if u["id"] == membre.id)["bloque"] == "definitif"
    r = client.post(f"/api/auth/users/{membre.id}/debloquer", headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["bloque"] == ""
    assert _essai(client, "m@test.fr", "test1234").status_code == 200
    db.expire_all()
    debloque = db.query(AuditLog).filter(AuditLog.action == "account_unlocked").one()
    assert debloque.user_id == membre.id and "syndic.a@test.fr" in debloque.detail


def test_comptes_avec_2fa_exemptes_sauf_si_demande(client, db, copro_a, syndic_a):
    _regler(db, copro_a, verrouillage_actif=True, verrouillage_seuil=2, verrouillage_seuil_definitif=0)
    membre = _make_membre(db, "m@test.fr", copro_a)
    membre.totp_enabled = True
    db.commit()
    for _ in range(4):
        _essai(client, "m@test.fr", "mauvais")
    db.refresh(membre)
    assert membre.bloque == "" and membre.echecs_connexion == 4      # compté, mais pas bloqué
    _regler(db, copro_a, verrouillage_avec_2fa=True)
    _essai(client, "m@test.fr", "mauvais")
    _essai(client, "m@test.fr", "mauvais")
    db.refresh(membre)
    assert membre.bloque == "temporaire"


def test_compte_de_demonstration_jamais_bloque(client, db, copro_a, syndic_a):
    _regler(db, copro_a, verrouillage_actif=True, verrouillage_seuil=1, verrouillage_seuil_definitif=2)
    demo = _make_membre(db, "demo@test.fr", copro_a)
    demo.is_demo = True
    db.commit()
    for _ in range(3):
        _essai(client, "demo@test.fr", "mauvais")
    assert _essai(client, "demo@test.fr", "test1234").status_code == 200


def test_regle_la_plus_stricte(client, db, copro_a, copro_b, syndic_a):
    _regler(db, copro_a, verrouillage_actif=True, verrouillage_seuil=5, verrouillage_seuil_definitif=0)
    _regler(db, copro_b, verrouillage_actif=True, verrouillage_seuil=2, verrouillage_seuil_definitif=0)
    membre = _make_membre(db, "m@test.fr", copro_a)
    db.add(UserCopro(user_id=membre.id, copropriete_id=copro_b.id, principale=False))
    db.commit()
    _essai(client, "m@test.fr", "mauvais")
    _essai(client, "m@test.fr", "mauvais")
    db.refresh(membre)
    assert membre.bloque == "temporaire"


# ---------------------------------------------------------------- droits
def test_droits(client, db, copro_a, copro_b, syndic_a, syndic_b):
    membre = _make_membre(db, "m@test.fr", copro_a)
    membre.bloque_definitif_le = datetime.now()
    db.commit()
    tok_membre = create_access_token(membre.id, copro_a.id)
    autre = _make_membre(db, "autre@test.fr", copro_a)
    assert client.get(f"/api/auth/users/{autre.id}/connexions", headers=auth(tok_membre)).status_code == 403
    tok_b = create_access_token(syndic_b.id, copro_b.id)
    assert client.post(f"/api/auth/users/{membre.id}/debloquer", headers=auth(tok_b)).status_code == 404
    assert client.get("/api/admin/comptes-bloques", headers=auth(tok_b)).status_code == 403
    syndic_b.is_instance_admin = True                               # administrateur de l'instance
    db.commit()
    bloques = client.get("/api/admin/comptes-bloques", headers=auth(tok_b))
    assert bloques.status_code == 200, bloques.text
    assert [(c["email"], c["bloque"], c["coproprietes"]) for c in bloques.json()] == \
        [("m@test.fr", "definitif", [copro_a.nom])]
    assert client.post(f"/api/auth/users/{membre.id}/debloquer", headers=auth(tok_b)).status_code == 200
    assert client.get("/api/admin/comptes-bloques", headers=auth(tok_b)).json() == []


def test_reglages_valides(client, db, copro_a, syndic_a):
    tok = create_access_token(syndic_a.id, copro_a.id)
    r = client.put("/api/copro", json={"verrouillage_seuil": 0}, headers=auth(tok))
    assert r.status_code == 422
    r = client.put("/api/copro", json={"connexions_historique": True, "verrouillage_actif": True,
                                       "verrouillage_seuil": 5, "verrouillage_minutes": 15,
                                       "verrouillage_seuil_definitif": 0, "verrouillage_avec_2fa": False},
                   headers=auth(tok))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["connexions_historique"] and j["verrouillage_actif"] and j["verrouillage_seuil_definitif"] == 0


# ---------------------------------------------------------------- commande serveur, migration
def test_commande_de_deblocage(db, copro_a, capsys):
    from app.cli import debloquer
    syndic = _make_syndic(db, "seul.admin@test.fr", copro_a)
    syndic.bloque_definitif_le = datetime.now()
    syndic.echecs_connexion = 10
    db.commit()
    assert debloquer.main(["--liste"], session=db) == 0
    assert "seul.admin@test.fr : bloqué jusqu'au déblocage" in capsys.readouterr().out
    assert debloquer.main(["Seul.Admin@test.fr"], session=db) == 0
    db.refresh(syndic)
    assert syndic.bloque == "" and syndic.echecs_connexion == 0
    assert "account_unlocked" in _actions(db, syndic)
    assert debloquer.main(["inconnu@test.fr"], session=db) == 1


def test_migration_les_copros_existantes_gardent_l_historique(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = demarrage.config_alembic(url)
    command.upgrade(cfg, "b8c9d0e1f2a3")
    with create_engine(url).begin() as c:
        c.execute(text("insert into coproprietes (id, nom) values (1, 'R')"))
        c.execute(text("insert into users (id, email, password_hash, nom, role) "
                       "values (1, 'syndic@exemple.fr', 'h', 'Syndic', 'syndic')"))
    command.upgrade(cfg, "head")
    with create_engine(url).connect() as c:
        assert c.execute(text("select connexions_historique, verrouillage_actif, verrouillage_seuil, "
                              "verrouillage_minutes, verrouillage_seuil_definitif from coproprietes")).one() \
            == (1, 0, 5, 15, 10)
        assert c.execute(text("select echecs_connexion, bloque_definitif_le from users")).one() == (0, None)
    command.downgrade(cfg, "b8c9d0e1f2a3")
    command.upgrade(cfg, "head")
