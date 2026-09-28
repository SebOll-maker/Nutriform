# Page privée de présentation

Publiée sur **https://seboll.tech/nutriform/**, protégée par mot de passe au
niveau de nginx, non liée depuis le site et marquée `noindex`.

Deux onglets, sans une ligne de JavaScript : deux boutons radio masqués pilotent
l'affichage en CSS. La page fonctionne donc même script désactivé.

## Publier ou mettre à jour

```bash
cd "C:/Users/sebas/Dev/Application Nutriform"
cp Etude-de-cas/0*.png Etude-de-cas/Etude-de-cas.pdf deploy/page-privee/
ssh root@76.13.63.150 "rm -rf /tmp/page-privee && mkdir -p /tmp/page-privee"
scp deploy/page-privee/*.png deploy/page-privee/*.html deploy/page-privee/*.pdf \
    root@76.13.63.150:/tmp/page-privee/
scp deploy/installer-page-privee.sh root@76.13.63.150:/tmp/
ssh root@76.13.63.150 "bash /tmp/installer-page-privee.sh"
```

Les images et le PDF ne sont pas versionnés ici : ils sont produits dans
`Etude-de-cas/` et copiés au moment de publier.

## Le mot de passe

L'installeur crée un mot de passe **aléatoire que personne ne connaît**, pour que
la page soit protégée dès la première seconde. Pour poser le tien — il est saisi
au clavier, jamais passé en argument ni écrit dans un fichier d'historique :

```bash
ssh -t root@76.13.63.150 'read -p "Identifiant : " u; read -s -p "Mot de passe : " m; echo; printf "%s:%s\n" "$u" "$(printf "%s" "$m" | openssl passwd -apr1 -stdin)" > /etc/nginx/.htpasswd-nutriform; chown root:www-data /etc/nginx/.htpasswd-nutriform; chmod 640 /etc/nginx/.htpasswd-nutriform; nginx -t && systemctl reload nginx && echo "mot de passe pose"'
```

## Ce que cette protection vaut

`auth_basic` est une **vraie** protection côté serveur : sans le mot de passe,
ni la page, ni les images, ni le PDF ne sont servis — vérifié. Ce n'est pas un
verrou en JavaScript que l'on contourne en lisant le code source.

Ses limites, à connaître : les identifiants transitent à chaque requête (ici
toujours en HTTPS, donc chiffrés), il n'y a ni déconnexion ni limitation du
nombre d'essais. Pour une page de présentation sans données sensibles — les
captures utilisent un compte fictif — c'est proportionné.
