from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Proprietas"
    database_url: str = "sqlite:///./copro.db"
    # Pool de connexions PostgreSQL (issue #66) : à régler sous la limite de connexions de la base
    # (petites offres d'hébergeur). db_pool_size = 0 : aucun pool, une connexion par requête.
    db_pool_size: int = Field(5, ge=0)          # connexions gardées ouvertes
    db_max_overflow: int = Field(5, ge=0)       # connexions en plus, aux pointes
    db_pool_timeout: int = Field(30, ge=1)      # secondes d'attente d'une connexion libre
    db_pool_recycle: int = Field(1800, ge=-1)   # secondes avant de renouveler une connexion (-1 : jamais)
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 30
    upload_dir: str = "./uploads"
    upload_max_mb: float = 25.0
    # Taille maximale d'une sauvegarde de copropriété importée (archive ZIP, documents compris).
    import_max_mb: float = 500.0
    # Taille maximale de cette archive une fois DÉCOMPRESSÉE (données + fichiers) : une archive très
    # compressible ne doit pas remplir la mémoire ni le disque.
    import_max_decompresse_mb: float = Field(2000.0, gt=0)
    # Envoi des e-mails : réglages de l'INSTANCE (PR #70). Utilisés par les copropriétés qui n'ont pas
    # saisi leur propre serveur dans Réglages → E-mails et relances (jamais de mélange : une
    # copropriété qui a un serveur utilise ses réglages en entier). Voir services/emailer.config_smtp.
    smtp_host: str = ""
    smtp_port: int = Field(587, ge=0)
    smtp_user: str = ""
    smtp_password: str = ""
    email_expediteur: str = ""
    # Adresse publique de l'instance, citée dans les e-mails quand la copropriété n'a pas la sienne.
    frontend_url: str = ""
    # Réunion en ligne : serveur Jitsi des liens créés par l'application (COPRO_JITSI_URL).
    jitsi_url: str = "https://meet.jit.si"
    # Supervision externe : jeton de GET /api/metrics (format Prometheus) ; vide = désactivé.
    metrics_token: str = ""
    # Journaux : « texte » (défaut) ou « json » (une ligne JSON par message et par requête, pour Loki…).
    log_format: str = "texte"
    # Stockage des documents : « local » (dossier upload_dir) ou « s3 » (bucket compatible S3 :
    # AWS, Clever Cloud Cellar, OVH, Scaleway, MinIO…). Voir app/core/stockage.py.
    stockage: str = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""          # vide = AWS ; sinon https://cellar-c2.services.clever-cloud.com, etc.
    s3_region: str = ""
    s3_access_key_id: str = ""         # vides : variables AWS_* / rôle (chaîne standard boto3)
    s3_secret_access_key: str = ""
    s3_prefix: str = "documents/"
    # Drive des copropriétés (WebDAV : Nextcloud, ownCloud, Synology… ; core/drive.py).
    # drive_actif=false : la fonction est retirée de l'instance. drive_reseau_local=false : refuse
    # les adresses du réseau privé (à régler ainsi sur une instance hébergée pour des tiers).
    drive_actif: bool = True
    drive_reseau_local: bool = True
    # Dépôts mis en attente quand le drive d'une copropriété est injoignable : le fichier est gardé sur
    # le serveur (« en attente du drive ») et rangé sur le drive dès son retour. Plafond en Mo pour toute
    # l'instance (fichiers en attente de toutes les copropriétés) ; 50 par défaut ; 0 = désactivé : le dépôt
    # est refusé (serveurs avec peu d'espace).
    drive_attente_mo: float = Field(50, ge=0)
    # Google Drive comme drive d'une copropriété (core/drive_google.py) : application OAuth « Web »
    # déclarée dans la console Google Cloud, portée drive.file, adresse de retour
    # <adresse de l'instance>/api/drive/google/retour. Ici : l'application de toute l'instance (facultatif) ;
    # une copropriété peut saisir la sienne dans Réglages → Drive, qui passe avant (core/drive.py).
    google_client_id: str = ""
    google_client_secret: str = ""
    # RGPD : durée de conservation du journal d'audit et des infos de dernière connexion
    # (IP, navigateur), en mois. 0 = jamais purgé. CNIL : 6 mois à 1 an pour la journalisation.
    retention_journal_mois: int = 12
    frontend_dist: str = ""
    # Origines CORS autorisées (JSON dans l'environnement, ex. '["https://app.example.fr"]').
    # Vide en production : le frontend est servi par le même backend, le CORS ne sert à rien.
    cors_origins: list[str] = []
    # Politique 2FA (TOTP) appliquée par défaut aux NOUVELLES copropriétés :
    # « off » | « syndic » (le syndic doit activer la double authentification) | « all ».
    # Défaut pensé pour une instance exposée sur internet ; l'app desktop la passe à « off ».
    totp_default_policy: str = "syndic"
    # ---- Mises à jour (voir app/services/updates.py et deploy/apply-update.py) ----
    # Les administrateurs de l'instance se gèrent dans l'application (users.is_instance_admin).
    # Dossier partagé avec l'applicateur de l'hôte (bind mount ./data/updates).
    update_dir: str = "./data/updates"
    update_repo: str = "LostInTheBugs/Proprietas"
    # « server » : l'applicateur de l'hôte peut appliquer ; « desktop » : notification seule.
    update_mode: str = "server"
    # extra=ignore : une ancienne variable restée dans un .env (ex. COPRO_INSTANCE_ADMINS)
    # ne doit pas empêcher l'application de démarrer.
    model_config = {"env_prefix": "COPRO_", "env_file": ".env", "extra": "ignore"}

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
    if s.stockage not in ("local", "s3"):
        raise RuntimeError(f"COPRO_STOCKAGE invalide : « {s.stockage} » (attendu : local ou s3).")
    if s.stockage == "s3" and not s.s3_bucket:
        raise RuntimeError("COPRO_STOCKAGE=s3 exige COPRO_S3_BUCKET (nom du bucket).")
    return s
