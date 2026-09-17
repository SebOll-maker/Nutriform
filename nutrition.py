# -*- coding: utf-8 -*-
"""
Moteur nutritionnel : macros d'une recette et calibrage sur une cible calorique.

C'est le cœur de l'application, et la seule partie qui mérite d'être lue
attentivement. Tout y est PUR : aucune dépendance à Flask ni à la base. Les
aliments sont passés en argument sous forme d'un dictionnaire
{code: {kcal, proteines, ...}}, ce qui rend l'ensemble testable directement.

                            --- LE CALIBRAGE ---

Chaque ingrédient est « variable » (il suit la cible calorique) ou « fixe »
(sel, épices, levure : passer une portion de 400 à 600 kcal ne doit pas
multiplier le piment par 1,5).

Soit une recette de P portions, F les kcal totales de ses ingrédients fixes
et V celles de ses ingrédients variables. Pour obtenir N portions de T kcal :

  - les ingrédients fixes suivent le nombre de portions       -> x N/P
  - les variables reçoivent le coefficient k tel que
        N.T = F.(N/P) + V.k
    soit
        k = (N.T - F.N/P) / V

                    --- LES UNITES INDIVISIBLES ---

Un ingrédient variable peut porter `unite_piece` (le poids d'une pièce) : on
n'achète pas 1,27 œuf. Il est alors arrondi à la pièce entière la plus proche,
et — c'est le point important — les ingrédients variables restants sont
**réajustés** pour retomber exactement sur la cible. Sans ce réajustement,
l'arrondi ferait dériver les calories, ce qui viderait le calibrage de son sens.

En notant I les kcal des indivisibles une fois arrondis et D celles des
variables divisibles :

        k_div = (N.T - F.N/P - I) / D

Une pièce au minimum : un ingrédient inscrit dans la recette ne doit pas
disparaître silencieusement parce que la cible est basse.

Les situations dégradées sont détectées et EXPLIQUEES au lieu de produire un
résultat absurde :

  - V = 0           : recette 100 % fixe, rien à faire varier.
  - k <= 0          : la cible est sous le plancher imposé par les
                      assaisonnements et les pièces entières.
  - D = 0           : tous les variables sont indivisibles, la cible ne peut
                      être atteinte qu'approximativement — on le dit.
  - k hors [1/3, 3] : on calibre mais on avertit, les proportions ont changé.
"""

NUTRIMENTS = ("kcal", "proteines", "glucides", "lipides", "fibres", "sucres", "sel")

# `unite` dans une recette : masse ou volume. Le volume est ramené à la masse
# à 1 g/ml, ce qui est exact pour l'eau et le lait, et surestime de 5 à 10 %
# les huiles. Précision suffisante pour un suivi de régime ; pour être exact,
# saisir l'huile en grammes.
DENSITES = {"g": 1.0, "ml": 1.0}

COEF_MIN_RAISONNABLE = 1 / 3
COEF_MAX_RAISONNABLE = 3.0

LIBELLE_NUTRIMENT = {
    "kcal": "énergie", "proteines": "protéines", "glucides": "glucides",
    "lipides": "lipides", "fibres": "fibres", "sucres": "sucres", "sel": "sel",
}


def grammes_ingredient(ing: dict) -> float | None:
    """Quantité d'un ingrédient en grammes, ou None si l'unité est inconnue."""
    unite = str(ing.get("unite") or "g").strip().lower()
    if unite not in DENSITES:
        return None
    try:
        return float(ing["quantite"]) * DENSITES[unite]
    except (TypeError, ValueError, KeyError):
        return None


def macros_pour(aliment: dict | None, grammes: float) -> dict:
    """Apports d'une quantité d'aliment. None reste None (donnée absente)."""
    if not aliment or grammes is None:
        return {n: None for n in NUTRIMENTS}
    facteur = grammes / 100.0
    return {n: (None if aliment.get(n) is None else aliment[n] * facteur)
            for n in NUTRIMENTS}


