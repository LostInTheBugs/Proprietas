#!/usr/bin/env python3
"""Exercice de reprise : perte du serveur, restauration depuis le drive, panne du drive.

Joue de bout en bout, sur deux instances de test vides (A = le serveur « perdu », B = le serveur neuf)
et un drive WebDAV de test, ce que ferait un syndic :

  1. A : premier compte, copropriété, documents déposés sur le serveur ;
  2. A : drive branché, documents déplacés dessus, un document déposé directement sur le drive ;
  3. A : sauvegarde chiffrée sur le drive ; puis A est détruit (commande PERDRE_A) ;
  4. B : premier compte (même e-mail), sauvegarde récupérée sur le drive et importée ;
  5. B : drive rebranché sur le même dossier ; chaque document relu et comparé (SHA-256) à l'original ;
  6. panne du drive (COUPER_DRIVE) : lecture, dépôt, sauvegarde, test, passage du planificateur
     (PLANIFICATEUR_B) ; messages relevés ; puis RALLUMER_DRIVE et vérification du retour à la normale.

Bibliothèque standard seulement. Réglages par variables d'environnement :
  URL_A, URL_B                adresses des instances (ex. http://192.168.10.196:8093)
  DAV_URL, DAV_USER, DAV_MDP  drive WebDAV (adresse vue par les instances ET par ce script)
  PERDRE_A, COUPER_DRIVE, RALLUMER_DRIVE, PLANIFICATEUR_B : commandes shell (PLANIFICATEUR_B est
                               facultative : lance un passage des sauvegardes automatiques sur B)
Sortie : une ligne par vérification (« OK » ou « ÉCART »), puis le bilan. Code retour 1 s'il y a un écart.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

E = os.environ
URL_A, URL_B = E["URL_A"].rstrip("/"), E["URL_B"].rstrip("/")
DAV, DAV_USER, DAV_MDP = E["DAV_URL"].rstrip("/") + "/", E["DAV_USER"], E["DAV_MDP"]
RUN = time.strftime("%Y%m%d-%H%M%S")
DOSSIER = f"Proprietas/Reprise {RUN}"
EMAIL, MDP = "syndic.reprise@exemple.test", "Reprise-Essai-2026!"
MDP_SAUVEGARDE = "Sauvegarde-Essai-2026"
ecarts: list[str] = []
verifs = 0


def verifier(ok: bool, texte: str) -> bool:
    global verifs
    verifs += 1
    print(("OK     " if ok else "ÉCART  ") + texte, flush=True)
    if not ok:
        ecarts.append(texte)
    return ok


def etape(titre: str) -> None:
    print(f"\n== {titre}", flush=True)


def shell(nom: str) -> None:
    cmd = E.get(nom, "")
    if not cmd:
        print(f"(pas de commande {nom})")
        return
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"$ {nom} → code {r.returncode}" + (f" : {(r.stdout + r.stderr).strip()[-300:]}" if r.returncode else ""))


# ---------------------------------------------------------------- HTTP
def http(methode, url, donnees=None, jeton=None, entetes=None, brut=False, delai=120):
    entetes = dict(entetes or {})
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    if isinstance(donnees, (dict, list)):
        donnees, entetes["Content-Type"] = json.dumps(donnees).encode(), "application/json"
    req = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            corps = r.read()
            return r.status, corps if brut else _json(corps)
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, {"detail": f"{type(e).__name__}: {e}"}


def _json(corps: bytes):
    try:
        return json.loads(corps)
    except ValueError:
        return {"brut": corps[:200].decode(errors="replace")}


def multipart(champs: dict, fichier: tuple[str, str, bytes]) -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    morceaux = []
    for k, v in champs.items():
        morceaux.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    champ, nom, contenu = fichier
    morceaux.append(f'--{limite}\r\nContent-Disposition: form-data; name="{champ}"; filename="{nom}"\r\n'
                    f"Content-Type: application/octet-stream\r\n\r\n".encode() + contenu + b"\r\n")
    morceaux.append(f"--{limite}--\r\n".encode())
    return b"".join(morceaux), f"multipart/form-data; boundary={limite}"


def deposer(base, jeton, libelle, categorie, nom, contenu):
    corps, type_ = multipart({"libelle": libelle, "categorie": categorie}, ("fichier", nom, contenu))
    return http("POST", f"{base}/api/documents", corps, jeton, {"Content-Type": type_})


def premier_compte(base) -> str:
    code, r = http("POST", f"{base}/api/auth/register", {"email": EMAIL, "password": MDP, "nom": "Reprise", "prenom": "Syndic"})
    if code == 403:                                  # instance déjà initialisée par un essai précédent
        code, r = http("POST", f"{base}/api/auth/login", {"email": EMAIL, "password": MDP})
    if not verifier(code == 200 and r.get("access_token"), f"{base} : compte syndic ({code})"):
        sys.exit(f"impossible d'ouvrir une session sur {base} : {r}")
    return r["access_token"]


def dav_get(chemin: str) -> tuple[int, bytes]:
    url = DAV + "/".join(urllib.parse.quote(s) for s in chemin.split("/"))
    auth = base64.b64encode(f"{DAV_USER}:{DAV_MDP}".encode()).decode()
    return http("GET", url, entetes={"Authorization": f"Basic {auth}"}, brut=True)


def attendre(base, chemin="/api/health", secondes=120) -> bool:
    fin = time.time() + secondes
    while time.time() < fin:
        if http("GET", base + chemin, delai=5)[0] == 200:
            return True
        time.sleep(3)
    return False


# ---------------------------------------------------------------- exercice
def main() -> int:
    print(f"Exercice de reprise {RUN} : A={URL_A} B={URL_B} drive={DAV} dossier « {DOSSIER} »")
    for base in (URL_A, URL_B):
        verifier(attendre(base), f"{base} répond")

    etape("1. Serveur A : copropriété et documents sur le serveur")
    ja = premier_compte(URL_A)
    nom_copro = f"Résidence Reprise {RUN}"
    code, _ = http("PUT", f"{URL_A}/api/copro", {"nom": nom_copro}, ja)
    verifier(code == 200, f"copropriété « {nom_copro} » ({code})")
    originaux: dict[str, str] = {}                  # libellé → sha256
    pieces = [("Facture électricité janvier", "facture", "elec.pdf", os.urandom(30_000)),
              ("Contrat d'entretien ascenseur", "contrat", "contrat.pdf", os.urandom(120_000)),
              ("Devis toiture — été", "devis", "devis.pdf", os.urandom(2_500_000)),
              ("PV AG 2026", "pv_ag", "pv.pdf", os.urandom(50_000)),
              ("Diagnostic amiante", "diagnostic", "diag.pdf", os.urandom(10_000))]
    for libelle, cat, nom, contenu in pieces:
        code, r = deposer(URL_A, ja, libelle, cat, nom, contenu)
        if verifier(code == 200 and r.get("emplacement") == "", f"dépôt « {libelle} » sur le serveur ({code})"):
            originaux[libelle] = hashlib.sha256(contenu).hexdigest()

    etape("2. Serveur A : drive branché, fichiers déplacés")
    drive = {"type": "webdav", "url": DAV, "utilisateur": DAV_USER, "mot_de_passe": DAV_MDP, "dossier": DOSSIER}
    code, r = http("POST", f"{URL_A}/api/drive/test", drive, ja)
    verifier(code == 200 and r.get("ok"), f"test du drive : {r.get('detail')}")
    code, r = http("PUT", f"{URL_A}/api/drive", drive, ja)
    verifier(code == 200 and r.get("type") == "webdav", f"drive branché ({code})")
    for _ in range(20):
        code, r = http("POST", f"{URL_A}/api/drive/deplacer", None, ja, delai=300)
        if code != 200 or not r.get("restants"):
            break
    verifier(code == 200 and r.get("restants") == 0, f"déplacement terminé ({code}, {r})")
    contenu = os.urandom(40_000)
    code, r = deposer(URL_A, ja, "Facture eau — après branchement", "facture", "eau.pdf", contenu)
    if verifier(code == 200 and r.get("emplacement") == "drive", f"dépôt direct sur le drive : {r.get('fichier')}"):
        originaux["Facture eau — après branchement"] = hashlib.sha256(contenu).hexdigest()
    code, r = http("GET", f"{URL_A}/api/drive/verification", jeton=ja)
    verifier(code == 200, f"vérification du drive sur A : {json.dumps(r, ensure_ascii=False)[:200]}")

    etape("3. Serveur A : sauvegarde chiffrée sur le drive, puis perte du serveur")
    code, r = http("PUT", f"{URL_A}/api/drive/sauvegarde", {"auto": True, "mot_de_passe": MDP_SAUVEGARDE}, ja)
    verifier(code == 200 and r["sauvegarde"]["auto"], f"sauvegarde chaque semaine, mot de passe choisi ({code})")
    code, r = http("POST", f"{URL_A}/api/drive/sauvegarde/maintenant", None, ja, delai=300)
    archive = r.get("fichier", "") if code == 200 else ""
    verifier(bool(archive), f"sauvegarde déposée : {archive} ({r.get('taille')} octets)" if archive else f"sauvegarde : {code} {r}")
    shell("PERDRE_A")
    verifier(http("GET", f"{URL_A}/api/health", delai=5)[0] != 200, "serveur A hors service")

    etape("4. Serveur B (neuf) : sauvegarde récupérée sur le drive et importée")
    code, zip_ = dav_get(f"{DOSSIER}/{archive}")       # « Sauvegardes/Sauvegarde AAAA-MM-JJ HHhMM.zip »
    if not verifier(code == 200 and zip_[:2] == b"PK", f"archive téléchargée depuis le drive ({code}, {len(zip_)} octets)"):
        sys.exit(f"impossible de poursuivre sans l'archive : {zip_}")
    nom_archive = archive.rsplit("/", 1)[-1]
    jb = premier_compte(URL_B)
    corps, type_ = multipart({"mot_de_passe": "mauvais-mot-de-passe"}, ("fichier", nom_archive, zip_))
    code, r = http("POST", f"{URL_B}/api/sauvegarde/import", corps, jb, {"Content-Type": type_}, delai=300)
    verifier(code in (400, 422), f"mauvais mot de passe refusé ({code} : {r.get('detail')})")
    corps, type_ = multipart({"mot_de_passe": MDP_SAUVEGARDE}, ("fichier", nom_archive, zip_))
    code, r = http("POST", f"{URL_B}/api/sauvegarde/import", corps, jb, {"Content-Type": type_}, delai=300)
    verifier(code == 200 and r.get("nom") == nom_copro, f"import : {json.dumps(r, ensure_ascii=False)[:250]}")
    cid = r.get("copropriete_id")
    code, r = http("POST", f"{URL_B}/api/auth/switch-copro/{cid}", None, jb)
    jb = r.get("access_token", jb)

    etape("5. Serveur B : drive rebranché, documents relus et comparés")
    code, etat = http("GET", f"{URL_B}/api/drive", jeton=jb)
    verifier(code == 200 and etat.get("type") == "" and etat.get("documents_sur_le_drive") == len(originaux),
             f"avant rebranchement : drive {etat.get('type') or 'non branché'}, {etat.get('documents_sur_le_drive')} "
             f"document(s) annoncés sur le drive, dossier attendu « {etat.get('dossier')} »")
    code, r = http("PUT", f"{URL_B}/api/drive", {**drive, "dossier": etat.get("dossier") or DOSSIER}, jb)
    verifier(code == 200 and r.get("type") == "webdav", f"drive rebranché sur le même dossier ({code} {r.get('detail', '')})")
    code, docs = http("GET", f"{URL_B}/api/documents", jeton=jb)
    verifier(code == 200 and len(docs) == len(originaux), f"{len(docs) if code == 200 else code} document(s) sur B")
    premier = None
    for d in docs if code == 200 else []:
        c, contenu = http("GET", f"{URL_B}/api/documents/{d['id']}/download", jeton=jb, brut=True, delai=300)
        identique = c == 200 and hashlib.sha256(contenu).hexdigest() == originaux.get(d["libelle"])
        verifier(identique, f"« {d['libelle']} » relu depuis le drive, identique à l'original ({c})")
        premier = premier or d
    code, r = http("GET", f"{URL_B}/api/drive/verification", jeton=jb)
    verifier(code == 200, f"vérification du drive sur B : {json.dumps(r, ensure_ascii=False)[:200]}")
    code, r = http("GET", f"{URL_B}/api/drive/sauvegardes", jeton=jb)
    verifier(code == 200 and any(s.get("fichier") == archive for s in (r if isinstance(r, list) else r.get("sauvegardes", []))),
             f"la sauvegarde de A est listée sur B ({code})")
    code, r = http("PUT", f"{URL_B}/api/drive/sauvegarde", {"auto": True, "mot_de_passe": MDP_SAUVEGARDE}, jb)
    verifier(code == 200, f"sauvegardes automatiques réactivées sur B ({code})")

    etape("6. Panne du drive")
    shell("COUPER_DRIVE")
    time.sleep(3)
    if premier:
        code, r = http("GET", f"{URL_B}/api/documents/{premier['id']}/download", jeton=jb, delai=120)
        verifier(code == 503, f"lecture pendant la panne : {code} « {r.get('detail') if isinstance(r, dict) else ''} »")
    contenu_panne = os.urandom(5_000)
    code, r = deposer(URL_B, jb, "Facture pendant la panne", "facture", "panne.pdf", contenu_panne)
    # Refusé (503), ou gardé sur le serveur « en attente du drive » si l'instance l'autorise (COPRO_DRIVE_ATTENTE_MO).
    verifier(code == 503 or (code == 200 and r.get("emplacement") == "attente"),
             f"dépôt pendant la panne : {code} « {r.get('detail') or r.get('emplacement')} »")
    en_attente = r.get("id") if code == 200 else None
    if en_attente:
        c, contenu = http("GET", f"{URL_B}/api/documents/{en_attente}/download", jeton=jb, brut=True)
        verifier(c == 200 and contenu == contenu_panne, f"dépôt en attente lisible pendant la panne ({c})")
    code, r = http("POST", f"{URL_B}/api/drive/sauvegarde/maintenant", None, jb, delai=120)
    verifier(code == 503, f"sauvegarde pendant la panne : {code} « {r.get('detail')} »")
    code, r = http("POST", f"{URL_B}/api/drive/test", {"type": "webdav", "url": DAV, "utilisateur": DAV_USER,
                                                     "mot_de_passe": "", "dossier": DOSSIER}, jb)
    verifier(code == 200 and not r.get("ok"), f"test du drive pendant la panne : « {r.get('detail')} »")
    if E.get("PLANIFICATEUR_B"):
        shell("PLANIFICATEUR_B")
        code, r = http("GET", f"{URL_B}/api/drive", jeton=jb)
        verifier(bool(r.get("sauvegarde", {}).get("erreur")),
                 f"échec de la sauvegarde automatique affiché dans Réglages : « {r.get('sauvegarde', {}).get('erreur')} »")
    code, r = http("GET", f"{URL_B}/api/health")
    verifier(code == 200, "l'application reste disponible pendant la panne du drive")
    shell("RALLUMER_DRIVE")
    ok = False
    for _ in range(40):
        c, r = http("POST", f"{URL_B}/api/drive/test", {"type": "webdav", "url": DAV, "utilisateur": DAV_USER,
                                                      "mot_de_passe": "", "dossier": DOSSIER}, jb)
        if c == 200 and r.get("ok"):
            ok = True
            break
        time.sleep(5)
    verifier(ok, "drive revenu (test de connexion)")
    if premier:
        c, contenu = http("GET", f"{URL_B}/api/documents/{premier['id']}/download", jeton=jb, brut=True)
        verifier(c == 200 and hashlib.sha256(contenu).hexdigest() == originaux.get(premier["libelle"]),
                 f"lecture après la panne : « {premier['libelle']} » identique ({c})")
    if en_attente:
        code, r = http("POST", f"{URL_B}/api/drive/ranger-attente", None, jb, delai=300)
        # (le planificateur, toutes les 5 min, a pu le ranger juste avant : « deplaces » vaut alors 0)
        verifier(code == 200 and r.get("restants") == 0, f"dépôts en attente rangés sur le drive ({code}, {r})")
        code, docs = http("GET", f"{URL_B}/api/documents", jeton=jb)
        d = next((x for x in docs if x["id"] == en_attente), {}) if code == 200 else {}
        c, contenu = http("GET", f"{URL_B}/api/documents/{en_attente}/download", jeton=jb, brut=True)
        verifier(d.get("emplacement") == "drive" and contenu == contenu_panne,
                 f"« Facture pendant la panne » sur le drive, identique : {d.get('fichier')}")
    code, r = http("POST", f"{URL_B}/api/drive/sauvegarde/maintenant", None, jb, delai=300)
    verifier(code == 200, f"sauvegarde après la panne : {r.get('fichier') or r.get('detail')}")
    code, r = http("GET", f"{URL_B}/api/drive", jeton=jb)
    verifier(not r.get("sauvegarde", {}).get("erreur"),
             f"plus d'erreur affichée après une sauvegarde réussie (« {r.get('sauvegarde', {}).get('erreur')} »)")

    print(f"\nBilan : {verifs} vérification(s), {len(ecarts)} écart(s).")
    for t in ecarts:
        print(f"  - {t}")
    return 1 if ecarts else 0


if __name__ == "__main__":
    sys.exit(main())
