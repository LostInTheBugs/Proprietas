from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Proprietas"
    database_url: str = "sqlite:///./copro.db"
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 30
    upload_dir: str = "./uploads"
    upload_max_mb: float = 25.0
    frontend_dist: str = ""
    # Origines CORS autorisées (JSON dans l'environnement, ex. '["https://app.example.fr"]').
    # Vide en production : le frontend est servi par le même backend, le CORS ne sert à rien.
    cors_origins: list[str] = []
    # Politique 2FA (TOTP) appliquée par défaut aux NOUVELLES copropriétés :
    # « off » | « syndic » (le syndic doit activer la double authentification) | « all ».
    # Défaut pensé pour une instance exposée sur internet ; l'app desktop la passe à « off ».
    totp_default_policy: str = "syndic"
    # ---- Mises à jour (voir app/services/updates.py et deploy/apply-update.py) ----
    # Comptes autorisés à piloter les mises à jour de l'INSTANCE (e-mails séparés par
    # des virgules). Vide = personne : le panneau reste en lecture seule. Le compte de
    # démonstration public ne doit jamais y figurer.
    instance_admins: str = ""
    # Dossier partagé avec l'applicateur de l'hôte (bind mount ./data/updates).
    update_dir: str = "./data/updates"
    update_repo: str = "LostInTheBugs/Proprietas"
    # « server » : l'applicateur de l'hôte peut appliquer ; « desktop » : notification seule.
    update_mode: str = "server"
    model_config = {"env_prefix": "COPRO_", "env_file": ".env"}

    @property
    def instance_admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.instance_admins.split(",") if e.strip()}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Garde-fou : ne jamais signer les JWT avec la clé publique par défaut hors dev SQLite.
    if s.secret_key == "change-me" and not s.is_sqlite:
        raise RuntimeError(
            "COPRO_SECRET_KEY n'est pas définie (valeur par défaut 'change-me'). "
            "Définissez la variable d'environnement COPRO_SECRET_KEY avec une clé "
            "aléatoire avant de démarrer sur une base non-SQLite."
        )
    return s
