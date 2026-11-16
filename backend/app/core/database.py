from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import get_settings

settings = get_settings()


def options_moteur(s) -> dict:
    """Options de create_engine. PostgreSQL : pool réglable (COPRO_DB_POOL_SIZE, COPRO_DB_MAX_OVERFLOW,
    COPRO_DB_POOL_TIMEOUT, COPRO_DB_POOL_RECYCLE) pour rester sous la limite de connexions de la base ;
    pre_ping : une connexion coupée par l'hébergeur est détectée et remplacée."""
    if s.database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    if s.db_pool_size == 0:
        return {"poolclass": NullPool, "pool_pre_ping": True}
    return {"pool_size": s.db_pool_size, "max_overflow": s.db_max_overflow, "pool_timeout": s.db_pool_timeout,
            "pool_recycle": s.db_pool_recycle, "pool_pre_ping": True}


engine = create_engine(settings.database_url, **options_moteur(settings))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# NOTE — migrations :
# Le schéma est géré par Alembic (backend/alembic/, commande `alembic upgrade head`).
# L'ancien init_db() (create_all + _MIGRATIONS) a été supprimé : ne jamais
# recréer de create_all au démarrage — voir README (section Déploiement).
