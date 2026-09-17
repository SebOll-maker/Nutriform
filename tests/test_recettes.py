# -*- coding: utf-8 -*-
"""
Tests du format des recettes JSON (script autonome, sans pytest).

    python tests/test_recettes.py

Ecrit dans un dossier temporaire : ne touche jamais aux vraies recettes.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recettes  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


def recette_valide():
    return {
        "id": "poulet-curry",
        "titre": "Poulet au curry",
        "source": "photo",
        "portions_base": 4,
        "ingredients": [
            {"nom": "Poulet", "ciqual_code": "36007", "quantite": 500,
             "unite": "g", "quantite_affichee": "4 blancs", "echelle": "variable"},
            {"nom": "Curry", "ciqual_code": "11015", "quantite": 6,
             "unite": "g", "quantite_affichee": "2 c. à café", "echelle": "fixe"},
        ],
        "etapes": ["Découper.", "Cuire."],
    }


print("=== recette conforme ===")
verifier(recettes.valider(recette_valide()) == [], "aucune erreur",
         recettes.valider(recette_valide()))

print()
print("=== champs obligatoires ===")
for champ, attendu in (("titre", "titre"), ("id", "id"),
                       ("portions_base", "portions_base"),
                       ("ingredients", "ingrédient")):
    r = recette_valide()
    del r[champ]
    erreurs = recettes.valider(r)
    verifier(any(attendu in e for e in erreurs),
             f"{champ} manquant -> erreur", erreurs)

print()
print("=== valeurs aberrantes ===")
cas = [
    ("portions_base à 0", {"portions_base": 0}, "portions_base"),
    ("portions_base texte", {"portions_base": "quatre"}, "portions_base"),
    ("id non slug", {"id": "Poulet Curry !"}, "id"),
]
for libelle, patch, attendu in cas:
    r = recette_valide()
    r.update(patch)
    erreurs = recettes.valider(r)
    verifier(any(attendu in e for e in erreurs), f"{libelle} -> erreur", erreurs)

print()
print("=== ingrédients ===")
cas_ing = [
    ("quantité négative", {"quantite": -5}, "quantite"),
    ("quantité manquante", {"quantite": None}, "quantite"),
    ("nom vide", {"nom": ""}, "nom"),
    ("echelle inconnue", {"echelle": "moyenne"}, "echelle"),
    ("echelle absente", {"echelle": None}, "echelle"),
    ("unité de cuisine interdite", {"unite": "c. à soupe"}, "interdite"),
    ("unité vide", {"unite": ""}, "unite"),
    ("champ inconnu", {"calories": 300}, "inconnu"),
    ("unite_piece à 0", {"unite_piece": 0}, "unite_piece"),
    ("unite_piece texte", {"unite_piece": "un oeuf"}, "unite_piece"),
]
for libelle, patch, attendu in cas_ing:
    r = recette_valide()
    r["ingredients"][0].update(patch)
    erreurs = recettes.valider(r)
    verifier(any(attendu in e for e in erreurs), f"{libelle} -> erreur", erreurs)

r = recette_valide()
r["ingredients"] = []
verifier(any("ingrédient" in e for e in recettes.valider(r)),
         "liste d'ingrédients vide -> erreur")

print()
print("=== unités indivisibles ===")
r = recette_valide()
r["ingredients"][0].update({"unite_piece": 125, "nom_piece": "blanc"})
verifier(recettes.valider(r) == [], "unite_piece + nom_piece sur un variable",
         recettes.valider(r))

r = recette_valide()
r["ingredients"][1].update({"unite_piece": 2})     # le curry est « fixe »
verifier(any("fixe" in e for e in recettes.valider(r)),
         "unite_piece sur un ingrédient fixe -> erreur", recettes.valider(r))

r = recette_valide()
r["ingredients"][0].update({"unite_piece": 40, "nom_piece": "tranche",
                            "pas_piece": 2})
verifier(recettes.valider(r) == [], "pas_piece = 2 avec unite_piece : valide",
         recettes.valider(r))

cas_pas = [
    ("pas_piece sans unite_piece", {"pas_piece": 2}, "unite_piece"),
    ("pas_piece à 0", {"unite_piece": 40, "pas_piece": 0}, "entier"),
    ("pas_piece non entier", {"unite_piece": 40, "pas_piece": 1.5}, "entier"),
    ("pas_piece texte", {"unite_piece": 40, "pas_piece": "deux"}, "pas_piece"),
]
for libelle, patch, attendu in cas_pas:
    r = recette_valide()
    r["ingredients"][0].update(patch)
    erreurs = recettes.valider(r)
    verifier(any(attendu in e for e in erreurs), f"{libelle} -> erreur", erreurs)

print()
print("=== ciqual_code absent : toléré (aliment non encore rattaché) ===")
r = recette_valide()
del r["ingredients"][0]["ciqual_code"]
verifier(recettes.valider(r) == [], "pas d'erreur bloquante",
         recettes.valider(r))

print()
print("=== slug ===")
cas_slug = [("Poulet au curry & coco", "poulet-au-curry-coco"),
            ("Crème brûlée", "creme-brulee"),
            ("  Tarte   aux   pommes  ", "tarte-aux-pommes"),
            ("!!!", "recette")]
for entree, attendu in cas_slug:
    obtenu = recettes.slug(entree)
    verifier(obtenu == attendu, f"slug({entree!r}) = {attendu!r}", obtenu)

print()
print("=== lecture / écriture sur disque ===")
dossier_reel = recettes.DOSSIER
temporaire = Path(tempfile.mkdtemp(prefix="nutriform-test-"))
try:
    recettes.DOSSIER = temporaire

    chemin = recettes.ecrire(recette_valide())
    verifier(chemin.exists(), "fichier écrit", chemin)
    verifier(chemin.name == "poulet-curry.json", "nommé d'après l'id", chemin.name)

    relue = recettes.charger("poulet-curry")
    verifier(relue["titre"] == "Poulet au curry", "relecture fidèle")
    verifier(relue["ingredients"][0]["quantite"] == 500, "quantités préservées")

    contenu = chemin.read_text(encoding="utf-8")
    verifier("Découper" in contenu, "accents écrits en clair (pas d'échappement)")

    verifier(recettes.charger("inexistante") is None,
             "recette absente -> None")

    toutes = recettes.charger_toutes()
    verifier(len(toutes) == 1, "charger_toutes voit la recette", len(toutes))

    # une recette invalide ne doit pas disparaitre silencieusement
    (temporaire / "cassee.json").write_text(
        json.dumps({"titre": "Cassée", "portions_base": 2, "ingredients": []}),
        encoding="utf-8")
    toutes = recettes.charger_toutes()
    cassee = [r for r in toutes if r["id"] == "cassee"]
    verifier(len(cassee) == 1 and cassee[0].get("_erreurs"),
             "recette invalide listée avec ses erreurs",
             cassee[0].get("_erreurs") if cassee else "absente")

    # JSON illisible
    (temporaire / "illisible.json").write_text("{ pas du json", encoding="utf-8")
    toutes = recettes.charger_toutes()
    illisible = [r for r in toutes if r["id"] == "illisible"]
    verifier(len(illisible) == 1 and illisible[0].get("_erreurs"),
             "JSON illisible signalé sans faire planter la liste")

    # les fichiers _ sont de la documentation, pas des recettes
    (temporaire / "_exemple.json").write_text("{}", encoding="utf-8")
    ids = [r["id"] for r in recettes.charger_toutes()]
    verifier("_exemple" not in ids, "les fichiers _*.json sont ignorés", ids)

    # ecrire() refuse une recette invalide
    try:
        recettes.ecrire({"id": "x", "titre": "", "portions_base": 1,
                         "ingredients": []})
        verifier(False, "ecrire() refuse une recette invalide")
    except ValueError:
        verifier(True, "ecrire() refuse une recette invalide")

    verifier(recettes.supprimer("poulet-curry"), "suppression")
    verifier(not recettes.supprimer("poulet-curry"),
             "suppression d'une recette déjà absente -> False")
finally:
    recettes.DOSSIER = dossier_reel
    shutil.rmtree(temporaire, ignore_errors=True)

print()
if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Tous les tests du format de recette passent.")
