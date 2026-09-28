#!/bin/bash
# Publie la page privée Nutriform sur https://seboll.tech/nutriform/
# et la protège par mot de passe au niveau de nginx.
#
# Idempotent : relançable pour mettre à jour la page sans retoucher nginx ni le
# mot de passe.
set -euo pipefail

CIBLE=/opt/pages-privees/nutriform
VHOST=/etc/nginx/sites-available/seboll.tech
HTPASSWD=/etc/nginx/.htpasswd-nutriform
SOURCE=/tmp/page-privee

[[ $EUID -eq 0 ]] || { echo "À lancer en root."; exit 1; }
[[ -d $SOURCE ]] || { echo "Source absente : $SOURCE"; exit 1; }

echo "=== Fichiers ==="
mkdir -p "$CIBLE"
cp -f "$SOURCE"/* "$CIBLE"/
chown -R root:www-data "$CIBLE"
chmod 750 "$CIBLE"; chmod 640 "$CIBLE"/*
ls -1 "$CIBLE" | sed 's/^/  /'

echo
echo "=== Mot de passe ==="
if [[ -s $HTPASSWD ]]; then
    echo "fichier existant conservé ($(wc -l < "$HTPASSWD") compte)"
else
    # Mot de passe aléatoire que PERSONNE ne connaît : la page est protégée dès
    # la première seconde. L'utilisateur pose ensuite le sien, interactivement.
    printf 'nutriform:%s\n' \
        "$(openssl rand -base64 30 | openssl passwd -apr1 -stdin)" > "$HTPASSWD"
    echo "placeholder inutilisable créé — à remplacer (voir la commande fournie)"
fi
chown root:www-data "$HTPASSWD"
chmod 640 "$HTPASSWD"

echo
echo "=== nginx ==="
if grep -q "location /nutriform/" "$VHOST"; then
    echo "bloc déjà présent"
else
    cp "$VHOST" "$VHOST.avant-page-privee-$(date +%F-%H%M)"
    python3 - "$VHOST" <<'PY'
import re, sys
chemin = sys.argv[1]
s = open(chemin, encoding="utf-8").read()

bloc = '''
    # Page privée de présentation — non liée, non indexée, sous mot de passe.
    # Servie depuis l'hôte : le conteneur du site vitrine n'est pas concerné.
    location /nutriform/ {
        alias /opt/pages-privees/nutriform/;
        index index.html;
        auth_basic           "Acces reserve";
        auth_basic_user_file /etc/nginx/.htpasswd-nutriform;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    }

'''
# Insertion dans le SEUL bloc server qui sert seboll.tech en 443, juste avant
# son "location /". Les autres blocs (www, redirection 80) ne doivent pas bouger.
blocs = re.split(r'(?=^server\s*\{)', s, flags=re.M)
for i, b in enumerate(blocs):
    if "server_name seboll.tech;" in b and "listen 443" in b:
        j = b.index("    location / {")
        blocs[i] = b[:j] + bloc.lstrip("\n") + b[j:]
        break
else:
    raise SystemExit("bloc server seboll.tech:443 introuvable")
open(chemin, "w", encoding="utf-8").write("".join(blocs))
print("  bloc location inséré")
PY
fi
nginx -t && systemctl reload nginx

echo
echo "=== Vérification ==="
# systemctl reload rend la main avant que les nouveaux workers ne servent :
# sans cette attente, la première requête tombe encore sur l'ancienne
# configuration et rapporte un 404 trompeur.
for _ in 1 2 3 4 5; do
    sleep 1
    [[ "$(curl -sS -o /dev/null -w '%{http_code}' https://seboll.tech/nutriform/)" == "401" ]] && break
done
code_sans=$(curl -sS -o /dev/null -w '%{http_code}' https://seboll.tech/nutriform/)
echo "  sans identifiants        -> HTTP $code_sans (401 attendu)"
code_racine=$(curl -sS -o /dev/null -w '%{http_code}' https://seboll.tech/)
echo "  site vitrine inchangé    -> HTTP $code_racine (200 attendu)"
[[ "$code_sans" == "401" && "$code_racine" == "200" ]] || {
    echo "  ATTENTION : résultat inattendu, vérifier le vhost."; exit 1; }
echo "  en-tête noindex          -> $(curl -sSI https://seboll.tech/nutriform/ | grep -ci x-robots-tag) ligne(s)"
