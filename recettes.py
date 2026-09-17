# -*- coding: utf-8 -*-
"""
Recettes : un fichier JSON par recette dans `recettes/`.

Pourquoi des fichiers et pas la base ? Les recettes sont saisies une fois
pour toutes (extraites de photos), rarement modifiées, et ont vocation à
être relues et corrigées à la main. En JSON versionné dans git, elles sont
lisibles, diffables et restaurables — ce qu'une ligne de SQLite n'est pas.

Contrat du format (cf. recettes/_exemple.json) :

    id                 slug, = nom du fichier sans .json
    titre              obligatoire
    source             d'où vient la recette (photo, livre, site…)
    portions_base      nombre de portions de la recette d'origine (> 0)
    temps_prepa_min    entier, optionnel
    temps_cuisson_min  entier, optionnel
    tags               liste de mots-clés, optionnelle
    ingredients[]      nom, ciqual_code, quantite, unite,
                       quantite_affichee (texte de cuisine), echelle
    etapes[]           mode opératoire, une chaîne par étape
    notes              texte libre, optionnel

`echelle` vaut « variable » (l'ingrédient suit la cible calorique) ou
« fixe » (assaisonnements : sel, épices, levure — doubler les calories d'un
plat ne doit pas doubler le piment). C'est ce champ qui rend le calibrage
réaliste ; voir nutrition.calibrer().
"""
import json
import re
import unicodedata
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent / "recettes"
ECHELLES = ("variable", "fixe")
# Dans une recette, `quantite` est TOUJOURS une masse ou un volume : la
# conversion des « 1 gousse » / « 2 c. à soupe » est faite en amont, à
# l'extraction depuis la photo, et le texte de cuisine d'origine est conservé
# dans `quantite_affichee`. On n'a ainsi jamais à deviner une densité au
# moment du calcul.
UNITES_RECETTE = ("g", "ml")
CHAMPS_INGREDIENT = {"nom", "ciqual_code", "quantite", "unite",
                     "quantite_affichee", "echelle", "notes",
                     "unite_piece", "nom_piece", "pas_piece"}


def slug(texte: str) -> str:
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", sans_accent).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "recette"


def chemin(recette_id: str) -> Path:
    return DOSSIER / f"{slug(recette_id)}.json"


