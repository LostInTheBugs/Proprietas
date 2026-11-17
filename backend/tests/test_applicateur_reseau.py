"""Applicateur de mises à jour : coupure réseau pendant le téléchargement de l'image.

Cas réel (ionos02, 17/11/2026, mise à jour 2026.11.022 → 2026.11.028) : `docker compose pull backend` a
échoué sur « Get https://ghcr.io/v2/: TLS handshake timeout ». Deux défauts :
1. aucune nouvelle tentative, alors que ghcr.io répondait normalement quelques minutes plus tard ;
2. le dépôt est resté sur le tag 2026.11.028 (fichier VERSION compris) alors que 2026.11.022 était en
   service : la mise à jour suivante aurait pris 2026.11.028 pour la version « d'avant », et supprimé
   l'image de la vraie version précédente (plus de retour arrière possible).

Règles :
- `docker compose pull` est retenté 3 fois en tout, avec une pause (15 s puis 45 s ; réglable par
  PROPRIETAS_PULL_PAUSES pour les essais), sur toute erreur ;
- si la mise à jour échoue AVANT le redémarrage des conteneurs, le dépôt revient au tag en service et le
  .env à sa version : tout est comme avant la demande ;
- si elle échoue après (nouvelle version démarrée mais pas en bonne santé), le dépôt reste sur la nouvelle
  version, celle des conteneurs (comportement inchangé ; le retour arrière reste à la main).
"""
import json

from tests.test_deux_versions import FAUX_DOCKER, _depot, _en_service, _journal, _lancer

PANNE_PULL = r'''
case "$*" in
  "compose pull backend")
    n=$(cat "$FAUX_COMPTEUR" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAUX_COMPTEUR"
    if [ "$n" -le "$FAUX_ECHECS_PULL" ]; then echo 'Get "https://ghcr.io/v2/": net/http: TLS handshake timeout' >&2; exit 1; fi ;;
esac
'''


def _docker_en_panne(monkeypatch, tmp_path, echecs: int):
    import tests.test_deux_versions as td
    monkeypatch.setattr(td, "FAUX_DOCKER", FAUX_DOCKER.replace("echo \"$*\" >> \"$FAUX_JOURNAL\"\n",
                                                               "echo \"$*\" >> \"$FAUX_JOURNAL\"\n" + PANNE_PULL, 1))
    monkeypatch.setenv("FAUX_ECHECS_PULL", str(echecs))
    monkeypatch.setenv("FAUX_COMPTEUR", str(tmp_path / "compteur"))
    monkeypatch.setenv("PROPRIETAS_PULL_PAUSES", "0,0")


def test_coupure_passagere_le_telechargement_est_retente(tmp_path, monkeypatch):
    _docker_en_panne(monkeypatch, tmp_path, echecs=2)
    app = _depot(tmp_path)
    _en_service(app, "2026.11.001")
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.002", "by": "x"})
    assert res.returncode == 0, res.stderr
    assert status["result"] == "ok" and status["applied"] == "2026.11.002"
    assert docker.count("compose pull backend") == 3
    journal = _journal(app)
    assert journal.count("nouvel essai dans") == 2 and "TLS handshake timeout" in journal
    assert status["precedente"]["version"] == "2026.11.001"


def test_coupure_durable_tout_revient_comme_avant(tmp_path, monkeypatch):
    _docker_en_panne(monkeypatch, tmp_path, echecs=9)
    app = _depot(tmp_path)
    _en_service(app, "2026.11.001")
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.002", "by": "x"})
    assert res.returncode == 1
    assert status["result"].startswith("échec") and "TLS handshake timeout" in status["result"]
    assert docker.count("compose pull backend") == 3
    assert not [l for l in docker if l.startswith("compose up")]            # rien n'a été redémarré
    # Le dépôt et le .env sont revenus à la version en service.
    assert (app / "VERSION").read_text().strip() == "2026.11.001"
    assert "PROPRIETAS_VERSION=2026.11.001" in (app / ".env").read_text()
    assert "dépôt remis sur 2026.11.001" in _journal(app)
    # La demande suivante part donc de la bonne version « d'avant ».
    monkeypatch.setenv("FAUX_ECHECS_PULL", "0")
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.002", "by": "x"})
    assert res.returncode == 0 and status["precedente"]["version"] == "2026.11.001"


def test_echec_apres_le_redemarrage_le_depot_suit_les_conteneurs(tmp_path):
    app = _depot(tmp_path)
    _en_service(app, "2026.11.001")
    res, status, docker = _lancer(tmp_path, app, {"version": "2026.11.002", "by": "x"}, en_panne="2026.11.002")
    assert res.returncode == 1
    assert [l for l in docker if l.startswith("compose up")]                # la nouvelle version a démarré
    assert (app / "VERSION").read_text().strip() == "2026.11.002"
