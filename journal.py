# -*- coding: utf-8 -*-
"""
Journal de ce qui a été réellement mangé, et suivi du poids.

Règle structurante : les macros sont FIGÉES au moment de la saisie. Corriger
une recette aujourd'hui, ou ré-importer une nouvelle édition de Ciqual, ne doit
pas réécrire l'historique de la semaine dernière. Le journal est un relevé, pas
une vue calculée.

CLOISONNEMENT : c'est ici que vivent les données les plus sensibles de
l'application — ce que quelqu'un mange et ce qu'il pèse. Aucune fonction ne
s'exécute sans `personne_id`, et l'administrateur n'a aucun passe-droit :
il gère les comptes, il ne consulte pas les journaux.
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
def ajouter_recette(personne_id: int, jour: str, creneau: str, recette_id: str,
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
        """INSERT INTO journal (personne_id, date, creneau, libelle, recette_id,
                                portions, kcal, proteines, glucides, lipides,
                                cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (personne_id, jour, creneau, recette["titre"], recette_id, portions,
         calcul["total"]["kcal"], calcul["total"]["proteines"],
         calcul["total"]["glucides"], calcul["total"]["lipides"], _maintenant()))
    conn.commit()
    identifiant = curseur.lastrowid
    conn.close()
    return identifiant


def ajouter_aliment(personne_id: int, jour: str, creneau: str,
                    aliment_code: str, grammes: float) -> int:
    """Saisit un aliment seul (hors recette) : un fruit, un yaourt…"""
    aliment = aliments.get_aliment(aliment_code)
    if not aliment:
        raise ValueError(f"Aliment « {aliment_code} » introuvable.")
    macros = nutrition.macros_pour(aliment, grammes)
    conn = db.get_conn()
    curseur = conn.execute(
        """INSERT INTO journal (personne_id, date, creneau, libelle,
                                aliment_code, grammes, kcal, proteines,
                                glucides, lipides, cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (personne_id, jour, creneau, aliment["nom"], aliment_code, grammes,
         macros["kcal"], macros["proteines"], macros["glucides"],
         macros["lipides"], _maintenant()))
    conn.commit()
    identifiant = curseur.lastrowid
    conn.close()
    return identifiant


def supprimer(personne_id: int, entree_id: int) -> bool:
    """Filtré sur personne_id : un identifiant deviné ne doit pas permettre
    d'effacer une ligne du journal de quelqu'un d'autre."""
    conn = db.get_conn()
    curseur = conn.execute(
        "DELETE FROM journal WHERE id = ? AND personne_id = ?",
        (entree_id, personne_id))
    conn.commit()
    supprime = curseur.rowcount > 0
    conn.close()
    return supprime


def copier_planning(personne_id: int, jour: str) -> int:
    """Recopie le planning du jour dans le journal (« j'ai mangé ce qui était prévu »).

    Ne recopie que ce qui n'y est pas déjà, pour qu'un double clic ne compte
    pas le repas deux fois.
    """
    import planning as mod_planning

    deja = {(l["recette_id"], l["creneau"])
            for l in du_jour(personne_id, jour)["entrees"] if l["recette_id"]}
    ajoutes = 0
    for entree in mod_planning.entrees_entre(personne_id, jour, jour):
        if (entree["recette_id"], entree["creneau"]) in deja:
            continue
        try:
            ajouter_recette(personne_id, jour, entree["creneau"],
                            entree["recette_id"], entree["portions"],
                            entree["kcal_cible"])
            ajoutes += 1
        except ValueError:
            continue          # recette supprimée entre-temps : on ignore
    return ajoutes


# -------------------------------------------------------------------- lectures
def du_jour(personne_id: int, jour: str) -> dict:
    conn = db.get_conn()
    lignes = [dict(l) for l in conn.execute(
        "SELECT * FROM journal WHERE personne_id = ? AND date = ? ORDER BY id",
        (personne_id, jour)).fetchall()]
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


def historique(personne_id: int, debut: str, fin: str) -> list[dict]:
    """Totaux journaliers entre deux dates incluses."""
    conn = db.get_conn()
    lignes = conn.execute(
        """SELECT date,
                  SUM(kcal) kcal, SUM(proteines) proteines,
                  SUM(glucides) glucides, SUM(lipides) lipides
           FROM journal WHERE personne_id = ? AND date BETWEEN ? AND ?
           GROUP BY date ORDER BY date""", (personne_id, debut, fin)).fetchall()
    conn.close()
    return [dict(l) for l in lignes]


# ----------------------------------------------------------------------- poids
def enregistrer_poids(personne_id: int, jour: str, poids_kg: float,
                      commentaire: str | None = None):
    conn = db.get_conn()
    conn.execute(
        """INSERT INTO poids (personne_id, date, poids_kg, commentaire)
           VALUES (?,?,?,?)
           ON CONFLICT(personne_id, date)
           DO UPDATE SET poids_kg = excluded.poids_kg,
                         commentaire = excluded.commentaire""",
        (personne_id, jour, float(poids_kg), commentaire))
    conn.commit()
    conn.close()


def supprimer_poids(personne_id: int, jour: str) -> bool:
    conn = db.get_conn()
    curseur = conn.execute(
        "DELETE FROM poids WHERE personne_id = ? AND date = ?",
        (personne_id, jour))
    conn.commit()
    supprime = curseur.rowcount > 0
    conn.close()
    return supprime


def poids(personne_id: int, limite: int = 120) -> list[dict]:
    """Derniers pesages, du plus ancien au plus récent (sens de lecture d'une courbe)."""
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT * FROM poids WHERE personne_id = ? ORDER BY date DESC LIMIT ?",
        (personne_id, limite)).fetchall()
    conn.close()
    return [dict(l) for l in reversed(lignes)]


def dernier_poids(personne_id: int) -> dict | None:
    conn = db.get_conn()
    ligne = conn.execute(
        "SELECT * FROM poids WHERE personne_id = ? ORDER BY date DESC LIMIT 1",
        (personne_id,)).fetchone()
    conn.close()
    return dict(ligne) if ligne else None


def tendance_poids(personne_id: int, jours: int = 30) -> dict | None:
    """Écart entre le dernier pesage et le plus ancien de la période."""
    limite = (date.today() - timedelta(days=jours)).isoformat()
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT date, poids_kg FROM poids "
        "WHERE personne_id = ? AND date >= ? ORDER BY date",
        (personne_id, limite)).fetchall()
    conn.close()
    if len(lignes) < 2:
        return None
    premier, dernier = lignes[0], lignes[-1]
    return {"debut": premier["date"], "fin": dernier["date"],
            "depart": premier["poids_kg"], "arrivee": dernier["poids_kg"],
            "ecart": dernier["poids_kg"] - premier["poids_kg"]}
