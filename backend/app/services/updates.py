"""Mises à jour : vérification des releases GitHub et demande d'application.

Principe (repris de Cohors) : l'application ne redémarre JAMAIS ses propres conteneurs
(pas de socket Docker, pas de privilèges : choix de sécurité). Elle :
  1. vérifie périodiquement les releases publiées du dépôt (lecture anonyme de l'API GitHub) ;
  2. DÉPOSE une demande (`update-request.json`) dans un dossier partagé avec l'hôte ;
  3. affiche le battement de cœur et le dernier résultat de l'applicateur de l'hôte
     (`deploy/apply-update.py`, lancé par un timer systemd), qui sauvegarde la base,
     met le code à la version demandée et reconstruit les conteneurs.

Tout l'état vit dans des fichiers JSON du dossier partagé (aucune migration de schéma).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import get_settings
from app.core.version import VERSION

VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{3}(?:-c\d+)?$")
CHECK_INTERVALS = (0, 3600, 6 * 3600, 12 * 3600, 24 * 3600)   # secondes ; 0 = jamais
DEFAULT_SETTINGS = {"check_interval_s": 3600, "auto_apply": False}


# ---------------------------------------------------------------- fichiers partagés
def _dir() -> Path:
    d = Path(get_settings().update_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(name: str) -> dict:
    try:
        data = json.loads((_dir() / name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name: str, data: dict) -> None:
    tmp = _dir() / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_dir() / name)          # écriture atomique : l'applicateur ne lit jamais un fichier à moitié écrit


def read_settings() -> dict:
    s = {**DEFAULT_SETTINGS, **_read("settings.json")}
    if s.get("check_interval_s") not in CHECK_INTERVALS:
        s["check_interval_s"] = DEFAULT_SETTINGS["check_interval_s"]
    s["auto_apply"] = bool(s.get("auto_apply"))
    return s


def write_settings(values: dict) -> dict:
    s = read_settings()
    if "check_interval_s" in values:
        v = int(values["check_interval_s"])
        if v not in CHECK_INTERVALS:
            raise ValueError("Intervalle de vérification invalide")
        s["check_interval_s"] = v
    if "auto_apply" in values:
        s["auto_apply"] = bool(values["auto_apply"])
    _write("settings.json", s)
    return s


# ---------------------------------------------------------------- versions
def vtuple(version: str) -> tuple:
    """« 2026.10.012-c3 » → ((2026, 10, 12), 3), pour comparer deux versions du dépôt."""
    base, _, corr = str(version or "").strip().partition("-c")
    parts = []
    for piece in base.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    parts = (parts + [0, 0, 0])[:3]
    try:
        c = int(corr) if corr else 0
    except ValueError:
        c = 0
    return (tuple(parts), c)


# ---------------------------------------------------------------- GitHub
def _fetch_releases(etag: str = "") -> tuple[int, list, str]:
    """GET /releases (une page). Renvoie (statut HTTP, releases, nouvel ETag).

    `If-None-Match` : une réponse 304 ne consomme pas le quota anonyme (60 requêtes/h/IP).
    """
    repo = get_settings().update_repo
    headers = {"User-Agent": f"Proprietas/{VERSION}", "Accept": "application/vnd.github+json"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=30",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers.get("ETag", "")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, [], etag
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "")
            raise RuntimeError(f"limite de l'API GitHub atteinte (réinitialisation : {reset})") from exc
        raise


def _clean(releases: list) -> list[dict]:
    """Releases publiées (ni brouillon ni pré-version) au bon format, de la plus récente à la plus ancienne."""
    out = []
    for r in releases:
        tag = str(r.get("tag_name") or "").strip()
        if r.get("draft") or r.get("prerelease") or not VERSION_RE.match(tag):
            continue
        out.append({"version": tag,
                    "published_at": str(r.get("published_at") or ""),
                    "url": str(r.get("html_url") or ""),
                    "notes": str(r.get("body") or "")})
    return sorted(out, key=lambda x: vtuple(x["version"]), reverse=True)


def run_check() -> dict:
    """Vérifie les releases (cadence automatique ou bouton « Vérifier maintenant »)."""
    cache = _read("state.json")
    now = time.time()
    try:
        code, data, etag = _fetch_releases(cache.get("etag", ""))
        releases = cache.get("releases", []) if code == 304 else _clean(data)
        _write("state.json", {"etag": etag, "releases": releases, "checked_at": now, "error": ""})
    except Exception as exc:  # noqa: BLE001 — réseau / API : on note l'échec, rien ne casse
        _write("state.json", {**cache, "checked_at": now, "error": f"{type(exc).__name__} : {exc}"[:300]})
    return state()


# ---------------------------------------------------------------- demande d'application
def write_request(version: str, by: str) -> None:
    if not VERSION_RE.match(version):
        raise ValueError(f"version invalide : {version}")
    _write("update-request.json", {"version": version, "at": time.time(), "by": by})


def cancel_request() -> None:
    (_dir() / "update-request.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- état complet
def state() -> dict:
    cache = _read("state.json")
    releases = cache.get("releases", [])
    newer = [r for r in releases if vtuple(r["version"]) > vtuple(VERSION)]
    req = _read("update-request.json")
    app = _read("update-applier.json")
    return {
        "current": VERSION,
        "mode": get_settings().update_mode,
        "latest": releases[0] if releases else None,
        "available": bool(newer),
        "changes": newer,                         # toutes les notes entre la version installée et la dernière
        "check": {"last_at": float(cache.get("checked_at") or 0), "error": str(cache.get("error") or "")},
        "request": ({"version": req.get("version"), "at": float(req.get("at") or 0),
                     "by": str(req.get("by") or "")} if req.get("version") else None),
        "applier": {"installed": float(app.get("seen_at") or 0) > 0,
                    "seen_at": float(app.get("seen_at") or 0),
                    "result": str(app.get("result") or ""),
                    "applied": str(app.get("applied") or ""),
                    "applied_at": float(app.get("at") or 0),
                    "backup": str(app.get("backup") or "")},
        "settings": read_settings(),
    }


def tick() -> None:
    """Appelé toutes les 10 min par le planificateur : vérifie si l'intervalle est écoulé,
    puis dépose une demande si l'application automatique est activée (mode serveur seulement)."""
    s = read_settings()
    st = state()
    interval = s["check_interval_s"]
    if interval and time.time() - st["check"]["last_at"] >= interval:
        st = run_check()
    if (st["available"] and s["auto_apply"] and st["mode"] == "server" and not st["request"]):
        write_request(st["latest"]["version"], "application automatique")
