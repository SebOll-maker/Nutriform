# -*- coding: utf-8 -*-
"""
Planning prévisionnel des repas.

Une entrée de planning répond à : « tel jour, à tel créneau, je mange tant de
portions de telle recette, calibrées à tant de kcal ». La consommation prévue
d'un repas vaut donc `portions x kcal_cible` — c'est exactement le `total`
que renvoie nutrition.calculer() avec ces mêmes paramètres, ce qui évite de
recalculer la même chose de deux façons différentes.

Les recettes restant dans des fichiers, une entrée ne stocke que l'identifiant
de la recette. Si un fichier est supprimé, l'entrée est signalée comme
orpheline plutôt que de faire disparaître silencieusement le repas du planning.
"""
from datetime import date, datetime, timedelta

import aliments
import db
import nutrition
import recettes


def lundi_de(jour: date) -> date:
    """Lundi de la semaine contenant `jour` (semaine française)."""
    return jour - timedelta(days=jour.weekday())


def jours_semaine(lundi: date) -> list[date]:
    return [lundi + timedelta(days=i) for i in range(7)]


def parse_date(texte: str | None, defaut: date | None = None) -> date:
    try:
        return date.fromisoformat((texte or "").strip())
    except (ValueError, AttributeError):
        return defaut or date.today()


# ------------------------------------------------------------------- écritures
def ajouter(jour: str, creneau: str, recette_id: str,
            kcal_cible: float | None = None, portions: float = 1,
            notes: str | None = None) -> int:
    conn = db.get_conn()
    curseur = conn.execute(
        """INSERT INTO planning (date, creneau, recette_id, kcal_cible,
                                 portions, notes, cree_le)
           VALUES (?,?,?,?,?,?,?)""",
        (jour, creneau, recette_id, kcal_cible, portions or 1, notes,
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    identifiant = curseur.lastrowid
    conn.close()
    return identifiant


def supprimer(entree_id: int) -> bool:
    conn = db.get_conn()
    curseur = conn.execute("DELETE FROM planning WHERE id = ?", (entree_id,))
    conn.commit()
    supprime = curseur.rowcount > 0
    conn.close()
    return supprime


def dupliquer_semaine(lundi_source: date, lundi_cible: date) -> int:
    """Recopie une semaine entière vers une autre. Renvoie le nombre d'entrées."""
    decalage = (lundi_cible - lundi_source).days
    entrees = entrees_entre(lundi_source.isoformat(),
                            (lundi_source + timedelta(days=6)).isoformat())
    for entree in entrees:
        nouvelle_date = (date.fromisoformat(entree["date"])
                         + timedelta(days=decalage)).isoformat()
        ajouter(nouvelle_date, entree["creneau"], entree["recette_id"],
                entree["kcal_cible"], entree["portions"], entree["notes"])
    return len(entrees)


# -------------------------------------------------------------------- lectures
def entrees_entre(debut: str, fin: str) -> list[dict]:
    """Entrées de planning entre deux dates INCLUSES."""
    conn = db.get_conn()
    lignes = conn.execute(
        """SELECT * FROM planning WHERE date BETWEEN ? AND ?
           ORDER BY date, creneau""", (debut, fin)).fetchall()
    conn.close()
    return [dict(l) for l in lignes]


def detailler(entrees: list[dict]) -> list[dict]:
    """Enrichit des entrées de planning avec la recette et ses macros.

    Charge chaque recette et chaque aliment UNE SEULE FOIS, même si le même
    plat revient cinq fois dans la semaine.
    """
    if not entrees:
        return []

    cache_recettes: dict[str, dict | None] = {}
    for entree in entrees:
        rid = entree["recette_id"]
        if rid not in cache_recettes:
            cache_recettes[rid] = recettes.charger(rid)

    codes = {code
             for recette in cache_recettes.values() if recette
             for code in nutrition.codes_recette(recette)}
    table = aliments.get_aliments(codes)

    detaillees = []
    for entree in entrees:
        recette = cache_recettes.get(entree["recette_id"])
        if recette is None:
            detaillees.append({**entree, "recette": None, "calcul": None,
                               "orpheline": True})
            continue
        calcul = nutrition.calculer(recette, table,
                                    kcal_cible=entree["kcal_cible"],
                                    portions=entree["portions"])
        detaillees.append({**entree, "recette": recette, "calcul": calcul,
                           "orpheline": False})
    return detaillees


def semaine(lundi: date) -> dict:
    """Tout ce qu'il faut pour afficher une semaine de planning."""
    jours = jours_semaine(lundi)
    entrees = detailler(entrees_entre(jours[0].isoformat(), jours[-1].isoformat()))

    grille: dict[str, dict[str, list]] = {
        jour.isoformat(): {creneau: [] for creneau in db.CRENEAUX}
        for jour in jours
    }
    totaux = {jour.isoformat(): {n: 0.0 for n in nutrition.NUTRIMENTS}
              for jour in jours}

    for entree in entrees:
        jour = entree["date"]
        if jour not in grille:
            continue
        creneau = entree["creneau"] if entree["creneau"] in db.CRENEAUX else db.CRENEAUX[0]
        grille[jour][creneau].append(entree)
        if entree["calcul"]:
            for n in nutrition.NUTRIMENTS:
                totaux[jour][n] += entree["calcul"]["total"][n] or 0.0

    return {"lundi": lundi, "jours": jours, "grille": grille, "totaux": totaux,
            "entrees": entrees}
