/* Service worker de Nutriform.
 *
 * Stratégie volontairement prudente, parce qu'une application de suivi
 * alimentaire qui affiche des données périmées est pire qu'une application
 * qui affiche une erreur franche :
 *
 *   - /static/*  -> cache d'abord (CSS, icônes : ça ne change qu'aux mises à jour)
 *   - pages HTML -> réseau d'abord, cache en secours si le réseau manque
 *   - POST       -> jamais interceptés (aucune écriture ne doit être « rejouée »)
 *
 * Changer VERSION invalide tout l'ancien cache à la prochaine visite.
 */
const VERSION = 'nutriform-v1';
const SOCLE = [
  '/static/style.css',
  '/static/icons/icone-192.png',
  '/static/icons/icone-512.png',
];

self.addEventListener('install', (evenement) => {
  evenement.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(SOCLE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (evenement) => {
  evenement.waitUntil(
    caches.keys()
      .then((noms) => Promise.all(
        noms.filter((nom) => nom !== VERSION).map((nom) => caches.delete(nom))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (evenement) => {
  const requete = evenement.request;

  if (requete.method !== 'GET') return;                  // écritures : réseau seul

  const url = new URL(requete.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/static/')) {
    evenement.respondWith(
      caches.match(requete).then((enCache) => enCache || fetch(requete).then((reponse) => {
        const copie = reponse.clone();
        caches.open(VERSION).then((cache) => cache.put(requete, copie));
        return reponse;
      }))
    );
    return;
  }

  // Pages : réseau d'abord. Hors ligne, on ressort la dernière version vue.
  evenement.respondWith(
    fetch(requete)
      .then((reponse) => {
        if (reponse.ok) {
          const copie = reponse.clone();
          caches.open(VERSION).then((cache) => cache.put(requete, copie));
        }
        return reponse;
      })
      .catch(() => caches.match(requete).then((enCache) => enCache || new Response(
        `<!doctype html><html lang="fr"><head><meta charset="utf-8">
         <meta name="viewport" content="width=device-width,initial-scale=1">
         <title>Hors ligne — Nutriform</title>
         <link rel="stylesheet" href="/static/style.css"></head>
         <body><main><h1>Hors ligne</h1>
         <div class="carte"><p>Cette page n'a pas encore été consultée sur cet
         appareil, elle n'est donc pas disponible sans réseau.</p>
         <p class="muet">Les pages déjà visitées restent lisibles hors ligne.
         Les saisies, elles, exigent une connexion.</p></div></main></body></html>`,
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
      )))
  );
});
