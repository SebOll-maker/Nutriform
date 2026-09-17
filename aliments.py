# -*- coding: utf-8 -*-
"""
Accès au référentiel d'aliments : recherche, aliments perso, conversion
d'unités vers les grammes.

La recherche mérite un mot d'explication. Un simple LIKE '%terme%' est
inutilisable sur Ciqual : « oeuf » remonte « bOEUF », « sel » remonte
« faisSELle », et « blanc de poulet » ne remonte rien car Ciqual nomme
l'aliment « Poulet, blanc, sans peau, cru ». D'où :
  - découpage de la requête en MOTS, tous obligatoires (ET), dans n'importe
    quel ordre — « blanc poulet » trouve « Poulet, blanc, ... » ;
  - score privilégiant les mots trouvés en DEBUT DE MOT, ce qui élimine
    les boeuf/faisselle ;
  - à score égal, le nom le plus court gagne : les aliments génériques
    (« Poulet, blanc, cru ») passent devant les préparations élaborées.
"""
import re
import unicodedata
from datetime import datetime

import db

# Equivalences d'unités par défaut, appliquées quand l'aliment n'a pas la
# sienne (table unite_equiv, aliment_code = '*'). Valeurs usuelles pour une
# cuillère « rase » de produit courant ; l'utilisateur peut affiner par aliment.
# NB : pour les RECETTES, la source de vérité reste les grammes stockés dans
# le JSON — ces équivalences servent la saisie manuelle au journal.
UNITES_GENERIQUES = {
    "g": 1.0,
    "ml": 1.0,            # approximation eau ; à affiner par aliment si besoin
    "cl": 10.0,
    "l": 1000.0,
    "kg": 1000.0,
    "c. à café": 5.0,
    "c. à soupe": 15.0,
    "pincée": 1.0,
    "unité": 100.0,       # garde-fou : à préciser par aliment
}


def normaliser(texte: str) -> str:
    """Minuscule, sans accent, espaces compactés."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sans_accent).strip().lower()


def init_unites():
    """Sème les équivalences génériques (idempotent)."""
    conn = db.get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO unite_equiv (aliment_code, unite, grammes) "
        "VALUES ('*', ?, ?)",
        list(UNITES_GENERIQUES.items()),
    )
    conn.commit()
    conn.close()


# Mots qui n'apportent rien à la recherche (« blanc DE poulet »).
MOTS_VIDES = {"de", "du", "des", "d", "la", "le", "les", "l", "au", "aux",
              "un", "une", "et", "en", "a"}


def _racine(mot: str) -> str:
    """Racine grossière pour absorber le singulier/pluriel.

    Ciqual écrit « Lentille verte, cuite » quand on tape « lentilles vertes ».
    On coupe le -s / -x final (au-delà de 3 lettres) et on cherche la racine
    comme préfixe : « lentille » retrouve « lentilles » ET « lentille ».
    """
    if len(mot) > 3 and mot[-1] in "sx":
        return mot[:-1]
    return mot


def _score(nom_norm: str, requete_norm: str, mots: list[str]) -> float:
    score = 0.0
    if nom_norm == requete_norm:
        score += 200
    if nom_norm.startswith(requete_norm):
        score += 80
    for mot in mots:
        if re.search(r"(?<![a-z0-9])" + re.escape(mot), nom_norm):
            score += 10          # trouvé en début de mot -> pertinent
        elif mot in nom_norm:
            score += 1           # sous-chaîne au milieu d'un mot -> douteux
    return score - len(nom_norm) * 0.02   # à égalité, le nom le plus court gagne


def rechercher(terme: str, limite: int = 40, groupe: str | None = None) -> list[dict]:
    """Recherche d'aliments, du plus pertinent au moins pertinent.

    Deux passes, dans cet ordre :

    1. **Tous les mots exigés** (ET). C'est le cas le plus précis, celui qui
       répond à « blanc de poulet » ou « lentilles vertes ».
    2. **Au moins un mot** (OU), classé par nombre de mots retrouvés. C'est le
       repli quand le vocabulaire de cuisine ne colle pas à celui de l'ANSES :
       « boisson à base d'avoine » ne peut pas réussir en ET, puisque Ciqual
       écrit « Boisson à l'avoine, nature, sans sucres ajoutés ». Le mot
       parasite (« base ») est ici au MILIEU de la requête, d'où le classement
       par nombre de correspondances plutôt qu'une troncature des derniers mots,
       qui retombait sur « Boisson à base de plantes pour bébé ».
    """
    requete = normaliser(terme)
    tous = [m for m in re.split(r"[^a-z0-9]+", requete) if m]
    mots = [_racine(m) for m in tous if m not in MOTS_VIDES] or [_racine(m) for m in tous]
    conn = db.get_conn()

    if not mots:
        sql = "SELECT * FROM aliment"
        params: list = []
        if groupe:
            sql += " WHERE groupe = ?"
            params.append(groupe)
        sql += " ORDER BY nom LIMIT ?"
        params.append(limite)
        lignes = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(l) for l in lignes]

    def interroger(liaison: str):
        sql = ("SELECT * FROM aliment WHERE ("
               + f" {liaison} ".join(["nom_norm LIKE ?"] * len(mots)) + ")")
        params = [f"%{m}%" for m in mots]
        if groupe:
            sql += " AND groupe = ?"
            params.append(groupe)
        return conn.execute(sql, params).fetchall()

    lignes = interroger("AND") or interroger("OR")
    conn.close()

    resultats = sorted(
        (dict(l) for l in lignes),
        key=lambda a: _score(a["nom_norm"] or "", requete, mots),
        reverse=True,
    )
    return resultats[:limite]


def get_aliment(code: str) -> dict | None:
    conn = db.get_conn()
    ligne = conn.execute("SELECT * FROM aliment WHERE code = ?", (str(code),)).fetchone()
    conn.close()
    return dict(ligne) if ligne else None


def get_aliments(codes) -> dict[str, dict]:
    """Charge plusieurs aliments d'un coup (évite les requêtes en boucle)."""
    codes = [str(c) for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}
    conn = db.get_conn()
    marques = ",".join("?" * len(codes))
    lignes = conn.execute(
        f"SELECT * FROM aliment WHERE code IN ({marques})", codes).fetchall()
    conn.close()
    return {l["code"]: dict(l) for l in lignes}


