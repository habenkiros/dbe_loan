/* Collateral offline PWA — service worker (scope: /collateral/) */
const CACHE_NAME = 'collateral-field-v1';
const PRECACHE = [
  '/collateral/',
  '/static/css/collateral_field.css',
  '/static/css/collateral_offline.css',
  '/static/js/collateral_field.js',
  '/static/js/collateral_map.js',
  '/static/js/collateral_offline_db.js',
  '/static/js/collateral_offline.js',
  '/static/manifest-collateral.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isNavigational(request) {
  return request.mode === 'navigate' ||
    (request.method === 'GET' && request.headers.get('accept') || '').includes('text/html');
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.indexOf('/collateral/') !== 0 && url.pathname.indexOf('/static/') !== 0) return;
  // Never cache sync / CSRF / media uploads
  if (url.pathname.indexOf('/offline/sync') !== -1) return;
  if (url.pathname.indexOf('/media/') === 0) return;

  if (isNavigational(event.request) || url.pathname.indexOf('/collateral/') === 0) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          if (response.ok && event.request.method === 'GET') {
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(event.request).then((cached) =>
            cached || caches.match('/collateral/') || new Response(
              '<!DOCTYPE html><html><body style="font-family:sans-serif;padding:1.5rem">' +
              '<h1>Offline</h1><p>Open a field visit while online first, then return here.</p>' +
              '<p><a href="/collateral/">Collateral dashboard</a></p></body></html>',
              { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
            )
          )
        )
    );
    return;
  }

  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(
      caches.match(event.request).then((cached) =>
        cached || fetch(event.request).then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return response;
        })
      )
    );
  }
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
