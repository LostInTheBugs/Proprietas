#!/usr/bin/env python3
"""Proprietas — applicateur de mise à jour (côté hôte, lancé par proprietas-update.timer).

L'application ne fait que DÉPOSER une demande dans `data/updates/update-request.json`
(son conteneur n'a ni socket Docker ni privilèges : choix de sécurité). Ce script :

  1. valide la version demandée (format AAAA.MM.NNN[-cX], tag existant) ;
  2. SAUVEGARDE la base PostgreSQL (`pg_dump`) dans `data/backups/` (10 dernières gardées) ;
  3. met le dépôt sur le tag demandé (`git fetch --tags` + `git checkout <tag>`, en tant
     que propriétaire du dépôt) ;
  4. relance l'application dans la nouvelle version (les migrations Alembic s'appliquent
     au démarrage du conteneur), selon PROPRIETAS_UPDATE_STRATEGY dans le .env :
       - « build » (défaut) : `docker compose up -d --build` — construit l'image sur place ;
       - « pull » : image construite par GitHub (ghcr.io/lostinthebugs/proprietas:<version>),
         PROPRIETAS_VERSION=<version> écrit dans le .env, `docker compose pull backend`
         puis `docker compose up -d --no-build`. Pour les petits serveurs : construire
         le frontend demande 1 à 2 Go de RAM et peut faire tomber un petit VPS ;
  5. attend que l'API réponde avec la NOUVELLE version, sinon signale l'échec
     (la sauvegarde indiquée permet de revenir en arrière à la main) ;
  6. après un succès, fait le ménage Docker : images orphelines (`docker image prune -f`)
     et, en stratégie « build », cache de construction (`docker builder prune -af`) ;
     en stratégie « pull », supprime les images de l'application SAUF la nouvelle version et la
     version précédente (retour arrière possible). La version précédente est indiquée dans
     l'état (`precedente`) : l'administrateur choisit ensuite, depuis le site, de la garder, de
     l'oublier (`action: "oublier_precedente"`, l'image est supprimée) ou d'y revenir.

Retour arrière (`action: "rollback"`, version = la version précédente) :
  1. vérifie l'espace disque, sauvegarde la base (`pg_dump`) ;
  2. lit, dans le tag git de la version visée, la tête de ses migrations Alembic, et ramène la
     base à cette révision (`alembic downgrade`, exécuté par la version actuelle, qui connaît les
     migrations à annuler) : l'ancienne version refuserait sinon de démarrer sur une base plus
     récente. Les données saisies depuis restent ; seuls les champs ajoutés par les migrations
     annulées sont perdus ;
  3. remet le dépôt sur le tag, relance l'ancienne image (« pull ») ou la reconstruit (« build »),
     attend que l'API réponde dans cette version ;
  4. en cas d'échec après l'étape 2 : revient à la version actuelle (son démarrage réapplique
     les migrations) ; la sauvegarde de l'étape 1 reste disponible.

Avant toute modification, vérifie l'espace disque libre : 1,5 Go en « build », 0,5 Go en
« pull » (seuil réglable par PROPRIETAS_MIN_FREE_GB dans le .env). Sinon : refus, rien ne bouge.

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
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
UPD = APP_DIR / "data" / "updates"
BACKUPS = APP_DIR / "data" / "backups"
ENV = APP_DIR / ".env"
REQ = UPD / "update-request.json"
STATUS = UPD / "update-applier.json"
LOG = UPD / "update.log"
VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{3}(?:-c\d+)?$")
KEEP_BACKUPS = 10
IMAGE = "ghcr.io/lostinthebugs/proprietas"
ACTIONS = ("update", "rollback", "oublier_precedente")
HEALTH_TIMEOUT_S = int(os.environ.get("PROPRIETAS_HEALTH_TIMEOUT_S") or 180)
# Espace disque minimal avant une mise à jour (Go). Cas réel du 24/10/2026 : ionos01 à 99 %
# (cache de construction accumulé), `npm ci` échouait sans message clair.
MIN_FREE_GB = {"build": 1.5, "pull": 0.5}
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


def read_env(path: Path) -> dict:
    """Lecture simple d'un .env (CLE=valeur ; commentaires et lignes vides ignorés)."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            v = v.strip()
            # Comme docker compose : KEY="valeur" ou KEY='valeur' → valeur (guillemets appariés).
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def espace_libre_gb() -> float:
    return shutil.disk_usage(APP_DIR).free / 1024 ** 3


