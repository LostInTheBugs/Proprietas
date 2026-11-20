"""Relevés bancaires : import et rapprochement (demande de Fred, 20/11/2026).

Import
- Formats : CSV (export de la banque en ligne), OFX (1.x SGML ou 2.x XML) et QIF. Le compte est choisi à
  l'import : compte du syndicat ou compte du fonds de travaux.
- CSV : la ligne d'en-tête est cherchée dans les premières lignes (les banques mettent souvent le numéro
  de compte et la période au-dessus). Colonnes reconnues (casse et accents ignorés) : une date (date de
  l'opération de préférence à la date de valeur), un libellé, et soit un montant signé, soit deux
  colonnes débit et crédit. Séparateur « ; », tabulation ou « , » ; montants « 1 234,56 », « -12,30 »,
  « 1.234,56 » ou « 1,234.56 » ; dates JJ/MM/AAAA, JJ/MM/AA, JJ-MM-AAAA, JJ.MM.AAAA ou AAAA-MM-JJ.
  Les lignes sans date ni montant (totaux, soldes) sont passées.
- Refus en bloc : à la moindre erreur, rien n'est écrit ; chaque erreur cite sa ligne. « Vérifier »
  (simulation) montre la période, le nombre d'opérations nouvelles et déjà importées.
- Une opération déjà importée (même identifiant de la banque, ou même date, montant et libellé à la même
  place dans le fichier) n'est pas ajoutée deux fois : on peut importer des relevés qui se chevauchent.

Rapprochement (choix de Fred : l'application propose, le syndic valide)
- Une ligne du relevé est pointée quand des opérations saisies y sont rattachées et que leur total
  (encaissements +, dépenses −) est égal à son montant : une opération, ou plusieurs (paiement d'un
  copropriétaire réparti entre ses lots, charges et fonds de travaux).
- Propositions : opérations passées par la banque, pas encore pointées, de même sens et même montant,
  datées à 10 jours au plus de la ligne ; ou groupe d'encaissements du même paiement (même date, même
  libellé avant « — lot ») dont le total est le montant ; ou facture à payer (la ligne en donne la date
  de paiement). Une proposition est « sûre » si elle est la seule de sa ligne et que ses opérations ne
  sont proposées pour aucune autre ligne : un bouton les valide toutes.
- Ligne sans équivalent : le syndic crée l'opération depuis la ligne (dépense, encaissement, paiement
  d'un copropriétaire), ou la met de côté (« ignorée »).
- Opérations « absentes du relevé » : saisies, passées par la banque, datées dans la période des lignes
  importées, rattachées à aucune ligne ni proposées pour aucune.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal as D, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import audit
from app.core.money import arrondi, somme
from app.models.mouvement import Mouvement
from app.models.releve import LigneReleve
from app.services.factures import date_banque

COMPTES = {"syndicat": "Compte du syndicat", "fonds_travaux": "Compte du fonds de travaux"}
MAX_OCTETS = 5 * 1024 * 1024
MAX_LIGNES = 5000
JOURS = 10                      # écart de dates toléré pour proposer une opération
LIGNES_AVANT_ENTETE = 30        # en-tête cherché dans les 30 premières lignes du CSV

COL_DATE = ("date_operation", "date_de_l_operation", "date_d_operation", "date_operation_bancaire", "date",
            "date_comptable", "date_de_comptabilisation", "date_comptabilisation", "date_valeur", "date_de_valeur")
COL_LIBELLE = ("libelle", "libelle_operation", "libelle_de_l_operation", "libelle_simplifie", "libelle_complet",
               "intitule", "description", "operation", "nature_de_l_operation", "nature", "details", "detail",
               "communication", "motif", "beneficiaire", "tiers")
COL_MONTANT = ("montant", "montant_eur", "montant_euros", "montant_en_euros", "montant_de_l_operation", "somme",
               "amount", "valeur")
COL_DEBIT = ("debit", "debit_eur", "debit_euros", "debits", "montant_debit", "sortie", "sorties")
COL_CREDIT = ("credit", "credit_eur", "credit_euros", "credits", "montant_credit", "entree", "entrees")


# ---------------------------------------------------------------- lecture
def _norm(texte: str) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\(.*?\)", "", t)                       # « Montant (EUR) » → « montant »
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def montant(texte: str) -> D | None:
    """« 1 234,56 », « -12,30 », « +5 », « 1.234,56 », « 1,234.56 », « 12,30 € » → Decimal ; vide → None."""
    t = (texte or "").strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("€", "")
    t = t.replace("EUR", "").replace("eur", "")
    if not t:
        return None
    negatif = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("+-()")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        raise ValueError(texte)
    try:
        v = D(t)
    except InvalidOperation:
        raise ValueError(texte) from None
    return -v if negatif else v


def jour(texte: str) -> date | None:
    t = (texte or "").strip()
    if not t:
        return None
    t = t.split(" ")[0].split("T")[0]
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y%m%d", "%d-%m-%y", "%d.%m.%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(texte)


def _decoder(contenu: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return contenu.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenu.decode("latin-1")


def _choisir(entete: list[str], noms: tuple) -> int | None:
    for nom in noms:
        if nom in entete:
            return entete.index(nom)
    return None


def _csv(texte: str) -> tuple[list[dict], list[str]]:
    for sep in (";", "\t", ","):
        rangs = list(csv.reader(io.StringIO(texte), delimiter=sep))
        for i, rang in enumerate(rangs[:LIGNES_AVANT_ENTETE]):
            entete = [_norm(c) for c in rang]
            i_date, i_lib = _choisir(entete, COL_DATE), _choisir(entete, COL_LIBELLE)
            i_mt, i_deb, i_cre = _choisir(entete, COL_MONTANT), _choisir(entete, COL_DEBIT), _choisir(entete, COL_CREDIT)
            if i_date is None or (i_mt is None and (i_deb is None or i_cre is None)):
                continue
            return _lignes_csv(rangs, i, i_date, i_lib, i_mt, i_deb, i_cre)
    return [], ["En-tête introuvable : il faut une colonne de date et une colonne « montant » (ou deux colonnes "
                "« débit » et « crédit ») dans les 30 premières lignes du fichier."]


def _lignes_csv(rangs, i_entete, i_date, i_lib, i_mt, i_deb, i_cre) -> tuple[list[dict], list[str]]:
    out, erreurs = [], []
    for n, rang in enumerate(rangs[i_entete + 1:], start=i_entete + 2):
        cel = lambda i: rang[i].strip() if i is not None and i < len(rang) else ""   # noqa: E731
        if not any(c.strip() for c in rang):
            continue
        brut_date = cel(i_date)
        recap = any(re.search(r"\b(solde|total|totaux)\b", _norm(c).replace("_", " ")) for c in rang)
        try:
            if i_mt is not None:
                mt = montant(cel(i_mt))
            else:
                deb, cre = montant(cel(i_deb)), montant(cel(i_cre))
                mt = None if deb is None and cre is None else (cre or D(0)) - abs(deb or D(0))
        except ValueError as e:
            if not recap:
                erreurs.append(f"Ligne {n} : montant « {e} » illisible.")
            continue
        try:
            j = jour(brut_date)
        except ValueError:
            if mt is None or recap:
                continue                                  # ligne de total ou de solde
            erreurs.append(f"Ligne {n} : date « {brut_date} » illisible (attendu : JJ/MM/AAAA).")
            continue
        if j is None or mt is None:
            if j is not None and mt is None:
                continue                                  # ligne d'information sans montant
            if j is None and mt is not None and not recap:
                erreurs.append(f"Ligne {n} : montant sans date.")
            continue
        if mt == 0:
            continue
        out.append({"ligne": n, "date": j, "libelle": " ".join(cel(i_lib).split()), "montant": mt, "fitid": ""})
    return out, erreurs


def _ofx(texte: str) -> tuple[list[dict], list[str]]:
    out, erreurs = [], []
    for n, bloc in enumerate(re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texte, re.IGNORECASE | re.DOTALL), start=1):
        champs = {k.upper(): v.strip() for k, v in re.findall(r"<(\w+)>([^<\r\n]*)", bloc)}
        try:
            j = jour(champs.get("DTPOSTED", "")[:8])
            mt = montant(champs.get("TRNAMT", ""))
        except ValueError as e:
            erreurs.append(f"Opération {n} : valeur « {e} » illisible.")
            continue
        if j is None or mt is None:
            erreurs.append(f"Opération {n} : date ou montant manquant.")
            continue
        nom, memo = champs.get("NAME", ""), champs.get("MEMO", "")
        libelle = nom if not memo or memo == nom else (f"{nom} {memo}" if nom else memo)
        if mt != 0:
            out.append({"ligne": n, "date": j, "libelle": " ".join(libelle.split()), "montant": mt,
                        "fitid": champs.get("FITID", "")})
    if not out and not erreurs:
        erreurs.append("Aucune opération (<STMTTRN>) dans ce fichier OFX.")
    return out, erreurs


def _qif(texte: str) -> tuple[list[dict], list[str]]:
    blocs, cur = [], {}
    for brut in texte.splitlines():
        ligne = brut.strip()
        if not ligne or ligne.startswith("!"):
            continue
        if ligne == "^":
            blocs.append(cur)
            cur = {}
        else:
            cur.setdefault(ligne[0], ligne[1:].strip())
    ordre = _ordre_qif([b.get("D", "") for b in blocs])
    out, erreurs = [], []
    for n, b in enumerate(blocs, start=1):
        try:
            j = _jour_qif(b.get("D", ""), ordre)
            mt = montant(b.get("T", b.get("U", "")))
        except ValueError as e:
            erreurs.append(f"Opération {n} : valeur « {e} » illisible.")
            continue
        if j is None or mt is None:
            erreurs.append(f"Opération {n} : date ou montant manquant.")
        elif mt != 0:
            nom, memo = b.get("P", ""), b.get("M", "")
            libelle = nom if not memo or memo == nom else (f"{nom} {memo}" if nom else memo)
            out.append({"ligne": n, "date": j, "libelle": " ".join(libelle.split()), "montant": mt, "fitid": ""})
    if not out and not erreurs:
        erreurs.append("Aucune opération dans ce fichier QIF.")
    return out, erreurs


_DATE_QIF = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")


def _ordre_qif(dates: list[str]) -> str:
    """« jm » (JJ/MM, banques françaises) sauf si une date du fichier n'a de sens qu'en MM/JJ (second nombre > 12)."""
    for d in dates:
        m = _DATE_QIF.fullmatch((d or "").strip().replace("'", "/").replace(" ", ""))
        if m and int(m.group(1)) > 12:
            return "jm"
        if m and int(m.group(2)) > 12:
            return "mj"
    return "jm"


def _jour_qif(texte: str, ordre: str = "jm") -> date | None:
    """QIF : JJ/MM/AAAA en France, MM/JJ/AAAA ailleurs (ordre du fichier) ; l'apostrophe d'année (1/31'26) est admise."""
    t = (texte or "").strip().replace("'", "/").replace(" ", "")
    m = _DATE_QIF.fullmatch(t)
    if not m:
        return jour(t)
    a, b, an = int(m.group(1)), int(m.group(2)), int(m.group(3))
    an += 2000 if an < 100 else 0
    jj, mm = (a, b) if ordre == "jm" else (b, a)
    try:
        return date(an, mm, jj)
    except ValueError:
        raise ValueError(texte) from None


def lire(nom: str, contenu: bytes) -> tuple[list[dict], list[str]]:
    """Opérations du fichier [{ligne, date, libelle, montant, fitid}] et erreurs."""
    if len(contenu) > MAX_OCTETS:
        raise HTTPException(422, "Fichier trop volumineux (5 Mo au plus).")
    texte = _decoder(contenu)
    ext = (nom or "").lower().rsplit(".", 1)[-1] if "." in (nom or "") else ""
    if ext in ("ofx", "qfx") or re.search(r"<OFX>", texte[:4000], re.IGNORECASE):
        ops, erreurs = _ofx(texte)
    elif ext == "qif" or texte.lstrip().startswith("!Type"):
        ops, erreurs = _qif(texte)
    elif ext in ("csv", "txt", "tsv", ""):
        ops, erreurs = _csv(texte)
    else:
        raise HTTPException(422, "Format non reconnu : CSV, OFX ou QIF (export de votre banque en ligne).")
    if len(ops) > MAX_LIGNES:
        raise HTTPException(422, f"Trop d'opérations ({len(ops)}) : {MAX_LIGNES} au plus par fichier.")
    for o in ops:
        if abs(o["montant"]) >= D("100000000"):
            erreurs.append(f"Ligne {o['ligne']} : montant {o['montant']} hors limites.")
    return ops, erreurs


def _empreintes(ops: list[dict]) -> None:
    """Identifiant de la banque s'il existe ; sinon date, montant, libellé et rang parmi les opérations
    identiques du fichier (deux frais de 2 € le même jour restent deux lignes)."""
    vus: dict[str, int] = defaultdict(int)
    for o in ops:
        if o["fitid"]:
            o["empreinte"] = "fitid:" + o["fitid"][:200]
            continue
        cle = f"{o['date'].isoformat()}|{arrondi(o['montant'])}|{_norm(o['libelle'])}"
        vus[cle] += 1
        o["empreinte"] = "h:" + hashlib.sha256(f"{cle}|{vus[cle]}".encode()).hexdigest()[:40]


def _compte_valide(compte: str) -> str:
    if compte not in COMPTES:
        raise HTTPException(422, "Compte inconnu : compte du syndicat ou compte du fonds de travaux.")
    return compte


def importer(db: Session, copro_id: int, compte: str, nom: str, contenu: bytes, simuler: bool) -> dict:
    _compte_valide(compte)
    ops, erreurs = lire(nom, contenu)
    if not ops and not erreurs:
        erreurs = ["Aucune opération trouvée dans ce fichier."]
    _empreintes(ops)
    existantes = {e for (e,) in db.query(LigneReleve.empreinte).filter(
        LigneReleve.copropriete_id == copro_id, LigneReleve.compte == compte)}
    nouvelles = [o for o in ops if o["empreinte"] not in existantes]
    resume = {
        "erreurs": erreurs, "simulation": simuler, "operations": len(ops), "nouvelles": len(nouvelles),
        "deja_importees": len(ops) - len(nouvelles),
        "du": min((o["date"] for o in ops), default=None), "au": max((o["date"] for o in ops), default=None),
        "credits": arrondi(somme(o["montant"] for o in nouvelles if o["montant"] > 0)),
        "debits": arrondi(somme(-o["montant"] for o in nouvelles if o["montant"] < 0)),
    }
    if simuler:
        return resume
    if erreurs:
        raise HTTPException(422, f"{len(erreurs)} erreur(s) : rien n'a été importé. " + " ".join(erreurs[:5]))
    maintenant = datetime.now()
    for o in nouvelles:
        db.add(LigneReleve(copropriete_id=copro_id, compte=compte, date=o["date"], libelle=o["libelle"][:500],
                           montant=arrondi(o["montant"]), empreinte=o["empreinte"], fichier=(nom or "")[:200],
                           importe_le=maintenant))
    db.flush()
    return resume


# ---------------------------------------------------------------- rapprochement
def signe(m: Mouvement) -> D:
    """Montant de l'opération vu de la banque : encaissement +, dépense −."""
    v = D(m.montant or 0)
    return v if m.type == "encaissement" else -v


def total(mouvements) -> D:
    return arrondi(somme(signe(m) for m in mouvements))


def _passe_par_la_banque(m: Mouvement) -> bool:
    return m.type in ("encaissement", "depense") and not m.hors_banque


def _base_libelle(libelle: str) -> str:
    """« Virement — lot 3 (travaux) » → « Virement » : les encaissements d'un même paiement."""
    return (libelle or "").split(" — lot ")[0].strip()


def _dans_la_fenetre(m: Mouvement, l: LigneReleve) -> int | None:
    """Écart en jours entre l'opération et la ligne, ou None si trop loin."""
    if m.a_payer:
        fin = max(m.date, m.echeance or m.date) + timedelta(days=60)
        return abs((l.date - m.date).days) if m.date - timedelta(days=3) <= l.date <= fin else None
    ecart = abs((l.date - date_banque(m)).days)
    return ecart if ecart <= JOURS else None


def _candidats(lignes: list[LigneReleve], libres: list[Mouvement]) -> dict[int, list[dict]]:
    """{ligne_id: [{"ids": [...], "jours": n}]} pour les lignes pas encore pointées ni ignorées."""
    groupes: dict[tuple, list[Mouvement]] = defaultdict(list)
    for m in libres:
        if m.type == "encaissement" and not m.a_payer:
            groupes[(m.date, _base_libelle(m.libelle))].append(m)
    groupes = {k: v for k, v in groupes.items() if len(v) >= 2}
    out = {}
    for l in lignes:
        if l.ignoree or l.mouvements:
            continue
        cands = []
        for m in libres:
            if signe(m) == arrondi(D(l.montant)):
                j = _dans_la_fenetre(m, l)
                if j is not None:
                    cands.append({"ids": [m.id], "jours": j})
        for membres in groupes.values():
            if total(membres) == arrondi(D(l.montant)):
                j = _dans_la_fenetre(membres[0], l)
                if j is not None:
                    cands.append({"ids": sorted(m.id for m in membres), "jours": j})
        out[l.id] = sorted(cands, key=lambda c: (c["jours"], len(c["ids"]), c["ids"]))
    return out


def _libres(db: Session, copro_id: int) -> list[Mouvement]:
    return [m for m in db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id,
                                                  Mouvement.releve_ligne_id.is_(None))
            if _passe_par_la_banque(m)]


