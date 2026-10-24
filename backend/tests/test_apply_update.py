"""Applicateur de l'hôte (deploy/apply-update.py) en --dry-run, sur une copie isolée :
battement de cœur, refus des versions invalides, tag inexistant, dry-run complet,
stratégie « pull » (image construite par GitHub) et réécriture du .env."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# L'applicateur tourne sur l'HÔTE Linux (systemd, runuser, module pwd) : sans objet sous
# Windows (version de bureau, postes de développement).
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="applicateur Linux uniquement")

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "apply-update.py"


def _app(tmp_path, tag=None):
    app = tmp_path / "app"
    (app / "deploy").mkdir(parents=True)
    shutil.copy(SCRIPT, app / "deploy" / "apply-update.py")
    subprocess.run(["git", "init", "-q"], cwd=app, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "init"], cwd=app, check=True)
    if tag:
        subprocess.run(["git", "tag", tag], cwd=app, check=True)
    (app / "data" / "updates").mkdir(parents=True)
    return app


def _run(app, request=None):
    upd = app / "data" / "updates"
    if request is not None:
        (upd / "update-request.json").write_text(json.dumps(request), encoding="utf-8")
    res = subprocess.run([sys.executable, "deploy/apply-update.py", "--dry-run"], cwd=app,
                         capture_output=True, text=True)
    status = json.loads((upd / "update-applier.json").read_text(encoding="utf-8"))
    return res, status, (upd / "update-request.json").exists()


def test_sans_demande_battement_de_coeur(tmp_path):
    res, status, _ = _run(_app(tmp_path))
    assert res.returncode == 0 and status["seen_at"] > 0


def test_version_invalide_refusee_et_retiree(tmp_path):
    res, status, demande = _run(_app(tmp_path), {"version": "v1.2.0; rm -rf /", "by": "x"})
    assert res.returncode == 1 and "refusée" in status["result"] and not demande


def test_tag_inexistant_echoue_proprement(tmp_path):
    res, status, demande = _run(_app(tmp_path), {"version": "2026.10.099", "by": "x"})
    assert res.returncode == 1 and status["result"].startswith("échec") and not demande


def test_dry_run_complet_garde_la_demande(tmp_path):
    res, status, demande = _run(_app(tmp_path, tag="2026.10.002"), {"version": "2026.10.002", "by": "x"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert status["result"] == "dry-run ok" and demande      # rien n'a été appliqué
    journal = (tmp_path / "app" / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "sauvegarde →" in journal
    assert "git checkout --quiet 2026.10.002" in journal and "docker compose up -d --build" in journal


def test_dry_run_strategie_pull_n_utilise_pas_build(tmp_path):
    # Petit serveur : l'image est construite par GitHub (GHCR) et seulement téléchargée.
    app = _app(tmp_path, tag="2026.10.004")
    (app / ".env").write_text("POSTGRES_PASSWORD=x\nPROPRIETAS_UPDATE_STRATEGY=pull\n", encoding="utf-8")
    res, status, demande = _run(app, {"version": "2026.10.004", "by": "x"})
    assert res.returncode == 0, res.stdout + res.stderr
    journal = (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "PROPRIETAS_VERSION=2026.10.004" in journal
    assert "docker compose pull backend" in journal
    assert "docker compose up -d --no-build" in journal
    assert "--build" not in journal.replace("--no-build", "")
    # dry-run : le .env n'est pas modifié
    assert "PROPRIETAS_VERSION" not in (app / ".env").read_text(encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("apply_update", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_set_env_remplace_ou_ajoute_sans_toucher_au_reste(tmp_path):
    mod = _module()
    env = tmp_path / ".env"
    env.write_text("# commentaire\nPOSTGRES_PASSWORD=secret\nPROPRIETAS_VERSION=2026.10.003\n", encoding="utf-8")
    assert mod.set_env(env, "PROPRIETAS_VERSION", "2026.10.004") == "2026.10.003"
    assert env.read_text(encoding="utf-8") == (
        "# commentaire\nPOSTGRES_PASSWORD=secret\nPROPRIETAS_VERSION=2026.10.004\n")
    assert mod.set_env(env, "AUTRE", "1") is None          # absente : ajoutée à la fin
    assert env.read_text(encoding="utf-8").endswith("PROPRIETAS_VERSION=2026.10.004\nAUTRE=1\n")


def test_strategie_par_defaut_build(tmp_path):
    mod = _module()
    assert mod.read_env(tmp_path / ".env") == {}            # pas de .env
    (tmp_path / ".env").write_text("PROPRIETAS_UPDATE_STRATEGY = pull \n", encoding="utf-8")
    assert mod.read_env(tmp_path / ".env")["PROPRIETAS_UPDATE_STRATEGY"] == "pull"


# ---------------------------------------------------------------- tâche 18b : robustesse
# Cas réel (24/10/2026) : ionos01 a échoué 3 fois sur `npm ci` avec un disque plein à 99 %
# (2,2 Go de cache de construction accumulé) ; et un .env avec des guillemets
# (PROPRIETAS_UPDATE_STRATEGY="pull") aurait silencieusement choisi « build ».

def test_read_env_retire_les_guillemets_comme_docker(tmp_path):
    mod = _module()
    (tmp_path / ".env").write_text('A="pull"\nB=\'pull\'\nC="pull\nD=x"y\n', encoding="utf-8")
    env = mod.read_env(tmp_path / ".env")
    assert env["A"] == "pull" and env["B"] == "pull"
    assert env["C"] == '"pull' and env["D"] == 'x"y'          # guillemets non appariés : intacts


def test_strategie_pull_entre_guillemets(tmp_path):
    app = _app(tmp_path, tag="2026.10.004")
    (app / ".env").write_text('PROPRIETAS_UPDATE_STRATEGY="pull"\n', encoding="utf-8")
    res, status, _ = _run(app, {"version": "2026.10.004", "by": "x"})
    journal = (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "docker compose pull backend" in journal and "up -d --build" not in journal


def test_espace_disque_insuffisant_refuse_avant_tout_changement(tmp_path):
    app = _app(tmp_path, tag="2026.10.004")
    (app / ".env").write_text("PROPRIETAS_MIN_FREE_GB=999999\n", encoding="utf-8")
    res, status, demande = _run(app, {"version": "2026.10.004", "by": "x"})
    assert res.returncode == 1 and "espace disque insuffisant" in status["result"] and not demande
    journal = (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "sauvegarde →" not in journal and "git checkout" not in journal   # rien n'a bougé


def test_build_reussi_vide_le_cache(tmp_path):
    res, status, _ = _run(_app(tmp_path, tag="2026.10.002"), {"version": "2026.10.002", "by": "x"})
    assert res.returncode == 0, res.stdout + res.stderr
    journal = (tmp_path / "app" / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "docker builder prune -af" in journal and "docker image prune -f" in journal


def test_pull_reussi_supprime_les_images_orphelines_sans_toucher_au_cache(tmp_path):
    app = _app(tmp_path, tag="2026.10.004")
    (app / ".env").write_text("PROPRIETAS_UPDATE_STRATEGY=pull\n", encoding="utf-8")
    res, status, _ = _run(app, {"version": "2026.10.004", "by": "x"})
    journal = (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert "docker image prune -f" in journal and "builder prune" not in journal