def groupes() -> list[str]:
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT DISTINCT groupe FROM aliment WHERE groupe IS NOT NULL ORDER BY groupe"
    ).fetchall()
    conn.close()
    return [l["groupe"] for l in lignes]


def creer_aliment_perso(nom: str, kcal: float, proteines: float, glucides: float,
                        lipides: float, groupe: str | None = None, **autres) -> str:
    """Crée un aliment maison. Code 'PERSO-n' : jamais écrasé par un ré-import."""
    conn = db.get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM aliment WHERE source = 'perso'").fetchone()[0]
    code = f"PERSO-{n + 1:04d}"
    while conn.execute("SELECT 1 FROM aliment WHERE code = ?", (code,)).fetchone():
        n += 1
        code = f"PERSO-{n + 1:04d}"
    conn.execute(
        """INSERT INTO aliment (code, nom, nom_norm, groupe, sous_groupe, kcal,
                                proteines, glucides, lipides, sucres, fibres, sel,
                                source, maj)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'perso',?)""",
        (code, nom.strip(), normaliser(nom), groupe or "mes aliments", None,
         kcal, proteines, glucides, lipides,
         autres.get("sucres"), autres.get("fibres"), autres.get("sel"),
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return code


def modifier_aliment_perso(code: str, **champs) -> bool:
    """Corrige un aliment perso. Refuse de toucher au référentiel Ciqual.

    Sert au cas courant : on crée l'aliment avec des valeurs provisoires
    faute d'avoir l'emballage sous la main, puis on saisit l'étiquette.
    """
    modifiables = {"nom", "kcal", "proteines", "glucides", "lipides",
                   "fibres", "sucres", "sel", "groupe"}
    valeurs = {c: v for c, v in champs.items() if c in modifiables and v is not None}
    if not valeurs:
        return False

    conn = db.get_conn()
    ligne = conn.execute("SELECT source FROM aliment WHERE code = ?",
                         (str(code),)).fetchone()
    if not ligne or ligne["source"] != "perso":
        conn.close()
        raise ValueError(
            "Seuls les aliments perso sont modifiables : les valeurs Ciqual "
            "font foi et seraient de toute façon écrasées au prochain import.")

    if "nom" in valeurs:
        valeurs["nom"] = str(valeurs["nom"]).strip()
        valeurs["nom_norm"] = normaliser(valeurs["nom"])
    valeurs["maj"] = datetime.now().isoformat(timespec="seconds")

    affectations = ", ".join(f"{c} = :{c}" for c in valeurs)
    conn.execute(f"UPDATE aliment SET {affectations} WHERE code = :code",
                 {**valeurs, "code": str(code)})
    conn.commit()
    conn.close()
    return True


def unites_de(aliment_code: str) -> dict[str, float]:
    """Unités utilisables pour cet aliment : génériques + surcharges propres."""
    conn = db.get_conn()
    lignes = conn.execute(
        "SELECT aliment_code, unite, grammes FROM unite_equiv "
        "WHERE aliment_code IN ('*', ?)", (str(aliment_code),)).fetchall()
    conn.close()
    resultat = dict(UNITES_GENERIQUES)
    for l in lignes:                      # le spécifique écrase le générique
        if l["aliment_code"] == "*":
            resultat.setdefault(l["unite"], l["grammes"])
        else:
            resultat[l["unite"]] = l["grammes"]
    return resultat


def en_grammes(quantite: float, unite: str, aliment_code: str | None = None) -> float:
    """Convertit une quantité vers les grammes. Lève ValueError si unité inconnue."""
    unite = (unite or "g").strip().lower()
    table = unites_de(aliment_code) if aliment_code else dict(UNITES_GENERIQUES)
    table = {k.lower(): v for k, v in table.items()}
    if unite not in table:
        raise ValueError(f"Unité inconnue : « {unite} »")
    return float(quantite) * table[unite]


def definir_unite(aliment_code: str, unite: str, grammes: float):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO unite_equiv (aliment_code, unite, grammes) VALUES (?,?,?) "
        "ON CONFLICT(aliment_code, unite) DO UPDATE SET grammes = excluded.grammes",
        (str(aliment_code), unite.strip().lower(), float(grammes)))
    conn.commit()
    conn.close()