def surs(cands: dict[int, list[dict]]) -> dict[int, list[int]]:
    """{ligne_id: ids} des propositions sûres : seule proposition de sa ligne, opérations proposées nulle part ailleurs."""
    usage: dict[int, int] = defaultdict(int)
    for liste in cands.values():
        for c in liste:
            for i in c["ids"]:
                usage[i] += 1
    return {lid: liste[0]["ids"] for lid, liste in cands.items()
            if len(liste) == 1 and all(usage[i] == 1 for i in liste[0]["ids"])}


def statut(l: LigneReleve, cands: list[dict]) -> str:
    if l.ignoree:
        return "ignoree"
    if l.mouvements:
        return "pointee" if total(l.mouvements) == arrondi(D(l.montant)) else "ecart"
    return "proposee" if cands else "a_traiter"


def _mvt(m: Mouvement) -> dict:
    return {"id": m.id, "date": m.date, "date_banque": date_banque(m), "libelle": m.libelle, "type": m.type,
            "categorie": m.categorie, "montant": arrondi(D(m.montant or 0)), "lot_id": m.lot_id,
            "a_payer": bool(m.a_payer)}


def etat(db: Session, copro_id: int, compte: str) -> dict:
    _compte_valide(compte)
    from app.services.reprise import _compte
    lignes = (db.query(LigneReleve).filter(LigneReleve.copropriete_id == copro_id, LigneReleve.compte == compte)
              .order_by(LigneReleve.date.desc(), LigneReleve.id.desc()).all())
    libres = _libres(db, copro_id)
    par_id = {m.id: m for m in libres}
    cands = _candidats(lignes, libres)
    sur = surs(cands)
    sortie, compte_statuts = [], defaultdict(int)
    for l in lignes:
        st = statut(l, cands.get(l.id, []))
        compte_statuts[st] += 1
        sortie.append({
            "id": l.id, "date": l.date, "libelle": l.libelle, "montant": arrondi(D(l.montant)), "fichier": l.fichier,
            "statut": st, "mouvements": [_mvt(m) for m in sorted(l.mouvements, key=lambda m: m.id)],
            "ecart": arrondi(D(l.montant) - total(l.mouvements)) if l.mouvements else None,
            "candidats": [{"jours": c["jours"], "sure": sur.get(l.id) == c["ids"],
                           "mouvements": [_mvt(par_id[i]) for i in c["ids"]]} for c in cands.get(l.id, [])],
        })
    du, au = (min(l.date for l in lignes), max(l.date for l in lignes)) if lignes else (None, None)
    absentes = []
    if lignes:
        proposees = {i for liste in cands.values() for c in liste for i in c["ids"]}
        absentes = [_mvt(m) for m in sorted(libres, key=lambda m: (date_banque(m), m.id))
                    if not m.a_payer and m.id not in proposees and _compte(m) == compte and du <= date_banque(m) <= au]
    return {"compte": compte, "libelle_compte": COMPTES[compte], "du": du, "au": au,
            "resume": {"lignes": len(lignes), "pointees": compte_statuts["pointee"],
                       "proposees": compte_statuts["proposee"], "a_traiter": compte_statuts["a_traiter"],
                       "ecarts": compte_statuts["ecart"], "ignorees": compte_statuts["ignoree"],
                       "surs": len(sur), "absentes": len(absentes)},
            "lignes": sortie, "absentes": absentes}


