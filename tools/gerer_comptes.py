# -*- coding: utf-8 -*-
"""
Gestion des comptes en ligne de commande.

Indispensable à l'amorçage : le tout premier compte administrateur doit
exister avant que l'interface web ne soit utilisable. Sert aussi sur le VPS,
où l'on crée les comptes de la famille en SSH.

    python tools/gerer_comptes.py lister
    python tools/gerer_comptes.py creer <identifiant> <prénom> [--admin]
    python tools/gerer_comptes.py motdepasse <identifiant>
    python tools/gerer_comptes.py activer <identifiant>
    python tools/gerer_comptes.py desactiver <identifiant>

Le mot de passe n'est jamais passé en argument : il serait visible dans
l'historique du shell et dans la liste des processus. Il est demandé en
saisie masquée.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import personnes  # noqa: E402


def _trouver(identifiant: str) -> dict:
    cible = personnes.normaliser_identifiant(identifiant)
    for p in personnes.lister():
        if p["identifiant"] == cible:
            return p
    raise SystemExit(f"Aucun compte « {cible} ». "
                     f"Voir : python tools/gerer_comptes.py lister")


def _demander_mot_de_passe() -> str:
    while True:
        mot_de_passe = getpass.getpass("Mot de passe : ")
        try:
            personnes.verifier_mot_de_passe_acceptable(mot_de_passe)
        except ValueError as erreur:
            print(" ", erreur)
            continue
        if mot_de_passe != getpass.getpass("Confirmer     : "):
            print("  Les deux saisies diffèrent.")
            continue
        return mot_de_passe


def cmd_lister(_):
    liste = personnes.lister()
    if not liste:
        print("Aucun compte. En créer un :")
        print("  python tools/gerer_comptes.py creer <identifiant> <prénom> --admin")
        return
    print(f"{'id':>3}  {'identifiant':<18} {'prénom':<16} {'rôle':<8} état")
    for p in liste:
        print(f"{p['id']:>3}  {p['identifiant']:<18} {p['prenom']:<16} "
              f"{'admin' if p['admin'] else '':<8} "
              f"{'actif' if p['actif'] else 'désactivé'}")


def cmd_creer(args):
    # Juste après la migration V2, les données d'avant sont rattachées à la
    # personne 1 sans qu'aucun compte existe. Le premier compte créé doit
    # alors reprendre cet identifiant, faute de quoi ce planning, ce journal
    # et ces pesées resteraient inaccessibles.
    # La reprise elle-même est gérée par personnes.creer() ; on se contente
    # de l'annoncer, pour que la personne sache ce qui va se passer.
    reprise = personnes.compter() == 0 and personnes.donnees_orphelines()
    if reprise:
        print("Des données saisies avant le passage en multi-comptes attendent")
        print(f"un propriétaire : ce compte les reprendra "
              f"(personne {db.PERSONNE_ORIGINE}).")

    mot_de_passe = _demander_mot_de_passe()
    try:
        personne_id = personnes.creer(args.identifiant, args.prenom,
                                      mot_de_passe, admin=args.admin)
    except ValueError as erreur:
        raise SystemExit(f"Refusé : {erreur}")
    p = personnes.get(personne_id)
    print(f"[OK] compte {p['identifiant']} créé (id {personne_id}"
          f"{', administrateur' if p['admin'] else ''}), "
          f"avec ses objectifs par défaut.")
    if reprise:
        print("     Le planning, le journal et les pesées d'avant lui sont "
              "rattachés.")


def cmd_motdepasse(args):
    p = _trouver(args.identifiant)
    personnes.changer_mot_de_passe(p["id"], _demander_mot_de_passe())
    print(f"[OK] mot de passe de {p['identifiant']} remplacé.")


def cmd_activer(args):
    p = _trouver(args.identifiant)
    personnes.definir_actif(p["id"], True)
    print(f"[OK] {p['identifiant']} réactivé.")


def cmd_desactiver(args):
    p = _trouver(args.identifiant)
    try:
        personnes.definir_actif(p["id"], False)
    except ValueError as erreur:
        raise SystemExit(f"Refusé : {erreur}")
    print(f"[OK] {p['identifiant']} désactivé. Ses données sont conservées.")


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(
        description="Gestion des comptes Nutriform.")
    sous = analyseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("lister", help="afficher tous les comptes")

    p_creer = sous.add_parser("creer", help="créer un compte")
    p_creer.add_argument("identifiant")
    p_creer.add_argument("prenom")
    p_creer.add_argument("--admin", action="store_true",
                         help="peut gérer les comptes (jamais voir les données)")

    for nom, aide in (("motdepasse", "remplacer le mot de passe"),
                      ("activer", "réactiver un compte"),
                      ("desactiver", "désactiver un compte")):
        sp = sous.add_parser(nom, help=aide)
        sp.add_argument("identifiant")

    arguments = analyseur.parse_args()
    db.init_db()
    {"lister": cmd_lister, "creer": cmd_creer, "motdepasse": cmd_motdepasse,
     "activer": cmd_activer, "desactiver": cmd_desactiver}[arguments.commande](arguments)
