# Déployer Nutriform sur le VPS Hostinger

> **Rien de tout ceci n'a été exécuté.** Ces instructions sont prêtes pour le
> jour où l'application quittera le PC. Elles reprennent la procédure déjà
> éprouvée pour `demo-ncr.seboll.tech`, où nginx et certbot sont **déjà en
> place** — on ajoute juste un vhost, on ne touche pas à l'existant.

Le VPS héberge déjà `chat.seboll.tech`, `demo-ncr.seboll.tech` et Ollama.
Nutriform s'ajoute à côté, sur son propre port (**5001**, l'intranet occupe
le 5000).

## 1. Choisir le sous-domaine

Créer un enregistrement DNS `A` pour `nutriform.seboll.tech` vers l'IP du VPS
(`76.13.63.150`), et attendre sa propagation (`nslookup nutriform.seboll.tech`).

## 2. Envoyer le code

Depuis le PC — la clé SSH `~/.ssh/id_ed25519` est déjà autorisée sur le VPS :

```bash
cd "C:/Users/sebas/Dev/Application Nutriform"
tar --exclude=.venv --exclude=data/ciqual --exclude=__pycache__ \
    --exclude=.git --exclude='data/*.db' -czf /tmp/nutriform.tgz .
scp /tmp/nutriform.tgz root@76.13.63.150:/tmp/
```

Sur le VPS :

```bash
adduser --system --group --home /opt/nutriform nutriform
mkdir -p /opt/nutriform && tar -xzf /tmp/nutriform.tgz -C /opt/nutriform
cd /opt/nutriform
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Constituer la base

La table Ciqual n'est pas dans l'archive (1,5 Mo de données publiques, inutile
de les transporter). On la télécharge directement sur le serveur :

```bash
cd /opt/nutriform
mkdir -p data/ciqual
curl -L -o "data/ciqual/Table Ciqual 2025_FR.xlsx" \
  "https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260"
PYTHONUTF8=1 .venv/bin/python import_ciqual.py
chown -R nutriform:nutriform /opt/nutriform
```

> Alternative si on veut emporter aussi son planning et son journal :
> envoyer `data/nutriform.db` par `scp`. Les recettes JSON, elles, sont déjà
> dans l'archive.

## 4. Service systemd

```bash
cp /opt/nutriform/deploy/nutriform.service /etc/systemd/system/
# Renseigner NF_PASSWORD et NF_SECRET dans le fichier avant de démarrer :
python3 -c "import secrets; print(secrets.token_hex(32))"
nano /etc/systemd/system/nutriform.service
systemctl daemon-reload
systemctl enable --now nutriform
systemctl status nutriform
curl -s http://127.0.0.1:5001/sante     # doit répondre {"statut":"ok"}
```

**`NF_PASSWORD` n'est pas optionnelle sur un serveur public** : sans elle,
l'application est accessible sans mot de passe. C'est volontaire (confort en
développement local), mais c'est à vérifier avant d'ouvrir le port 80.

## 5. nginx + HTTPS

```bash
cp /opt/nutriform/deploy/nginx-nutriform.conf /etc/nginx/sites-available/nutriform
ln -s /etc/nginx/sites-available/nutriform /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d nutriform.seboll.tech      # redirection http->https + renouv. auto
```

## 6. Installer sur l'iPhone

Safari → `https://nutriform.seboll.tech` → se connecter → bouton Partager →
**Sur l'écran d'accueil**. L'application s'ouvre alors en plein écran, sans
barre d'adresse, avec son icône.

Le HTTPS est indispensable à cette étape : c'est lui qui active le service
worker et donc la lecture hors ligne des pages déjà visitées.

## Mettre à jour

```bash
# depuis le PC : renvoyer l'archive, puis sur le VPS
tar -xzf /tmp/nutriform.tgz -C /opt/nutriform
chown -R nutriform:nutriform /opt/nutriform
systemctl restart nutriform
```

Après une modification de `static/sw.js`, incrémenter `VERSION` dans ce fichier,
sinon les navigateurs garderont l'ancien cache.

## Exploitation

| Besoin | Commande |
|---|---|
| Journaux | `journalctl -u nutriform -f` |
| Redémarrer | `systemctl restart nutriform` |
| Sauvegarder | `cp /opt/nutriform/data/nutriform.db ~/sauvegardes/nutriform-$(date +%F).db` |
| Nouvelle édition Ciqual | retélécharger le xlsx puis `import_ciqual.py` (les aliments perso sont préservés) |

La sauvegarde utile tient en deux éléments : **`data/nutriform.db`** (planning,
journal, poids, aliments perso) et le dossier **`recettes/`**. Le reste se
reconstruit depuis le dépôt et les données publiques de l'ANSES.
