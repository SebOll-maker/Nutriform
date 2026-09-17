# -*- coding: utf-8 -*-
"""
Tests de l'agrégation de la liste de courses (script autonome, sans pytest).

    python tests/test_courses.py

Utilise une base SQLite ET un dossier de recettes TEMPORAIRES : ne touche
jamais aux données réelles.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# NF_DB doit être posée AVANT l'import de db (le chemin est lu à l'import).
BASE_TEMP = Path(tempfile.mkdtemp(prefix="nutriform-db-")) / "test.db"
os.environ["NF_DB"] = str(BASE_TEMP)

import courses as mod_courses  # noqa: E402
import db  # noqa: E402
import planning as mod_planning  # noqa: E402
import recettes  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


# ------------------------------------------------------------- jeu d'essai
db.init_db()
conn = db.get_conn()
conn.executemany(
    """INSERT INTO aliment (code, nom, nom_norm, groupe, kcal, proteines,
                            glucides, lipides, source)
       VALUES (?,?,?,?,?,?,?,?, 'ciqual')""",
    [
        ("POULET", "Poulet, blanc", "poulet, blanc",
         "viandes, oeufs, poissons", 120.0, 22.0, 0.0, 3.0),
        ("RIZ", "Riz basmati, cru", "riz basmati, cru",
         "produits céréaliers", 350.0, 7.0, 78.0, 1.0),
        ("OIGNON", "Oignon, cru", "oignon, cru",
         "fruits, légumes, légumineuses et oléagineux", 40.0, 1.0, 6.0, 0.5),
        ("SEL", "Sel", "sel", "aides culinaires et ingrédients divers",
         0.0, 0.0, 0.0, 0.0),
    ])
conn.commit()
conn.close()

DOSSIER_RECETTES = Path(tempfile.mkdtemp(prefix="nutriform-recettes-"))
recettes.DOSSIER = DOSSIER_RECETTES


def ecrire_recette(identifiant, titre, ingredients, portions=2):
    (DOSSIER_RECETTES / f"{identifiant}.json").write_text(
        json.dumps({"id": identifiant, "titre": titre,
                    "portions_base": portions, "ingredients": ingredients,
                    "etapes": []}, ensure_ascii=False), encoding="utf-8")


# Deux recettes qui PARTAGENT le poulet et le sel : c'est le cas qui doit
# fusionner dans la liste de courses.
ecrire_recette("plat-a", "Plat A", [
    {"nom": "Poulet", "ciqual_code": "POULET", "quantite": 200, "unite": "g",
     "echelle": "variable"},
    {"nom": "Riz", "ciqual_code": "RIZ", "quantite": 100, "unite": "g",
     "echelle": "variable"},
    {"nom": "Sel", "ciqual_code": "SEL", "quantite": 2, "unite": "g",
     "echelle": "fixe"},
])
ecrire_recette("plat-b", "Plat B", [
    {"nom": "Blanc de poulet", "ciqual_code": "POULET", "quantite": 300,
     "unite": "g", "echelle": "variable"},
    {"nom": "Oignon", "ciqual_code": "OIGNON", "quantite": 150, "unite": "g",
     "echelle": "variable"},
    {"nom": "Sel", "ciqual_code": "SEL", "quantite": 3, "unite": "g",
     "echelle": "fixe"},
])

print("=== agrégation sur 2 jours ===")
mod_planning.ajouter("2026-03-02", "dejeuner", "plat-a", portions=2)
mod_planning.ajouter("2026-03-03", "diner", "plat-b", portions=2)

liste = mod_courses.construire("2026-03-02", "2026-03-03")
par_nom = {l["nom"]: l for _, lignes in liste["rayons"] for l in lignes}

verifier(liste["n_repas"] == 2, "2 repas pris en compte", liste["n_repas"])
verifier(len(par_nom) == 4, "4 ingrédients distincts (poulet fusionné)",
         sorted(par_nom))
verifier(abs(par_nom["Poulet, blanc"]["grammes"] - 500) < 1e-6,
         "le poulet des 2 recettes est cumulé : 200 + 300 = 500 g",
         par_nom["Poulet, blanc"]["grammes"])
verifier(abs(par_nom["Sel"]["grammes"] - 5) < 1e-6,
         "le sel est cumulé : 2 + 3 = 5 g", par_nom["Sel"]["grammes"])
verifier(par_nom["Poulet, blanc"]["recettes"] == ["Plat A", "Plat B"],
         "les recettes d'origine sont citées",
         par_nom["Poulet, blanc"]["recettes"])
verifier(par_nom["Poulet, blanc"]["nom"] == "Poulet, blanc",
         "le nom affiché est celui de Ciqual, pas celui de la recette")

print()
print("=== rayons ===")
rayons = dict(liste["rayons"])
verifier("Fruits et légumes" in rayons, "rayon fruits et légumes", list(rayons))
verifier("Boucherie, poissonnerie" in rayons, "rayon boucherie", list(rayons))
verifier("Épices et condiments" in rayons, "le sel va aux condiments", list(rayons))
verifier(list(rayons)[0] == "Fruits et légumes",
         "les rayons sortent dans l'ordre du magasin", list(rayons))

print()
print("=== bornes de dates (incluses) ===")
verifier(mod_courses.construire("2026-03-02", "2026-03-02")["n_repas"] == 1,
         "le jour de début est inclus")
verifier(mod_courses.construire("2026-03-03", "2026-03-03")["n_repas"] == 1,
         "le jour de fin est inclus")
verifier(mod_courses.construire("2026-03-04", "2026-03-10")["n_repas"] == 0,
         "période sans repas : liste vide")
verifier(mod_courses.construire("2026-03-04", "2026-03-10")["rayons"] == [],
         "aucun rayon si aucun repas")

print()
print("=== calibrage pris en compte ===")
# Plat A recalibré : les quantités de la liste doivent suivre la CIBLE, pas
# la recette d'origine. Plat A d'origine = 2 portions de 295 kcal
# (200 g poulet = 240 kcal + 100 g riz = 350 kcal + sel 0 kcal, / 2 portions).
# Viser 590 kcal par portion, c'est donc doubler.
mod_planning.ajouter("2026-03-05", "dejeuner", "plat-a", kcal_cible=590,
                     portions=2)
calibree = mod_courses.construire("2026-03-05", "2026-03-05")
poulet = {l["nom"]: l for _, lg in calibree["rayons"] for l in lg}["Poulet, blanc"]
verifier(abs(poulet["grammes"] - 400) < 1e-6,
         "cible doublée -> poulet doublé (200 -> 400 g)", poulet["grammes"])
sel = {l["nom"]: l for _, lg in calibree["rayons"] for l in lg}["Sel"]
verifier(abs(sel["grammes"] - 2) < 1e-6,
         "le sel FIXE ne double pas malgré la cible", sel["grammes"])

print()
print("=== recette supprimée entre-temps ===")
mod_planning.ajouter("2026-03-06", "diner", "plat-disparu", portions=1)
orpheline = mod_courses.construire("2026-03-06", "2026-03-06")
verifier(len(orpheline["repas_sans_recette"]) == 1,
         "le repas orphelin est signalé et non ignoré silencieusement")
verifier(orpheline["rayons"] == [], "aucun ingrédient inventé")

print()
print("=== cases cochées ===")
verifier(liste["restant"] == 4, "4 articles restants au départ", liste["restant"])
mod_courses.cocher("2026-03-02", "2026-03-03", "POULET", True)
recharge = mod_courses.construire("2026-03-02", "2026-03-03")
poulet = {l["code"]: l for _, lg in recharge["rayons"] for l in lg}["POULET"]
verifier(poulet["coche"], "le poulet est coché")
verifier(recharge["restant"] == 3, "3 articles restants", recharge["restant"])
mod_courses.cocher("2026-03-02", "2026-03-03", "POULET", False)
verifier(not mod_courses.etat_coches("2026-03-02", "2026-03-03")["POULET"],
         "décocher fonctionne")
mod_courses.cocher("2026-03-02", "2026-03-03", "RIZ", True)
mod_courses.vider_coches("2026-03-02", "2026-03-03")
verifier(mod_courses.etat_coches("2026-03-02", "2026-03-03") == {},
         "vider efface toutes les cases de la période")

print()
print("=== quantités lisibles en magasin ===")
cas = [(1500, "1,5 kg"), (1000, "1 kg"), (432.7, "430 g"), (57.4, "57 g"),
       (2.5, "2,5 g")]
for grammes, attendu in cas:
    obtenu = mod_courses.formater_quantite(grammes)
    verifier(obtenu == attendu, f"{grammes} g -> {attendu}", obtenu)

print()
try:
    shutil.rmtree(DOSSIER_RECETTES, ignore_errors=True)
    shutil.rmtree(BASE_TEMP.parent, ignore_errors=True)
except OSError:
    pass

if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Tous les tests de la liste de courses passent.")
