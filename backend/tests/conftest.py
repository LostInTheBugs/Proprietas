"""Fixtures pytest partagées : FastAPI TestClient + SQLite en mémoire.

Les variables d'environnement sont posées AVANT l'import des modules de
l'application : `app.core.config` (caché par lru_cache) et le moteur global
de `app.core.database` sont créés à l'import.
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Base de données et uploads jetables pour toute la session de tests.
os.environ["COPRO_DATABASE_URL"] = "sqlite://"
os.environ["COPRO_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="copro-tests-uploads-")
# Les tests contrôlent explicitement la politique 2FA de chaque copro : pas de
# 2FA imposée par défaut (les tests dédiés activent la politique qu'ils testent).
os.environ["COPRO_TOTP_DEFAULT_POLICY"] = "off"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.copropriete import Copropriete  # noqa: E402
from app.models.user import User, UserCopro  # noqa: E402

from app import models  # noqa: E402, F401 — enregistre tous les modèles sur Base.metadata


@pytest.fixture()
def db_engine():
    """Moteur SQLite en mémoire, recréé à chaque test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db(db_engine):
    """Session SQLAlchemy directe pour préparer les données de test."""
    session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine):
    """TestClient FastAPI branché sur la base SQLite en mémoire.

    Pas de `with` : le lifespan (init_db, scheduler) n'est pas exécuté.
    """
    TestingSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        test_db = TestingSession()
        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_syndic(db, email: str, copro: Copropriete) -> User:
    """Crée un syndic lié à la copropriété donnée (liaison principale)."""
    user = User(
        email=email,
        password_hash=hash_password("test1234"),
        nom=f"Syndic {email}",
        role="syndic",
        copropriete_id=copro.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserCopro(user_id=user.id, copropriete_id=copro.id, principale=True))
    db.commit()
    return user


def _make_membre(db, email: str, copro: Copropriete) -> User:
    """Crée un compte membre (lecture seule) lié à la copropriété donnée."""
    user = User(
        email=email,
        password_hash=hash_password("test1234"),
        nom=f"Membre {email}",
        role="membre",
        copropriete_id=copro.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserCopro(user_id=user.id, copropriete_id=copro.id, principale=True))
    db.commit()
    return user


@pytest.fixture()
def copro_a(db):
    c = Copropriete(nom="Résidence A")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def copro_b(db):
    c = Copropriete(nom="Résidence B")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def syndic_a(db, copro_a):
    return _make_syndic(db, "syndic.a@test.fr", copro_a)


@pytest.fixture()
def syndic_b(db, copro_b):
    return _make_syndic(db, "syndic.b@test.fr", copro_b)


@pytest.fixture()
def token_a(syndic_a, copro_a):
    from app.core.security import create_access_token
    return create_access_token(syndic_a.id, copro_a.id)


@pytest.fixture()
def token_b(syndic_b, copro_b):
    from app.core.security import create_access_token
    return create_access_token(syndic_b.id, copro_b.id)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
