# -*- coding: utf-8 -*-
"""Vérifie que chaque ingrédient pointe vers la BONNE fiche Ciqual.

    python tools/auditer_recettes.py

Un code Ciqual est un nombre : rien n'empêche de saisir 11010 en croyant
désigner le paprika alors qu'il s'agit de la levure de boulanger. L'erreur est
invisible — la recette reste valide, le total calorique reste plausible — et
c'est exactement comme cela qu'elle s'est produite une fois.

Cet outil compare le nom donné à l'ingrédient et le libellé de sa fiche
Ciqual. S'ils ne partagent aucun mot significatif, il le signale. Beaucoup de
signalements sont légitimes (« salade verte » -> « Laitue, crue ») : ce sont
ceux qui portent une note explicative dans la recette. Les autres méritent un
second regard.
"""
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aliments  # noqa: E402
import recettes  # noqa: E402

# Mots trop courants pour signifier quoi que ce soit dans une comparaison.
VIDES = {"de", "du", "des", "la", "le", "les", "au", "aux", "en", "et", "un",
         "une", "sans", "cru", "crue", "crus", "cuit", "cuite", "poudre",
         "sechee", "seche", "frais", "fraiche", "nature", "vierge", "extra",
         "environ", "appertise", "egoutte", "preemballe", "surgele"}


def mots(texte: str) -> set[str]:
    """Racines des mots significatifs, accents et pluriels neutralisés."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte.lower())
        if unicodedata.category(c) != "Mn")
    # Le pluriel est coupé avant la troncature, sans quoi « oeufs » et
    # « oeuf » passeraient pour deux mots différents.
    return {re.sub(r"[sx]$", "", m)[:5]
            for m in re.findall(r"[a-z]+", sans_accent)
            if len(m) > 2 and m not in VIDES}


def main() -> int:
    connus = aliments.get_aliments(recettes.codes_utilises())
    introuvables, divergents = [], []

    for recette in recettes.charger_toutes():
        for ing in recette["ingredients"]:
            code = ing.get("ciqual_code")
            fiche = connus.get(code)
            if fiche is None:
                introuvables.append((recette["id"], ing["nom"], code))
            elif not (mots(ing["nom"]) & mots(fiche["nom"])):
                divergents.append((recette["id"], ing["nom"], fiche["nom"],
                                   bool(ing.get("notes"))))

    for rid, nom, code in introuvables:
        print(f"[KO]   {rid} : « {nom} » -> code {code} INTROUVABLE")

    explique = [d for d in divergents if d[3]]
    muets = [d for d in divergents if not d[3]]

    for rid, nom, fiche, _ in muets:
        print(f"[!]    {rid} : « {nom} » -> « {fiche} »  (sans note)")
    for rid, nom, fiche, _ in explique:
        print(f"[ok]   {rid} : « {nom} » -> « {fiche} »  (documenté)")

    print()
    print(f"{len(recettes.charger_toutes())} recettes, "
          f"{len(recettes.codes_utilises())} codes Ciqual distincts.")
    print(f"codes introuvables : {len(introuvables)}")
    print(f"noms divergents    : {len(divergents)} "
          f"dont {len(muets)} sans note explicative")

    # Un code introuvable est une erreur ; un nom divergent, une invitation à
    # vérifier. Seul le premier cas fait échouer l'audit.
    return 1 if introuvables else 0


if __name__ == "__main__":
    sys.exit(main())
