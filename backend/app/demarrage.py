"""Démarrage du conteneur : migrations de la base, puis l'application (issue #79).

`python -m app.demarrage` remplace `alembic upgrade head && uvicorn …` :

- pendant la migration, un petit serveur répond sur le port de l'application : `/api/health`
  renvoie 200 (`"phase": "migration"`), le reste 503 avec `Retry-After`. Un orchestrateur voit
  l'application vivante ; `/api/version` ne répond pas, donc l'applicateur de mise à jour attend
  toujours la vraie nouvelle version ;
- journal daté : révision actuelle → cible et nombre d'étapes, chaque étape avec sa durée, un
  battement toutes les 15 s, et sur PostgreSQL la connexion qui bloque la migration quand elle
  attend un verrou (cas typique : l'ancienne version encore branchée sur la même base) ;
- une fois la base à jour, le processus est remplacé par uvicorn (même PID, signaux inchangés).

Réglages : PROPRIETAS_HOTE (0.0.0.0), PROPRIETAS_PORT (8000), PROPRIETAS_MIGRATION_BATTEMENT_S (15).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("proprietas.demarrage")
RACINE = Path(__file__).resolve().parent.parent          # dossier qui contient alembic.ini
NOM_CONNEXION = "proprietas-migration"                   # application_name PostgreSQL de la migration


class Etat:
    def __init__(self) -> None:
        self.debut = time.monotonic()
        self.etape = ""                                  # « a -> b, message » (ligne d'Alembic en cours)
        self.debut_etape = self.debut

    def depuis(self) -> int:
        return int(time.monotonic() - self.debut)


ETAT = Etat()


# ---------------------------------------------------------------- serveur pendant la migration
class _Pendant(BaseHTTPRequestHandler):
    def _repondre(self, corps: bool) -> None:
        if self.path.split("?", 1)[0] == "/api/health":
            code, donnees = 200, {"status": "ok", "phase": "migration", "depuis_s": ETAT.depuis(), "etape": ETAT.etape}
        else:
            code, donnees = 503, {"detail": "Mise à jour de la base de données en cours : réessayez dans quelques instants."}
        brut = json.dumps(donnees, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(brut)))
        self.send_header("Cache-Control", "no-store")
        if code == 503:
            self.send_header("Retry-After", "10")
        self.end_headers()
        if corps:
            self.wfile.write(brut)

    def do_GET(self):  # noqa: N802
        self._repondre(True)

    def do_HEAD(self):  # noqa: N802
        self._repondre(False)

    def do_POST(self):  # noqa: N802
        self._repondre(True)

    def log_message(self, *args) -> None:          # pas une ligne par sonde de santé
        pass


def serveur_pendant(hote: str, port: int) -> ThreadingHTTPServer | None:
    try:
        serveur = ThreadingHTTPServer((hote, port), _Pendant)
    except OSError as e:
        log.warning("Port %s:%s indisponible pendant la migration (%s) : pas de health-check d'attente.", hote, port, e)
        return None
    serveur.daemon_threads = True
    threading.Thread(target=serveur.serve_forever, name="sante-migration", daemon=True).start()
    return serveur


# ---------------------------------------------------------------- Alembic
def config_alembic(url: str | None = None):
    from alembic.config import Config
    cfg = Config(str(RACINE / "alembic.ini"))
    cfg.set_main_option("script_location", str(RACINE / "alembic"))
    cfg.attributes["configure_logger"] = False      # le journal est réglé ici (heures comprises)
    if url:
        cfg.attributes["url"] = url
    return cfg


def _url(cfg) -> str:
    from app.core.config import get_settings
    return cfg.attributes.get("url") or get_settings().database_url


def revisions(cfg) -> tuple[str | None, str | None, list[str]]:
    """(révision actuelle de la base, révision cible, étapes à appliquer dans l'ordre)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    script = ScriptDirectory.from_config(cfg)
    cible = script.get_current_head()
    moteur = create_engine(_url(cfg), poolclass=NullPool)
    try:
        with moteur.connect() as c:
            actuelle = MigrationContext.configure(c).get_current_revision()
    finally:
        moteur.dispose()
    if actuelle == cible:
        return actuelle, cible, []
    etapes = [r.revision for r in script.iterate_revisions(cible, actuelle or "base")]
    return actuelle, cible, list(reversed(etapes))


class _SuiviEtapes(logging.Filter):
    """Repère les lignes « Running upgrade a -> b » d'Alembic : étape en cours et durée de la précédente."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if message.startswith("Running upgrade "):
            maintenant = time.monotonic()
            if ETAT.etape:
                log.info("Étape terminée en %.1f s : %s", maintenant - ETAT.debut_etape, ETAT.etape)
            ETAT.etape, ETAT.debut_etape = message.removeprefix("Running upgrade "), maintenant
        return True


def decrire_blocage(lignes: list[dict]) -> str:
    """Texte lisible des connexions qui bloquent la migration (lignes de pg_stat_activity)."""
    morceaux = []
    for b in lignes:
        requete = " ".join((b.get("requete") or "").split())[:120]
        morceaux.append(f"pid {b.get('pid')} ({b.get('app') or 'sans nom'}, {b.get('etat') or '?'} depuis "
                        f"{b.get('depuis') if b.get('depuis') is not None else '?'} s) : {requete or '—'}")
    return " ; ".join(morceaux)


SQL_ATTENTE = """
SELECT a.wait_event_type AS attente,
       (SELECT json_agg(json_build_object(
            'pid', b.pid, 'app', b.application_name, 'etat', b.state, 'requete', b.query,
            'depuis', extract(epoch FROM now() - coalesce(b.xact_start, b.query_start))::int))
          FROM pg_stat_activity b WHERE b.pid = ANY(pg_blocking_pids(a.pid))) AS bloqueurs
  FROM pg_stat_activity a
 WHERE a.application_name = :nom
"""


def _blocage(url: str) -> str:
    """Sur PostgreSQL : qui empêche la migration d'avancer (vide si elle n'attend pas de verrou)."""
    if not url.startswith("postgresql"):
        return ""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    moteur = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with moteur.connect() as c:
            for ligne in c.execute(text(SQL_ATTENTE), {"nom": NOM_CONNEXION}).mappings():
                bloqueurs = ligne["bloqueurs"] or []
                if isinstance(bloqueurs, str):
                    bloqueurs = json.loads(bloqueurs)
                if bloqueurs:
                    return decrire_blocage(bloqueurs)
    except Exception as e:  # noqa: BLE001 — le diagnostic ne doit jamais gêner la migration
        return f"(diagnostic des verrous impossible : {type(e).__name__})"
    finally:
        moteur.dispose()
    return ""


def _battement(url: str, fin: threading.Event, periode: int) -> None:
    while not fin.wait(periode):
        message = f"Migration en cours depuis {ETAT.depuis()} s" + (f" — étape {ETAT.etape}" if ETAT.etape else "")
        bloque = _blocage(url)
        if bloque:
            message += f". Elle attend un verrou tenu par : {bloque}"
        log.info(message)


def migrer(cfg, periode: int = 15) -> None:
    from alembic import command
    actuelle, cible, etapes = revisions(cfg)
    if not etapes:
        log.info("Base à jour (révision %s) : aucune migration.", actuelle)
        return
    log.info("Migration de la base : révision %s → %s, %d étape(s).", actuelle or "vide", cible, len(etapes))
    ETAT.etape = ""
    suivi = _SuiviEtapes()
    logging.getLogger("alembic.runtime.migration").addFilter(suivi)
    fin = threading.Event()
    threading.Thread(target=_battement, args=(_url(cfg), fin, periode), name="battement-migration", daemon=True).start()
    try:
        command.upgrade(cfg, "head")
    finally:
        fin.set()
        logging.getLogger("alembic.runtime.migration").removeFilter(suivi)
    if ETAT.etape:
        log.info("Étape terminée en %.1f s : %s", time.monotonic() - ETAT.debut_etape, ETAT.etape)
    log.info("Migration terminée en %d s.", ETAT.depuis())


def configurer_journal() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True,
                        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def main(executer=os.execvp) -> int:
    configurer_journal()
    hote = os.environ.get("PROPRIETAS_HOTE", "0.0.0.0")
    port = int(os.environ.get("PROPRIETAS_PORT", "8000"))
    periode = int(os.environ.get("PROPRIETAS_MIGRATION_BATTEMENT_S", "15"))
    serveur = serveur_pendant(hote, port)
    try:
        migrer(config_alembic(), periode)
    except Exception:
        log.exception("Migration ÉCHOUÉE après %d s : l'application ne démarre pas.", ETAT.depuis())
        return 1
    finally:
        if serveur:
            serveur.shutdown()
            serveur.server_close()
    log.info("Lancement de l'application sur %s:%s.", hote, port)
    executer("uvicorn", ["uvicorn", "app.main:app", "--host", hote, "--port", str(port)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
