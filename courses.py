# -*- coding: utf-8 -*-
"""
Liste de courses : agrégation des ingrédients du planning entre deux dates.

Principe : on reprend les quantités RÉELLEMENT calibrées de chaque repas
planifié (pas les quantités de la recette d'origine), on les additionne par
aliment, et on regroupe par rayon de magasin pour que la liste se parcoure
dans l'ordre où l'on marche dans les allées.

Les cases cochées sont persistées en base (table courses_coche) et non dans
le navigateur : on coche sur l'iPhone dans le magasin, et la liste reste
cohérente si on la rouvre sur le PC.

CLOISONNEMENT : la liste porte sur le planning d'UNE personne. Les proches qui
partagent l'application ne vivant pas sous le même toit, il n'y a rien à
agréger entre eux — chacun fait ses courses. Les cases cochées sont elles
aussi propres à chacun.
"""
import db
import planning

# Groupes Ciqual -> rayons de magasin. Le libellé Ciqual est une
# classification nutritionnelle, pas commerciale : cette table fait la
# traduction. Tout groupe non listé tombe dans « Divers ».
RAYONS = {
    "fruits, légumes, légumineuses et oléagineux": "Fruits et légumes",
    "viandes, oeufs, poissons": "Boucherie, poissonnerie",
    "produits laitiers": "Crèmerie",
    "produits céréaliers": "Épicerie salée",
    "matières grasses": "Épicerie salée",
    "aides culinaires et ingrédients divers": "Épices et condiments",
    "produits sucrés": "Épicerie sucrée",
    "eaux et autres boissons": "Boissons",
    "entrées et plats composés": "Traiteur et surgelés",
    "glaces et sorbets": "Traiteur et surgelés",
    "aliments infantiles": "Divers",
}
ORDRE_RAYONS = ["Fruits et légumes", "Boucherie, poissonnerie", "Crèmerie",
                "Épicerie salée", "Épicerie sucrée", "Épices et condiments",
                "Boissons", "Traiteur et surgelés", "Divers"]


def rayon_de(groupe: str | None) -> str:
    return RAYONS.get((groupe or "").strip(), "Divers")


def formater_quantite(grammes: float) -> str:
    """Quantité lisible en magasin : on n'achète pas « 1 072,5 g » de poulet."""
    if grammes >= 1000:
        return f"{grammes / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " kg"
    if grammes >= 100:
        return f"{round(grammes / 10) * 10:.0f} g"
    if grammes >= 10:
        return f"{round(grammes):.0f} g"
    return f"{grammes:.1f}".replace(".", ",") + " g"


def construire(personne_id: int, debut: str, fin: str) -> dict:
    """Liste de courses d'UNE personne pour la période [debut, fin] incluse."""
    entrees = planning.detailler(
        planning.entrees_entre(personne_id, debut, fin))

    cumul: dict[str, dict] = {}
    repas_sans_recette = []
    for entree in entrees:
        if entree["orpheline"] or not entree["calcul"]:
            repas_sans_recette.append(entree)
            continue
        for ingredient in entree["calcul"]["ingredients"]:
            # Clé d'agrégation : le code Ciqual si présent, sinon le nom —
            # ainsi deux recettes qui utilisent le même code fusionnent, même
            # si elles l'appellent « Poulet » et « Blanc de poulet ».
            cle = ingredient["ciqual_code"] or f"nom:{ingredient['nom'].lower()}"
            ligne = cumul.setdefault(cle, {
                "cle": cle,
                "code": ingredient["ciqual_code"],
                "nom": ingredient["aliment_nom"] or ingredient["nom"],
                "nom_recette": ingredient["nom"],
                "grammes": 0.0,
                "recettes": set(),
                "connu": ingredient["connu"],
            })
            ligne["grammes"] += ingredient["grammes"] or 0.0
            ligne["recettes"].add(entree["recette"]["titre"])

    codes = [l["code"] for l in cumul.values() if l["code"]]
    groupes = {}
    if codes:
        conn = db.get_conn()
        marques = ",".join("?" * len(codes))
        groupes = {r["code"]: r["groupe"] for r in conn.execute(
            f"SELECT code, groupe FROM aliment WHERE code IN ({marques})", codes)}
        conn.close()

    coches = etat_coches(personne_id, debut, fin)

    rayons: dict[str, list] = {}
    for ligne in cumul.values():
        ligne["quantite"] = formater_quantite(ligne["grammes"])
        ligne["recettes"] = sorted(ligne["recettes"])
        ligne["coche"] = bool(coches.get(ligne["cle"]))
        rayon = rayon_de(groupes.get(ligne["code"]))
        rayons.setdefault(rayon, []).append(ligne)

    for lignes in rayons.values():
        lignes.sort(key=lambda l: l["nom"].lower())

    ordonnes = [(rayon, rayons[rayon]) for rayon in ORDRE_RAYONS if rayon in rayons]
    ordonnes += [(rayon, lignes) for rayon, lignes in sorted(rayons.items())
                 if rayon not in ORDRE_RAYONS]

    total_lignes = sum(len(lignes) for _, lignes in ordonnes)
    return {
        "debut": debut, "fin": fin,
        "rayons": ordonnes,
        "n_lignes": total_lignes,
        "n_repas": len([e for e in entrees if not e["orpheline"]]),
        "repas_sans_recette": repas_sans_recette,
        "restant": total_lignes - sum(1 for _, lignes in ordonnes
                                      for l in lignes if l["coche"]),
    }


# --------------------------------------------------------------- cases cochées
def etat_coches(personne_id: int, debut: str, fin: str) -> dict[str, bool]:
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT aliment_code, coche FROM courses_coche "
        "WHERE personne_id = ? AND debut = ? AND fin = ?",
        (personne_id, debut, fin)).fetchall()
    conn.close()
    return {l["aliment_code"]: bool(l["coche"]) for l in lignes}


def cocher(personne_id: int, debut: str, fin: str, cle: str, coche: bool):
    conn = db.get_conn()
    conn.execute(
        """INSERT INTO courses_coche (personne_id, debut, fin, aliment_code, coche)
           VALUES (?,?,?,?,?)
           ON CONFLICT(personne_id, debut, fin, aliment_code)
           DO UPDATE SET coche = excluded.coche""",
        (personne_id, debut, fin, cle, 1 if coche else 0))
    conn.commit()
    conn.close()


def vider_coches(personne_id: int, debut: str, fin: str):
    conn = db.get_conn()
    conn.execute("DELETE FROM courses_coche "
                 "WHERE personne_id = ? AND debut = ? AND fin = ?",
                 (personne_id, debut, fin))
    conn.commit()
    conn.close()
