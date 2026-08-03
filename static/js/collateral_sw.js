/* Collateral offline PWA — service worker (scope: /collateral/)
 *
 * Important: when the phone leaves the PC hotspot but still has mobile data,
 * navigator.onLine is true and the LAN IP is unreachable. We must NOT
 * network-first in that case or Chrome shows "site can't be reached".
 * Strategy: cache-first for navigations / field pages; update in background.
 */
const CACHE_NAME = 'collateral-field-v9';
const OFFLINE_SHELL = '/collateral/offline/shell/';
const PRECACHE = [
  OFFLINE_SHELL,
  '/collateral/offline/setup/',
  '/collateral/',
  '/collateral/field-checklist/',
  '/static/css/styles.css',
  '/static/css/loan_workbench.css',
  '/static/css/collateral_field.css',
  '/static/css/collateral_offline.css',
  '/static/js/collateral_field.js',
  '/static/js/collateral_map.js',
  '/static/js/collateral_offline_db.js',
  '/static/js/collateral_offline.js',
  '/static/vendor/jquery/jquery-3.6.0.min.js',
  '/static/vendor/leaflet/leaflet.css',
  '/static/vendor/leaflet/leaflet.js',
  '/static/vendor/leaflet/images/marker-icon.png',
  '/static/vendor/leaflet/images/marker-icon-2x.png',
  '/static/vendor/leaflet/images/marker-shadow.png',
  '/static/manifest-collateral.webmanifest',
  '/static/img/collateral-pwa-192.png',
  '/static/img/collateral-pwa-512.png',
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
    (request.method === 'GET' && (request.headers.get('accept') || '').includes('text/html'));
}

function putInCache(request, response) {
  if (!response || !response.ok || request.method !== 'GET') return;
  const copy = response.clone();
  caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
}

function offlineFallback() {
  return caches.match(OFFLINE_SHELL).then((cached) =>
    cached ||
    caches.match('/collateral/').then((dash) =>
      dash ||
      new Response(
        '<!DOCTYPE html><html><body style="font-family:sans-serif;padding:1.5rem">' +
        '<h1>Offline</h1>' +
        '<p>Cached field pages are unavailable. Reconnect to the PC Wi‑Fi, open the field visit, tap Download for offline, then Install again.</p>' +
        '<p><a href="/collateral/offline/shell/">Offline help</a></p>' +
        '</body></html>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      )
    )
  );
}

/** Cache first; if missing, try network; if network fails, offline shell. */
function cacheFirst(request) {
  return caches.match(request).then((cached) => {
    if (cached) {
      // Soft refresh when possible (ignore failures — LAN may be gone)
      fetch(request).then((response) => putInCache(request, response)).catch(() => undefined);
      return cached;
    }
    return fetch(request)
      .then((response) => {
        putInCache(request, response);
        return response;
      })
      .catch(() => offlineFallback());
  });
}

/** Short network race then cache — used for static assets. */
function cacheOrNetwork(request) {
  return caches.match(request).then((cached) => {
    if (cached) return cached;
    return fetch(request)
      .then((response) => {
        putInCache(request, response);
        return response;
      })
      .catch(() => cached);
  });
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.indexOf('/collateral/') !== 0 && url.pathname.indexOf('/static/') !== 0) return;
  if (url.pathname.indexOf('/offline/sync') !== -1) return;
  if (url.pathname.indexOf('/offline/ping') !== -1) return;
  if (url.pathname.indexOf('/media/') === 0) return;

  if (isNavigational(event.request) || url.pathname.indexOf('/collateral/') === 0) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(cacheOrNetwork(event.request));
  }
});

self.addEventListener('message', (event) => {
  if (!event.data) return;
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data.type === 'PRECACHE_URLS' && Array.isArray(event.data.urls)) {
    event.waitUntil(
      caches.open(CACHE_NAME).then(async (cache) => {
        for (const u of event.data.urls) {
          try {
            const res = await fetch(u, { credentials: 'same-origin' });
            if (res && res.ok) {
              await cache.put(u, res.clone());
              // Also store by absolute request URL form
              await cache.put(new Request(u, { credentials: 'same-origin' }), res.clone());
            }
          } catch (e) { /* skip failed URL */ }
        }
      })
    );
  }
});
