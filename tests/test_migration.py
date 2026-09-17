# -*- coding: utf-8 -*-
"""
Migration V1 (mono-utilisateur) → V2 (comptes séparés).

    python tests/test_migration.py

Ces tests fabriquent une base au FORMAT V1, y écrivent des données, puis
lancent la migration et vérifient qu'absolument rien n'est perdu ni altéré.
C'est le filet de sécurité de la seule opération irréversible du projet : on ne
« re-saisit pas » un journal alimentaire et des pesées.

Trois tables changeaient de clé primaire (poids, reglage, courses_coche) et
devaient donc être reconstruites — c'est là que des données se perdent quand
on s'y prend mal.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

DOSSIER = Path(tempfile.mkdtemp(prefix="nf-migration-"))
os.environ["NF_DB"] = str(DOSSIER / "t.db")

import db  # noqa: E402
import personnes  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


# Schéma V1, tel qu'il était avant l'ajout des comptes. Reproduit à
# l'identique : c'est ce que contient la base de l'utilisateur.
SCHEMA_V1 = """
CREATE TABLE aliment (
    code TEXT PRIMARY KEY, nom TEXT NOT NULL, nom_norm TEXT, groupe TEXT,
    sous_groupe TEXT, kcal REAL, proteines REAL, glucides REAL, lipides REAL,
    fibres REAL, sucres REAL, sel REAL,
    source TEXT NOT NULL DEFAULT 'ciqual', maj TEXT
);
CREATE TABLE unite_equiv (
    aliment_code TEXT NOT NULL, unite TEXT NOT NULL, grammes REAL NOT NULL,
    PRIMARY KEY (aliment_code, unite)
);
CREATE TABLE import_ciqual_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fichier TEXT, importe_le TEXT,
    n_aliments INTEGER
);
CREATE TABLE planning (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
    creneau TEXT NOT NULL, recette_id TEXT NOT NULL, kcal_cible REAL,
    portions REAL NOT NULL DEFAULT 1, notes TEXT, cree_le TEXT
);
CREATE INDEX idx_planning_date ON planning(date);
CREATE TABLE journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, creneau TEXT,
    libelle TEXT NOT NULL, recette_id TEXT, aliment_code TEXT, portions REAL,
    grammes REAL, kcal REAL, proteines REAL, glucides REAL, lipides REAL,
    cree_le TEXT
);
CREATE INDEX idx_journal_date ON journal(date);
CREATE TABLE poids (
    date TEXT PRIMARY KEY, poids_kg REAL NOT NULL, commentaire TEXT
);
CREATE TABLE reglage (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE TABLE courses_coche (
    debut TEXT NOT NULL, fin TEXT NOT NULL, aliment_code TEXT NOT NULL,
    coche INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (debut, fin, aliment_code)
);
"""

PLANNING_V1 = [
    ("2026-09-14", "dejeuner", "poulet-curry-coco", 700.0, 1.0, None),
    ("2026-09-15", "diner", "dahl-legumes", 600.0, 1.0, "sans piment"),
    ("2026-09-17", "dejeuner", "pates-bolognaise", None, 2.0, None),
]
JOURNAL_V1 = [
    ("2026-09-17", "dejeuner", "Poulet au curry", "poulet-curry-coco",
     None, 1.0, None, 700.0, 43.9, 61.1, 26.0),
    ("2026-09-17", "collation", "Amandes", None, "15041", None, 15.0,
     94.7, 3.2, 1.3, 7.9),
]
POIDS_V1 = [("2026-09-04", 80.4, None), ("2026-09-11", 79.6, "après le sport"),
            ("2026-09-18", 79.1, None)]
REGLAGE_V1 = [("objectif_kcal", "2000"), ("part_petit_dej", "20"),
              ("part_dejeuner", "35"), ("objectif_proteines_g", "110")]
COCHES_V1 = [("2026-09-14", "2026-09-20", "36007", 1),
             ("2026-09-14", "2026-09-20", "9119", 0)]


def fabriquer_base_v1(chemin: Path):
    """Crée une base au format V1 remplie de données réalistes."""
    if chemin.exists():
        chemin.unlink()
    conn = sqlite3.connect(chemin)
    conn.executescript(SCHEMA_V1)
    conn.executemany(
        "INSERT INTO planning (date, creneau, recette_id, kcal_cible, portions,"
        " notes) VALUES (?,?,?,?,?,?)", PLANNING_V1)
    conn.executemany(
        "INSERT INTO journal (date, creneau, libelle, recette_id, aliment_code,"
        " portions, grammes, kcal, proteines, glucides, lipides)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)", JOURNAL_V1)
    conn.executemany("INSERT INTO poids VALUES (?,?,?)", POIDS_V1)
    conn.executemany("INSERT INTO reglage VALUES (?,?)", REGLAGE_V1)
    conn.executemany("INSERT INTO courses_coche VALUES (?,?,?,?)", COCHES_V1)
    conn.commit()
    conn.close()


chemin = Path(os.environ["NF_DB"])
fabriquer_base_v1(chemin)

print("=== la base de départ est bien au format V1 ===")
conn = sqlite3.connect(chemin)
verifier(conn.execute("PRAGMA user_version").fetchone()[0] == 0,
         "version de schéma à 0")
verifier("personne_id" not in
         {r[1] for r in conn.execute("PRAGMA table_info(planning)")},
         "planning n'a pas encore de personne_id")
verifier([r[1] for r in conn.execute("PRAGMA table_info(poids)") if r[5]] == ["date"],
         "la clé primaire de poids est la seule date")
conn.close()

print()
print("=== migration ===")
db.init_db()
conn = db.get_conn()
verifier(conn.execute("PRAGMA user_version").fetchone()[0] == db.VERSION_SCHEMA,
         f"version de schéma passée à {db.VERSION_SCHEMA}")

print()
print("=== rien n'est perdu ===")
for table, attendu in (("planning", len(PLANNING_V1)),
                       ("journal", len(JOURNAL_V1)),
                       ("poids", len(POIDS_V1)),
                       ("reglage", len(REGLAGE_V1)),
                       ("courses_coche", len(COCHES_V1))):
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    verifier(n == attendu, f"{table} : {attendu} lignes conservées", n)

print()
print("=== rien n'est altéré ===")
plan = sorted(tuple(r) for r in conn.execute(
    "SELECT date, creneau, recette_id, kcal_cible, portions, notes FROM planning"))
verifier(plan == sorted(PLANNING_V1), "le planning est identique au détail près",
         plan)

jour = sorted(tuple(r) for r in conn.execute(
    "SELECT date, creneau, libelle, recette_id, aliment_code, portions,"
    " grammes, kcal, proteines, glucides, lipides FROM journal"))
verifier(jour == sorted(JOURNAL_V1),
         "le journal est identique, macros figées incluses")

pesees = sorted(tuple(r) for r in conn.execute(
    "SELECT date, poids_kg, commentaire FROM poids"))
verifier(pesees == sorted(POIDS_V1),
         "les pesées sont identiques, commentaires inclus", pesees)

reglages = sorted(tuple(r) for r in conn.execute(
    "SELECT cle, valeur FROM reglage WHERE personne_id = ?",
    (db.PERSONNE_ORIGINE,)))
verifier(reglages == sorted(REGLAGE_V1), "les réglages sont identiques", reglages)

coches = sorted(tuple(r) for r in conn.execute(
    "SELECT debut, fin, aliment_code, coche FROM courses_coche"))
verifier(coches == sorted(COCHES_V1), "les cases cochées sont identiques")

print()
print("=== tout est attribué à la personne d'origine ===")
for table in ("planning", "journal", "poids", "reglage", "courses_coche"):
    proprietaires = {r[0] for r in
                     conn.execute(f"SELECT DISTINCT personne_id FROM {table}")}
    verifier(proprietaires in ({db.PERSONNE_ORIGINE}, set()),
             f"{table} appartient à la personne {db.PERSONNE_ORIGINE}",
             proprietaires)

print()
print("=== les clés primaires sont élargies ===")
for table, attendue in (("poids", ["personne_id", "date"]),
                        ("reglage", ["personne_id", "cle"]),
                        ("courses_coche",
                         ["personne_id", "debut", "fin", "aliment_code"])):
    obtenue = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[5]]
    verifier(obtenue == attendue, f"{table} : PK = {attendue}", obtenue)

verifier(not any(r[0].endswith("_v2") for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")),
    "aucune table de travail « _v2 » n'est restée derrière")

index = {r[0]: r[1] for r in conn.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
verifier("personne_id" in (index.get("idx_planning_date") or ""),
         "l'index du planning porte désormais sur personne_id")
verifier("personne_id" in (index.get("idx_journal_date") or ""),
         "celui du journal aussi")
conn.close()

print()
print("=== le premier compte reprend les données d'avant ===")
# Sans cette reprise, le premier compte créé recevrait l'identifiant 1 par
# simple AUTOINCREMENT : il hériterait des données migrées par accident, et
# sa première pesée écraserait celle d'avant via le ON CONFLICT. La reprise
# est donc faite dans personnes.creer() lui-même, quel que soit le chemin de
# création (ligne de commande ou interface).
import journal as mod_journal  # noqa: E402
import planning as mod_planning  # noqa: E402

verifier(personnes.compter() == 0, "aucun compte juste après la migration")
verifier(personnes.donnees_orphelines(),
         "les données d'avant sont détectées comme orphelines")
repris = personnes.creer("sebastien", "Sébastien", "mot-de-passe-repris",
                         admin=True)
verifier(repris == db.PERSONNE_ORIGINE,
         f"sans rien préciser, le compte prend l'identifiant "
         f"{db.PERSONNE_ORIGINE}", repris)
verifier(len(mod_planning.entrees_entre(repris, "2026-01-01", "2026-12-31"))
         == len(PLANNING_V1), "il retrouve son planning d'avant")
verifier(len(mod_journal.poids(repris)) == len(POIDS_V1), "et ses pesées")
verifier(mod_journal.dernier_poids(repris)["poids_kg"] == 79.1,
         "sa dernière pesée n'a pas été écrasée",
         mod_journal.dernier_poids(repris))
verifier(db.get_reglages(repris)["objectif_kcal"] == "2000", "et ses objectifs")
verifier(not personnes.donnees_orphelines(), "plus rien n'est orphelin")

print()
print("=== le compte SUIVANT est bien une autre personne ===")
autre = personnes.creer("autre", "Autre", "mot-de-passe-autre")
verifier(autre != repris, "il reçoit un identifiant distinct", (repris, autre))
verifier(len(mod_planning.entrees_entre(autre, "2026-01-01", "2026-12-31")) == 0,
         "il n'hérite d'aucun planning")
verifier(mod_journal.dernier_poids(autre) is None, "ni d'aucune pesée")
verifier(db.get_reglages(autre)["objectif_kcal"]
         == db.REGLAGES_DEFAUT["objectif_kcal"],
         "et il part des objectifs par défaut, pas de ceux du premier")

print()
print("=== deux personnes peuvent se peser le même jour ===")
# C'était impossible en V1 : la date était la clé primaire à elle seule.
mod_journal.enregistrer_poids(autre, "2026-09-18", 55.0)
verifier(mod_journal.dernier_poids(autre)["poids_kg"] == 55.0,
         "la seconde personne enregistre 55,0 kg le 18/09")
verifier(mod_journal.dernier_poids(repris)["poids_kg"] == 79.1,
         "et la pesée du premier est intacte",
         mod_journal.dernier_poids(repris))
conn = db.get_conn()
n = conn.execute(
    "SELECT COUNT(*) FROM poids WHERE date = '2026-09-18'").fetchone()[0]
conn.close()
verifier(n == 2, "deux pesées coexistent à la même date", n)

print()
print("=== la migration est rejouable sans effet ===")
avant = {}
conn = db.get_conn()
for table in ("planning", "journal", "poids", "reglage", "courses_coche"):
    avant[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
conn.close()
db.init_db()
db.init_db()
conn = db.get_conn()
apres = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in avant}
conn.close()
verifier(avant == apres, "rejouée deux fois, la base est inchangée",
         f"{avant} -> {apres}")

print()
print("=== une base neuve est directement au format V2 ===")
neuve = DOSSIER / "neuve.db"
os.environ["NF_DB"] = str(neuve)
import importlib  # noqa: E402
importlib.reload(db)
db.init_db()
conn = db.get_conn()
verifier(conn.execute("PRAGMA user_version").fetchone()[0] == db.VERSION_SCHEMA,
         "version de schéma correcte dès la création")
verifier("personne_id" in
         {r[1] for r in conn.execute("PRAGMA table_info(planning)")},
         "planning a personne_id sans avoir eu besoin de migration")
verifier(conn.execute("SELECT COUNT(*) FROM personne").fetchone()[0] == 0,
         "et aucun compte préexistant")
conn.close()

print()
shutil.rmtree(DOSSIER, ignore_errors=True)

if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("La migration préserve intégralement les données.")
