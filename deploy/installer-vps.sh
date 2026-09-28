#!/bin/bash
# Installation / mise à jour de Nutriform sur le VPS — version Docker.
#
# À exécuter EN ROOT SUR LE SERVEUR, après y avoir déposé /tmp/nutriform.tgz
# (et, au tout premier déploiement seulement, /tmp/nutriform.db pour emporter
# une base déjà remplie) :
#
#     bash /tmp/installer-vps.sh
#
# Le script est idempotent : le relancer reconstruit l'image et redémarre le
# conteneur sans toucher à la base, aux recettes, au NF_SECRET ni au certificat.
#
# Historique : jusqu'au 28/09/2026 l'application tournait sous systemd. Elle est
# désormais conteneurisée ; ce script désactive l'ancienne unité au passage,
# parce que la laisser active ferait deux processus en concurrence sur le
# port 5001.
set -euo pipefail

DOMAINE=nutriform.seboll.tech
RACINE=/opt/nutriform
UNITE=/etc/systemd/system/nutriform.service
ARCHIVE=/tmp/nutriform.tgz
BASE_IMPORTEE=/tmp/nutriform.db
UID_APP=113
GID_APP=121

etape() { echo; echo "=== $* ==="; }

[[ $EUID -eq 0 ]] || { echo "À lancer en root."; exit 1; }
[[ -f $ARCHIVE ]] || { echo "Archive absente : $ARCHIVE"; exit 1; }
command -v docker >/dev/null || { echo "Docker n'est pas installé."; exit 1; }

etape "Utilisateur de service"
if id nutriform >/dev/null 2>&1; then
    echo "déjà présent"
else
    adduser --system --group --home "$RACINE" nutriform
fi
# Le compose fige l'uid:gid pour que les volumes bind-montés gardent leur
# propriétaire et restent lisibles par la sauvegarde quotidienne. Si l'un des
# deux a changé, le conteneur écrirait sous une autre identité.
reel_uid=$(id -u nutriform)
reel_gid=$(id -g nutriform)
if [[ "$reel_uid:$reel_gid" != "$UID_APP:$GID_APP" ]]; then
    echo "ERREUR : l'utilisateur nutriform est $reel_uid:$reel_gid, le compose"
    echo "attend $UID_APP:$GID_APP. Corriger le 'user:' de docker-compose.yml"
    echo "avant de continuer, sinon les volumes changeront de propriétaire."
    exit 1
fi

etape "Ancienne unité systemd"
if [[ -f $UNITE ]] && systemctl is-active --quiet nutriform; then
    systemctl stop nutriform
    echo "arrêtée — elle occupait le port 5001"
fi
if [[ -f $UNITE ]] && systemctl is-enabled --quiet nutriform 2>/dev/null; then
    systemctl disable nutriform
    echo "désactivée"
fi
[[ -f $UNITE ]] && echo "unité conservée sur disque, mais hors service" || true

etape "Code"
mkdir -p "$RACINE"
tar -xzf "$ARCHIVE" -C "$RACINE"
echo "extrait dans $RACINE"
for f in Dockerfile docker-compose.yml; do
    [[ -f "$RACINE/$f" ]] || { echo "ERREUR : $f manquant dans l'archive."; exit 1; }
done

etape "Secret de session"
# Le compose exige NF_SECRET ; il vit dans .env, jamais dans le dépôt.
if [[ -f $RACINE/.env ]] && grep -q '^NF_SECRET=' "$RACINE/.env"; then
    echo "NF_SECRET conservé"
else
    printf '# Secret de session Nutriform. chmod 600.\nNF_SECRET=%s\n' \
        "$(openssl rand -hex 32)" > "$RACINE/.env"
    chmod 600 "$RACINE/.env"
    echo "NF_SECRET généré"
