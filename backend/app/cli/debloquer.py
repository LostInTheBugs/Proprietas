"""Débloque un compte bloqué après des échecs de connexion, depuis le serveur (secours).

    docker compose exec backend python -m app.cli.debloquer prenom.nom@exemple.fr
    docker compose exec backend python -m app.cli.debloquer --liste

À utiliser quand personne ne peut le faire dans l'application (par exemple le seul
administrateur de l'instance est lui-même bloqué). Le déblocage est journalisé.
"""
import argparse
import sys
from datetime import datetime

from sqlalchemy import func, or_

from app.core.database import SessionLocal
from app.models.user import User
from app.services import connexions


def main(argv=None, session=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli.debloquer", description=__doc__.split("\n")[0])
    p.add_argument("email", nargs="?", help="e-mail du compte à débloquer")
    p.add_argument("--liste", action="store_true", help="liste les comptes bloqués")
    a = p.parse_args(argv)
    if not a.email and not a.liste:
        p.error("indiquez l'e-mail du compte, ou --liste")
    db = session or SessionLocal()
    try:
        if a.liste:
            bloques = (db.query(User)
                       .filter(or_(User.bloque_definitif_le.isnot(None), User.bloque_jusqua > datetime.now()))
                       .order_by(User.email).all())
            for u in bloques:
                quand = (f"jusqu'au déblocage (depuis le {u.bloque_definitif_le:%d/%m/%Y %H:%M})"
                         if u.bloque_definitif_le else f"jusqu'à {u.bloque_jusqua:%H:%M}")
                print(f"{u.email} : bloqué {quand}")
            print(f"{len(bloques)} compte(s) bloqué(s)")
            return 0
        cible = db.query(User).filter(func.lower(User.email) == a.email.strip().lower()).first()
        if not cible:
            print(f"Aucun compte avec l'e-mail {a.email}", file=sys.stderr)
            return 1
        if not cible.bloque and not cible.echecs_connexion:
            print(f"{cible.email} n'est pas bloqué")
            return 0
        connexions.debloquer(db, cible, None, None, origine="par la commande serveur")
        print(f"{cible.email} débloqué")
        return 0
    finally:
        if session is None:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
