"""Applicateur : garder deux versions (la nouvelle et la précédente) et revenir en arrière.

Règles retenues :
- après une mise à jour réussie en stratégie « pull », les images de l'application sont supprimées
  sauf celles de la nouvelle version et de la version précédente ; l'état indique la précédente ;
- l'administrateur peut ne pas la conserver (`oublier_precedente` : image supprimée) ou y revenir
  (`rollback`) ;
- le retour arrière sauvegarde la base, ramène les migrations à la tête de l'ancienne version (lue
  dans son tag git), remet le dépôt sur ce tag et relance ; il n'est permis que vers la version
  précédente conservée ;
- une action inconnue est refusée.
"""
import json
import subprocess
import sys

import pytest

from tests.test_apply_update import _app, _module, _run

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="applicateur Linux uniquement")

MIGRATION = '''revision: str = "{rev}"
down_revision: Union[str, Sequence[str], None] = {down}
'''


def _commit(app, message, tag=None):
    subprocess.run(["git", "add", "-A"], cwd=app, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message],
                   cwd=app, check=True)
    if tag:
        subprocess.run(["git", "tag", tag], cwd=app, check=True)


def _depot(tmp_path):
    """Deux versions : 2026.11.001 (migrations a → b) puis 2026.11.002 (ajoute c)."""
    app = _app(tmp_path)
    versions = app / "backend" / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a_init.py").write_text(MIGRATION.format(rev="aaa111", down="None"), encoding="utf-8")
    (versions / "b_suite.py").write_text(MIGRATION.format(rev="bbb222", down="'aaa111'"), encoding="utf-8")
    (app / "VERSION").write_text("2026.11.001\n", encoding="utf-8")
    _commit(app, "v1", tag="2026.11.001")
    (versions / "c_nouveau.py").write_text(MIGRATION.format(rev="ccc333", down='"bbb222"'), encoding="utf-8")
    (app / "VERSION").write_text("2026.11.002\n", encoding="utf-8")
    _commit(app, "v2", tag="2026.11.002")
    (app / ".env").write_text("PROPRIETAS_UPDATE_STRATEGY=pull\n", encoding="utf-8")
    return app


def _etat(app, **valeurs):
    (app / "data" / "updates" / "update-applier.json").write_text(json.dumps(valeurs), encoding="utf-8")


