# -*- coding: utf-8 -*-
"""
Base SQLite de Nutriform.

Deux mondes, comme dans l'intranet qualité, mais la frontière est ici
fichiers / base :

  - REFERENTIEL (table `aliment`) : importé depuis la table Ciqual de l'ANSES,
    rafraîchi par `import_ciqual.py`. Fait foi, ne se saisit pas à la main
    (sauf les aliments `source='perso'`, qui survivent aux ré-imports).
  - RECETTES : ne sont PAS en base. Un fichier JSON par recette dans
    `recettes/`, versionné dans git (voir `recettes.py`).
  - DONNEES PERSONNELLES (planning, journal, poids, reglage, courses_coche) :
    saisies, jamais écrasées par un import, et CLOISONNEES par personne_id.
    Les proches qui partagent l'application ne vivant pas sous le même toit,
    aucune donnée personnelle n'est commune : seuls les aliments et les
    recettes le sont.

Chemin de la base configurable via NF_DB (utile pour les tests et le serveur).
"""
import os
import sqlite3
from pathlib import Path

RACINE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NF_DB") or RACINE / "data" / "nutriform.db")

CRENEAUX = ("petit_dej", "dejeuner", "diner", "collation")
CRENEAU_LIBELLE = {
    "petit_dej": "Petit-déjeuner",
    "dejeuner": "Déjeuner",
    "diner": "Dîner",
    "collation": "Collation",
}


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
-- ==================== REFERENTIEL ALIMENTS ====================
-- Toutes les valeurs nutritionnelles sont exprimées POUR 100 g.
-- NULL = donnée absente de Ciqual (à distinguer de 0 : voir import_ciqual.py).
CREATE TABLE IF NOT EXISTS aliment (
    code        TEXT PRIMARY KEY,   -- code Ciqual (ex. '36018') ou 'PERSO-xxx'
    nom         TEXT NOT NULL,
    nom_norm    TEXT,               -- nom sans accents/minuscule -> recherche
    groupe      TEXT,
    sous_groupe TEXT,
    kcal        REAL,
    proteines   REAL,
    glucides    REAL,
    lipides     REAL,
    fibres      REAL,
    sucres      REAL,
    sel         REAL,
    source      TEXT NOT NULL DEFAULT 'ciqual',   -- 'ciqual' | 'perso'
    -- 1 = l'énergie ne vient pas de Ciqual, elle a été CALCULEE depuis les
    -- macronutriments (143 aliments de la table n'ont pas d'énergie).
    -- Voir import_ciqual.energie_depuis_macros().
    kcal_estimee INTEGER NOT NULL DEFAULT 0,
    maj         TEXT
);
CREATE INDEX IF NOT EXISTS idx_aliment_nom_norm ON aliment(nom_norm);
CREATE INDEX IF NOT EXISTS idx_aliment_groupe   ON aliment(groupe);

-- Equivalences unité -> grammes. aliment_code = '*' pour une équivalence
-- générique (ex. 1 c. à café rase de poudre = 5 g), sinon spécifique à
-- l'aliment (1 gousse d'ail = 5 g, 1 oeuf moyen = 50 g).
CREATE TABLE IF NOT EXISTS unite_equiv (
    aliment_code TEXT NOT NULL,
    unite        TEXT NOT NULL,
    grammes      REAL NOT NULL,
    PRIMARY KEY (aliment_code, unite)
);

CREATE TABLE IF NOT EXISTS import_ciqual_run (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier    TEXT,
    importe_le TEXT,
    n_aliments INTEGER
);

-- ==================== LES PERSONNES ====================
-- Une personne = un compte indépendant. Les proches n'habitant pas sous le
-- même toit, il n'y a AUCUNE donnée personnelle en commun : chacun a son
-- planning, son journal, ses pesées et ses objectifs. Seuls le référentiel
-- d'aliments et les recettes sont partagés.
CREATE TABLE IF NOT EXISTS personne (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    identifiant       TEXT NOT NULL UNIQUE,   -- sert à se connecter
    prenom            TEXT NOT NULL,          -- sert à l'affichage
    mot_de_passe_hash TEXT NOT NULL,          -- scrypt (werkzeug), jamais en clair
    admin             INTEGER NOT NULL DEFAULT 0,  -- gère les comptes, PAS les données
    actif             INTEGER NOT NULL DEFAULT 1,
    cree_le           TEXT
);

