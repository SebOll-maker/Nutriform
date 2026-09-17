# -*- coding: utf-8 -*-
"""
Tests du moteur de calibrage (script autonome, sans pytest).

    python tests/test_nutrition.py

Aliments fictifs, valeurs rondes : si un calcul est faux, l'écart saute aux yeux.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nutrition  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


def presque(a, b, tolerance=1e-6):
    return a is not None and b is not None and abs(a - b) <= tolerance


# --------------------------------------------------------------- jeu d'essai
ALIMENTS = {
    # 100 g de poulet = 100 kcal, 20 g de protéines
    "POULET": {"nom": "Poulet", "kcal": 100.0, "proteines": 20.0,
               "glucides": 0.0, "lipides": 2.0, "fibres": 0.0,
               "sucres": 0.0, "sel": 0.1},
    # 100 g d'huile = 900 kcal, 100 g de lipides
    "HUILE": {"nom": "Huile", "kcal": 900.0, "proteines": 0.0,
              "glucides": 0.0, "lipides": 100.0, "fibres": 0.0,
              "sucres": 0.0, "sel": 0.0},
    # épice : 300 kcal/100 g, ingrédient FIXE
    "EPICE": {"nom": "Épice", "kcal": 300.0, "proteines": 10.0,
              "glucides": 50.0, "lipides": 5.0, "fibres": 20.0,
              "sucres": 2.0, "sel": 0.0},
    "SEL": {"nom": "Sel", "kcal": 0.0, "proteines": 0.0, "glucides": 0.0,
            "lipides": 0.0, "fibres": 0.0, "sucres": 0.0, "sel": 100.0},
    # aliment dont Ciqual ne donne pas l'énergie
    "TROU": {"nom": "Aliment sans données", "kcal": None, "proteines": None,
             "glucides": None, "lipides": None, "fibres": None,
             "sucres": None, "sel": None},
}


def recette_base():
    """2 portions : 200 g poulet (200 kcal) + 10 g huile (90 kcal)
    + 5 g épice FIXE (15 kcal)  =>  305 kcal, soit 152,5 kcal/portion.
    F = 15 kcal, V = 290 kcal."""
    return {
        "id": "test", "titre": "Test", "portions_base": 2,
        "ingredients": [
            {"nom": "Poulet", "ciqual_code": "POULET", "quantite": 200,
             "unite": "g", "quantite_affichee": "2 blancs", "echelle": "variable"},
            {"nom": "Huile", "ciqual_code": "HUILE", "quantite": 10,
             "unite": "g", "quantite_affichee": "1 c. à soupe", "echelle": "variable"},
            {"nom": "Épice", "ciqual_code": "EPICE", "quantite": 5,
             "unite": "g", "quantite_affichee": "1 c. à café", "echelle": "fixe"},
        ],
        "etapes": ["Cuire."],
    }


print("=== recette telle qu'écrite ===")
r = nutrition.calculer(recette_base(), ALIMENTS)
verifier(presque(r["total"]["kcal"], 305.0), "total = 305 kcal", r["total"]["kcal"])
verifier(presque(r["par_portion"]["kcal"], 152.5), "par portion = 152,5 kcal",
         r["par_portion"]["kcal"])
verifier(presque(r["total"]["proteines"], 40.5), "protéines = 40,5 g",
         r["total"]["proteines"])
verifier(presque(r["kcal_fixes"], 15.0) and presque(r["kcal_variables"], 290.0),
         "F = 15 kcal et V = 290 kcal")
verifier(r["coefficient"] == 1.0, "coefficient = 1 sans cible", r["coefficient"])
verifier(r["avertissements"] == [], "aucun avertissement", r["avertissements"])
verifier(r["ingredients"][0]["apercu"] == "2 blancs",
         "le texte de cuisine est conservé quand rien ne bouge")

print()
print("=== calibrage à 400 kcal/portion, 2 portions ===")
r = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=400)
verifier(r["possible"], "calibrage possible")
verifier(presque(r["par_portion"]["kcal"], 400.0),
         "la portion vaut EXACTEMENT la cible", r["par_portion"]["kcal"])
verifier(presque(r["total"]["kcal"], 800.0), "total = 800 kcal", r["total"]["kcal"])
verifier(presque(r["coefficient"], (800 - 15) / 290), "k = (N.T - F.N/P) / V",
         r["coefficient"])
fixe = [i for i in r["ingredients"] if i["echelle"] == "fixe"][0]
verifier(presque(fixe["grammes"], 5.0), "l'épice FIXE reste à 5 g", fixe["grammes"])
verifier(fixe["apercu"] == "1 c. à café",
         "l'épice garde son texte de cuisine (quantité inchangée)")
variable = r["ingredients"][0]
verifier(variable["apercu"] is None,
         "le poulet mis à l'échelle n'affiche plus « 2 blancs » (trompeur)")

print()
print("=== la même recette à 600 kcal : seuls les variables bougent ===")
r400 = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=400)
r600 = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=600)
f400 = [i for i in r400["ingredients"] if i["echelle"] == "fixe"][0]["grammes"]
f600 = [i for i in r600["ingredients"] if i["echelle"] == "fixe"][0]["grammes"]
verifier(presque(f400, f600), "l'ingrédient fixe est identique à 400 et à 600 kcal",
         f"{f400} vs {f600}")
verifier(r600["ingredients"][0]["grammes"] > r400["ingredients"][0]["grammes"],
         "l'ingrédient variable augmente avec la cible")
verifier(presque(r600["par_portion"]["kcal"], 600.0), "600 kcal atteint",
         r600["par_portion"]["kcal"])

print()
print("=== changement du nombre de portions ===")
r = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=400, portions=4)
verifier(presque(r["par_portion"]["kcal"], 400.0), "4 portions de 400 kcal",
         r["par_portion"]["kcal"])
verifier(presque(r["total"]["kcal"], 1600.0), "total = 1600 kcal", r["total"]["kcal"])
fixe = [i for i in r["ingredients"] if i["echelle"] == "fixe"][0]
verifier(presque(fixe["grammes"], 10.0),
         "l'épice fixe suit le nombre de portions (5 g x 4/2 = 10 g)",
         fixe["grammes"])

print()
print("=== cible sous le plancher des ingrédients fixes ===")
r = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=5)
verifier(not r["possible"], "calibrage refusé")
verifier(r["message"] and "inatteignable" in r["message"],
         "message d'explication présent", r["message"])
verifier(presque(r["plancher_kcal_portion"], 7.5), "plancher = 7,5 kcal/portion",
         r["plancher_kcal_portion"])

print()
print("=== recette 100 % fixe ===")
rec = {"id": "t", "titre": "T", "portions_base": 1, "ingredients": [
    {"nom": "Épice", "ciqual_code": "EPICE", "quantite": 10, "unite": "g",
     "echelle": "fixe"}]}
r = nutrition.calculer(rec, ALIMENTS, kcal_cible=500)
verifier(not r["possible"], "calibrage impossible sans ingrédient variable")
verifier(r["message"] and "fixe" in r["message"], "message explicite", r["message"])

print()
print("=== coefficient extrême : on calibre mais on avertit ===")
r = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=2000)
verifier(r["possible"], "calibrage effectué")
verifier(any("multipliés par" in a for a in r["avertissements"]),
         "avertissement sur les proportions", r["avertissements"])
verifier(presque(r["par_portion"]["kcal"], 2000.0), "cible quand même atteinte",
         r["par_portion"]["kcal"])

print()
print("=== pas de faux avertissement quand rien ne peut se déformer ===")
# Une collation d'un seul ingrédient, tout variable : la tripler, c'est juste
# une plus grosse poignée. Aucune proportion ne change, donc aucun avertissement.
collation = {"id": "c", "titre": "Noix", "portions_base": 1, "ingredients": [
    {"nom": "Noix", "ciqual_code": "POULET", "quantite": 15, "unite": "g",
     "echelle": "variable"}]}
r = nutrition.calculer(collation, ALIMENTS, kcal_cible=60)   # k = 4
verifier(presque(r["coefficient"], 4.0), "coefficient bien de 4", r["coefficient"])
verifier(not any("proportions" in a for a in r["avertissements"]),
         "aucun avertissement de proportions sur un ingrédient unique",
         r["avertissements"])
verifier(presque(r["par_portion"]["kcal"], 60.0), "cible atteinte")

# Deux ingrédients variables, aucun fixe : leur rapport est préservé aussi.
deux = {"id": "d", "titre": "Deux", "portions_base": 1, "ingredients": [
    {"nom": "A", "ciqual_code": "POULET", "quantite": 50, "unite": "g",
     "echelle": "variable"},
    {"nom": "B", "ciqual_code": "HUILE", "quantite": 5, "unite": "g",
     "echelle": "variable"}]}
r = nutrition.calculer(deux, ALIMENTS, kcal_cible=400)
verifier(not any("proportions" in a for a in r["avertissements"]),
         "ni sur deux ingrédients tous deux variables", r["avertissements"])

# En revanche, dès qu'un ingrédient FIXE existe, l'avertissement reprend
# son sens : le rapport fixe/variable, lui, se déforme vraiment.
r = nutrition.calculer(recette_base(), ALIMENTS, kcal_cible=2000)
verifier(any("proportions" in a for a in r["avertissements"]),
         "mais il réapparaît dès qu'un ingrédient fixe est présent",
         r["avertissements"])

print()
print("=== données nutritionnelles manquantes ===")
rec = recette_base()
rec["ingredients"].append({"nom": "Mystère", "ciqual_code": "TROU",
                           "quantite": 50, "unite": "g", "echelle": "variable"})
r = nutrition.calculer(rec, ALIMENTS)
verifier(any("inconnue" in a for a in r["avertissements"]),
         "l'ingrédient sans énergie est signalé", r["avertissements"])
verifier(presque(r["total"]["kcal"], 305.0),
         "il compte pour 0 (et non pour une valeur inventée)", r["total"]["kcal"])

print()
print("=== trou Ciqual sur UN nutriment seulement ===")
# Cas réel : la levure chimique a une valeur énergétique mais aucune teneur
# en sel. Le total « sel » est alors sous-estimé, et il faut le dire.
ALIMENTS_TROU = dict(ALIMENTS)
ALIMENTS_TROU["LEVURE"] = {"nom": "Levure chimique", "kcal": 108.0,
                           "proteines": 0.1, "glucides": 26.9, "lipides": 0.0,
                           "fibres": None, "sucres": None, "sel": None}
rec = recette_base()
rec["ingredients"].append({"nom": "Levure", "ciqual_code": "LEVURE",
                           "quantite": 5, "unite": "g", "echelle": "fixe"})
r = nutrition.calculer(rec, ALIMENTS_TROU)
verifier("sel" in r["nutriments_incomplets"],
         "le sel est signalé comme incomplet", r["nutriments_incomplets"])
verifier(r["nutriments_incomplets"]["sel"] == ["Levure"],
         "l'ingrédient fautif est nommé", r["nutriments_incomplets"].get("sel"))
verifier(any("ne renseigne pas tous les nutriments" in a
             for a in r["avertissements"]),
         "un avertissement le dit à l'utilisateur", r["avertissements"])
verifier(not any("Valeur énergétique inconnue" in a for a in r["avertissements"]),
         "pas de fausse alerte sur l'énergie, qui est connue")
verifier(presque(r["total"]["kcal"], 310.4),
         "l'énergie reste juste (305 + 5,4 de levure)", r["total"]["kcal"])
verifier(r["nutriments_incomplets"].get("proteines") is None,
         "les nutriments complets ne sont pas signalés")

r = nutrition.calculer(recette_base(), ALIMENTS)
verifier(r["nutriments_incomplets"] == {},
         "aucun signalement quand tout est renseigné",
         r["nutriments_incomplets"])

print()
print("=== énergie calculée par l'import : la recette le dit ===")
ALIMENTS_CALC = dict(ALIMENTS)
ALIMENTS_CALC["AGAVE"] = {"nom": "Sirop d'agave", "kcal": 317.5,
                          "proteines": 0.25, "glucides": 78.0, "lipides": 0.5,
                          "fibres": 0.0, "sucres": 68.0, "sel": 0.0,
                          "kcal_estimee": 1}
rec = recette_base()
rec["ingredients"].append({"nom": "Sirop d'agave", "ciqual_code": "AGAVE",
                           "quantite": 10, "unite": "g", "echelle": "variable"})
r = nutrition.calculer(rec, ALIMENTS_CALC)
verifier(r["energies_calculees"] == ["Sirop d'agave"],
         "l'ingrédient à énergie calculée est identifié",
         r["energies_calculees"])
verifier(any("Énergie calculée" in a for a in r["avertissements"]),
         "et la recette le mentionne", r["avertissements"])
verifier(r["ingredients"][-1]["kcal_estimee"] is True,
         "le drapeau remonte jusqu'à la ligne d'ingrédient")
verifier(presque(r["total"]["kcal"], 305.0 + 31.75),
         "son énergie est bien comptée dans le total", r["total"]["kcal"])
verifier(not any("inconnue" in a for a in r["avertissements"]),
         "et surtout : plus d'alerte « valeur énergétique inconnue »",
         r["avertissements"])

r = nutrition.calculer(recette_base(), ALIMENTS)
verifier(r["energies_calculees"] == [],
         "rien signalé quand toutes les énergies viennent de Ciqual")

print()
print("=== ingrédient dont l'aliment est introuvable ===")
rec = recette_base()
rec["ingredients"][0]["ciqual_code"] = "CODE-INEXISTANT"
r = nutrition.calculer(rec, ALIMENTS)
verifier(any("inconnue" in a for a in r["avertissements"]),
         "code inconnu signalé", r["avertissements"])
verifier(not r["ingredients"][0]["connu"], "l'ingrédient est marqué non connu")

print()
print("=== cas limites ===")
r = nutrition.calculer({"id": "v", "titre": "Vide", "portions_base": 2,
                        "ingredients": []}, ALIMENTS)
verifier(r["total"]["kcal"] == 0.0, "recette sans ingrédient : 0 kcal, pas de crash")
r = nutrition.calculer({"id": "v", "titre": "Vide", "portions_base": 2,
                        "ingredients": []}, ALIMENTS, kcal_cible=400)
verifier(not r["possible"], "recette vide : cible impossible")

rec = recette_base()
rec["ingredients"][1]["unite"] = "cuillère"
r = nutrition.calculer(rec, ALIMENTS)
verifier(any("Unité non exploitable" in a for a in r["avertissements"]),
         "unité invalide signalée", r["avertissements"])

rec = recette_base()
rec["portions_base"] = 0            # division par zéro potentielle
r = nutrition.calculer(rec, ALIMENTS, kcal_cible=400)
verifier(r["par_portion"]["kcal"] is not None,
         "portions_base = 0 ne fait pas planter le calcul")

print()
print("=== unités indivisibles : arrondi à la pièce entière ===")
# 1 portion : 1 oeuf de 50 g (50 kcal, indivisible) + 100 g de riz-poulet
# variable divisible (100 kcal) + 2 g d'épice fixe (6 kcal).
def recette_oeuf():
    return {
        "id": "o", "titre": "Omelette", "portions_base": 1,
        "ingredients": [
            {"nom": "Oeuf", "ciqual_code": "POULET", "quantite": 50,
             "unite": "g", "quantite_affichee": "1 oeuf", "echelle": "variable",
             "unite_piece": 50, "nom_piece": "oeuf"},
            {"nom": "Garniture", "ciqual_code": "POULET", "quantite": 100,
             "unite": "g", "echelle": "variable"},
            {"nom": "Épice", "ciqual_code": "EPICE", "quantite": 2,
             "unite": "g", "echelle": "fixe"},
        ],
    }

r = nutrition.calculer(recette_oeuf(), ALIMENTS)
oeuf = r["ingredients"][0]
verifier(presque(oeuf["grammes"], 50.0), "recette d'origine : 1 oeuf entier",
         oeuf["grammes"])
verifier(oeuf["pieces"] == 1, "compté en pièces", oeuf["pieces"])
verifier(oeuf["libelle_piece"] == "1 oeuf", "libellé au singulier",
         oeuf["libelle_piece"])

# Cible 300 kcal : k initial = (300 - 6) / 150 = 1,96 -> 1,96 oeuf -> 2 oeufs.
r = nutrition.calculer(recette_oeuf(), ALIMENTS, kcal_cible=300)
oeuf, garniture = r["ingredients"][0], r["ingredients"][1]
verifier(oeuf["pieces"] == 2, "arrondi à 2 oeufs entiers", oeuf["pieces"])
verifier(presque(oeuf["grammes"], 100.0), "soit exactement 100 g",
         oeuf["grammes"])
verifier(oeuf["libelle_piece"] == "2 oeufs", "libellé au pluriel",
         oeuf["libelle_piece"])
verifier(presque(r["par_portion"]["kcal"], 300.0),
         "la cible reste atteinte AU KCAL PRES après arrondi",
         r["par_portion"]["kcal"])
verifier(garniture["grammes"] != 100.0 * 1.96,
         "la garniture a été réajustée pour compenser l'arrondi",
         garniture["grammes"])

# L'arrondi vers le BAS doit aussi être compensé, en sens inverse.
r_bas = nutrition.calculer(recette_oeuf(), ALIMENTS, kcal_cible=170)
oeuf_bas = r_bas["ingredients"][0]
verifier(oeuf_bas["pieces"] == 1, "k = 1,09 -> arrondi à 1 oeuf",
         oeuf_bas["pieces"])
verifier(presque(r_bas["par_portion"]["kcal"], 170.0),
         "cible atteinte malgré l'arrondi vers le bas",
         r_bas["par_portion"]["kcal"])

# Une pièce au minimum : un ingrédient de la recette ne disparaît pas.
r = nutrition.calculer(recette_oeuf(), ALIMENTS, kcal_cible=60)
verifier(r["ingredients"][0]["pieces"] == 1,
         "cible basse : jamais 0 pièce, l'oeuf reste dans la recette",
         r["ingredients"][0]["pieces"])
verifier(presque(r["par_portion"]["kcal"], 60.0), "cible atteinte",
         r["par_portion"]["kcal"])

print()
print("=== pas d'arrondi : les pièces qui vont par deux ===")
# Un croque-monsieur exige DEUX tranches de pain : l'arrondi doit tomber sur
# 2, 4, 6 tranches, jamais 3.
def recette_croque():
    return {
        "id": "cr", "titre": "Croque", "portions_base": 1,
        "ingredients": [
            {"nom": "Pain", "ciqual_code": "POULET", "quantite": 80,
             "unite": "g", "echelle": "variable",
             "unite_piece": 40, "nom_piece": "tranche", "pas_piece": 2},
            {"nom": "Garniture", "ciqual_code": "POULET", "quantite": 100,
             "unite": "g", "echelle": "variable"},
        ],
    }

r = nutrition.calculer(recette_croque(), ALIMENTS)
pain = r["ingredients"][0]
verifier(pain["pieces"] == 2, "recette d'origine : 2 tranches", pain["pieces"])
verifier(pain["libelle_piece"] == "2 tranches", "libellé", pain["libelle_piece"])

# Base = 180 kcal. L'arrondi va au multiple de 2 le PLUS PROCHE :
#   260 kcal -> 2,89 tranches -> 2  (et non 3, que donnerait un pas de 1)
#   288 kcal -> 3,20 tranches -> 4  (arrondi vers le haut)
for cible, attendu in ((120, 2), (260, 2), (288, 4), (400, 4), (500, 6)):
    r = nutrition.calculer(recette_croque(), ALIMENTS, kcal_cible=cible)
    pieces = r["ingredients"][0]["pieces"]
    verifier(pieces == attendu and pieces % 2 == 0,
             f"cible {cible} kcal -> {attendu} tranches (pair)", pieces)
    verifier(presque(r["par_portion"]["kcal"], float(cible)),
             f"cible {cible} kcal atteinte malgré l'arrondi par 2",
             r["par_portion"]["kcal"])

# Le minimum n'est plus 1 pièce mais `pas` pièces : une seule tranche ne
# fait pas un croque.
r = nutrition.calculer(recette_croque(), ALIMENTS, kcal_cible=95)
verifier(r["ingredients"][0]["pieces"] == 2,
         "jamais 1 tranche : le minimum est le pas (2)",
         r["ingredients"][0]["pieces"])
verifier(presque(r["plancher_kcal_portion"], 80.0),
         "plancher = 2 tranches (80 g de poulet fictif = 80 kcal)",
         r["plancher_kcal_portion"])
r = nutrition.calculer(recette_croque(), ALIMENTS, kcal_cible=50)
verifier(not r["possible"], "cible sous ce plancher relevé : refusée")

# pas_piece absent = comportement d'avant (pas de 1)
rec = recette_croque()
del rec["ingredients"][0]["pas_piece"]
r = nutrition.calculer(rec, ALIMENTS, kcal_cible=260)
verifier(r["ingredients"][0]["pieces"] == 3,
         "sans pas_piece, 3 tranches redeviennent possibles",
         r["ingredients"][0]["pieces"])

# un pas absurde est ignoré plutôt que de casser le calcul
for valeur in (0, -3, "deux", None):
    rec = recette_croque()
    rec["ingredients"][0]["pas_piece"] = valeur
    r = nutrition.calculer(rec, ALIMENTS, kcal_cible=260)
    verifier(r["ingredients"][0]["pieces"] == 3,
             f"pas_piece = {valeur!r} -> traité comme 1",
             r["ingredients"][0]["pieces"])

print()
print("=== plancher relevé par les pièces entières ===")
r = nutrition.calculer(recette_oeuf(), ALIMENTS, kcal_cible=20)
verifier(presque(r["plancher_kcal_portion"], 56.0),
         "plancher = 6 kcal d'épice + 50 kcal pour 1 oeuf",
         r["plancher_kcal_portion"])
verifier(not r["possible"], "cible sous ce plancher : refusée")
verifier(r["message"] and "pièces entières" in r["message"],
         "le message cite les pièces entières", r["message"])

print()
print("=== aucun ingrédient divisible pour compenser ===")
rec = {"id": "o2", "titre": "Oeufs seuls", "portions_base": 1, "ingredients": [
    {"nom": "Oeuf", "ciqual_code": "POULET", "quantite": 50, "unite": "g",
     "echelle": "variable", "unite_piece": 50, "nom_piece": "oeuf"}]}
r = nutrition.calculer(rec, ALIMENTS, kcal_cible=180)
verifier(r["ingredients"][0]["pieces"] == 4, "180 kcal -> 4 oeufs (200 kcal)",
         r["ingredients"][0]["pieces"])
verifier(any("compenser l'arrondi" in a for a in r["avertissements"]),
         "l'écart à la cible est annoncé, pas masqué", r["avertissements"])
verifier(presque(r["par_portion"]["kcal"], 200.0),
         "les macros affichées sont celles réellement obtenues",
         r["par_portion"]["kcal"])

print()
print("=== un ingrédient fixe ignore unite_piece ===")
rec = recette_oeuf()
rec["ingredients"][0]["echelle"] = "fixe"
r = nutrition.calculer(rec, ALIMENTS, kcal_cible=400)
verifier(r["ingredients"][0]["pieces"] is None,
         "pas d'arrondi en pièces sur un ingrédient fixe")
verifier(presque(r["ingredients"][0]["grammes"], 50.0),
         "il garde simplement sa quantité", r["ingredients"][0]["grammes"])

print()
if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Tous les tests du moteur nutritionnel passent.")