def valider(recette: dict) -> list[str]:
    """Renvoie la liste des erreurs. Liste vide = recette exploitable."""
    erreurs: list[str] = []

    if not isinstance(recette, dict):
        return ["La recette n'est pas un objet JSON."]
    if not str(recette.get("titre") or "").strip():
        erreurs.append("titre manquant")
    if not str(recette.get("id") or "").strip():
        erreurs.append("id manquant")
    elif slug(recette["id"]) != recette["id"]:
        erreurs.append(f"id « {recette['id']} » non conforme "
                       f"(attendu : « {slug(recette['id'])} »)")

    try:
        portions = float(recette.get("portions_base"))
        if portions <= 0:
            erreurs.append("portions_base doit être > 0")
    except (TypeError, ValueError):
        erreurs.append("portions_base manquant ou non numérique")

    ingredients = recette.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        erreurs.append("aucun ingrédient")
    else:
        for i, ing in enumerate(ingredients, 1):
            prefixe = f"ingrédient {i}"
            if not isinstance(ing, dict):
                erreurs.append(f"{prefixe} : format invalide")
                continue
            nom = str(ing.get("nom") or "").strip()
            if not nom:
                erreurs.append(f"{prefixe} : nom manquant")
            prefixe = f"« {nom or i} »"
            try:
                if float(ing.get("quantite")) <= 0:
                    erreurs.append(f"{prefixe} : quantite doit être > 0")
            except (TypeError, ValueError):
                erreurs.append(f"{prefixe} : quantite manquante ou non numérique")
            unite = str(ing.get("unite") or "").strip().lower()
            if not unite:
                erreurs.append(f"{prefixe} : unite manquante")
            elif unite not in UNITES_RECETTE:
                erreurs.append(
                    f"{prefixe} : unite « {unite} » interdite (attendu : "
                    f"{' ou '.join(UNITES_RECETTE)} ; le texte de cuisine va "
                    f"dans quantite_affichee)")
            if ing.get("echelle") not in ECHELLES:
                erreurs.append(f"{prefixe} : echelle doit valoir "
                               f"« variable » ou « fixe »")
            if "unite_piece" in ing and ing["unite_piece"] is not None:
                try:
                    if float(ing["unite_piece"]) <= 0:
                        erreurs.append(f"{prefixe} : unite_piece doit être > 0")
                except (TypeError, ValueError):
                    erreurs.append(f"{prefixe} : unite_piece non numérique")
                if ing.get("echelle") == "fixe":
                    erreurs.append(
                        f"{prefixe} : unite_piece n'a pas de sens sur un "
                        f"ingrédient « fixe » (sa quantité ne varie pas)")
            if "pas_piece" in ing and ing["pas_piece"] is not None:
                if not ing.get("unite_piece"):
                    erreurs.append(f"{prefixe} : pas_piece exige unite_piece "
                                   f"(un pas d'arrondi sans pièce à arrondir)")
                try:
                    pas = float(ing["pas_piece"])
                    if pas < 1 or pas != int(pas):
                        erreurs.append(f"{prefixe} : pas_piece doit être un "
                                       f"entier >= 1")
                except (TypeError, ValueError):
                    erreurs.append(f"{prefixe} : pas_piece non numérique")
            inconnus = set(ing) - CHAMPS_INGREDIENT
            if inconnus:
                erreurs.append(f"{prefixe} : champ(s) inconnu(s) "
                               f"{', '.join(sorted(inconnus))}")

    etapes = recette.get("etapes")
    if etapes is not None and not isinstance(etapes, list):
        erreurs.append("etapes doit être une liste de chaînes")

    return erreurs


def charger(recette_id: str) -> dict | None:
    fichier = chemin(recette_id)
    if not fichier.exists():
        return None
    recette = json.loads(fichier.read_text(encoding="utf-8"))
    recette.setdefault("id", fichier.stem)
    return recette


def charger_toutes(silencieux: bool = True) -> list[dict]:
    """Toutes les recettes valides, triées par titre.

    Une recette invalide est ignorée mais signalée dans sa clé `_erreurs`
    afin de rester visible dans la liste plutôt que de disparaître sans bruit.
    """
    resultat = []
    if not DOSSIER.exists():
        return resultat
    for fichier in sorted(DOSSIER.glob("*.json")):
        if fichier.name.startswith("_"):
            continue            # _exemple.json, _schema.json : documentation
        try:
            recette = json.loads(fichier.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            if not silencieux:
                raise
            resultat.append({"id": fichier.stem, "titre": fichier.stem,
                             "ingredients": [], "portions_base": 1,
                             "_erreurs": [f"JSON illisible : {e}"]})
            continue
        recette.setdefault("id", fichier.stem)
        erreurs = valider(recette)
        if erreurs:
            recette["_erreurs"] = erreurs
        resultat.append(recette)
    return sorted(resultat, key=lambda r: (r.get("titre") or "").lower())


def ecrire(recette: dict) -> Path:
    """Ecrit la recette sur disque. Refuse une recette invalide."""
    erreurs = valider(recette)
    if erreurs:
        raise ValueError("Recette invalide : " + " ; ".join(erreurs))
    DOSSIER.mkdir(parents=True, exist_ok=True)
    fichier = chemin(recette["id"])
    fichier.write_text(
        json.dumps(recette, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return fichier


def supprimer(recette_id: str) -> bool:
    fichier = chemin(recette_id)
    if fichier.exists():
        fichier.unlink()
        return True
    return False


def codes_utilises() -> set[str]:
    """Tous les codes d'aliments référencés par les recettes."""
    codes = set()
    for recette in charger_toutes():
        for ing in recette.get("ingredients") or []:
            if ing.get("ciqual_code"):
                codes.add(str(ing["ciqual_code"]))
    return codes