-- ==================== DONNEES PERSONNELLES (cloisonnées) ====================
-- Toutes les tables ci-dessous portent personne_id. Les fonctions d'accès
-- l'exigent en PREMIER argument, sans valeur par défaut : un oubli est une
-- erreur Python immédiate, pas une fuite silencieuse.

-- Planning prévisionnel : quelle recette, à quelle cible calorique.
CREATE TABLE IF NOT EXISTS planning (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    personne_id INTEGER NOT NULL,
    date        TEXT NOT NULL,             -- AAAA-MM-JJ
    creneau     TEXT NOT NULL,             -- cf. db.CRENEAUX
    recette_id  TEXT NOT NULL,             -- slug du fichier recettes/<id>.json
    kcal_cible  REAL,                      -- NULL = recette à ses proportions d'origine
    portions    REAL NOT NULL DEFAULT 1,
    notes       TEXT,
    cree_le     TEXT
);
CREATE INDEX IF NOT EXISTS idx_planning_date ON planning(personne_id, date);

-- Journal de ce qui a été REELLEMENT mangé.
-- Les macros sont FIGEES à la saisie : corriger une recette aujourd'hui ne doit
-- pas réécrire l'historique de la semaine dernière.
CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    personne_id  INTEGER NOT NULL,
    date         TEXT NOT NULL,
    creneau      TEXT,
    libelle      TEXT NOT NULL,            -- titre de recette ou nom d'aliment
    recette_id   TEXT,                     -- l'un
    aliment_code TEXT,                     -- ou l'autre
    portions     REAL,                     -- si recette
    grammes      REAL,                     -- si aliment
    kcal         REAL,
    proteines    REAL,
    glucides     REAL,
    lipides      REAL,
    cree_le      TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal(personne_id, date);

CREATE TABLE IF NOT EXISTS poids (
    personne_id INTEGER NOT NULL,
    date        TEXT NOT NULL,             -- AAAA-MM-JJ
    poids_kg    REAL NOT NULL,
    commentaire TEXT,
    PRIMARY KEY (personne_id, date)
);

CREATE TABLE IF NOT EXISTS reglage (
    personne_id INTEGER NOT NULL,
    cle         TEXT NOT NULL,
    valeur      TEXT,
    PRIMARY KEY (personne_id, cle)
);