def _journal(app):
    return (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")


def test_images_a_supprimer():
    mod = _module()
    lignes = ["2026.11.013\tabc", "2026.11.012\tdef", "2026.11.011\t123", "latest\tabc", "<none>\t999", ""]
    assert mod.images_a_supprimer(lignes, {"2026.11.013", "2026.11.012"}) == ["2026.11.011", "latest"]


def test_choisir_precedente():
    """Initialisation (premier passage du nouvel applicateur) : la plus récente des versions plus anciennes."""
    mod = _module()
    lignes = ["2026.11.013\ta", "2026.11.012\tb", "2026.10.024\tc", "2026.11.011-c2\td", "latest\te", "<none>\tf"]
    assert mod.choisir_precedente(lignes, "2026.11.013") == "2026.11.012"
    assert mod.choisir_precedente(lignes, "2026.11.012") == "2026.11.011-c2"
    assert mod.choisir_precedente(["2026.11.013\ta"], "2026.11.013") == ""


def test_tete_alembic_lue_dans_le_tag(tmp_path, monkeypatch):
    app = _depot(tmp_path)
    mod = _module()
    monkeypatch.setattr(mod, "APP_DIR", app)
    monkeypatch.setattr(mod, "LOG", tmp_path / "journal.log")
    assert mod.tete_alembic("2026.11.001") == "bbb222"
    assert mod.tete_alembic("2026.11.002") == "ccc333"


def test_tete_alembic_du_vrai_depot(monkeypatch, tmp_path):
    """Les migrations réelles du dépôt ont une seule tête (sinon le retour arrière serait impossible)."""
    mod = _module()
    monkeypatch.setattr(mod, "LOG", tmp_path / "journal.log")
    tete = mod.tete_alembic("HEAD")
    assert list((mod.APP_DIR / "backend" / "alembic" / "versions").glob(f"{tete}_*.py")), tete


def test_mise_a_jour_garde_la_nouvelle_et_la_precedente(tmp_path):
    app = _depot(tmp_path)
    subprocess.run(["git", "checkout", "-q", "2026.11.001"], cwd=app, check=True)
    res, status, _ = _run(app, {"version": "2026.11.002", "by": "x"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "seules 2026.11.001, 2026.11.002 seraient gardées" in _journal(app)


def test_retour_arriere(tmp_path):
    app = _depot(tmp_path)                       # en service : 2026.11.002
    _etat(app, precedente={"version": "2026.11.001", "image": True})
    res, status, demande = _run(app, {"version": "2026.11.001", "by": "x", "action": "rollback"})
    assert res.returncode == 0, res.stdout + res.stderr
    journal = _journal(app)
    assert "retour arrière de 2026.11.002 vers 2026.11.001" in journal
    assert "sauvegarde →" in journal
    # La base est ramenée à la tête de l'ancienne version AVANT de changer de code.
    i_down = journal.index("alembic downgrade bbb222")
    i_checkout = journal.index("git checkout --quiet 2026.11.001")
    assert "sauvegarde →" in journal[:i_down] and i_down < i_checkout
    assert "docker compose up -d --no-build" in journal[i_checkout:]
    assert status["result"] == "dry-run ok" and demande


def test_retour_arriere_seulement_vers_la_precedente(tmp_path):
    app = _depot(tmp_path)
    _etat(app, precedente={"version": "2026.11.001", "image": True})
    res, status, demande = _run(app, {"version": "2026.10.024", "by": "x", "action": "rollback"})
    assert res.returncode == 1 and "précédente" in status["result"] and not demande
    _etat(app)                                   # aucune version précédente conservée
    res, status, _ = _run(app, {"version": "2026.11.001", "by": "x", "action": "rollback"})
    assert res.returncode == 1
    assert "downgrade" not in _journal(app) and "sauvegarde →" not in _journal(app)


def test_ne_pas_conserver_la_precedente(tmp_path):
    app = _depot(tmp_path)
    _etat(app, precedente={"version": "2026.11.001", "image": True})
    res, status, _ = _run(app, {"version": "2026.11.001", "by": "x", "action": "oublier_precedente"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "docker rmi ghcr.io/lostinthebugs/proprietas:2026.11.001" in _journal(app)


def test_action_inconnue_refusee(tmp_path):
    app = _depot(tmp_path)
    res, status, demande = _run(app, {"version": "2026.11.001", "by": "x", "action": "rm -rf"})
    assert res.returncode == 1 and "action refusée" in status["result"] and not demande


# ---------------------------------------------------------------- sans dry-run, docker simulé
FAUX_DOCKER = r'''#!/bin/bash
echo "$*" >> "$FAUX_JOURNAL"
case "$*" in
  "images "*) printf '2026.11.002\tid2\n2026.11.001\tid1\n2026.10.009\tid0\nlatest\tidx\n<none>\tidn\n' ;;
  "image inspect"*) echo 304000000 ;;
  "compose exec -T db pg_dump"*) head -c 2000 /dev/zero | tr '\0' 'x' ;;
  "compose exec -T backend alembic current") echo "ccc333 (head)" ;;
  "compose exec -T backend python -c"*)
    v=$(grep '^PROPRIETAS_VERSION=' .env | cut -d= -f2)
    if [ -n "$FAUX_EN_PANNE" ] && [ "$v" = "$FAUX_EN_PANNE" ]; then echo "502"; else echo "$v"; fi ;;
esac
exit 0
'''


def _lancer(tmp_path, app, request, en_panne=""):
    import os
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
    (bin_ / "docker").chmod(0o755)
    (app / "data" / "updates" / "update-request.json").write_text(json.dumps(request), encoding="utf-8")
    journal = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAUX_JOURNAL": str(journal),
           "FAUX_EN_PANNE": en_panne, "PROPRIETAS_HEALTH_TIMEOUT_S": "1"}
    res = subprocess.run([sys.executable, "deploy/apply-update.py"], cwd=app, capture_output=True, text=True, env=env)
    status = json.loads((app / "data" / "updates" / "update-applier.json").read_text(encoding="utf-8"))
    return res, status, journal.read_text(encoding="utf-8").splitlines()


def _en_service(app, version):
    subprocess.run(["git", "checkout", "-q", version], cwd=app, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(app)], cwd=app, check=False)   # git fetch origin
    (app / ".env").write_text(f"PROPRIETAS_UPDATE_STRATEGY=pull\nPROPRIETAS_VERSION={version}\n", encoding="utf-8")


def test_reel_mise_a_jour_supprime_les_anciennes_images(tmp_path):
    app = _depot(tmp_path)
    _en_service(app, "2026.11.001")
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.002", "by": "x"})
    assert res.returncode == 0, res.stdout + res.stderr
    rmi = [l for l in docker if l.startswith("rmi ")]
    assert rmi == ["rmi ghcr.io/lostinthebugs/proprietas:2026.10.009", "rmi ghcr.io/lostinthebugs/proprietas:latest"]
    assert status["precedente"] == {"version": "2026.11.001", "image": True, "octets": 304000000}


def test_reel_retour_arriere(tmp_path):
    app = _depot(tmp_path)
    _en_service(app, "2026.11.002")
    _etat(app, precedente={"version": "2026.11.001", "image": True})
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.001", "by": "x", "action": "rollback"})
    assert res.returncode == 0, res.stdout + res.stderr
    assert "compose exec -T backend alembic downgrade bbb222" in docker
    assert (app / "VERSION").read_text().strip() == "2026.11.001"
    assert "PROPRIETAS_VERSION=2026.11.001" in (app / ".env").read_text()
    # La version quittée devient la précédente : on peut y revenir (ou l'oublier).
    assert status["applied"] == "2026.11.001" and status["precedente"]["version"] == "2026.11.002"
    assert not (app / "data" / "updates" / "update-request.json").exists()


def test_reel_retour_arriere_en_echec_revient_a_la_version_actuelle(tmp_path):
    app = _depot(tmp_path)
    _en_service(app, "2026.11.002")
    _etat(app, precedente={"version": "2026.11.001", "image": True})
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.001", "by": "x", "action": "rollback"},
                                  en_panne="2026.11.001")
    assert res.returncode == 1
    assert status["result"].startswith("échec du retour arrière")
    assert (app / "VERSION").read_text().strip() == "2026.11.002"
    assert "PROPRIETAS_VERSION=2026.11.002" in (app / ".env").read_text()
    # Les migrations annulées sont réappliquées.
    assert docker.index("compose exec -T backend alembic downgrade bbb222") < docker.index(
        "compose exec -T backend alembic upgrade head")


def test_reel_premier_battement_initialise_les_versions(tmp_path):
    app = _depot(tmp_path)
    _en_service(app, "2026.11.002")
    (app / "data" / "updates" / "update-request.json").unlink(missing_ok=True)
    import os
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
    (bin_ / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAUX_JOURNAL": str(tmp_path / "docker.log")}
    for _ in range(2):          # deux battements : l'initialisation n'est faite qu'une fois
        subprocess.run([sys.executable, "deploy/apply-update.py"], cwd=app, check=True, env=env, capture_output=True)
    docker = (tmp_path / "docker.log").read_text().splitlines()
    assert [l for l in docker if l.startswith("rmi ")] == [
        "rmi ghcr.io/lostinthebugs/proprietas:2026.10.009", "rmi ghcr.io/lostinthebugs/proprietas:latest"]
    journal = (app / "data" / "updates" / "update.log").read_text(encoding="utf-8")
    assert journal.count("initialisation : versions gardées 2026.11.002 et 2026.11.001") == 1
    status = json.loads((app / "data" / "updates" / "update-applier.json").read_text())
    assert status["precedente"]["version"] == "2026.11.001"


def test_reel_precedente_egale_a_la_version_en_service_retrie(tmp_path):
    """Cas réel : la dernière mise à jour a été faite par un ancien applicateur ; l'état indique comme
    « précédente » la version en service. Le battement suivant refait le tri et la corrige."""
    import os
    app = _depot(tmp_path)
    _en_service(app, "2026.11.002")
    _etat(app, precedente={"version": "2026.11.002", "image": True})
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
    (bin_ / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAUX_JOURNAL": str(tmp_path / "docker.log")}
    subprocess.run([sys.executable, "deploy/apply-update.py"], cwd=app, check=True, env=env, capture_output=True)
    status = json.loads((app / "data" / "updates" / "update-applier.json").read_text())
    assert status["precedente"]["version"] == "2026.11.001"