fi
# Ces deux variables n'existent que pour le confort du développement local :
# l'une court-circuite l'écran de connexion, l'autre autorise le cookie de
# session en clair. Sur un serveur exposé, chacune est une faille.
for interdite in NF_PERSONNE_DEFAUT NF_COOKIE_HTTP; do
    if grep -qE "^[[:space:]]*(-[[:space:]]*)?$interdite" "$RACINE/.env" \
                                                          "$RACINE/docker-compose.yml"; then
        echo "ERREUR : $interdite est définie côté serveur. Retirer la ligne."
        exit 1
    fi
done

etape "Données"
mkdir -p "$RACINE/data" "$RACINE/data/sauvegardes" "$RACINE/recettes"
if [[ -f $RACINE/data/nutriform.db ]]; then
    # Une base existe : elle fait foi. Sauvegarde avant toute manipulation.
    cp "$RACINE/data/nutriform.db" \
       "$RACINE/data/sauvegardes/avant-maj-$(date +%F-%H%M).db"
    echo "base existante conservée (sauvegarde prise)"
elif [[ -f $BASE_IMPORTEE ]]; then
    cp "$BASE_IMPORTEE" "$RACINE/data/nutriform.db"
    echo "base importée depuis $BASE_IMPORTEE"
else
    echo "aucune base : elle sera créée puis remplie avec Ciqual"
fi
chown -R nutriform:nutriform "$RACINE/data" "$RACINE/recettes"
chmod 750 "$RACINE/data"

etape "Image et conteneur"
cd "$RACINE"
docker compose build
docker compose up -d
docker compose ps --format '  {{.Service}} {{.Status}}'

etape "Schéma et référentiel"
# db.py est idempotent : il crée les tables manquantes et applique les
# migrations de version. serve.py l'appelle déjà au démarrage ; on le relance
# ici pour que le script échoue bruyamment si la migration pose problème.
docker compose exec -T -u "$UID_APP:$GID_APP" app python db.py
aliments=$(docker compose exec -T -u "$UID_APP:$GID_APP" app python -c \
    "import db; c = db.get_conn(); print(c.execute('SELECT COUNT(*) FROM aliment').fetchone()[0]); c.close()")
echo "aliments en base : $aliments"
if [[ "${aliments:-0}" -lt 100 ]]; then
    echo "référentiel vide : téléchargement de la table Ciqual"
    mkdir -p "$RACINE/data/ciqual"
    curl -fsSL -o "$RACINE/data/ciqual/Table Ciqual 2025_FR.xlsx" \
      "https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260"
    chown -R nutriform:nutriform "$RACINE/data"
    docker compose exec -T -u "$UID_APP:$GID_APP" app python import_ciqual.py
fi

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
# La base reste sur l'hôte malgré la conteneurisation, justement pour que ce
# script continue de fonctionner sans rien savoir de Docker.
install -m 755 /dev/stdin /etc/cron.daily/nutriform-sauvegarde <<'CRON'
#!/bin/sh
mkdir -p /root/sauvegardes
cp /opt/nutriform/data/nutriform.db \
   "/root/sauvegardes/nutriform-$(date +%F).db"
find /root/sauvegardes -name 'nutriform-*.db' -mtime +30 -delete
CRON
/etc/cron.daily/nutriform-sauvegarde && ls -1 /root/sauvegardes | tail -1

etape "Vérifications"
docker compose exec -T app date '+  heure du conteneur : %F %H:%M %Z'
curl -fsS http://127.0.0.1:5001/sante && echo
curl -fsS "https://$DOMAINE/sante" && echo
# Le cookie doit être Secure, HttpOnly et SameSite=Strict, sinon la session
# voyagerait en clair ou accompagnerait une requête venue d'un autre site.
entete=$(curl -sSI "https://$DOMAINE/connexion" | grep -i '^set-cookie' || true)
for attendu in Secure HttpOnly SameSite=Strict; do
    case "$entete" in
        *"$attendu"*) : ;;
        *) echo "ERREUR : le cookie de session n'a pas l'attribut $attendu."; exit 1 ;;
    esac
done
echo "  cookie de session : Secure + HttpOnly + SameSite=Strict"
docker compose exec -T -u "$UID_APP:$GID_APP" app python tools/gerer_comptes.py lister