def verifier_espace(strategy: str, env: dict) -> None:
    """Refuse la mise à jour si le disque est trop plein (avant sauvegarde et checkout)."""
    try:
        minimum = float(env.get("PROPRIETAS_MIN_FREE_GB") or MIN_FREE_GB.get(strategy, 1.5))
    except ValueError:
        minimum = MIN_FREE_GB.get(strategy, 1.5)
    libre = espace_libre_gb()
    log(f"espace disque libre : {libre:.1f} Go (minimum {minimum:g} Go, stratégie {strategy})")
    if libre < minimum:
        conseil = ("libérez de la place (docker builder prune -af ; docker image prune -f) "
                   "ou passez en PROPRIETAS_UPDATE_STRATEGY=pull") if strategy == "build" \
            else "libérez de la place (docker image prune -af)"
        raise RuntimeError(f"espace disque insuffisant : {libre:.1f} Go libres, {minimum:g} Go "
                           f"nécessaires — {conseil}")


def menage_docker(strategy: str) -> None:
    """Après un succès : ne pas laisser grossir le disque à chaque version (best effort)."""
    commandes = [["docker", "image", "prune", "-f"]]
    if strategy != "pull":
        commandes.insert(0, ["docker", "builder", "prune", "-af"])
    for cmd in commandes:
        try:
            run(cmd)
        except Exception as exc:  # noqa: BLE001 — le ménage n'invalide jamais la mise à jour
            log(f"ménage non bloquant en échec : {exc}")


