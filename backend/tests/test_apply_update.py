"""Applicateur de l'hôte (deploy/apply-update.py) en --dry-run, sur une copie isolée :
battement de cœur, refus des versions invalides, tag inexistant, dry-run complet."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

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
