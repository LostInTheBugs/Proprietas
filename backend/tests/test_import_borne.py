"""Revue externe de la 2026.11.022 : deux durcissements.

1. Docker Compose : le conteneur backend ne recevait que 5 variables ; les réglages documentés
   « dans le .env » (pool PostgreSQL, stockage S3, plafonds, conservation du journal, 2FA par défaut)
   n'arrivaient donc jamais à l'application. Le service backend lit maintenant le `.env` (env_file,
   facultatif) ; les 5 variables fixées par Compose gardent la priorité.

2. Import d'une sauvegarde : la taille reçue (compressée) était bornée, pas la taille décompressée.
   Règles :
   - `donnees.json` : 50 Mo au plus une fois décompressé ; `manifest.json` : 1 Mo ;
   - total décompressé (données + fichiers) : COPRO_IMPORT_MAX_DECOMPRESSE_MB, 2000 Mo par défaut ;
   - la limite est vérifiée À LA LECTURE (une taille annoncée dans l'archive peut mentir) ;
   - dépassement : 413, rien n'est créé (ni copropriété, ni fichier).
"""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.models.copropriete import Copropriete
from app.services import sauvegarde as svc
from tests.test_sauvegarde import _copro_complete, _export, _import, _ouvrir, MDP

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _service_backend() -> str:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml absent (image Docker)")
    texte = COMPOSE.read_text(encoding="utf-8")
    return re.search(r"^  backend:\n(.*?)(?=^  \w)", texte, re.S | re.M).group(1)


def test_compose_transmet_le_env_au_backend():
    bloc = _service_backend()
    assert re.search(r"^    env_file:\n      - path: \.env\n        required: false$", bloc, re.M), bloc
    # Les valeurs imposées par Compose restent dans `environment` (prioritaire sur env_file).
    for cle in ("COPRO_DATABASE_URL", "COPRO_SECRET_KEY", "COPRO_UPLOAD_DIR", "COPRO_FRONTEND_DIST",
                "COPRO_UPDATE_DIR"):
        assert re.search(rf"^      {cle}:", bloc, re.M), cle


def _archive(membres: dict[str, bytes]) -> bytes:
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in membres.items():
            z.writestr(nom, contenu)
    return sortie.getvalue()


def _reecrire(contenu: bytes, remplacer: dict[str, bytes]) -> bytes:
    z = _ouvrir(contenu)
    return _archive({nom: remplacer.get(nom, z.read(nom)) for nom in z.namelist()} |
                    {k: v for k, v in remplacer.items() if k not in z.namelist()})


def test_donnees_json_trop_gros_une_fois_decompresse(client, db, copro_a, syndic_a, token_a, monkeypatch):
    monkeypatch.setattr(svc, "MAX_DONNEES", 100_000)
    # 5 Mo d'espaces : quelques Ko une fois compressés.
    bombe = _archive({"manifest.json": json.dumps({"format": svc.FORMAT, "version_format": 1}).encode(),
                      "donnees.json": b"{" + b" " * 5_000_000 + b"}"})
    assert len(bombe) < 50_000
    avant = db.query(Copropriete).count()
    r = _import(client, token_a, bombe, mot_de_passe="")
    assert r.status_code == 413, r.text
    assert "décompress" in r.json()["detail"]
    assert db.query(Copropriete).count() == avant


def test_manifest_trop_gros(client, db, copro_a, syndic_a, token_a):
    bombe = _archive({"manifest.json": b" " * 2_000_000, "donnees.json": b"{}"})
    assert _import(client, token_a, bombe, mot_de_passe="").status_code == 413


def test_fichiers_trop_gros_une_fois_decompresses(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b,
                                                  monkeypatch):
    _copro_complete(client, db, copro_a, token_a)
    contenu = _export(client, token_a)
    z = _ouvrir(contenu)
    fichiers = [n for n in z.namelist() if n.startswith("documents/")]
    assert fichiers
    # Un document de 3 Mo de zéros (très compressible) ; plafond total : 1 Mo.
    piege = _reecrire(contenu, {fichiers[0]: b"\0" * 3_000_000})
    assert len(piege) < 200_000
    monkeypatch.setattr(get_settings(), "import_max_decompresse_mb", 1.0)
    avant = db.query(Copropriete).count()
    r = _import(client, token_b, piege, mot_de_passe="")
    assert r.status_code == 413, r.text
    assert "1 Mo" in r.json()["detail"]
    db.expire_all()
    assert db.query(Copropriete).count() == avant           # rien n'est créé


def test_import_normal_sous_la_limite(client, db, copro_a, copro_b, syndic_a, syndic_b, token_a, token_b):
    _copro_complete(client, db, copro_a, token_a)
    r = _import(client, token_b, _export(client, token_a))
    assert r.status_code == 200, r.text
    assert r.json()["documents"] >= 1


def test_taille_annoncee_trop_grande_refusee_sans_lire(client, db, copro_a, syndic_a, token_a, monkeypatch):
    """Rejet rapide d'après les tailles annoncées, avant toute décompression."""
    monkeypatch.setattr(get_settings(), "import_max_decompresse_mb", 1.0)
    lu = []
    monkeypatch.setattr(svc, "_lire_borne", lambda *a, **k: lu.append(1) or b"{}")
    bombe = _archive({"manifest.json": b"{}", "donnees.json": b"{}", "documents/x.pdf": b"\0" * 3_000_000})
    assert _import(client, token_a, bombe, mot_de_passe="").status_code == 413
    assert not lu