def set_env(path: Path, key: str, value: str):
    """Remplace (ou ajoute à la fin) KEY=value dans le .env, sans toucher aux autres lignes.
    Retourne l'ancienne valeur (None si la clé était absente), pour pouvoir la remettre."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    old = None
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == key and not line.lstrip().startswith("#"):
            old = line.partition("=")[2].strip()
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if path.exists():
        os.chmod(tmp, path.stat().st_mode)
    tmp.replace(path)
    return old


def version_installee() -> str:
    """Version du code actuellement en place (fichier VERSION du dépôt)."""
    try:
        return (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def images_a_supprimer(lignes: list[str], garder: set[str]) -> list[str]:
    """Lignes `TAG\tID` de `docker images IMAGE` → tags à supprimer (ni gardés, ni <none>).
    Un tag qui pointe sur la même image qu'un tag gardé est seulement retiré (docker rmi d'un
    tag ne supprime pas une image encore étiquetée)."""
    out = []
    for ligne in lignes:
        tag = ligne.split("\t")[0].strip()
        if tag and tag != "<none>" and tag not in garder:
            out.append(tag)
    return out


def menage_versions(garder: set[str]) -> None:
    """Stratégie « pull » : ne garder que les images des versions `garder` (best effort)."""
    if DRY:
        log(f"images de l'application : seules {', '.join(sorted(garder))} seraient gardées (dry-run)")
        return
    try:
        lignes = run(["docker", "images", IMAGE, "--format", "{{.Tag}}\t{{.ID}}"], capture=True).splitlines()
        for tag in images_a_supprimer(lignes, garder):
            run(["docker", "rmi", f"{IMAGE}:{tag}"])
    except Exception as exc:  # noqa: BLE001 — le ménage n'invalide jamais la mise à jour
        log(f"ménage des versions non bloquant en échec : {exc}")


def vcle(version: str) -> tuple:
    base, _, corr = version.partition("-c")
    return tuple(int(x) for x in base.split(".")) + (int(corr or 0),)


def choisir_precedente(lignes: list[str], actuelle: str) -> str:
    """Parmi les images locales (`TAG\tID`), la version la plus récente plus ancienne que `actuelle`."""
    tags = [l.split("\t")[0].strip() for l in lignes]
    anciennes = [t for t in tags if VERSION_RE.match(t) and VERSION_RE.match(actuelle) and vcle(t) < vcle(actuelle)]
    return max(anciennes, key=vcle) if anciennes else ""


def initialiser_versions(strategy: str) -> None:
    """Au premier battement de cœur de cet applicateur (la mise à jour qui l'a installé a été faite
    par l'ancien, qui gardait toutes les images), et chaque fois que la « précédente » notée est la
    version en service : en « pull », garder la version en service et la plus récente des
    anciennes, supprimer les autres."""
    actuelle = version_installee()
    try:
        etat = json.loads(STATUS.read_text(encoding="utf-8"))
        p = etat.get("precedente")
        # Déjà fait, sauf si la « précédente » notée est la version en service : la dernière mise à
        # jour a alors été faite par un ancien applicateur (cas réel du 09/11/2026 : retour arrière
        # vers 2026.11.013, puis remise à jour automatique par l'applicateur de 2026.11.013).
        if "precedente" in etat and not (isinstance(p, dict) and p.get("version") == actuelle):
            return
    except (OSError, ValueError):
        pass
    if strategy != "pull" or not VERSION_RE.match(actuelle):
        status(precedente=None)
        return
    try:
        lignes = run(["docker", "images", IMAGE, "--format", "{{.Tag}}\t{{.ID}}"], capture=True).splitlines()
    except Exception as exc:  # noqa: BLE001 — on réessaiera au prochain battement
        log(f"initialisation des versions reportée : {exc}")
        return
    precedente = choisir_precedente(lignes, actuelle)
    log(f"initialisation : versions gardées {actuelle}{' et ' + precedente if precedente else ''}")
    menage_versions({actuelle, precedente} - {""})
    status(precedente={"version": precedente, "image": True, "octets": taille_image(precedente)} if precedente else None)


def taille_image(version: str):
    if DRY:
        return None
    try:
        return int(run(["docker", "image", "inspect", "-f", "{{.Size}}", f"{IMAGE}:{version}"], capture=True).strip())
    except Exception:  # noqa: BLE001
        return None


REV_RE = re.compile(r"""^revision\s*(?::[^=]*)?=\s*['"]([0-9a-zA-Z_]+)['"]""", re.M)
DOWN_RE = re.compile(r"^down_revision\s*(?::[^=]*)?=(.*)$", re.M)


def tete_alembic(tag: str) -> str:
    """Révision Alembic la plus récente de la version `tag`, lue dans le dépôt git (sans la lancer)."""
    fichiers = run(["git", "ls-tree", "--name-only", f"{tag}:backend/alembic/versions/"],
                   as_owner=True, capture=True).split()
    revisions, parents = set(), set()
    for nom in fichiers:
        if not nom.endswith(".py"):
            continue
        texte = run(["git", "show", f"{tag}:backend/alembic/versions/{nom}"], as_owner=True, capture=True)
        rev = REV_RE.search(texte)
        if rev:
            revisions.add(rev.group(1))
        down = DOWN_RE.search(texte)
        if down:
            parents |= set(re.findall(r"""['"]([0-9a-zA-Z_]+)['"]""", down.group(1)))
    tetes = revisions - parents
    if len(tetes) != 1:
        raise RuntimeError(f"tête des migrations de {tag} introuvable ({sorted(tetes)})")
    return tetes.pop()


def revision_base() -> str:
    """Révision Alembic actuelle de la base (exécutée dans le conteneur en service)."""
    if DRY:
        return ""
    sortie = run(["docker", "compose", "exec", "-T", "backend", "alembic", "current"], capture=True)
    m = re.search(r"^([0-9a-zA-Z_]+)", sortie.strip().splitlines()[-1] if sortie.strip() else "")
    return m.group(1) if m else ""


def relancer(strategy: str) -> None:
    if strategy == "pull":
        run(["docker", "compose", "up", "-d", "--no-build"])
    else:
        run(["docker", "compose", "up", "-d", "--build"])


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
        if not DRY:
            initialiser_versions(read_env(ENV).get("PROPRIETAS_UPDATE_STRATEGY", "build").lower())
        return 0
    try:
        payload = json.loads(REQ.read_text(encoding="utf-8"))
        version = str(payload.get("version") or "").strip()
        by = str(payload.get("by") or "?")
        action = str(payload.get("action") or "update")
    except (OSError, ValueError) as exc:
        log(f"demande illisible : {exc}")
        REQ.unlink(missing_ok=True)
        status(result="demande illisible")
        return 1
    if action not in ACTIONS:
        log(f"action refusée : {action!r}")
        REQ.unlink(missing_ok=True)
        status(result=f"action refusée : {action}"[:300])
        return 1
    if not VERSION_RE.match(version):
        log(f"version refusée : {version!r}")
        REQ.unlink(missing_ok=True)
        status(result=f"version refusée : {version}"[:300])
        return 1
    env = read_env(ENV)
    strategy = env.get("PROPRIETAS_UPDATE_STRATEGY", "build").lower()
    if action == "oublier_precedente":
        return oublier_precedente(version, by, strategy)
    if action == "rollback":
        return retour_arriere(version, by, strategy)
    log(f"demande de {by} : mise à jour vers {version}{' (dry-run)' if DRY else ''}")
    status(result="en cours", running=version, running_at=time.time())
    dump = ""
    avant = version_installee()
    env_restore = False
    old_version = None
    try:
        run(["git", "fetch", "--tags", "--quiet", "origin"], as_owner=True)
        run(["git", "rev-parse", "--verify", f"refs/tags/{version}"], as_owner=True, capture=True)
        verifier_espace(strategy, env)
        dump = backup()
        run(["git", "checkout", "--quiet", version], as_owner=True)
        if strategy == "pull":
            log(f".env : PROPRIETAS_VERSION={version}")
            if not DRY:
                old_version = set_env(ENV, "PROPRIETAS_VERSION", version)
                env_restore = True
            run(["docker", "compose", "pull", "backend"])
            run(["docker", "compose", "up", "-d", "--no-build"])
        else:
            run(["docker", "compose", "up", "-d", "--build"])
        wait_version(version)
    except Exception as exc:  # noqa: BLE001 — on note l'échec ; la demande est retirée pour ne pas boucler
        log(f"ÉCHEC : {exc}")
        if env_restore:
            # L'image précédente reste celle du .env : un `docker compose up -d` manuel la relance.
            if old_version is None:
                set_env(ENV, "PROPRIETAS_VERSION", "latest")
            else:
                set_env(ENV, "PROPRIETAS_VERSION", old_version)
            log(f".env : PROPRIETAS_VERSION remis à {old_version or 'latest'}")
        REQ.unlink(missing_ok=True)
        status(result=f"échec : {exc}"[:300], running="", backup=dump, at=time.time())
        return 1
    menage_docker(strategy)
    precedente = None
    if avant and avant != version and VERSION_RE.match(avant):
        if strategy == "pull":
            menage_versions({version, avant})
        precedente = {"version": avant, "image": strategy == "pull",
                      "octets": taille_image(avant) if strategy == "pull" else None}
    elif strategy == "pull":
        menage_versions({version})
    log(f"mise à jour vers {version} terminée (sauvegarde : {dump})"
        + (f" ; version précédente gardée : {avant}" if precedente else ""))
    if DRY:
        status(result="dry-run ok", running="")
    else:
        REQ.unlink(missing_ok=True)
        status(applied=version, at=time.time(), result="ok", running="", backup=dump, precedente=precedente)
    return 0


def lire_precedente() -> dict | None:
    try:
        p = json.loads(STATUS.read_text(encoding="utf-8")).get("precedente")
        return p if isinstance(p, dict) and p.get("version") else None
    except (OSError, ValueError):
        return None


def oublier_precedente(version: str, by: str, strategy: str) -> int:
    """L'administrateur ne garde pas la version précédente : son image est supprimée."""
    log(f"demande de {by} : ne pas conserver la version {version}{' (dry-run)' if DRY else ''}")
    precedente = lire_precedente()
    if not precedente or precedente["version"] != version or version == version_installee():
        REQ.unlink(missing_ok=True)
        status(result=f"échec : {version} n'est pas la version précédente conservée"[:300])
        return 1
    if strategy == "pull":
        try:
            run(["docker", "rmi", f"{IMAGE}:{version}"])
        except Exception as exc:  # noqa: BLE001 — déjà absente : rien à faire
            log(f"image {version} non supprimée : {exc}")
    log(f"version {version} oubliée")
    if not DRY:
        REQ.unlink(missing_ok=True)
        status(result="ok", running="", precedente=None, at=time.time())
    return 0


def retour_arriere(version: str, by: str, strategy: str) -> int:
    """Revient à la version précédente conservée (voir l'en-tête du fichier)."""
    actuelle = version_installee()
    log(f"demande de {by} : retour arrière de {actuelle} vers {version}{' (dry-run)' if DRY else ''}")
    precedente = lire_precedente()
    if not precedente or precedente["version"] != version or version == actuelle:
        log(f"retour arrière refusé : {version} n'est pas la version précédente conservée")
        REQ.unlink(missing_ok=True)
        status(result=f"échec : {version} n'est pas la version précédente conservée"[:300])
        return 1
    status(result="en cours", running=version, running_at=time.time())
    env = read_env(ENV)
    dump = ""
    base_modifiee = False
    bascule = False
    old_env = None
    try:
        run(["git", "rev-parse", "--verify", f"refs/tags/{version}"], as_owner=True, capture=True)
        verifier_espace(strategy, env)
        dump = backup()
        cible = tete_alembic(version)
        courante = revision_base()
        log(f"migrations : base en {courante or '?'}, version {version} en {cible}")
        if courante != cible:
            run(["docker", "compose", "exec", "-T", "backend", "alembic", "downgrade", cible])
            base_modifiee = True
        bascule = True
        run(["git", "checkout", "--quiet", version], as_owner=True)
        if strategy == "pull" and not DRY:
            old_env = set_env(ENV, "PROPRIETAS_VERSION", version)
        relancer(strategy)
        wait_version(version)
    except Exception as exc:  # noqa: BLE001
        log(f"ÉCHEC du retour arrière : {exc}")
        if bascule or base_modifiee:
            try:
                log(f"retour à {actuelle}")
                if bascule:
                    run(["git", "checkout", "--quiet", actuelle], as_owner=True)
                    if strategy == "pull" and not DRY:
                        set_env(ENV, "PROPRIETAS_VERSION", old_env or actuelle)
                relancer(strategy)
                wait_version(actuelle)
                # Le conteneur n'est pas forcément recréé (rien n'a changé pour docker compose) :
                # on réapplique explicitement les migrations annulées.
                run(["docker", "compose", "exec", "-T", "backend", "alembic", "upgrade", "head"])
                log(f"{actuelle} relancée, migrations réappliquées")
            except Exception as exc2:  # noqa: BLE001
                log(f"ÉCHEC du retour à {actuelle} : {exc2} — restaurer à la main la sauvegarde {dump}")
        REQ.unlink(missing_ok=True)
        status(result=f"échec du retour arrière : {exc}"[:300], running="", backup=dump, at=time.time())
        return 1
    log(f"retour arrière vers {version} terminé (sauvegarde : {dump})")
    if DRY:
        status(result="dry-run ok", running="")
    else:
        REQ.unlink(missing_ok=True)
        # La version quittée devient à son tour la précédente (son image est gardée en « pull »).
        status(applied=version, at=time.time(), result="ok", running="", backup=dump,
               precedente={"version": actuelle, "image": strategy == "pull",
                           "octets": taille_image(actuelle) if strategy == "pull" else None})
    return 0


if __name__ == "__main__":
    sys.exit(main())
