# -*- coding: utf-8 -*-
"""
Import de la table Ciqual de l'ANSES dans la table `aliment`.

Source : https://ciqual.anses.fr — jeu de données Recherche Data Gouv
DOI 10.57745/RDMHWY, licence Etalab 2.0 (attribution obligatoire).
Fichier attendu : « Table Ciqual 2025_FR_*.xlsx » (feuille
« composition nutritionnelle »), 3 484 aliments, 84 colonnes.

Deux partis pris, volontaires et documentés ici :

1. CHOIX DES COLONNES. Ciqual propose plusieurs variantes du même nutriment.
   On retient celles de l'étiquetage réglementaire européen, qui sont celles
   qu'on lit sur un paquet :
     - énergie  -> « Energie, Règlement UE N° 1169/2011 (kcal/100 g) »
     - protéines-> « Protéines, N x facteur de Jones » (et non N x 6,25)
   Les colonnes sont repérées par MOTS-CLES d'en-tête, pas par numéro, pour
   survivre à une future édition de la table.

2. VALEURS NON NUMERIQUES. Ciqual n'utilise pas que des nombres :
     - « - »       -> donnée absente      -> NULL  (à ne PAS confondre avec 0)
     - « traces »  -> présence infime     -> 0.0
     - « < 0,5 »   -> sous le seuil de quantification -> 0,5
       (on garde la borne HAUTE : mieux vaut surestimer légèrement un apport
        que de le sous-estimer dans un suivi de régime)
   Le séparateur décimal est la VIRGULE.

Usage :
    python import_ciqual.py                     # cherche le xlsx dans data/ciqual/
    python import_ciqual.py chemin/vers/fichier.xlsx
"""
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import openpyxl

import db

FEUILLE = "composition nutritionnelle"
DOSSIER_DEFAUT = Path(__file__).resolve().parent / "data" / "ciqual"

# Chaque champ -> liste de mots-clés qui doivent TOUS figurer dans l'en-tête
# (normalisé : espaces compactés, minuscules).
COLONNES = {
    "code":        ["alim_code"],
    "nom":         ["alim_nom_fr"],
    "groupe":      ["alim_grp_nom_fr"],
    "sous_groupe": ["alim_ssgrp_nom_fr"],
    "kcal":        ["energie", "règlement", "kcal"],
    "proteines":   ["protéines", "facteur de jones"],
    "glucides":    ["glucides ("],
    "lipides":     ["lipides ("],
    "sucres":      ["sucres ("],
    "fibres":      ["fibres alimentaires"],
    "sel":         ["sel chlorure de sodium"],
    # Lues uniquement pour reconstituer l'énergie manquante (voir
    # energie_depuis_macros) : elles ne sont pas stockées.
    "polyols":     ["polyols totaux"],
    "alcool":      ["alcool"],
    "acides_org":  ["acides organiques"],
}

NUTRIMENTS = ("kcal", "proteines", "glucides", "lipides", "sucres", "fibres", "sel")
POUR_ENERGIE = ("polyols", "alcool", "acides_org")

# Coefficients de conversion de l'annexe XIV du règlement (UE) n° 1169/2011,
# en kcal par gramme. Ce sont ceux avec lesquels l'ANSES calcule elle-même la
# colonne « Energie, Règlement UE » de la table.
FACTEURS_ENERGIE = {
    "proteines": 4.0,
    "glucides": 4.0,     # hors polyols : Ciqual les compte à part
    "lipides": 9.0,
    "fibres": 2.0,
    "polyols": 2.4,
    "alcool": 7.0,
    "acides_org": 3.0,
}


def normaliser_entete(valeur) -> str:
    """En-têtes Ciqual multi-lignes -> une chaîne comparable."""
    return re.sub(r"\s+", " ", str(valeur or "")).strip().lower()


