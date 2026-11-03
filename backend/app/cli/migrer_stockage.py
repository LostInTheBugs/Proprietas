"""Copie les documents existants entre le dossier local et le bucket S3.

    python -m app.cli.migrer_stockage                 # dossier local → S3
    python -m app.cli.migrer_stockage --simulation    # n'écrit rien, affiche le bilan
    python -m app.cli.migrer_stockage --sens s3-vers-local

Le S3 visé est décrit par COPRO_S3_* (même si COPRO_STOCKAGE vaut encore « local ») et le
dossier par COPRO_UPLOAD_DIR. On peut donc copier AVANT de basculer, puis relancer après
la bascule pour rattraper les documents déposés entre-temps.

- Seuls les fichiers référencés en base (table documents) sont copiés.
- Un fichier déjà présent à destination avec la même taille est laissé tel quel :
  la commande peut être relancée sans risque.
- La source n'est JAMAIS supprimée : à faire à la main, après vérification.
- Code de sortie 1 si une copie a échoué.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, field

from app.core.stockage import (BLOC, NomInvalide, Stockage, StockageIndisponible,
                               StockageLocal, _stockage_s3)


@dataclass
class Bilan:
    copies: int = 0
    deja_presents: int = 0
    manquants: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)

    def ligne(self) -> str:
        return (f"Bilan : {self.copies} copié(s), {self.deja_presents} déjà présent(s), "
                f"{len(self.manquants)} manquant(s) à la source, {len(self.erreurs)} erreur(s)")


def copier(noms: list[str], source: Stockage, destination: Stockage,
           simulation: bool = False) -> Bilan:
    bilan = Bilan()
    for nom in noms:
        try:
            taille = source.taille(nom)
            if taille is None:
                bilan.manquants.append(nom)
                continue
            if destination.taille(nom) == taille:
                bilan.deja_presents += 1
                continue
            if not simulation:
                with tempfile.SpooledTemporaryFile(max_size=BLOC) as tmp:
                    for bloc in source.lire_par_blocs(nom):
                        tmp.write(bloc)
                    tmp.seek(0)
                    destination.enregistrer(nom, tmp)
                copie = destination.taille(nom)
                if copie != taille:
                    bilan.erreurs.append(f"{nom} : {copie} octet(s) à destination, {taille} attendu(s)")
                    continue
            bilan.copies += 1
        except NomInvalide:
            bilan.erreurs.append(f"{nom!r} : nom refusé (il sortirait du dossier)")
        except (StockageIndisponible, OSError) as e:
            bilan.erreurs.append(f"{nom} : {e}")
    return bilan


def noms_en_base(db) -> list[str]:
    from app.models.document import Document
    return sorted({f for (f,) in db.query(Document.fichier).all() if f})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.migrer_stockage",
                                     description="Copie les documents entre dossier local et S3.")
    parser.add_argument("--sens", choices=["local-vers-s3", "s3-vers-local"], default="local-vers-s3")
    parser.add_argument("--simulation", action="store_true", help="n'écrit rien, affiche le bilan")
    args = parser.parse_args(argv)

    from app.core.config import get_settings
    from app.core.database import SessionLocal
    s = get_settings()
    if not s.s3_bucket:
        print("COPRO_S3_BUCKET n'est pas défini : aucun bucket S3 à utiliser.", file=sys.stderr)
        return 2
    local = StockageLocal(s.upload_dir)
    s3 = _stockage_s3(s.s3_bucket, s.s3_prefix, s.s3_endpoint_url, s.s3_region,
                      s.s3_access_key_id, s.s3_secret_access_key)
    source, destination = (local, s3) if args.sens == "local-vers-s3" else (s3, local)
    try:
        destination.verifier_ecriture()
    except StockageIndisponible as e:
        print(e, file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        noms = noms_en_base(db)
    finally:
        db.close()
    print(f"{len(noms)} document(s) en base ; sens {args.sens}"
          + (" (simulation : rien n'est écrit)" if args.simulation else ""))
    bilan = copier(noms, source, destination, simulation=args.simulation)
    for nom in bilan.manquants:
        print(f"  manquant à la source : {nom}")
    for err in bilan.erreurs:
        print(f"  ERREUR : {err}")
    print(bilan.ligne())
    return 1 if bilan.erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