def _cumuler(total: dict, part: dict) -> dict:
    """Somme de macros. Une valeur absente compte pour 0 dans le total, mais
    l'ingrédient concerné est signalé à part (voir `calculer`)."""
    for n in NUTRIMENTS:
        total[n] = (total.get(n) or 0.0) + (part.get(n) or 0.0)
    return total


def _taille_piece(ing: dict) -> float | None:
    """Poids d'une pièce, si l'ingrédient est indivisible."""
    try:
        taille = float(ing.get("unite_piece"))
    except (TypeError, ValueError):
        return None
    return taille if taille > 0 else None


def _pas_piece(ing: dict) -> int:
    """Pas d'arrondi, en nombre de pièces (défaut : 1).

    Certains ingrédients ne s'emploient que par multiples : il faut DEUX
    tranches de pain de mie pour faire un croque-monsieur, deux moitiés de
    pain pour un burger. Avec `pas_piece: 2`, l'arrondi tombe sur 2, 4, 6
    tranches — jamais 3 — et le minimum est de 2 pièces, pas d'une.
    """
    try:
        pas = int(ing.get("pas_piece") or 1)
    except (TypeError, ValueError):
        return 1
    return pas if pas >= 1 else 1


def _pluriel(nom: str, n: float) -> str:
    if n <= 1 or nom.endswith(("s", "x")):
        return nom
    return nom + "s"


