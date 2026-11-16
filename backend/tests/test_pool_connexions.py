"""Pool de connexions à la base réglable (issue #66, zorglube).

Constat : pas de fuite (chaque session est fermée en fin de requête), mais le pool SQLAlchemy restait
aux valeurs par défaut (5 + 10 en dépassement = 15 connexions), au-delà de la limite des petites bases
(offres de dev des hébergeurs).

Règles retenues :
- PostgreSQL : COPRO_DB_POOL_SIZE (5), COPRO_DB_MAX_OVERFLOW (5), COPRO_DB_POOL_TIMEOUT (30 s),
  COPRO_DB_POOL_RECYCLE (1800 s) ; pre_ping toujours actif (connexion coupée par l'hébergeur rejetée) ;
- COPRO_DB_POOL_SIZE=0 : aucun pool, une connexion ouverte puis fermée par requête (NullPool) ;
- valeurs négatives refusées au démarrage ; SQLite : aucun réglage de pool.
"""
import pytest
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import options_moteur

PG = "postgresql://u:p@h/db"


def test_valeurs_par_defaut_postgresql():
    o = options_moteur(Settings(database_url=PG))
    assert o == {"pool_size": 5, "max_overflow": 5, "pool_timeout": 30, "pool_recycle": 1800, "pool_pre_ping": True}


def test_valeurs_reglees():
    o = options_moteur(Settings(database_url=PG, db_pool_size=2, db_max_overflow=0, db_pool_timeout=10,
                                db_pool_recycle=300))
    assert (o["pool_size"], o["max_overflow"], o["pool_timeout"], o["pool_recycle"]) == (2, 0, 10, 300)


def test_sans_pool():
    o = options_moteur(Settings(database_url=PG, db_pool_size=0))
    assert o == {"poolclass": NullPool, "pool_pre_ping": True}


def test_sqlite_sans_reglage_de_pool():
    assert options_moteur(Settings(database_url="sqlite:///./x.db")) == {
        "connect_args": {"check_same_thread": False}}


def test_valeur_negative_refusee():
    with pytest.raises(ValueError):
        Settings(database_url=PG, db_max_overflow=-1)


def test_variables_d_environnement(monkeypatch):
    monkeypatch.setenv("COPRO_DB_POOL_SIZE", "3")
    monkeypatch.setenv("COPRO_DB_MAX_OVERFLOW", "1")
    s = Settings(database_url=PG)
    assert (s.db_pool_size, s.db_max_overflow) == (3, 1)