-- Cases cochées d'une liste de courses, persistées pour survivre au
-- passage du PC à l'iPhone. Propres à chaque personne, comme son planning.
CREATE TABLE IF NOT EXISTS courses_coche (
    personne_id  INTEGER NOT NULL,
    debut        TEXT NOT NULL,
    fin          TEXT NOT NULL,
    aliment_code TEXT NOT NULL,
    coche        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (personne_id, debut, fin, aliment_code)
);
"""

# Colonnes ajoutées après coup : migration idempotente (CREATE TABLE IF NOT
# EXISTS ne modifie pas une table déjà créée). {table: {colonne: type SQL}}
MIGRATIONS: dict[str, dict[str, str]] = {
    "aliment": {"kcal_estimee": "INTEGER NOT NULL DEFAULT 0"},
}

REGLAGES_DEFAUT = {
    "objectif_kcal": "2000",
    "part_petit_dej": "25",
    "part_dejeuner": "35",
    "part_diner": "30",
    "part_collation": "10",
    "objectif_proteines_g": "110",
    "objectif_glucides_g": "200",
    "objectif_lipides_g": "70",
}


# Version du schéma, suivie par PRAGMA user_version (pas de table dédiée).
#   1 = mono-utilisateur (V1)
#   2 = comptes séparés : personne_id sur les cinq tables personnelles
VERSION_SCHEMA = 2

# La personne à qui appartiennent les données saisies avant la V2.
PERSONNE_ORIGINE = 1


def _colonnes(conn, table) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrer_v2(conn):
    """Passe une base mono-utilisateur en base multi-comptes.

    SQLite ne sait pas modifier une clé primaire par ALTER TABLE : `poids`,
    `reglage` et `courses_coche` doivent donc être reconstruites. `planning`
    et `journal`, dont la clé est un simple `id`, se contentent d'une colonne
    en plus.

    Tout ce qui existait est attribué à la personne 1 (l'utilisateur d'origine).
    La fonction ne fait rien si la base est déjà au format V2, donc la rejouer
    est sans effet.
    """
    # -- 1. colonne en plus, données conservées telles quelles
    for table in ("planning", "journal"):
        if "personne_id" not in _colonnes(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN personne_id "
                         f"INTEGER NOT NULL DEFAULT {PERSONNE_ORIGINE}")

    # -- 2. reconstruction, clé primaire à élargir
    #    (table, colonnes à recopier, définition de la nouvelle table)
    reconstructions = [
        ("poids", "date, poids_kg, commentaire", """
            CREATE TABLE poids_v2 (
                personne_id INTEGER NOT NULL,
                date        TEXT NOT NULL,
                poids_kg    REAL NOT NULL,
                commentaire TEXT,
                PRIMARY KEY (personne_id, date)
            )"""),
        ("reglage", "cle, valeur", """
            CREATE TABLE reglage_v2 (
                personne_id INTEGER NOT NULL,
                cle         TEXT NOT NULL,
                valeur      TEXT,
                PRIMARY KEY (personne_id, cle)
            )"""),
        ("courses_coche", "debut, fin, aliment_code, coche", """
            CREATE TABLE courses_coche_v2 (
                personne_id  INTEGER NOT NULL,
                debut        TEXT NOT NULL,
                fin          TEXT NOT NULL,
                aliment_code TEXT NOT NULL,
                coche        INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (personne_id, debut, fin, aliment_code)
            )"""),
    ]
    for table, colonnes, creation in reconstructions:
        if "personne_id" in _colonnes(conn, table):
            continue
        conn.execute(f"DROP TABLE IF EXISTS {table}_v2")
        conn.executescript(creation)
        conn.execute(f"INSERT INTO {table}_v2 (personne_id, {colonnes}) "
                     f"SELECT {PERSONNE_ORIGINE}, {colonnes} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_v2 RENAME TO {table}")

    # Les index portaient sur l'ancienne forme : on les recrée.
    conn.execute("DROP INDEX IF EXISTS idx_planning_date")
    conn.execute("DROP INDEX IF EXISTS idx_journal_date")
    conn.execute("CREATE INDEX idx_planning_date ON planning(personne_id, date)")
    conn.execute("CREATE INDEX idx_journal_date  ON journal(personne_id, date)")


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        existants = _colonnes(conn, table)
        for col, type_sql in cols.items():
            if col not in existants:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_sql}")

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        _migrer_v2(conn)
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")

    conn.commit()
    conn.close()


def creer_reglages_defaut(personne_id: int):
    """Dote une nouvelle personne de ses objectifs par défaut."""
    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO reglage (personne_id, cle, valeur) VALUES (?,?,?)",
        [(personne_id, cle, valeur) for cle, valeur in REGLAGES_DEFAUT.items()])
    conn.commit()
    conn.close()


def get_reglages(personne_id: int) -> dict[str, str]:
    """Objectifs d'UNE personne. Les valeurs par défaut comblent les trous, ce
    qui rend la fonction sûre même pour un compte créé avant l'ajout d'un
    nouveau réglage."""
    conn = get_conn()
    rows = conn.execute("SELECT cle, valeur FROM reglage WHERE personne_id = ?",
                        (personne_id,)).fetchall()
    conn.close()
    return {**REGLAGES_DEFAUT, **{r["cle"]: r["valeur"] for r in rows}}


def set_reglage(personne_id: int, cle: str, valeur):
    conn = get_conn()
    conn.execute(
        "INSERT INTO reglage (personne_id, cle, valeur) VALUES (?,?,?) "
        "ON CONFLICT(personne_id, cle) DO UPDATE SET valeur = excluded.valeur",
        (personne_id, cle, str(valeur)))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Base initialisee :", DB_PATH)
