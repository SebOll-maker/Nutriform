# CLAUDE.md

Guide pour Claude Code sur ce dépôt.

## Projet

**Nutriform** — application web de suivi nutritionnel, **partagée entre
proches qui ne vivent pas sous le même toit**. Chacun a son compte, son
planning, son journal, ses pesées et ses objectifs ; seules les recettes et la
base d'aliments sont communes.

Phase 1 (livrée) : mono-utilisateur en local. Phase 2 (en cours) : comptes
séparés et déploiement sur le VPS Hostinger — le multi-compte n'ayant aucun
sens sur localhost.

Le besoin central n'est pas de compter des calories (toutes les apps le font)
mais de **cuisiner ses propres recettes à une cible calorique variable** : la
même recette doit sortir en portion 400 kcal ou 600 kcal, puis alimenter un
planning hebdomadaire et une liste de courses. C'est le rôle de `nutrition.py`.

## Environnement & commandes

- **Python du projet** (toujours l'utiliser, chemin absolu) :
  `C:\Users\sebas\Dev\Application Nutriform\.venv\Scripts\python.exe`
  (Flask, waitress, openpyxl — rien d'autre).
- **Toujours `PYTHONUTF8=1`** : sans cela, crash `cp1252` sur les accents des
  noms d'aliments Ciqual.
- Le **cwd du shell se réinitialise** entre deux appels : utiliser des chemins
  absolus, ou `cd` en début de commande.

```bash
cd "C:/Users/sebas/Dev/Application Nutriform"
py=./.venv/Scripts/python.exe

PYTHONUTF8=1 $py serve.py          # waitress, http://127.0.0.1:5001
PYTHONUTF8=1 $py app.py            # Flask debug avec rechargement auto
PYTHONUTF8=1 $py import_ciqual.py  # (ré)importe la table Ciqual de data/ciqual/
PYTHONUTF8=1 $py db.py             # crée/migre la base

# Comptes (le premier est indispensable : sans lui, on ne peut pas se connecter)
PYTHONUTF8=1 $py tools/gerer_comptes.py lister
PYTHONUTF8=1 $py tools/gerer_comptes.py creer <identifiant> <prénom> --admin
PYTHONUTF8=1 $py tools/gerer_comptes.py motdepasse <identifiant>

# Développement local : le cookie de session est réservé à HTTPS, il faut
# donc l'autoriser explicitement sur http://127.0.0.1
NF_COOKIE_HTTP=1 PYTHONUTF8=1 $py serve.py

# Sans passer par l'écran de connexion (les deux : JAMAIS sur le serveur)
NF_PERSONNE_DEFAUT=1 NF_COOKIE_HTTP=1 PYTHONUTF8=1 $py serve.py

PYTHONUTF8=1 $py tests/test_nutrition.py     # calibrage calorique
PYTHONUTF8=1 $py tests/test_recettes.py      # format JSON des recettes
PYTHONUTF8=1 $py tests/test_courses.py       # agrégation liste de courses
PYTHONUTF8=1 $py tests/test_import_ciqual.py # lecture Ciqual + énergie calculée
PYTHONUTF8=1 $py tests/test_personnes.py     # comptes, mots de passe
PYTHONUTF8=1 $py tests/test_migration.py     # migration V1 -> V2 sans perte
PYTHONUTF8=1 $py tests/test_cloisonnement.py # AUCUNE donnée ne traverse
```

Les tests sont des **scripts autonomes** qui impriment `[OK]` / `[KO]` et
sortent en code 1 en cas d'échec — pas de pytest. `test_courses.py` travaille
sur une base et un dossier de recettes **temporaires** ; il ne touche jamais aux
données réelles.

⚠️ **waitress n'a pas de rechargement automatique.** Après une modification de
code, tuer le serveur et le relancer, sinon l'ancien code continue d'être servi :

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*serve.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

⚠️ **Le panneau navigateur intégré de Claude Code n'autorise pas les service
workers** (`An unknown error occurred when fetching the script`). Ce n'est pas
un bug de l'application : vérifié dans un vrai Chrome, le worker s'enregistre et
s'active normalement. Pour tester la PWA, utiliser Chrome, pas le panneau.

## Architecture

### Le cloisonnement entre comptes — la règle la plus importante

**L'identifiant de la personne vient de la session, jamais de la requête.**
Aucune route ne lit un `personne_id` dans un formulaire ou une URL pour
accéder à des données personnelles : on passe par `app.pid()`. C'est ce qui
empêche qu'une URL bricolée donne accès au journal de quelqu'un d'autre.

Corollaires à respecter en ajoutant du code :

1. Toute fonction touchant `planning`, `journal`, `poids`, `reglage` ou
   `courses_coche` prend **`personne_id` en premier argument, sans valeur par
   défaut** : un oubli lève une `TypeError` immédiate au lieu de laisser filtrer
   les données de la personne 1.
2. Les `DELETE` et `UPDATE` filtrent **aussi** sur `personne_id` : un
   identifiant deviné ne doit pas permettre d'effacer chez le voisin.
3. L'administrateur gère les comptes, il ne lit **aucune** donnée personnelle.
   Il n'existe pas de route qui le permette, et c'est volontaire.
4. `tests/test_cloisonnement.py` vérifie tout cela, y compris en trichant sur
   les identifiants d'URL. Le faire tourner après toute modification de route.

Ce qui est **partagé** : la table `aliment` (Ciqual + aliments perso), les
équivalences d'unités, et les recettes de `recettes/`. C'est le patrimoine
commun, et c'est l'intérêt même du partage.

### Deux mondes de stockage — c'est structurant

- **Recettes = fichiers JSON** dans `recettes/`, un par recette, versionnés dans
  git. Elles sont saisies une fois (extraites de photos par Claude), rarement
  modifiées, et doivent rester lisibles et corrigeables à la main. Format
  documenté dans `recettes/_exemple.json` et en tête de `recettes.py`.
- **Tout le reste = SQLite** (`data/nutriform.db`, gitignorée) : référentiel
  Ciqual, planning, journal, poids, réglages, cases de la liste de courses.

### Modules

| Fichier | Rôle |
|---|---|
| `app.py` | routes Flask uniquement — lire la requête, appeler un module, rendre un gabarit |
| `personnes.py` | comptes : création, authentification (scrypt), activation |
| `db.py` | `SCHEMA` + migration versionnée + `init_db()`, chemin via `NF_DB`, `CRENEAUX` |
| `nutrition.py` | **cœur de l'app** : macros et calibrage calorique. **Pur** : ni Flask ni base, les aliments arrivent en argument |
| `recettes.py` | lecture / validation / écriture des JSON |
| `aliments.py` | recherche dans le référentiel, aliments perso, unités → grammes |
| `planning.py` | planning prévisionnel, totaux par jour |
| `courses.py` | agrégation de la liste de courses, rayons de magasin |
| `journal.py` | repas réellement mangés (macros **figées**) et poids |
| `import_ciqual.py` | xlsx ANSES → table `aliment` |
| `tools/generer_icones.py` | régénère les icônes PNG de la PWA (encodeur PNG maison, pas de Pillow) |
| `tools/gerer_comptes.py` | comptes en ligne de commande — indispensable à l'amorçage |

### Le calibrage calorique (`nutrition.py`)

Chaque ingrédient est `variable` (suit la cible) ou `fixe` (assaisonnements :
passer de 400 à 600 kcal ne doit pas multiplier le piment par 1,5).

**Comment classer un ingrédient** — règles arrêtées avec l'utilisateur, à
appliquer telles quelles en écrivant une recette (voir aussi
`recettes/_exemple.json`) :

| Cas | Classement |
|---|---|
| Assaisonnements : sel, poivre, épices, herbes, ail, levure, sauce soja, vinaigre | `fixe` |
| Accompagnement : une salade verte reste 50 g, que le plat vise 400 ou 800 kcal | `fixe` |
| **Matière grasse** : cela dépend de l'**usage**, pas de l'aliment | — |
| … elle ne sert qu'à graisser la poêle (huile de coco des pancakes) | `fixe` |
| … elle assaisonne ou enrichit (huiles d'olive du canard : écrasé, vinaigrette) | `variable` |
| Tout le reste | `variable` |

`unite_piece` est réservé à ce qui ne se coupe pas sans gâchis : un œuf en a un,
une orange non (une demi-orange se presse très bien).

Pour une recette de `P` portions, `F` les kcal des ingrédients fixes et `V`
celles des variables, produire `N` portions de `T` kcal donne aux variables le
coefficient `k = (N·T − F·N/P) / V`, les fixes suivant `N/P`.

**Unités indivisibles.** Un ingrédient variable peut porter `unite_piece` (poids
d'une pièce : œuf, tortilla, tranche de pain). Il est arrondi à la pièce entière
la plus proche — **une au minimum**, un ingrédient de la recette ne disparaît
pas — puis les variables *divisibles* sont **réajustés** pour retomber exactement
sur la cible : `k_div = (N·T − F·N/P − I) / D`, où `I` est l'apport des pièces
après arrondi et `D` celui des divisibles. Sans ce réajustement l'arrondi ferait
dériver les calories et viderait le calibrage de son sens.

`pas_piece` (entier ≥ 1, défaut 1) arrondit par **multiples** de pièces, pour ce
qui ne s'emploie que par paire : les deux tranches d'un croque-monsieur, les deux
moitiés d'un pain à burger. Avec `pas_piece: 2` l'arrondi donne 2, 4, 6 tranches
et jamais 3, et le minimum passe de 1 à 2 pièces — ce qui relève le plancher en
conséquence. Un `pas_piece` absurde (0, négatif, non numérique) est ramené à 1
par le moteur, et refusé par la validation des recettes.

Cas dégradés **expliqués** plutôt que calculés de travers : `V = 0` (recette
100 % fixe), `k ≤ 0` (cible sous le plancher des assaisonnements et des pièces
entières), `D = 0` (aucun divisible pour compenser l'arrondi : l'écart à la
cible est annoncé), `k` hors `[1/3, 3]` (on calibre mais on avertit).

### Règles à ne pas casser

1. **Le journal fige ses macros à la saisie.** Corriger une recette ou
   ré-importer Ciqual ne doit jamais réécrire l'historique.
2. **Une donnée absente de Ciqual reste `None`**, jamais `0`. Le filtre Jinja
   `| nombre` l'affiche « — », et un ingrédient sans énergie déclenche un
   avertissement visible au lieu d'un total faussement rassurant.
   Attention, les trous sont **par nutriment** : la levure chimique (11046) a
   une valeur énergétique mais aucune teneur en sel. `calculer()` renvoie
   `nutriments_incomplets` et avertit, sinon le total serait sous-estimé en
   silence. Toute nouvelle somme de nutriments doit respecter ce principe.
   **Seule exception, et elle est calculée, pas devinée** : l'énergie. 143
   aliments n'en ont pas ; pour les 62 dont les macros sont complètes,
   `import_ciqual.energie_depuis_macros()` la reconstitue avec les
   coefficients de l'annexe XIV du règlement (UE) 1169/2011, marque
   `aliment.kcal_estimee = 1`, et l'interface l'annonce (fiche de l'aliment,
   astérisque dans les résultats de recherche, mention dans la recette via
   `calculer()["energies_calculees"]`). Sans les trois macros de base, on
   renvoie `None` : on ne devine pas.
3. **Les aliments perso (`source = 'perso'`, code `PERSO-nnnn`) survivent aux
   ré-imports** — la clause `WHERE aliment.source = 'ciqual'` de
   `import_ciqual.py` en dépend.
4. **Dans une recette, `unite` vaut `g` ou `ml`**, jamais « c. à soupe » : la
   conversion se fait à la saisie et le texte de cuisine va dans
   `quantite_affichee`. La validation le refuse explicitement. `unite_piece`
   n'est admis que sur un ingrédient `variable` (sur un `fixe`, la quantité ne
   bouge pas : l'arrondi n'aurait aucun sens).
5. **Les colonnes Ciqual sont repérées par mots-clés d'en-tête**, pas par
   numéro, pour survivre à l'édition 2026.

## Données Ciqual

Table ANSES 2025, 3 484 aliments, DOI `10.57745/RDMHWY` sur Recherche Data Gouv,
**licence Etalab 2.0** : l'attribution « Anses. 2025. Table de composition
nutritionnelle des aliments Ciqual » doit rester affichée (pied de page de
`base.html`).

Pièges du fichier, traités dans `import_ciqual.py` : séparateur décimal
**virgule**, `-` → `None` (donnée absente), `traces` → `0`, `< 0,5` → `0,5`
(borne haute retenue : mieux vaut surestimer un apport que le sous-estimer).

**Énergie manquante** : 143 aliments n'ont pas de valeur énergétique. Pour les
62 dont protéines, glucides et lipides sont tous renseignés, l'importeur la
calcule (`energie_depuis_macros`) et pose `kcal_estimee = 1`. La formule a été
contrôlée sur les 3 108 aliments dont Ciqual donne *aussi* l'énergie : écart
médian 0,2 %, 3,1 % au 90e centile. Les colonnes polyols, alcool et acides
organiques sont lues **uniquement** pour ce calcul et ne sont pas stockées.

Le xlsx vit dans `data/ciqual/` (gitignoré) ; le retélécharger au besoin :
`https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260`.

### Choix d'entrées arrêtés avec l'utilisateur

Ciqual propose souvent plusieurs entrées pour le même ingrédient de cuisine.
Ces arbitrages sont tranchés, à réutiliser sans reposer la question :

| Ingrédient | Code | Pourquoi |
|---|---|---|
| Thon en boîte au naturel | `26181` Thon **albacore**, au naturel, appertisé, égoutté | Fidélité au libellé des recettes. À noter : cette entrée porte 3,67 g de glucides/100 g, ce qui surprend pour du thon nature — l'entrée générique `26039` (0 g) collerait mieux aux valeurs de MyFitRace, mais le choix retenu est l'albacore. |
| Aiguillettes / filet de canard | `36201` Canard, viande crue | Le plus proche d'une viande de canard sans peau. Aucune des six entrées « canard cru » ne dépasse 18,7 g de protéines. |
| Compléments (whey, BCAA…) | aliment perso `PERSO-nnnn` | **Ciqual n'en référence aucun.** Saisir l'étiquette du produit via l'écran Aliments. |

Principe général : **fidélité au libellé de la recette**, et l'ANSES fait foi.
Quand un écart avec la source persiste, il s'explique — et se documente dans les
`notes` de l'ingrédient — plutôt que de se corriger en choisissant l'entrée qui
arrange.

## Interface

Jinja2 + CSS maison + JS vanilla. **Aucun framework front, aucune étape de
build.** Mobile-first : barre d'onglets basse sur téléphone, horizontale
au-delà de 720 px. Thème clair/sombre automatique via
`prefers-color-scheme`. Tout le style tient dans `static/style.css` et
s'appuie sur les variables CSS de `:root`.

PWA : `/manifest.webmanifest` et `/sw.js` sont servis **depuis la racine** par
`app.py` (le périmètre d'un service worker est limité à son dossier, un
`/static/sw.js` ne pourrait pas mettre les pages en cache).

## Authentification

`@login_required` est **obligatoire** sur toute route qui affiche ou modifie
des données : il faut savoir *qui* entre, pas seulement qu'on a le droit
d'entrer. `@admin_required` s'y ajoute pour la seule gestion des comptes.

Mots de passe hachés avec `werkzeug.security` (scrypt), déjà une dépendance de
Flask. Le condensat ne sort jamais de `personnes.py`.

`NF_PERSONNE_DEFAUT=1` court-circuite l'écran de connexion en développement
local. **À ne jamais définir sur le serveur.**

### CSRF : un jeton dans chaque formulaire

`_verifier_csrf()` est un `before_request` : **toute** requête autre que GET,
HEAD ou OPTIONS doit porter le jeton de la session, sinon 400. Il n'y a pas
d'exception, pas de liste blanche — c'est ce qui rend la règle tenable.

Conséquence pour tout nouveau formulaire : `{{ champ_csrf() }}` juste après la
balise `<form method="post">`. L'oubli se voit immédiatement (400 au premier
essai), ce qui est le bon moment pour s'en apercevoir. Pour un futur appel
`fetch()`, il faudra joindre le champ `_csrf` dans le corps.

Le cookie de session est `HttpOnly`, `SameSite=Strict` et `Secure`. Ce dernier
réglage est **actif par défaut** : `NF_COOKIE_HTTP=1` le désactive pour le
développement en clair. Le défaut protège la production ; l'oubli ne casse que
le confort local, et bruyamment.

### Migration de schéma

`PRAGMA user_version` porte la version (`db.VERSION_SCHEMA`). `_migrer_v2()`
ajoute `personne_id` aux cinq tables personnelles ; trois d'entre elles
(`poids`, `reglage`, `courses_coche`) changeaient de clé primaire et ont dû
être **reconstruites**, SQLite ne sachant pas modifier une PK par `ALTER`. La
migration est idempotente et attribue tout l'existant à `db.PERSONNE_ORIGINE`.

Le **premier compte créé** sur une base migrée reprend automatiquement cet
identifiant (`personnes.creer` s'en charge, via `donnees_orphelines()`) : sans
cela il recevrait l'id 1 par simple AUTOINCREMENT et écraserait la dernière
pesée par un `ON CONFLICT`.

## Hors périmètre actuel

- **Substitution d'aliments** (V2) : le schéma la prévoit, rien à refondre.
- **Module sportif / Garmin Connect** (V3) : pas d'API publique gratuite ; les
  voies réalistes sont la bibliothèque non officielle `garminconnect` ou
  l'export FIT/TCX.
- **Open Food Facts / code-barres** : s'ajouterait via `source` sur `aliment`.
