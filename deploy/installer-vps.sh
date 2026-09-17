#!/bin/bash
# Installation / mise à jour de Nutriform sur le VPS.
#
# À exécuter EN ROOT SUR LE SERVEUR, après y avoir déposé /tmp/nutriform.tgz
# (et, au tout premier déploiement seulement, /tmp/nutriform.db pour emporter
# une base déjà remplie) :
#
#     bash /tmp/installer-vps.sh
#
# Le script est idempotent : le relancer met le code à jour sans toucher à la
# base, aux comptes, au NF_SECRET ni au certificat.
set -euo pipefail

DOMAINE=nutriform.seboll.tech
RACINE=/opt/nutriform
UNITE=/etc/systemd/system/nutriform.service
ARCHIVE=/tmp/nutriform.tgz
BASE_IMPORTEE=/tmp/nutriform.db

etape() { echo; echo "=== $* ==="; }

[[ $EUID -eq 0 ]] || { echo "À lancer en root."; exit 1; }
[[ -f $ARCHIVE ]] || { echo "Archive absente : $ARCHIVE"; exit 1; }

etape "Utilisateur de service"
if id nutriform >/dev/null 2>&1; then
    echo "déjà présent"
else
    adduser --system --group --home "$RACINE" nutriform
fi

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
    # Une base existe déjà : elle fait foi. On la sauvegarde et on laisse
    # db.py appliquer d'éventuelles migrations de schéma.
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
if [[ -f $UNITE ]]; then
    echo "unité déjà installée, NF_SECRET conservé"
else
    install -m 644 "$RACINE/deploy/nutriform.service" "$UNITE"
    # Clé de signature des cookies : générée ici, jamais dans le dépôt.
    sed -i "s|A_REMPLACER_PAR_UNE_CLE_ALEATOIRE|$(openssl rand -hex 32)|" "$UNITE"
    systemctl daemon-reload
    systemctl enable nutriform
    echo "unité installée, NF_SECRET généré"
fi

# Le serveur tourne en UTC. Sans fuseau explicite, date.today() daterait de la
# veille tout ce qui est saisi entre minuit et 2 h, heure de Paris — pour un
# journal alimentaire ce n'est pas un détail. Rattrapage des unités installées
# avant l'existence de cette ligne.
if ! grep -qE '^[[:space:]]*Environment=TZ=' "$UNITE"; then
    sed -i '/^Environment=PYTHONUTF8=1/a Environment=TZ=Europe/Paris' "$UNITE"
    systemctl daemon-reload
    echo "fuseau Europe/Paris ajouté à l'unité"
fi

# Une vraie affectation, pas le commentaire qui l'interdit : sans le
# ^Environment= ce garde-fou se déclencherait sur sa propre mise en garde.
if grep -qE '^[[:space:]]*Environment=NF_PERSONNE_DEFAUT' "$UNITE"; then
    echo "ERREUR : NF_PERSONNE_DEFAUT est défini dans l'unité systemd."
    echo "Cela donnerait ce compte à n'importe quel visiteur. Retirer la ligne."
    exit 1
fi

# Toujours recharger : l unite a pu changer sur disque sans passer par les
# branches ci-dessus, et systemd garderait alors l ancienne version.
systemctl daemon-reload
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
# Les pesées et les journaux de plusieurs personnes n'existent plus qu'ici.
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
TZ=Europe/Paris date '+%F %H:%M %Z'
curl -fsS "https://$DOMAINE/sante" && echo
sudo -u nutriform env PYTHONUTF8=1 "$RACINE/.venv/bin/python" \
    "$RACINE/tools/gerer_comptes.py" lister
