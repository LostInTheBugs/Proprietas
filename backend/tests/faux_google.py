"""Faux Google (jetons OAuth + API Drive v3) en mémoire, pour httpx.MockTransport.

Calé sur la documentation de Google (17/11/2026) : jeton par POST https://oauth2.googleapis.com/token
(authorization_code → refresh_token ; refresh_token → access_token ; invalid_grant), révocation,
files.list avec q (« 'id' in parents », name =, mimeType = / !=, trashed = false ; \\' échappé),
files.create (dossier), envoi « resumable » (POST → Location, PUT → 200 + id), alt=media, PATCH
{trashed}, DELETE, about. N'est PAS une preuve que le vrai service se comporte ainsi.
"""
import itertools
import json
import re
from urllib.parse import parse_qs

import httpx

DOSSIER = "application/vnd.google-apps.folder"
CODE = "code-valide"


class FauxGoogle:
    def __init__(self, compte="syndic@exemple.fr"):
        self.compte = compte
        self.n = itertools.count(1)
        self.fichiers: dict[str, dict] = {}         # id → {name, parent, mimeType, data, trashed}
        self.renouvellements: set[str] = set()
        self.titulaires: dict[str, str] = {}        # jeton de renouvellement → compte Google qui l'a accordé
        self.acces: dict[str, str] = {}             # jeton d'accès → jeton de renouvellement
        self.revoques: list[str] = []
        self.requetes: list[tuple[str, str]] = []
        self.jetons_demandes = 0
        self.sessions: dict[str, dict] = {}
        self.panne = False
        self.plein = False
        self.portee_refusee = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._repondre)

    # --- aides pour les tests
    def chemin(self, ident: str) -> str:
        f, parties = self.fichiers[ident], []
        while f:
            parties.append(f["name"])
            f = self.fichiers.get(f["parent"])
        return "/".join(reversed(parties))

    def chemins(self) -> list[str]:
        return sorted(self.chemin(i) for i, f in self.fichiers.items() if f["mimeType"] != DOSSIER and not f["trashed"])

    def contenu(self, chemin: str) -> bytes:
        [f] = [f for i, f in self.fichiers.items() if self.chemin(i) == chemin and not f["trashed"]]
        return f["data"]

    def deplacer(self, chemin: str, dossier_id: str | None = None, nom: str | None = None) -> None:
        [i] = [i for i, f in self.fichiers.items() if self.chemin(i) == chemin and not f["trashed"]]
        if nom:
            self.fichiers[i]["name"] = nom
        if dossier_id:
            self.fichiers[i]["parent"] = dossier_id

    def corbeille(self) -> list[str]:
        return sorted(self.chemin(i) for i, f in self.fichiers.items() if f["trashed"])

    # --- serveur
    def _repondre(self, r: httpx.Request) -> httpx.Response:
        if self.panne:
            raise httpx.ConnectError("connexion refusée", request=r)
        url = r.url
        self.requetes.append((r.method, url.host + url.path))
        if url.host == "oauth2.googleapis.com":
            return self._oauth(r)
        if url.host != "www.googleapis.com":
            return httpx.Response(404)
        jeton = (r.headers.get("authorization") or "").removeprefix("Bearer ")
        if jeton not in self.acces or self.acces[jeton] not in self.renouvellements:
            return httpx.Response(401, json={"error": {"code": 401, "errors": [{"reason": "authError"}]}})
        p = url.path
        if p == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"emailAddress": self.compte, "displayName": "Syndic"}})
        if p == "/drive/v3/files" and r.method == "GET":
            return self._lister(dict(url.params))
        if p == "/drive/v3/files" and r.method == "POST":
            corps = json.loads(r.content)
            ident = self._creer(corps["name"], corps["parents"][0], corps.get("mimeType", "application/octet-stream"))
            return httpx.Response(200, json={"id": ident})
        if p == "/upload/drive/v3/files" and r.method == "POST":
            assert url.params.get("uploadType") == "resumable"
            corps = json.loads(r.content)
            session = f"sess-{next(self.n)}"
            self.sessions[session] = {"name": corps["name"], "parent": corps["parents"][0],
                                      "taille": int(r.headers["x-upload-content-length"])}
            return httpx.Response(200, headers={"Location": f"https://www.googleapis.com/upload/session/{session}"})
        if p.startswith("/upload/session/") and r.method == "PUT":
            s = self.sessions.pop(p.rsplit("/", 1)[1])
            if self.plein:
                return httpx.Response(403, json={"error": {"errors": [{"reason": "storageQuotaExceeded"}]}})
            donnees = r.read()
            assert len(donnees) == s["taille"] == int(r.headers["content-length"])
            return httpx.Response(200, json={"id": self._creer(s["name"], s["parent"], "application/octet-stream", donnees)})
        m = re.fullmatch(r"/drive/v3/files/([^/]+)", p)
        if m:
            f = self.fichiers.get(m.group(1))
            if f is None:
                return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
            if r.method == "GET" and url.params.get("alt") == "media":
                return httpx.Response(200, content=f["data"])
            if r.method == "PATCH":
                f.update(trashed=bool(json.loads(r.content).get("trashed")))
                return httpx.Response(200, json={"id": m.group(1)})
            if r.method == "DELETE":
                del self.fichiers[m.group(1)]
                return httpx.Response(204)
        return httpx.Response(400)

    def _oauth(self, r: httpx.Request) -> httpx.Response:
        champs = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
        if r.url.path == "/revoke":
            jeton = champs.get("token", "")
            self.revoques.append(jeton)
            # Comme Google : révoquer un jeton retire l'autorisation entière (ce compte, cette application),
            # donc aussi les autres jetons de renouvellement accordés par le même compte.
            compte = self.titulaires.get(jeton)
            self.renouvellements -= {rt for rt, c in self.titulaires.items() if c == compte} | {jeton}
            return httpx.Response(200)
        assert r.url.path == "/token"
        self.jetons_demandes += 1
        if champs.get("client_secret") != "secret-appli":
            return httpx.Response(401, json={"error": "invalid_client"})
        if champs.get("grant_type") == "authorization_code":
            if champs.get("code") != CODE:
                return httpx.Response(400, json={"error": "invalid_grant"})
            rt = f"rt-{next(self.n)}"
            self.renouvellements.add(rt)
            self.titulaires[rt] = self.compte
            return httpx.Response(200, json={"access_token": self._acces(rt), "expires_in": 3599, "refresh_token": rt,
                                             "scope": "openid" if self.portee_refusee else
                                             "https://www.googleapis.com/auth/drive.file", "token_type": "Bearer"})
        if champs.get("grant_type") == "refresh_token":
            if champs.get("refresh_token") not in self.renouvellements:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            return httpx.Response(200, json={"access_token": self._acces(champs["refresh_token"]), "expires_in": 3599,
                                             "token_type": "Bearer"})
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _acces(self, rt: str) -> str:
        at = f"at-{next(self.n)}"
        self.acces[at] = rt
        return at

    def _creer(self, nom, parent, mime, data=b"") -> str:
        assert parent == "root" or parent in self.fichiers, parent
        ident = f"id{next(self.n)}"
        self.fichiers[ident] = {"name": nom, "parent": parent, "mimeType": mime, "data": data, "trashed": False}
        return ident

    def _lister(self, params: dict) -> httpx.Response:
        q = params["q"]
        val = r"'((?:[^'\\]|\\.)*)'"
        texte = lambda v: re.sub(r"\\(.)", r"\1", v)          # noqa: E731
        parent = texte(re.search(val + r" in parents", q).group(1))
        nom = re.search(r"name = " + val, q)
        mime_eq = re.search(r"mimeType = " + val, q)
        mime_ne = re.search(r"mimeType != " + val, q)
        assert "trashed = false" in q
        res = []
        for i, f in self.fichiers.items():
            if f["parent"] != parent or f["trashed"]:
                continue
            if nom and f["name"] != texte(nom.group(1)):
                continue
            if mime_eq and f["mimeType"] != texte(mime_eq.group(1)):
                continue
            if mime_ne and f["mimeType"] == texte(mime_ne.group(1)):
                continue
            item = {"id": i, "name": f["name"], "mimeType": f["mimeType"]}
            if f["mimeType"] != DOSSIER:
                item["size"] = str(len(f["data"]))
            res.append(item)
        return httpx.Response(200, json={"files": res})
