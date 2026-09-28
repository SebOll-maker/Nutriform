# Étude de cas — Nutriform

Produite avec le générateur maison `EI/Etude-de-cas/generate_case_study.py`, à
partir de `content.json` : il en sort `Etude-de-cas.md` (pour le web) et
`Etude-de-cas.pdf` (pour l'envoi).

```bash
cd "C:/Users/sebas/Dev/EI/Etude-de-cas"
PYTHONUTF8=1 ".venv/Scripts/python.exe" generate_case_study.py \
  "C:/Users/sebas/Dev/Application Nutriform/Etude-de-cas/content.json" \
  "C:/Users/sebas/Dev/Application Nutriform/Etude-de-cas"
```

## D'où viennent les images

| Fichier | Origine |
|---|---|
| `00-architecture*.png` | rendu de `deploy/architecture.svg`, découpé en deux panneaux |
| `01` à `05` | captures de l'application sur un **jeu de démonstration** |

Les captures n'utilisent **aucune donnée réelle** : compte fictif « Camille »,
et trois recettes neutres écrites pour l'occasion. Les recettes du dépôt
appartiennent à leur éditeur et n'ont pas à figurer dans une page publiable —
c'est d'ailleurs la raison pour laquelle ce dépôt est privé.

## Pour refaire les captures

Monter une base jetable (copie de la base réelle vidée de ses tables
personnelles), un dossier de recettes neutres, puis servir l'application sur un
port dédié avec `NF_PERSONNE_DEFAUT` pour éviter l'écran de connexion. Les
captures se prennent en navigateur sans interface :

```bash
msedge.exe --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1400,880 \
  --user-data-dir=<profil dédié> --screenshot=<chemin ABSOLU .png> <url>
```

Deux pièges : le chemin de sortie doit être **absolu** (un chemin relatif ne
produit rien, silencieusement), et l'écriture du fichier est **différée de
quelques secondes** — vérifier son existence en boucle plutôt qu'aussitôt.
