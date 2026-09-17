# -*- coding: utf-8 -*-
"""
Tests de l'import Ciqual : lecture des valeurs et reconstitution de l'énergie.

    python tests/test_import_ciqual.py

Tout est pur : aucun accès au fichier xlsx ni à la base.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import import_ciqual as ic  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


def presque(a, b, tolerance=0.05):
    return a is not None and b is not None and abs(a - b) <= tolerance


print("=== lecture des valeurs Ciqual ===")
# Les pièges réels du fichier de l'ANSES.
cas = [
    ("7,52", 7.52, "virgule décimale"),
    ("255", 255.0, "entier"),
    ("-", None, "« - » = donnée ABSENTE, pas zéro"),
    ("traces", 0.0, "« traces » = 0"),
    ("< 0,5", 0.5, "« < 0,5 » -> borne haute 0,5"),
    ("< 3", 3.0, "« < 3 » -> borne haute 3"),
    ("", None, "cellule vide"),
    (None, None, "cellule absente"),
    (12.5, 12.5, "nombre déjà typé"),
    ("0,00001", 0.00001, "très petite valeur"),
    ("n/a", None, "texte inattendu -> absent plutôt que faux"),
]
for brut, attendu, libelle in cas:
    obtenu = ic.parse_valeur(brut)
    ok = (obtenu is None and attendu is None) or presque(obtenu, attendu, 1e-9)
    verifier(ok, f"{libelle} : {brut!r} -> {attendu}", obtenu)

print()
print("=== normalisation des en-têtes multi-lignes ===")
entete = "Energie,\nRèglement\nUE N°\n1169\n2011 (kcal\n100 g)"
verifier(ic.normaliser_entete(entete)
         == "energie, règlement ue n° 1169 2011 (kcal 100 g)",
         "en-tête sur 6 lignes compacté en une chaîne comparable",
         ic.normaliser_entete(entete))
verifier(ic.normaliser_nom("Pâtes sèches, aux œufs") == "pates seches, aux œufs",
         "nom d'aliment sans accent pour la recherche",
         ic.normaliser_nom("Pâtes sèches, aux œufs"))

print()
print("=== reconstitution de l'énergie manquante ===")
# Sirop d'agave : Ciqual donne les macros mais laisse l'énergie vide.
agave = {"proteines": 0.25, "glucides": 78.0, "lipides": 0.5, "fibres": 0.0}
verifier(presque(ic.energie_depuis_macros(agave), 317.5),
         "sirop d'agave -> 317,5 kcal/100 g",
         ic.energie_depuis_macros(agave))

# Câpres au vinaigre : mêmes symptômes, avec beaucoup de fibres.
capres = {"proteines": 2.18, "glucides": 3.5, "lipides": 0.86, "fibres": 3.6}
verifier(presque(ic.energie_depuis_macros(capres), 37.7),
         "câpres au vinaigre -> 37,7 kcal/100 g",
         ic.energie_depuis_macros(capres))

verifier(presque(ic.energie_depuis_macros(
    {"proteines": 10, "glucides": 0, "lipides": 0}), 40.0),
    "10 g de protéines seules -> 40 kcal")
verifier(presque(ic.energie_depuis_macros(
    {"proteines": 0, "glucides": 0, "lipides": 10}), 90.0),
    "10 g de lipides seuls -> 90 kcal")

print()
print("=== les termes au-delà des trois macros de base ===")
base = {"proteines": 0.0, "glucides": 0.0, "lipides": 0.0}
verifier(presque(ic.energie_depuis_macros({**base, "fibres": 10}), 20.0),
         "fibres comptées à 2 kcal/g")
verifier(presque(ic.energie_depuis_macros({**base, "polyols": 10}), 24.0),
         "polyols comptés à 2,4 kcal/g (bonbons sans sucres)")
verifier(presque(ic.energie_depuis_macros({**base, "alcool": 10}), 70.0),
         "alcool compté à 7 kcal/g (liqueurs)")
verifier(presque(ic.energie_depuis_macros({**base, "acides_org": 10}), 30.0),
         "acides organiques comptés à 3 kcal/g")
verifier(presque(ic.energie_depuis_macros(base), 0.0),
         "aucune macro -> 0 kcal, pas None (les trois de base sont là)")

print()
print("=== on ne devine pas : refus si les macros de base manquent ===")
for manquant in ("proteines", "glucides", "lipides"):
    partiel = dict(agave)
    partiel[manquant] = None
    verifier(ic.energie_depuis_macros(partiel) is None,
             f"{manquant} absent -> None (donnée laissée absente)",
             ic.energie_depuis_macros(partiel))
verifier(ic.energie_depuis_macros({}) is None, "dictionnaire vide -> None")
verifier(ic.energie_depuis_macros({"proteines": 1, "glucides": 1}) is None,
         "lipides jamais renseignés -> None")

# Les termes secondaires absents sont comptés 0, pas bloquants.
verifier(presque(ic.energie_depuis_macros(
    {"proteines": 1, "glucides": 1, "lipides": 1}), 17.0),
    "fibres/polyols/alcool absents comptés 0 (1x4 + 1x4 + 1x9 = 17)",
    ic.energie_depuis_macros({"proteines": 1, "glucides": 1, "lipides": 1}))

print()
print("=== les coefficients sont bien ceux du règlement UE 1169/2011 ===")
attendus = {"proteines": 4.0, "glucides": 4.0, "lipides": 9.0, "fibres": 2.0,
            "polyols": 2.4, "alcool": 7.0, "acides_org": 3.0}
verifier(ic.FACTEURS_ENERGIE == attendus, "annexe XIV respectée",
         ic.FACTEURS_ENERGIE)

print()
print("=== repérage des colonnes par mots-clés ===")
entetes = [ic.normaliser_entete(h) for h in (
    "alim_grp_code", "alim_ssgrp_code", "alim_ssssgrp_code", "alim_grp_nom_fr",
    "alim_ssgrp_nom_fr", "alim_ssssgrp_nom_fr", "alim_code", "alim_nom_fr",
    "alim_nom_sci",
    "Energie,\nRèglement\nUE N°\n1169\n2011 (kJ\n100 g)",
    "Energie,\nRèglement\nUE N°\n1169\n2011 (kcal\n100 g)",
    "Energie, N x\nfacteur\nJones, avec\nfibres (kJ\n100 g)",
    "Energie, N x\nfacteur\nJones, avec\nfibres (kcal\n100 g)",
    "Eau\n(g\n100\ng)",
    "Protéines,\nN x\nfacteur de\nJones (g\n100 g)",
    "Protéines,\nN x 6.25\n(g\n100 g)",
    "Glucides\n(g\n100 g)", "Lipides\n(g\n100 g)", "Sucres\n(g\n100 g)",
    "Fibres\nalimentaires\n(g\n100 g)", "Polyols totaux\n(g\n100 g)",
    "Alcool (éthanol)\n(g\n100 g)", "Acides organiques\n(g\n100 g)",
    "Sel chlorure de sodium\n(g\n100 g)")]
col = ic.reperer_colonnes(entetes)
verifier(col["kcal"] == 10,
         "l'énergie retenue est celle du RÈGLEMENT UE, pas celle « N x Jones »",
         col["kcal"])
verifier(col["proteines"] == 14,
         "les protéines retenues sont « N x facteur de Jones », pas « N x 6.25 »",
         col["proteines"])
verifier(col["polyols"] == 20 and col["alcool"] == 21 and col["acides_org"] == 22,
         "les colonnes servant au calcul d'énergie sont repérées",
         {k: col[k] for k in ("polyols", "alcool", "acides_org")})

# Une colonne disparue doit faire échouer l'import, pas passer inaperçue.
try:
    ic.reperer_colonnes([h for h in entetes if "glucides" not in h])
    verifier(False, "colonne manquante -> l'import s'arrête")
except SystemExit as e:
    verifier("glucides" in str(e), "colonne manquante -> l'import s'arrête "
             "en nommant le champ", str(e)[:70])

print()
if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Tous les tests de l'import Ciqual passent.")