def calculer(recette: dict, aliments: dict,
             kcal_cible: float | None = None,
             portions: float | None = None) -> dict:
    """Analyse une recette, éventuellement calibrée sur une cible calorique.

    kcal_cible = None -> recette à ses proportions d'origine (simple mise à
    l'échelle sur le nombre de portions voulu).
    """
    portions_base = float(recette.get("portions_base") or 1) or 1.0
    portions_voulues = float(portions) if portions else portions_base
    facteur_portions = portions_voulues / portions_base

    lignes: list[dict] = []
    sans_donnees: list[str] = []
    unites_invalides: list[str] = []
    energies_calculees: list[str] = []
    # Ciqual laisse des trous nutriment par nutriment : la levure chimique,
    # par exemple, a bien une valeur énergétique mais aucune teneur en sel.
    # Sommer sans le dire sous-estimerait le total en silence.
    incomplets: dict[str, list[str]] = {}

    for ing in recette.get("ingredients") or []:
        code = str(ing.get("ciqual_code")) if ing.get("ciqual_code") else None
        aliment = aliments.get(code) if code else None
        grammes = grammes_ingredient(ing)
        nom = ing.get("nom") or "(sans nom)"

        if grammes is None:
            unites_invalides.append(nom)
        if aliment is None or aliment.get("kcal") is None:
            sans_donnees.append(nom)
        elif grammes:
            # L'aliment est connu : on relève les nutriments qui, LUI, manquent.
            for nutriment in NUTRIMENTS:
                if nutriment != "kcal" and aliment.get(nutriment) is None:
                    incomplets.setdefault(nutriment, []).append(nom)
            if aliment.get("kcal_estimee"):
                energies_calculees.append(nom)

        base = macros_pour(aliment, grammes or 0.0)
        fixe = ing.get("echelle") == "fixe"
        taille_piece = None if fixe else _taille_piece(ing)

        lignes.append({
            "nom": nom,
            "ciqual_code": code,
            "aliment_nom": (aliment or {}).get("nom"),
            "echelle": "fixe" if fixe else "variable",
            "quantite_affichee": ing.get("quantite_affichee"),
            "grammes_base": grammes or 0.0,
            "macros_base": base,
            "connu": aliment is not None and aliment.get("kcal") is not None,
            "unite_piece": taille_piece,
            "pas_piece": _pas_piece(ing) if taille_piece else 1,
            "indivisible": bool(taille_piece),
            "nom_piece": ing.get("nom_piece") or nom.lower(),
            "kcal_estimee": bool((aliment or {}).get("kcal_estimee")),
        })

    fixes = [l for l in lignes if l["echelle"] == "fixe"]
    indivisibles = [l for l in lignes
                    if l["echelle"] == "variable" and l["unite_piece"]]
    divisibles = [l for l in lignes
                  if l["echelle"] == "variable" and not l["unite_piece"]]

    def kcal_de(groupe) -> float:
        return sum(l["macros_base"]["kcal"] or 0.0 for l in groupe)

    kcal_fixes = kcal_de(fixes)
    kcal_indivisibles = kcal_de(indivisibles)
    kcal_divisibles = kcal_de(divisibles)
    kcal_variables = kcal_indivisibles + kcal_divisibles

    # Plancher : ce que la portion coûte au minimum, une fois les
    # assaisonnements mis à l'échelle et chaque indivisible réduit à son
    # plus petit emploi possible (une pièce, ou `pas_piece` pièces).
    kcal_une_piece = sum(
        (l["macros_base"]["kcal"] or 0.0) / l["grammes_base"]
        * l["unite_piece"] * l["pas_piece"]
        for l in indivisibles if l["grammes_base"])
    plancher = ((kcal_fixes * facteur_portions + kcal_une_piece)
                / portions_voulues) if portions_voulues else 0.0

    avertissements: list[str] = []
    message = None
    possible = True
    coefficient = facteur_portions          # appliqué aux variables divisibles
    coefficient_indivisibles = facteur_portions

    if kcal_cible is not None:
        besoin = portions_voulues * float(kcal_cible)
        apport_fixe = kcal_fixes * facteur_portions

        if kcal_variables <= 0:
            possible = False
            message = ("Tous les ingrédients caloriques de cette recette sont "
                       "marqués « fixe » : il n'y a rien à faire varier pour "
                       "atteindre une cible calorique.")
        else:
            k0 = (besoin - apport_fixe) / kcal_variables
            coefficient_indivisibles = k0
            if k0 <= 0:
                possible = False
                message = (
                    f"Cible inatteignable : les ingrédients fixes apportent "
                    f"déjà {kcal_fixes / portions_base:.0f} kcal par portion. "
                    f"Viser au moins {kcal_fixes / portions_base:.0f} kcal, ou "
                    f"passer un ingrédient en « variable ».")
                coefficient = facteur_portions
            else:
                coefficient = k0

    # --- Quantités des indivisibles : arrondi à la pièce entière ---------
    kcal_apres_arrondi = 0.0
    for ligne in indivisibles:
        if not ligne["grammes_base"]:
            ligne["pieces"] = 0
            ligne["facteur"] = 0.0
            continue
        vise = ligne["grammes_base"] * coefficient_indivisibles
        pas = ligne["pas_piece"]
        # Arrondi au multiple de `pas` le plus proche, `pas` au minimum.
        pieces = max(pas, round(vise / ligne["unite_piece"] / pas) * pas)
        grammes = pieces * ligne["unite_piece"]
        ligne["pieces"] = pieces
        ligne["facteur"] = grammes / ligne["grammes_base"]
        kcal_apres_arrondi += ((ligne["macros_base"]["kcal"] or 0.0)
                               * ligne["facteur"])

    # --- Réajustement des divisibles pour retomber sur la cible ----------
    if kcal_cible is not None and possible:
        reste = (portions_voulues * float(kcal_cible)
                 - kcal_fixes * facteur_portions - kcal_apres_arrondi)
        if kcal_divisibles > 0:
            coefficient = reste / kcal_divisibles
            if coefficient <= 0:
                possible = False
                message = (
                    f"Cible inatteignable : les ingrédients fixes et les pièces "
                    f"entières (œufs et assimilés) apportent déjà "
                    f"{plancher:.0f} kcal par portion. Viser au moins "
                    f"{plancher:.0f} kcal.")
                coefficient = coefficient_indivisibles
        elif indivisibles:
            # Rien de divisible pour compenser : la cible ne sera
            # qu'approchée, et il faut le dire plutôt que de le masquer.
            atteint = (kcal_fixes * facteur_portions
                       + kcal_apres_arrondi) / portions_voulues
            if abs(atteint - float(kcal_cible)) > 1:
                avertissements.append(
                    f"Aucun ingrédient divisible pour compenser l'arrondi aux "
                    f"pièces entières : la portion fait {atteint:.0f} kcal au "
                    f"lieu des {float(kcal_cible):.0f} kcal visées.")

    # Avertir sur les proportions n'a de sens que si elles peuvent réellement
    # se déformer, c'est-à-dire s'il existe un ingrédient qui NE suit PAS le
    # coefficient : un fixe, ou un indivisible arrondi. Sans cela, tous les
    # ingrédients sont multipliés par le même nombre et le plat reste
    # rigoureusement lui-même — une collation d'un seul ingrédient triplée
    # n'est pas « déformée », c'est juste une plus grosse poignée.
    if (possible and kcal_cible is not None and facteur_portions
            and (fixes or indivisibles)):
        rapport = coefficient / facteur_portions
        if rapport > COEF_MAX_RAISONNABLE or rapport < COEF_MIN_RAISONNABLE:
            avertissements.append(
                f"Les ingrédients variables sont multipliés par "
                f"{rapport:.2f}".replace(".", ",") +
                " par rapport à la recette d'origine : les proportions ne "
                "sont plus celles du plat initial.")

    if sans_donnees:
        avertissements.append(
            "Valeur énergétique inconnue pour : " + ", ".join(sans_donnees) +
            ". Ces ingrédients comptent pour 0, le total est donc sous-estimé.")
    if incomplets:
        details = "; ".join(
            f"{LIBELLE_NUTRIMENT.get(n, n)} ({', '.join(noms)})"
            for n, noms in incomplets.items())
        avertissements.append(
            "Ciqual ne renseigne pas tous les nutriments de tous les "
            f"ingrédients : {details}. Ces totaux-là sont sous-estimés.")
    if energies_calculees:
        avertissements.append(
            "Énergie calculée depuis les macronutriments (Ciqual ne la "
            "fournit pas) pour : " + ", ".join(energies_calculees) + ".")
    if unites_invalides:
        avertissements.append(
            "Unité non exploitable pour : " + ", ".join(unites_invalides) + ".")

    # --- Quantités finales et macros recalculées dessus ------------------
    total = {n: 0.0 for n in NUTRIMENTS}
    for ligne in lignes:
        if not ligne["indivisible"]:          # les indivisibles sont déjà figés
            ligne["facteur"] = (facteur_portions if ligne["echelle"] == "fixe"
                                else coefficient)
            ligne["pieces"] = None

        ligne["grammes"] = ligne["grammes_base"] * ligne["facteur"]
        ligne["macros"] = {n: (None if ligne["macros_base"][n] is None
                               else ligne["macros_base"][n] * ligne["facteur"])
                           for n in NUTRIMENTS}
        # Le texte de cuisine ne reste affichable que si la quantité n'a pas
        # bougé : « 4 blancs de poulet » x 1,3 n'aurait aucun sens.
        ligne["apercu"] = (ligne["quantite_affichee"]
                           if abs(ligne["facteur"] - 1.0) < 1e-9 else None)
        # Un indivisible, lui, s'affiche toujours en pièces : c'est tout
        # l'intérêt de l'arrondi.
        ligne["libelle_piece"] = (
            f"{ligne['pieces']:.0f} {_pluriel(ligne['nom_piece'], ligne['pieces'])}"
            if ligne["pieces"] else None)
        _cumuler(total, ligne["macros"])

    par_portion = {n: (total[n] / portions_voulues if portions_voulues else 0.0)
                   for n in NUTRIMENTS}

    return {
        "recette_id": recette.get("id"),
        "titre": recette.get("titre"),
        "portions_base": portions_base,
        "portions": portions_voulues,
        "kcal_cible": float(kcal_cible) if kcal_cible is not None else None,
        "coefficient": coefficient,
        "possible": possible,
        "message": message,
        "avertissements": avertissements,
        "kcal_fixes": kcal_fixes,
        "kcal_variables": kcal_variables,
        "nutriments_incomplets": incomplets,
        "energies_calculees": energies_calculees,
        "plancher_kcal_portion": plancher,
        "ingredients": lignes,
        "total": total,
        "par_portion": par_portion,
    }


def codes_recette(recette: dict) -> list[str]:
    """Codes d'aliments à charger pour calculer cette recette."""
    return [str(i["ciqual_code"]) for i in (recette.get("ingredients") or [])
            if i.get("ciqual_code")]
