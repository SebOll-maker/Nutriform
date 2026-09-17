#!/bin/bash
# Installation / mise à jour de Nutriform sur le VPS.
#
# À exécuter EN ROOT SUR LE SERVEUR, après y avoir déposé /tmp/nutriform.tgz
# (et éventuellement /tmp/nutriform.db pour emporter une base existante) :
#
#     bash /tmp/installer-vps.sh
#
# Le script est idempotent : le relancer met simplement le code à jour sans
# toucher à la base, aux comptes, ni au certificat.
set -euo pipefail

DOMAINE=nutriform.seboll.tech
RACINE=/opt/nutriform
ARCHIVE=/tmp/nutriform.tgz
BASE_IMPORTEE=/tmp/nutriform.db

etape() { echo; echo "=== $* ==="; }

[[ $EUID -eq 0 ]] || { echo "À lancer en root."; exit 1; }
[[ -f $ARCHIVE ]] || { echo "Archive absente : $ARCHIVE"; exit 1; }

etape "Utilisateur de service"
id nutriform >/dev/null 2>&1 \
    && echo "déjà présent" \
    || adduser --system --group --home "$RACINE" nutriform

etape "Code"
mkdir -p "$RACINE"
tar -xzf "$ARCHIVE" -C "$RACINE"
echo "extrait dans $RACINE"

etape "Environnement Python"
cd "$RACINE"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -r requirements.txt
.venv/bin/pip list 2>/dev/null | grep -Ei 'flask|waitress|openpyxl'

etape "Base de données"
mkdir -p "$RACINE/data" "$RACINE/data/sauvegardes"
if [[ -f $RACINE/data/nutriform.db ]]; then
    # Une base existe déjà : on ne l'écrase jamais, on la sauvegarde et on
    # laisse db.py appliquer d'éventuelles migrations de schéma.
    cp "$RACINE/data/nutriform.db" \
       "$RACINE/data/sauvegardes/avant-maj-$(date +%F-%H%M).db"
    echo "base existante conservée (sauvegarde prise)"
elif [[ -f $BASE_IMPORTEE ]]; then
    cp "$BASE_IMPORTEE" "$RACINE/data/nutriform.db"
    echo "base importée depuis $BASE_IMPORTEE"
else
    # Pas de base : on constitue le référentiel Ciqual sur place. 1,5 Mo de
    # données publiques ANSES, inutile de les faire voyager.
    mkdir -p "$RACINE/data/ciqual"
    curl -fsSL -o "$RACINE/data/ciqual/Table Ciqual 2025_FR.xlsx" \
      "https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260"
    PYTHONUTF8=1 .venv/bin/python import_ciqual.py
fi
PYTHONUTF8=1 .venv/bin/python db.py
chown -R nutriform:nutriform "$RACINE"
chmod 750 "$RACINE/data"

etape "Service systemd"
if [[ ! -f /etc/systemd/system/nutriform.service ]]; then
    install -m 644 "$RACINE/deploy/nutriform.service" \
                   /etc/systemd/system/nutriform.service
    # Clé de signature des cookies : générée ici, jamais dans le dépôt.
    sed -i "s|A_REMPLACER_PAR_UNE_CLE_ALEATOIRE|$(openssl rand -hex 32)|" \
           /etc/systemd/system/nutriform.service
    systemctl daemon-reload
    systemctl enable nutriform
    echo "unité installée, NF_SECRET généré"
else
    echo "unité déjà installée, NF_SECRET conservé"
fi
grep -q NF_PERSONNE_DEFAUT /etc/systemd/system/nutriform.service \
    && { echo "ERREUR : NF_PERSONNE_DEFAUT présent dans l'unité."; exit 1; } \
    || true
systemctl restart nutriform
sleep 2
curl -fsS http://127.0.0.1:5001/sante && echo

etape "nginx"
if [[ ! -e /etc/nginx/sites-enabled/nutriform ]]; then
    install -m 644 "$RACINE/deploy/nginx-nutriform.conf" \
                   /etc/nginx/sites-available/nutriform
    ln -s /etc/nginx/sites-available/nutriform /etc/nginx/sites-enabled/
fi
nginx -t && systemctl reload nginx

etape "Certificat"
if [[ -d /etc/letsencrypt/live/$DOMAINE ]]; then
    echo "certificat déjà en place"
else
    certbot --nginx -d "$DOMAINE" --non-interactive --agree-tos \
            --redirect -m sebastien.ollagnier@gmail.com
fi

etape "Sauvegarde quotidienne"
# Les pesées et les journaux de plusieurs personnes n'existent qu'ici.
install -m 755 /dev/stdin /etc/cron.daily/nutriform-sauvegarde <<'CRON'
#!/bin/sh
mkdir -p /root/sauvegardes
cp /opt/nutriform/data/nutriform.db \
   "/root/sauvegardes/nutriform-$(date +%F).db"
find /root/sauvegardes -name 'nutriform-*.db' -mtime +30 -delete
CRON
/etc/cron.daily/nutriform-sauvegarde && ls -1 /root/sauvegardes | tail -1

etape "Terminé"
systemctl is-active nutriform
curl -fsS "https://$DOMAINE/sante" && echo
sudo -u nutriform env PYTHONUTF8=1 "$RACINE/.venv/bin/python" \
    "$RACINE/tools/gerer_comptes.py" lister
