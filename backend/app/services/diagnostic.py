"""Diagnostic « profil internet » — l'exposition est-elle réelle et protégée ?

Chaque vérification est best-effort et renvoie un item {id, label, statut, detail}
avec statut ∈ ok | attention | echec | ignore. Aucune exception ne remonte : un
check en échec devient un item « echec » avec le détail.

Les seams testables : `_fetch`, `_ip_publique`, `_test_rate_limit`
(monkeypatchés dans les tests — aucun accès réseau réel).
"""
import json
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro

UA = "Proprietas-Diagnostic/1.0"
DELAI = 10  # secondes


def item(ident: str, label: str, statut: str, detail: str = "") -> dict:
    return {"id": ident, "label": label, "statut": statut, "detail": detail}


# ---------- Seams réseau (monkeypatchés dans les tests) ----------

def _fetch(url: str, timeout: float = DELAI) -> tuple[int, dict, bytes]:
    """GET avec User-Agent navigateur (Cloudflare refuse les UA techniques)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # certificat vérifié
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(4096)


def _ip_publique() -> str:
    """IP publique sortante de la machine (2 services, silencieux en cas d'échec)."""
    for url, extract in (
        ("https://api.ipify.org?format=json", lambda body: json.loads(body).get("ip", "")),
        ("https://ifconfig.me/ip", lambda body: body.strip()),
    ):
        try:
            _, _, body = _fetch(url, timeout=6)
            ip = extract(body.decode("utf-8", "ignore"))
            if ip:
                return ip
        except Exception:
            continue
    return ""


def _test_rate_limit(url: str) -> tuple[bool, str]:
    """6 tentatives de connexion bidon → le serveur DOIT répondre 429 à la fin."""
    email = f"diag-{secrets.token_hex(6)}@invalid.example"
    code = 0
    try:
        for _ in range(6):
            req = urllib.request.Request(
                url + "/api/auth/login",
                data=json.dumps({"email": email, "password": "x"}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": UA},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
    except Exception as e:  # réseau coupé en cours de test…
        return False, f"test impossible : {e}"[:200]
    if code == 429:
        return True, "5 tentatives bloquées, la 6e répond 429 (limiteur actif)"
    return False, f"attendu 429 après 5 échecs, reçu HTTP {code}"


def _jours_certificat(host: str) -> int | None:
    """Jours restants avant expiration du certificat TLS (None si illisible)."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                cert = ss.getpeercert()
        return int((ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400)
    except Exception:
        return None


# ---------- Diagnostic ----------

def lancer_diagnostic(db: Session, copro: Copropriete, instance) -> list[dict]:
    resultats: list[dict] = []
    url = (instance.public_url or "").strip().rstrip("/")
    host = urlparse(url).hostname if url else None

    resultats.append(item(
        "url", "URL publique configurée",
        "ok" if url else "echec",
        url or "Renseignez l'adresse publique (ex. https://copro.exemple.fr).",
    ))

    # 2. Application joignable par son URL publique (certificat TLS vérifié par urllib)
    headers: dict = {}
    joignable = False
    https_ok = False
    if url:
        try:
            statut, headers, corps = _fetch(url + "/api/health")
            joignable = statut == 200 and b"Proprietas" in corps
            if not joignable:
                resultats.append(item("https", "Application joignable (HTTPS)", "echec",
                                      f"HTTP {statut} sur {url}/api/health"))
            elif not url.startswith("https://"):
                resultats.append(item("https", "Application joignable (HTTPS)", "echec",
                                      "répond en HTTP — échanges non chiffrés : activez le "
                                      "profil internet (proxy TLS) ou un tunnel"))
            else:
                resultats.append(item("https", "Application joignable (HTTPS)", "ok",
                                      f"HTTP {statut} — certificat TLS vérifié"))
                https_ok = True
        except urllib.error.URLError as e:
            resultats.append(item("https", "Application joignable (HTTPS)", "echec",
                                  f"{getattr(e, 'reason', e)}"[:300]))
        except Exception as e:
            resultats.append(item("https", "Application joignable (HTTPS)", "echec", str(e)[:300]))
    else:
        resultats.append(item("https", "Application joignable (HTTPS)", "ignore", "URL manquante"))

    # 3. Expiration du certificat
    if https_ok and host:
        jours = _jours_certificat(host)
        if jours is None:
            resultats.append(item("cert", "Certificat TLS", "ignore", "expiration indétectable"))
        elif jours < 0:
            resultats.append(item("cert", "Certificat TLS", "echec", "certificat EXPIRÉ"))
        elif jours < 15:
            resultats.append(item("cert", "Certificat TLS", "attention",
                                  f"expire dans {jours} jours"))
        else:
            resultats.append(item("cert", "Certificat TLS", "ok", f"expire dans {jours} jours"))
    else:
        resultats.append(item("cert", "Certificat TLS", "ignore", ""))

    # 4. DNS : le domaine pointe-t-il vers ce serveur (ou un proxy ?)
    if host:
        try:
            adresses = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        except socket.gaierror:
            adresses = []
        if not adresses:
            resultats.append(item("dns", "DNS du domaine", "echec",
                                  f"« {host} » ne résout pas — vérifiez le record DNS."))
        else:
            ip_pub = _ip_publique()
            proxy_cf = "cloudflare" in (headers.get("server", "") + headers.get("cf-ray", "")).lower()
            if ip_pub and ip_pub in adresses:
                resultats.append(item("dns", "DNS du domaine", "ok",
                                      f"« {host} » pointe vers ce serveur ({ip_pub})"))
            elif proxy_cf:
                resultats.append(item("dns", "DNS du domaine", "ok",
                                      f"« {host} » → {adresses[0]} (proxy Cloudflare — origine non exposée)"))
            elif ip_pub:
                resultats.append(item("dns", "DNS du domaine", "attention",
                                      f"« {host} » résout vers {adresses[0]} ; ce serveur sort en {ip_pub} (proxy ?)"))
            else:
                resultats.append(item("dns", "DNS du domaine", "attention",
                                      f"« {host} » résout vers {adresses[0]} (IP du serveur indéterminable)"))
    else:
        resultats.append(item("dns", "DNS du domaine", "ignore", ""))

    # 5. En-têtes de sécurité servis par l'application
    if joignable:
        manquants = [h for h in ("x-content-type-options", "content-security-policy")
                     if h not in headers]
        if manquants:
            resultats.append(item("headers", "En-têtes de sécurité", "echec",
                                  "manquants : " + ", ".join(manquants) + " — mettez à jour l'application"))
        else:
            resultats.append(item("headers", "En-têtes de sécurité", "ok",
                                  "CSP et protection MIME présentes"))
    else:
        resultats.append(item("headers", "En-têtes de sécurité", "ignore", ""))

    # 6. Limiteur anti-force brute effectif (bout en bout, compte bidon)
    if joignable:
        ok_rl, detail_rl = _test_rate_limit(url)
        resultats.append(item("ratelimit", "Limiteur anti-force brute", "ok" if ok_rl else "echec", detail_rl))
    else:
        resultats.append(item("ratelimit", "Limiteur anti-force brute", "ignore", ""))

    # 7. Couverture 2FA des comptes de la copropriété active
    resultats.append(_check_2fa(db, copro))

    return resultats


def _check_2fa(db: Session, copro: Copropriete) -> dict:
    politique = copro.totp_policy or "off"
    comptes = (db.query(User)
               .join(UserCopro, UserCopro.user_id == User.id)
               .filter(UserCopro.copropriete_id == copro.id, User.is_demo == False)  # noqa: E712
               .all())
    if politique == "off":
        return item("2fa", "Double authentification", "attention",
                    "politique désactivée — recommandé : « syndic » au minimum")
    concernes = [u for u in comptes if politique == "all" or u.role == "syndic"]
    sans = [u for u in concernes if not u.totp_enabled]
    proteges = len(concernes) - len(sans)
    if sans:
        return item("2fa", "Double authentification", "echec",
                    f"{proteges}/{len(concernes)} comptes protégés — sans 2FA : "
                    + ", ".join(u.email for u in sans))
    return item("2fa", "Double authentification", "ok",
                f"{proteges}/{len(concernes)} comptes protégés (politique « {politique} »)")
