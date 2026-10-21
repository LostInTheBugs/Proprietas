#!/usr/bin/env python3
"""Proprietas — applicateur de mise à jour (côté hôte, lancé par proprietas-update.timer).

L'application ne fait que DÉPOSER une demande dans `data/updates/update-request.json`
(son conteneur n'a ni socket Docker ni privilèges : choix de sécurité). Ce script :

  1. valide la version demandée (format AAAA.MM.NNN[-cX], tag existant) ;
  2. SAUVEGARDE la base PostgreSQL (`pg_dump`) dans `data/backups/` (10 dernières gardées) ;
  3. met le dépôt sur le tag demandé (`git fetch --tags` + `git checkout <tag>`, en tant
     que propriétaire du dépôt) ;
  4. reconstruit et relance (`docker compose up -d --build` ; les migrations Alembic
     s'appliquent au démarrage du conteneur) ;
  5. attend que l'API réponde avec la NOUVELLE version, sinon signale l'échec
     (la sauvegarde indiquée permet de revenir en arrière à la main).

    sudo python3 deploy/apply-update.py            # applique la demande en attente
    sudo python3 deploy/apply-update.py --dry-run  # montre ce qui serait fait, ne change rien

Écrit `data/updates/update-applier.json` (battement de cœur + résultat, lu par le site)
et journalise dans `data/updates/update.log`.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
UPD = APP_DIR / "data" / "updates"
BACKUPS = APP_DIR / "data" / "backups"
REQ = UPD / "update-request.json"
STATUS = UPD / "update-applier.json"
LOG = UPD / "update.log"
VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{3}(?:-c\d+)?$")
KEEP_BACKUPS = 10
HEALTH_TIMEOUT_S = 180
DRY = "--dry-run" in sys.argv


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def status(**updates) -> None:
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["seen_at"] = time.time()
    data.update(updates)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS)


def run(cmd: list[str], as_owner: bool = False, capture: bool = False) -> str:
    """Exécute une commande dans APP_DIR. `as_owner` : en tant que propriétaire du dépôt
    (évite l'erreur git « dubious ownership » et des fichiers .git appartenant à root)."""
    if as_owner and os.geteuid() == 0:
        owner = pwd.getpwuid(APP_DIR.stat().st_uid).pw_name
        if owner != "root":
            cmd = ["runuser", "-u", owner, "--"] + cmd
    log("exécute : " + " ".join(cmd))
    if DRY and not capture:
        return ""
    res = subprocess.run(cmd, cwd=APP_DIR, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} — code {res.returncode} : {(res.stderr or res.stdout).strip()[-400:]}")
    return res.stdout


def backup() -> str:
    """pg_dump de la base dans data/backups ; garde les KEEP_BACKUPS plus récentes."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    target = BACKUPS / f"proprietas-{time.strftime('%Y%m%d-%H%M%S')}.sql"
    log(f"sauvegarde → {target}")
    if DRY:
        return str(target)
    with target.open("w", encoding="utf-8") as fh:
        res = subprocess.run(["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", "copro", "copro"],
                             cwd=APP_DIR, stdout=fh, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0 or target.stat().st_size < 1024:
        raise RuntimeError(f"sauvegarde impossible ou vide : {res.stderr.strip()[-300:]}")
    for old in sorted(BACKUPS.glob("proprietas-*.sql"))[:-KEEP_BACKUPS]:
        old.unlink()
    return str(target)


def wait_version(version: str) -> None:
    """Attend que l'API du conteneur réponde avec la version demandée."""
    if DRY:
        return
    probe = ("import json,urllib.request;"
             "print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/version'))['version'])")
    deadline = time.time() + HEALTH_TIMEOUT_S
    last = ""
    while time.time() < deadline:
        res = subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c", probe],
                             cwd=APP_DIR, capture_output=True, text=True)
        last = (res.stdout or res.stderr).strip()[-200:]
        if res.returncode == 0 and last == version:
            return
        time.sleep(5)
    raise RuntimeError(f"l'API ne répond pas en {version} après {HEALTH_TIMEOUT_S} s (dernière réponse : {last!r})")


def main() -> int:
    UPD.mkdir(parents=True, exist_ok=True)
    if not REQ.exists():
        status()                      # simple battement de cœur : le site sait que l'applicateur tourne
        return 0
    try:
        payload = json.loads(REQ.read_text(encoding="utf-8"))
        version = str(payload.get("version") or "").strip()
        by = str(payload.get("by") or "?")
    except (OSError, ValueError) as exc:
        log(f"demande illisible : {exc}")
        REQ.unlink(missing_ok=True)
        status(result="demande illisible")
        return 1
    if not VERSION_RE.match(version):
        log(f"version refusée : {version!r}")
        REQ.unlink(missing_ok=True)
        status(result=f"version refusée : {version}"[:300])
        return 1
    log(f"demande de {by} : mise à jour vers {version}{' (dry-run)' if DRY else ''}")
    status(result="en cours", running=version, running_at=time.time())
    dump = ""
    try:
        run(["git", "fetch", "--tags", "--quiet", "origin"], as_owner=True)
        run(["git", "rev-parse", "--verify", f"refs/tags/{version}"], as_owner=True, capture=True)
        dump = backup()
        run(["git", "checkout", "--quiet", version], as_owner=True)
        run(["docker", "compose", "up", "-d", "--build"])
        wait_version(version)
    except Exception as exc:  # noqa: BLE001 — on note l'échec ; la demande est retirée pour ne pas boucler
        log(f"ÉCHEC : {exc}")
        REQ.unlink(missing_ok=True)
        status(result=f"échec : {exc}"[:300], running="", backup=dump, at=time.time())
        return 1
    log(f"mise à jour vers {version} terminée (sauvegarde : {dump})")
    if DRY:
        status(result="dry-run ok", running="")
    else:
        REQ.unlink(missing_ok=True)
        status(applied=version, at=time.time(), result="ok", running="", backup=dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
