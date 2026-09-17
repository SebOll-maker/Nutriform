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
  - MES DONNEES (planning, journal, poids, reglage, courses_coche) : saisies,
    jamais écrasées par un import.

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

-- ==================== MES DONNEES (jamais écrasées) ====================
-- Planning prévisionnel : quelle recette, à quelle cible calorique.
CREATE TABLE IF NOT EXISTS planning (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,              -- AAAA-MM-JJ
    creneau    TEXT NOT NULL,              -- cf. db.CRENEAUX
    recette_id TEXT NOT NULL,              -- slug du fichier recettes/<id>.json
    kcal_cible REAL,                       -- NULL = recette à ses proportions d'origine
    portions   REAL NOT NULL DEFAULT 1,
    notes      TEXT,
    cree_le    TEXT
);
CREATE INDEX IF NOT EXISTS idx_planning_date ON planning(date);

-- Journal de ce qui a été REELLEMENT mangé.
-- Les macros sont FIGEES à la saisie : corriger une recette aujourd'hui ne doit
-- pas réécrire l'historique de la semaine dernière.
CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal(date);

CREATE TABLE IF NOT EXISTS poids (
    date        TEXT PRIMARY KEY,          -- AAAA-MM-JJ
    poids_kg    REAL NOT NULL,
    commentaire TEXT
);

CREATE TABLE IF NOT EXISTS reglage (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);

-- Cases cochées d'une liste de courses, persistées pour être partagées
-- entre le PC et l'iPhone.
CREATE TABLE IF NOT EXISTS courses_coche (
    debut        TEXT NOT NULL,
    fin          TEXT NOT NULL,
    aliment_code TEXT NOT NULL,
    coche        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (debut, fin, aliment_code)
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


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        existants = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, type_sql in cols.items():
            if col not in existants:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_sql}")
    for cle, valeur in REGLAGES_DEFAUT.items():
        conn.execute("INSERT OR IGNORE INTO reglage (cle, valeur) VALUES (?, ?)",
                     (cle, valeur))
    conn.commit()
    conn.close()


def get_reglages() -> dict[str, str]:
    conn = get_conn()
    rows = conn.execute("SELECT cle, valeur FROM reglage").fetchall()
    conn.close()
    return {r["cle"]: r["valeur"] for r in rows}


def set_reglage(cle: str, valeur):
    conn = get_conn()
    conn.execute("INSERT INTO reglage (cle, valeur) VALUES (?, ?) "
                 "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                 (cle, str(valeur)))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Base initialisee :", DB_PATH)
