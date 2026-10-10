/* Met la console en cache au premier chargement : ensuite elle s'ouvre
   intégralement hors ligne, y compris depuis l'icône de l'écran d'accueil. */
const CACHE = 'mag-v3';
const FICHIERS = ['./', './index.html', './manifest.webmanifest', './icone-180.png', './icone-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(FICHIERS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* Cache d'abord : en séance, aucune requête réseau ne doit pouvoir bloquer. */
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request, {ignoreSearch: true}).then(r => r || fetch(e.request)
      .then(rep => {
        const copie = rep.clone();
        caches.open(CACHE).then(c => c.put(e.request, copie)).catch(() => {});
        return rep;
      })
      .catch(() => caches.match('./index.html')))
  );
});