def normaliser_nom(nom: str) -> str:
    """Nom d'aliment -> forme sans accent, minuscule, pour la recherche."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", nom)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sans_accent).strip().lower()


def parse_valeur(brut):
    """Valeur Ciqual -> float ou None. Voir le parti pris n°2 en tête de module."""
    if brut is None:
        return None
    if isinstance(brut, (int, float)):
        return float(brut)
    texte = str(brut).strip()
    if texte in ("", "-"):
        return None
    if texte.lower() == "traces":
        return 0.0
    texte = texte.lstrip("<").strip()          # « < 0,5 » -> borne haute 0,5
    texte = texte.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return None


def energie_depuis_macros(valeurs: dict) -> float | None:
    """Reconstitue l'énergie d'un aliment à partir de ses macronutriments.

    143 aliments de la table Ciqual n'ont pas de valeur énergétique, alors que
    62 d'entre eux ont des macros complètes. Les compter pour 0 kcal fausse
    visiblement le total d'une recette (le sirop d'agave, par exemple, vaut
    une trentaine de kcal pour 10 g).

    On applique donc les coefficients de l'annexe XIV du règlement (UE)
    1169/2011 — ceux-là même avec lesquels l'ANSES calcule sa colonne énergie.
    Contrôle effectué sur les 3 108 aliments dont Ciqual donne AUSSI l'énergie :
    la formule la retrouve avec un écart médian de 0,2 % (3,1 % au 90e centile).

    Exige protéines, glucides ET lipides ; les autres termes (fibres, polyols,
    alcool, acides organiques) sont comptés pour 0 s'ils manquent, ce qui
    sous-estime légèrement. Renvoie None si les trois macros de base manquent :
    on ne devine pas, on laisse la donnée absente.
    """
    if any(valeurs.get(n) is None for n in ("proteines", "glucides", "lipides")):
        return None
    return round(sum(FACTEURS_ENERGIE[n] * (valeurs.get(n) or 0.0)
                     for n in FACTEURS_ENERGIE), 1)


def reperer_colonnes(entetes: list[str]) -> dict[str, int]:
    """Associe chaque champ à son index de colonne. Echoue fort si absent."""
    trouvees: dict[str, int] = {}
    for champ, motifs in COLONNES.items():
        for i, entete in enumerate(entetes):
            if all(m in entete for m in motifs):
                trouvees[champ] = i
                break
    manquantes = set(COLONNES) - set(trouvees)
    if manquantes:
        raise SystemExit(
            "Colonnes Ciqual introuvables : " + ", ".join(sorted(manquantes)) +
            "\nLa structure du fichier a probablement changé : ajuster COLONNES "
            "dans import_ciqual.py."
        )
    return trouvees


def lire_fichier(chemin: Path) -> list[dict]:
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    if FEUILLE not in wb.sheetnames:
        raise SystemExit(f"Feuille « {FEUILLE} » absente de {chemin.name} "
                         f"(feuilles : {wb.sheetnames})")
    ws = wb[FEUILLE]
    lignes = ws.iter_rows(values_only=True)
    entetes = [normaliser_entete(h) for h in next(lignes)]
    col = reperer_colonnes(entetes)

    aliments = []
    for ligne in lignes:
        code = ligne[col["code"]]
        nom = ligne[col["nom"]]
        if code is None or not nom:
            continue
        aliment = {
            "code": str(code).strip(),
            "nom": re.sub(r"\s+", " ", str(nom)).strip(),
            "groupe": re.sub(r"\s+", " ", str(ligne[col["groupe"]] or "")).strip() or None,
            "sous_groupe": re.sub(r"\s+", " ", str(ligne[col["sous_groupe"]] or "")).strip() or None,
        }
        aliment["nom_norm"] = normaliser_nom(aliment["nom"])
        for champ in NUTRIMENTS:
            aliment[champ] = parse_valeur(ligne[col[champ]])

        # Energie absente de Ciqual : on la reconstitue depuis les macros,
        # en marquant l'aliment pour que l'application le dise.
        aliment["kcal_estimee"] = 0
        if aliment["kcal"] is None:
            extras = {c: parse_valeur(ligne[col[c]]) for c in POUR_ENERGIE}
            estimee = energie_depuis_macros({**aliment, **extras})
            if estimee is not None:
                aliment["kcal"] = estimee
                aliment["kcal_estimee"] = 1

        aliments.append(aliment)
    wb.close()
    return aliments


def importer(chemin: Path | None = None) -> int:
    if chemin is None:
        candidats = sorted(DOSSIER_DEFAUT.glob("*Ciqual*.xlsx"))
        if not candidats:
            raise SystemExit(
                f"Aucun fichier Ciqual dans {DOSSIER_DEFAUT}.\n"
                "Télécharger « Table Ciqual 2025_FR_*.xlsx » depuis "
                "https://entrepot.recherche.data.gouv.fr (DOI 10.57745/RDMHWY)."
            )
        chemin = candidats[-1]

    aliments = lire_fichier(Path(chemin))
    db.init_db()
    conn = db.get_conn()
    maintenant = datetime.now().isoformat(timespec="seconds")

    # Un ré-import rafraîchit le référentiel Ciqual et ne touche JAMAIS aux
    # aliments perso (clause WHERE sur source).
    conn.executemany(
        """
        INSERT INTO aliment (code, nom, nom_norm, groupe, sous_groupe, kcal,
                             proteines, glucides, lipides, sucres, fibres, sel,
                             source, kcal_estimee, maj)
        VALUES (:code, :nom, :nom_norm, :groupe, :sous_groupe, :kcal,
                :proteines, :glucides, :lipides, :sucres, :fibres, :sel,
                'ciqual', :kcal_estimee, :maj)
        ON CONFLICT(code) DO UPDATE SET
            nom = excluded.nom, nom_norm = excluded.nom_norm,
            groupe = excluded.groupe, sous_groupe = excluded.sous_groupe,
            kcal = excluded.kcal, proteines = excluded.proteines,
            glucides = excluded.glucides, lipides = excluded.lipides,
            sucres = excluded.sucres, fibres = excluded.fibres,
            sel = excluded.sel, kcal_estimee = excluded.kcal_estimee,
            maj = excluded.maj
        WHERE aliment.source = 'ciqual'
        """,
        [dict(a, maj=maintenant) for a in aliments],
    )
    conn.execute(
        "INSERT INTO import_ciqual_run (fichier, importe_le, n_aliments) VALUES (?,?,?)",
        (Path(chemin).name, maintenant, len(aliments)),
    )
    conn.commit()
    conn.close()
    return len(aliments)


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    n = importer(source)
    print(f"[OK] {n} aliments importes dans {db.DB_PATH}")
