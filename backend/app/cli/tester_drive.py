"""Essaie un drive WebDAV comme le fera Proprietas, sans toucher à la base.

    DRIVE_MOT_DE_PASSE=… python -m app.cli.tester_drive --url https://cloud.exemple.fr/remote.php/dav/files/syndic/ \\
        --utilisateur syndic --dossier "Proprietas/Essai"

Étapes : essai d'écriture (dossier, fichier témoin), dépôt de deux fichiers du même nom avec accents
et apostrophe, tailles, relecture, liste du dossier, suppression. Tout ce qui est créé est supprimé, sauf les dossiers.
Code de sortie 0 si tout est conforme.
"""
import argparse
import io
import os
import sys
from datetime import date

from app.core import drive
from app.core.config import get_settings
from app.core.stockage import StockageIndisponible


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli.tester_drive", description=__doc__.split("\n")[0])
    p.add_argument("--url", required=True)
    p.add_argument("--utilisateur", default="")
    p.add_argument("--dossier", default=f"{drive.RACINE}/Essai")
    a = p.parse_args(argv)
    try:
        url = drive.verifier_adresse(a.url, get_settings().drive_reseau_local)
        st = drive.StockageWebDAV(url, a.utilisateur, os.environ.get("DRIVE_MOT_DE_PASSE", ""), a.dossier)
        st.verifier_ecriture()
        print(f"essai d'écriture : OK ({a.dossier})")
        contenu = ("Proprietas — essai accentué éèàç\n" * 3).encode()
        nom = drive.nom_lisible(date.today(), "Facture d'électricité — août", ".txt")
        chemins = []
        for n in (1, 2):
            chemin = st.nom_libre(drive.DOSSIERS["facture"], nom)
            st.enregistrer(chemin, io.BytesIO(contenu + str(n).encode()))
            chemins.append(chemin)
            print(f"dépôt {n} : {chemin}")
        ok = chemins[0] != chemins[1]
        for n, chemin in enumerate(chemins, 1):
            taille = st.taille(chemin)
            lu = b"".join(st.lire_par_blocs(chemin))
            conforme = taille == len(contenu) + 1 and lu == contenu + str(n).encode()
            ok = ok and conforme
            print(f"relecture {n} : {taille} octets, {'conforme' if conforme else 'DIFFÉRENT'}")
        # Liste du dossier (vérification du drive, fichiers renommés) : les deux dépôts y sont, à la bonne taille.
        arbre = st.lister_arbre()
        listes = all(arbre.get(c) == len(contenu) + 1 for c in chemins)
        ok = ok and listes
        print(f"liste du dossier : {len(arbre)} fichier(s), {'les deux dépôts y sont' if listes else 'DÉPÔTS ABSENTS OU TAILLE FAUSSE'}")
        for chemin in chemins:
            st.supprimer(chemin)
        restes = [c for c in chemins if st.existe(c)]
        ok = ok and not restes and st.taille("Factures/absent.txt") is None
        print(f"suppression : {'OK' if not restes else 'RESTE ' + ', '.join(restes)}")
    except (drive.AdresseRefusee, StockageIndisponible) as e:
        print(f"ÉCHEC : {e}")
        return 1
    print("RÉSULTAT : " + ("conforme" if ok else "NON CONFORME"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
