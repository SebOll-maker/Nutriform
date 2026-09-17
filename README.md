# Nutriform

Application web personnelle de suivi nutritionnel : recettes **calibrées sur une
cible calorique**, planning hebdomadaire, liste de courses agrégée et journal
alimentaire. Utilisable au navigateur sur le PC et installable sur l'écran
d'accueil d'un iPhone (PWA).

Python + Flask, SQLite, aucune dépendance front.

## Ce qu'elle sait faire

- **Recettes calibrées** — la même recette sort en portion de 400 ou de 600 kcal.
  Les assaisonnements (sel, épices, ail) sont marqués « fixes » et ne bougent
  pas : seuls les ingrédients principaux suivent la cible. Les quantités
  affichées sont directement cuisinables.
- **Base d'aliments officielle** — table **Ciqual 2025 de l'ANSES**, 3 484
  aliments, importée en local. Recherche tolérante au pluriel et aux
  formulations de cuisine (« lentilles vertes » trouve « Lentille verte,
  cuite »). Possibilité d'ajouter ses propres aliments.
- **Planning hebdomadaire** — 7 jours × 4 créneaux, avec la cible calorique de
  chaque repas et le total du jour face à l'objectif.
- **Liste de courses** — entre deux dates, ingrédients cumulés à partir des
  quantités *réellement calibrées*, regroupés par rayon de magasin, avec des
  cases à cocher persistées (on coche sur l'iPhone, c'est à jour sur le PC).
- **Journal** — ce qui a été réellement mangé (repas planifié en deux clics, ou
  aliment seul), suivi du poids et courbe d'évolution.

## Démarrer

```bash
cd "C:/Users/sebas/Dev/Application Nutriform"
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

# Table Ciqual (1,5 Mo, données publiques ANSES)
mkdir -p data/ciqual
curl -L -o "data/ciqual/Table Ciqual 2025_FR.xlsx" \
  "https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260"
PYTHONUTF8=1 .venv/Scripts/python.exe import_ciqual.py

PYTHONUTF8=1 .venv/Scripts/python.exe serve.py
```

L'application écoute sur <http://127.0.0.1:5001>.

Pour y accéder depuis l'iPhone sur le réseau local :
`NF_HOST=0.0.0.0` puis ouvrir `http://<ip-du-pc>:5001`. L'application est
pleinement utilisable ainsi, mais le cache hors ligne restera inactif — un
service worker exige HTTPS (ou localhost). Voir [deploy/DEPLOY.md](deploy/DEPLOY.md)
pour l'installation complète sur l'écran d'accueil.

## Ajouter une recette

Les recettes sont des fichiers JSON dans `recettes/`, un par recette. Le format
est documenté dans [`recettes/_exemple.json`](recettes/_exemple.json).

En pratique : photographier la recette, l'envoyer à Claude Code dans ce dépôt,
et le fichier JSON est produit avec les ingrédients rattachés à leur code Ciqual,
les quantités converties en grammes et les assaisonnements marqués « fixes ».

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `NF_DB` | `data/nutriform.db` | chemin de la base |
| `NF_HOST` | `127.0.0.1` | `0.0.0.0` pour exposer sur le réseau local |
| `NF_PORT` | `5001` | port d'écoute |
| `NF_PASSWORD` | *(non définie)* | si définie, active l'écran de connexion |
| `NF_SECRET` | clé de développement | signature des cookies de session |

## Tests

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_nutrition.py
PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_recettes.py
PYTHONUTF8=1 .venv/Scripts/python.exe tests/test_courses.py
```

## Sauvegarde

Deux choses seulement : `data/nutriform.db` (planning, journal, poids, aliments
perso) et le dossier `recettes/`. Le référentiel Ciqual se retélécharge.

## Crédits

Données nutritionnelles : **Anses. 2025. Table de composition nutritionnelle des
aliments Ciqual** — [ciqual.anses.fr](https://ciqual.anses.fr),
licence Etalab 2.0.
