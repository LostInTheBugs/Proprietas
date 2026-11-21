"""Ressources du serveur (Réglages → Serveur, administrateur de l'instance ; demande de Fred, 21/11/2026).

- L'applicateur de mises à jour (deploy/apply-update.py, côté hôte) écrit chaque minute `ressources.json` dans le
  dossier partagé : processeur, mémoire, disque de la machine, et chaque conteneur du projet (`docker stats`).
  Le conteneur de l'application n'a pas le socket Docker (choix de sécurité) : il ne voit pas les autres.
- Sans applicateur (ou chiffres de plus de trois minutes) : ce que voit l'application elle-même.
- Toujours : la mémoire du processus de l'application et la taille de la base (la place des documents est dans
  la carte « Espace de stockage », plus longue à calculer).
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import time
from pathlib import Path

from app.core.config import get_settings

FRAICHEUR_S = 180
GROUPES = (("jitsi-", "Jitsi"), ("backend", "Application"), ("db", "Base de données"), ("caddy", "Proxy (Caddy)"))


def _groupe(service: str) -> str:
    return next((g for prefixe, g in GROUPES if service == prefixe or (prefixe.endswith("-") and service.startswith(prefixe))),
                service or "Autre")


def _lire() -> dict | None:
    try:
        d = json.loads((Path(get_settings().update_dir) / "ressources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _memoire_vue_locale() -> dict:
    vals = {}
    try:
        for ligne in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            cle, _, reste = ligne.partition(":")
            vals[cle] = int(reste.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {"total": None, "disponible": None}
    return {"total": vals.get("MemTotal"), "disponible": vals.get("MemAvailable")}


def _memoire_processus() -> int:
    """Mémoire résidente du processus de l'application (octets)."""
    try:
        for ligne in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if ligne.startswith("VmRSS:"):
                return int(ligne.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss          # Ko sous Linux, octets sous macOS
    return maxrss if maxrss > 1 << 32 else maxrss * 1024


def _vue_locale(chemin: str) -> dict:
    try:
        charge = list(os.getloadavg())
    except (OSError, AttributeError):
        charge = []
    u = shutil.disk_usage(chemin if os.path.isdir(chemin) else ".")
    return {"cpus": os.cpu_count() or 1, "charge": charge, "memoire": _memoire_vue_locale(),
            "disque": {"total": u.total, "utilise": u.total - u.free, "libre": u.free}, "demarre_depuis_s": None}


def _completer_memoire(systeme: dict) -> dict:
    m = dict(systeme.get("memoire") or {})
    if m.get("total") and m.get("disponible") is not None:
        m["utilisee"] = m["total"] - m["disponible"]
    systeme["memoire"] = m
    return systeme


def _services(liste: list[dict]) -> list[dict]:
    groupes: dict[str, dict] = {}
    for c in liste:
        g = groupes.setdefault(_groupe(c.get("service", "")), {"groupe": _groupe(c.get("service", "")),
                                                               "cpu_pct": 0.0, "mem_octets": 0, "conteneurs": []})
        g["cpu_pct"] = round(g["cpu_pct"] + float(c.get("cpu_pct") or 0), 2)
        g["mem_octets"] += int(c.get("mem_octets") or 0)
        g["conteneurs"].append(c)
    ordre = [g for _, g in GROUPES]
    return sorted(groupes.values(), key=lambda g: (ordre.index(g["groupe"]) if g["groupe"] in ordre else 99, g["groupe"]))


def etat(chemin_documents: str, base_octets: int | None) -> dict:
    fichier = _lire()
    age = time.time() - float(fichier.get("at") or 0) if fichier else None
    a_jour = fichier is not None and age is not None and age <= FRAICHEUR_S
    hote = fichier.get("hote") if a_jour and isinstance(fichier.get("hote"), dict) else None
    return {
        "source": "hote" if hote else "application",
        "applicateur": {"present": fichier is not None, "a_jour": a_jour, "at": float(fichier.get("at") or 0) if fichier else None},
        "systeme": _completer_memoire(dict(hote) if hote else _vue_locale(chemin_documents)),
        "services": _services(fichier.get("services") or []) if a_jour else [],
        "services_anciens": bool(fichier and not a_jour and fichier.get("services")),
        "application": {"memoire_octets": _memoire_processus(), "base_octets": base_octets},
    }
