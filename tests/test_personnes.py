# -*- coding: utf-8 -*-
"""
Comptes utilisateurs : création, authentification, mots de passe.

    python tests/test_personnes.py

Base SQLite temporaire : ne touche jamais aux vraies données.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

DOSSIER = Path(tempfile.mkdtemp(prefix="nf-personnes-"))
os.environ["NF_DB"] = str(DOSSIER / "t.db")

import db  # noqa: E402
import personnes  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


def refuse(libelle, fonction, attendu_dans=""):
    try:
        fonction()
        verifier(False, f"{libelle} -> refusé")
    except ValueError as erreur:
        verifier(attendu_dans in str(erreur).lower() or not attendu_dans,
                 f"{libelle} -> refusé", str(erreur)[:60])


db.init_db()

print("=== normalisation des identifiants ===")
# « Sébastien » tapé avec ou sans accent doit désigner le même compte, sinon
# on se connecte en tâtonnant.
for brut, attendu in (("Sébastien", "sebastien"),
                      ("Marie-Claude", "marie-claude"),
                      ("  JEAN  ", "jean"),
                      ("a@b!c", "abc"),
                      ("élise.d", "elise.d"),
                      ("Renée O'Neil", "reneeoneil")):
    obtenu = personnes.normaliser_identifiant(brut)
    verifier(obtenu == attendu, f"{brut!r} -> {attendu!r}", obtenu)

print()
print("=== création ===")
sid = personnes.creer("Sébastien", "Sébastien", "motdepasse-solide", admin=True)
mid = personnes.creer("maman", "Maman", "un-autre-mot-de-passe")
verifier(sid != mid, "deux identifiants distincts", (sid, mid))
verifier(personnes.compter() == 2, "deux comptes en base")
verifier(personnes.get(sid)["admin"] is True, "le premier est administrateur")
verifier(personnes.get(mid)["admin"] is False, "le second ne l'est pas")
verifier(personnes.get(sid)["identifiant"] == "sebastien",
         "l'identifiant est normalisé à la création")
verifier(personnes.get(sid)["prenom"] == "Sébastien",
         "le prénom garde ses accents : c'est l'affichage")
verifier(len(db.get_reglages(sid)) == len(db.REGLAGES_DEFAUT)
         and len(db.get_reglages(mid)) == len(db.REGLAGES_DEFAUT),
         "chacun reçoit ses objectifs par défaut")

print()
print("=== le condensat ne sort jamais du module ===")
p = personnes.get(sid)
verifier("mot_de_passe_hash" not in p,
         "get() ne renvoie pas le condensat", sorted(p))
verifier(all("mot_de_passe_hash" not in x for x in personnes.lister()),
         "lister() non plus")
conn = db.get_conn()
h = conn.execute("SELECT mot_de_passe_hash FROM personne WHERE id = ?",
                 (sid,)).fetchone()[0]
conn.close()
verifier(h.startswith("scrypt:"), "le stockage utilise scrypt", h[:16])
verifier("motdepasse-solide" not in h,
         "le mot de passe n'apparaît nulle part en clair")

print()
print("=== authentification ===")
for ident, mdp, attendu, libelle in (
        ("sebastien", "motdepasse-solide", True, "identifiant exact"),
        ("Sébastien", "motdepasse-solide", True, "identifiant avec accents"),
        ("  SEBASTIEN ", "motdepasse-solide", True, "espaces et majuscules"),
        ("sebastien", "mauvais", False, "mauvais mot de passe"),
        ("sebastien", "", False, "mot de passe vide"),
        ("inconnu", "motdepasse-solide", False, "identifiant inconnu"),
        ("maman", "un-autre-mot-de-passe", True, "second compte"),
        ("maman", "motdepasse-solide", False,
         "le mot de passe de l'un ne marche pas pour l'autre")):
    obtenu = personnes.authentifier(ident, mdp) is not None
    verifier(obtenu == attendu, libelle)

verifier(personnes.authentifier(None, None) is None,
         "des arguments nuls ne font pas planter l'authentification")

print()
print("=== refus à la création ===")
refuse("identifiant déjà pris",
       lambda: personnes.creer("maman", "Autre", "motdepasse-x"), "déjà pris")
refuse("identifiant déjà pris malgré la casse",
       lambda: personnes.creer("MAMAN", "Autre", "motdepasse-x"), "déjà pris")
refuse("identifiant sans caractère exploitable",
       lambda: personnes.creer("!!!", "X", "motdepasse-x"), "identifiant")
refuse("prénom vide",
       lambda: personnes.creer("vide", "   ", "motdepasse-x"), "prénom")
refuse("mot de passe trop court",
       lambda: personnes.creer("court", "Court", "abc"), "caractères")
refuse("mot de passe vide",
       lambda: personnes.creer("sansmdp", "Sans", ""), "caractères")
verifier(personnes.compter() == 2, "aucun compte n'a été créé au passage")

print()
print("=== changement de mot de passe ===")
personnes.changer_mot_de_passe(mid, "nouveau-mot-de-passe")
verifier(personnes.authentifier("maman", "un-autre-mot-de-passe") is None,
         "l'ancien mot de passe ne marche plus")
verifier(personnes.authentifier("maman", "nouveau-mot-de-passe") is not None,
         "le nouveau marche")
refuse("changer pour un mot de passe trop court",
       lambda: personnes.changer_mot_de_passe(mid, "abc"), "caractères")
verifier(personnes.authentifier("maman", "nouveau-mot-de-passe") is not None,
         "et le mot de passe valide est resté en place")

print()
print("=== activation et désactivation ===")
personnes.definir_actif(mid, False)
verifier(personnes.authentifier("maman", "nouveau-mot-de-passe") is None,
         "un compte désactivé ne peut plus se connecter")
verifier(personnes.get(mid) is not None,
         "mais le compte existe toujours : les données sont conservées")
verifier(len(personnes.lister(inclure_inactifs=False)) == 1,
         "il disparaît de la liste des comptes actifs")
verifier(len(personnes.lister()) == 2,
         "sans disparaître de la liste complète")
personnes.definir_actif(mid, True)
verifier(personnes.authentifier("maman", "nouveau-mot-de-passe") is not None,
         "réactivé, il se reconnecte")

print()
print("=== on ne se coupe pas la branche ===")
# Sans administrateur actif, plus personne ne pourrait gérer les comptes.
refuse("désactiver le dernier administrateur",
       lambda: personnes.definir_actif(sid, False), "administrateur")
refuse("retirer le rôle au dernier administrateur",
       lambda: personnes.definir_admin(sid, False), "administrateur")
verifier(personnes.get(sid)["actif"] and personnes.get(sid)["admin"],
         "l'administrateur est intact")

# Avec un second administrateur, les deux opérations redeviennent possibles.
personnes.definir_admin(mid, True)
personnes.definir_actif(sid, False)
verifier(not personnes.get(sid)["actif"],
         "un administrateur peut être désactivé s'il en reste un autre")
personnes.definir_actif(sid, True)
personnes.definir_admin(mid, False)
verifier(not personnes.get(mid)["admin"], "et le rôle peut être retiré")

print()
print("=== données orphelines ===")
verifier(not personnes.donnees_orphelines(),
         "aucune donnée orpheline quand les comptes existent")
conn = db.get_conn()
conn.execute("INSERT INTO poids (personne_id, date, poids_kg) VALUES (?,?,?)",
             (9999, "2026-01-01", 70.0))
conn.commit()
conn.close()
verifier(personnes.donnees_orphelines(),
         "une donnée rattachée à un compte inexistant est détectée")

print()
shutil.rmtree(DOSSIER, ignore_errors=True)

if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Tous les tests des comptes passent.")
