# -*- coding: utf-8 -*-
"""
Journal de ce qui a été réellement mangé, et suivi du poids.

Règle structurante : les macros sont FIGÉES au moment de la saisie. Corriger
une recette aujourd'hui, ou ré-importer une nouvelle édition de Ciqual, ne doit
pas réécrire l'historique de la semaine dernière. Le journal est un relevé, pas
une vue calculée.
"""
from datetime import date, datetime, timedelta

import aliments
import db
import nutrition
import recettes

MACROS = ("kcal", "proteines", "glucides", "lipides")


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------- écritures
def ajouter_recette(jour: str, creneau: str, recette_id: str,
                    portions: float = 1, kcal_cible: float | None = None) -> int:
    """Saisit un repas issu d'une recette. Les macros sont calculées maintenant."""
    recette = recettes.charger(recette_id)
    if not recette:
        raise ValueError(f"Recette « {recette_id} » introuvable.")
    table = aliments.get_aliments(nutrition.codes_recette(recette))
    calcul = nutrition.calculer(recette, table, kcal_cible=kcal_cible,
                                portions=portions)
    conn = db.get_conn()
    curseur = conn.execute(
        """INSERT INTO journal (date, creneau, libelle, recette_id, portions,
                                kcal, proteines, glucides, lipides, cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (jour, creneau, recette["titre"], recette_id, portions,
         calcul["total"]["kcal"], calcul["total"]["proteines"],
         calcul["total"]["glucides"], calcul["total"]["lipides"], _maintenant()))
    conn.commit()
    identifiant = curseur.lastrowid
    conn.close()
    return identifiant


def ajouter_aliment(jour: str, creneau: str, aliment_code: str,
                    grammes: float) -> int:
    """Saisit un aliment seul (hors recette) : un fruit, un yaourt…"""
    aliment = aliments.get_aliment(aliment_code)
    if not aliment:
        raise ValueError(f"Aliment « {aliment_code} » introuvable.")
    macros = nutrition.macros_pour(aliment, grammes)
    conn = db.get_conn()
    curseur = conn.execute(
        """INSERT INTO journal (date, creneau, libelle, aliment_code, grammes,
                                kcal, proteines, glucides, lipides, cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (jour, creneau, aliment["nom"], aliment_code, grammes,
         macros["kcal"], macros["proteines"], macros["glucides"],
         macros["lipides"], _maintenant()))
    conn.commit()
    identifiant = curseur.lastrowid
    conn.close()
    return identifiant


def supprimer(entree_id: int) -> bool:
    conn = db.get_conn()
    curseur = conn.execute("DELETE FROM journal WHERE id = ?", (entree_id,))
    conn.commit()
    supprime = curseur.rowcount > 0
    conn.close()
    return supprime


def copier_planning(jour: str) -> int:
    """Recopie le planning du jour dans le journal (« j'ai mangé ce qui était prévu »).

    Ne recopie que ce qui n'y est pas déjà, pour qu'un double clic ne compte
    pas le repas deux fois.
    """
    import planning as mod_planning

    deja = {(l["recette_id"], l["creneau"]) for l in du_jour(jour)["entrees"]
            if l["recette_id"]}
    ajoutes = 0
    for entree in mod_planning.entrees_entre(jour, jour):
        if (entree["recette_id"], entree["creneau"]) in deja:
            continue
        try:
            ajouter_recette(jour, entree["creneau"], entree["recette_id"],
                            entree["portions"], entree["kcal_cible"])
            ajoutes += 1
        except ValueError:
            continue          # recette supprimée entre-temps : on ignore
    return ajoutes


# -------------------------------------------------------------------- lectures
def du_jour(jour: str) -> dict:
    conn = db.get_conn()
    lignes = [dict(l) for l in conn.execute(
        "SELECT * FROM journal WHERE date = ? ORDER BY id", (jour,)).fetchall()]
    conn.close()

    totaux = {m: 0.0 for m in MACROS}
    par_creneau = {creneau: {m: 0.0 for m in MACROS} for creneau in db.CRENEAUX}
    for ligne in lignes:
        for m in MACROS:
            valeur = ligne[m] or 0.0
            totaux[m] += valeur
            if ligne["creneau"] in par_creneau:
                par_creneau[ligne["creneau"]][m] += valeur
    return {"date": jour, "entrees": lignes, "totaux": totaux,
            "par_creneau": par_creneau}


def historique(debut: str, fin: str) -> list[dict]:
    """Totaux journaliers entre deux dates incluses."""
    conn = db.get_conn()
    lignes = conn.execute(
        """SELECT date,
                  SUM(kcal) kcal, SUM(proteines) proteines,
                  SUM(glucides) glucides, SUM(lipides) lipides
           FROM journal WHERE date BETWEEN ? AND ?
           GROUP BY date ORDER BY date""", (debut, fin)).fetchall()
    conn.close()
    return [dict(l) for l in lignes]


# ----------------------------------------------------------------------- poids
def enregistrer_poids(jour: str, poids_kg: float, commentaire: str | None = None):
    conn = db.get_conn()
    conn.execute(
        """INSERT INTO poids (date, poids_kg, commentaire) VALUES (?,?,?)
           ON CONFLICT(date) DO UPDATE SET poids_kg = excluded.poids_kg,
                                           commentaire = excluded.commentaire""",
        (jour, float(poids_kg), commentaire))
    conn.commit()
    conn.close()


def supprimer_poids(jour: str) -> bool:
    conn = db.get_conn()
    curseur = conn.execute("DELETE FROM poids WHERE date = ?", (jour,))
    conn.commit()
    supprime = curseur.rowcount > 0
    conn.close()
    return supprime


def poids(limite: int = 120) -> list[dict]:
    """Derniers pesages, du plus ancien au plus récent (sens de lecture d'une courbe)."""
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT * FROM poids ORDER BY date DESC LIMIT ?", (limite,)).fetchall()
    conn.close()
    return [dict(l) for l in reversed(lignes)]


def dernier_poids() -> dict | None:
    conn = db.get_conn()
    ligne = conn.execute(
        "SELECT * FROM poids ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    return dict(ligne) if ligne else None


def tendance_poids(jours: int = 30) -> dict | None:
    """Écart entre le dernier pesage et le plus ancien de la période."""
    limite = (date.today() - timedelta(days=jours)).isoformat()
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT date, poids_kg FROM poids WHERE date >= ? ORDER BY date",
        (limite,)).fetchall()
    conn.close()
    if len(lignes) < 2:
        return None
    premier, dernier = lignes[0], lignes[-1]
    return {"debut": premier["date"], "fin": dernier["date"],
            "depart": premier["poids_kg"], "arrivee": dernier["poids_kg"],
            "ecart": dernier["poids_kg"] - premier["poids_kg"]}