def ligne(db: Session, copro_id: int, ligne_id: int) -> LigneReleve:
    l = db.query(LigneReleve).filter(LigneReleve.id == ligne_id, LigneReleve.copropriete_id == copro_id).first()
    if l is None:
        raise HTTPException(404, "Ligne de relevé introuvable.")
    return l


def pointer(db: Session, copro, l: LigneReleve, ids: list[int], user, request) -> LigneReleve:
    """Rattache des opérations saisies à la ligne : leur total doit être son montant. Une facture à payer
    rattachée est marquée payée à la date de la ligne."""
    from app.services import factures
    if l.ignoree:
        raise HTTPException(409, "Cette ligne est mise de côté : reprenez-la d'abord.")
    if l.mouvements:
        raise HTTPException(409, "Cette ligne est déjà pointée : dépointez-la d'abord.")
    ids = sorted(set(ids))
    if not ids:
        raise HTTPException(422, "Choisissez au moins une opération.")
    ms = db.query(Mouvement).filter(Mouvement.id.in_(ids), Mouvement.copropriete_id == copro.id).all()
    if len(ms) != len(ids):
        raise HTTPException(422, "Une des opérations n'appartient pas à la copropriété.")
    for m in ms:
        if not _passe_par_la_banque(m):
            raise HTTPException(422, f"« {m.libelle} » n'est pas passée par la banque (avance ou déduction).")
        if m.releve_ligne_id is not None:
            raise HTTPException(409, f"« {m.libelle} » est déjà pointée sur une autre ligne du relevé.")
    t = total(ms)
    if t != arrondi(D(l.montant)):
        raise HTTPException(422, f"Les opérations choisies totalisent {t:.2f} € et la ligne du relevé "
                                 f"{arrondi(D(l.montant)):.2f} €.".replace(".", ","))
    for m in ms:
        if m.a_payer:
            factures.payer(db, copro, m, l.date, None, user, request)
        m.releve_ligne_id = l.id
    db.flush()
    db.refresh(l)
    audit.enregistrer(db, "releve_pointe", user=user, copro_id=copro.id, request=request,
                      detail=f"{l.date:%d/%m/%Y} « {l.libelle} » {arrondi(D(l.montant)):.2f} € : "
                             + ", ".join(f"#{m.id}" for m in ms))
    return l


def depointer(db: Session, copro, l: LigneReleve, user, request) -> LigneReleve:
    """Détache les opérations ; une facture payée par le pointage reste payée."""
    for m in list(l.mouvements):
        m.releve_ligne_id = None
    db.flush()
    db.refresh(l)
    audit.enregistrer(db, "releve_depointe", user=user, copro_id=copro.id, request=request,
                      detail=f"{l.date:%d/%m/%Y} « {l.libelle} » {arrondi(D(l.montant)):.2f} €")
    return l


def pointer_surs(db: Session, copro, compte: str, user, request) -> int:
    _compte_valide(compte)
    lignes = db.query(LigneReleve).filter(LigneReleve.copropriete_id == copro.id, LigneReleve.compte == compte).all()
    sur = surs(_candidats(lignes, _libres(db, copro.id)))
    par_id = {l.id: l for l in lignes}
    for lid, ids in sur.items():
        pointer(db, copro, par_id[lid], ids, user, request)
    return len(sur)


def supprimer(db: Session, l: LigneReleve) -> None:
    if l.mouvements:
        raise HTTPException(409, "Cette ligne est pointée : dépointez-la avant de la supprimer.")
    db.delete(l)
