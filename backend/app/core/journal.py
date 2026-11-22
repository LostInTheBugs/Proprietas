"""Journaux structurés (demande de Fred, 22/11/2026).

`COPRO_LOG_FORMAT=json` : chaque message du journal devient une ligne JSON (`ts`, `niveau`, `logger`, `message`,
`exception`, et les champs ajoutés par `extra=`), prête pour Loki ou un autre collecteur. Le middleware de
app/main.py écrit alors une ligne par requête de l'API sur le journal « proprietas.requete » (identifiant, compte,
copropriété, méthode, chemin, code, durée) et le journal d'accès d'uvicorn, redondant, est coupé.
Par défaut (`texte`), rien ne change.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

# Attributs standard d'un LogRecord : tout le reste vient de `extra=` et passe dans la ligne JSON.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName", "color_message"}


class FormatJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ligne = {"ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                 "niveau": record.levelname, "logger": record.name, "message": record.getMessage()}
        for cle, valeur in vars(record).items():
            if cle not in _STANDARD and not cle.startswith("_"):
                ligne[cle] = valeur
        if record.exc_info:
            ligne["exception"] = self.formatException(record.exc_info)
        return json.dumps(ligne, ensure_ascii=False, default=str)


def configurer(format_journal: str) -> None:
    if (format_journal or "").lower() != "json":
        return
    gestionnaire = logging.StreamHandler()
    gestionnaire.setFormatter(FormatJSON())
    for nom in ("", "uvicorn", "uvicorn.error", "proprietas", "alembic"):
        journal = logging.getLogger(nom)
        journal.handlers = [gestionnaire] if nom == "" else []
        journal.propagate = nom != ""
    logging.getLogger().setLevel(logging.INFO)
    acces = logging.getLogger("uvicorn.access")
    acces.handlers, acces.propagate, acces.disabled = [], False, True
