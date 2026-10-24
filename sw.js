// sunme service worker: keeps the app shell and libraries on the phone so it opens instantly,
// caches map tiles you've already viewed (capped), and fetches everything else normally.
const SHELL = 'sunme-shell-v3', TILES = 'sunme-tiles-v1', MAX_TILES = 600;
const SHELL_FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png',
  'https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js',
  'https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css',
  'https://cdn.jsdelivr.net/npm/tz-lookup@6.1.25/tz.js', 'https://unpkg.com/pmtiles@3.2.1/dist/pmtiles.js'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== TILES).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
async function trimTiles() { const c = await caches.open(TILES), keys = await c.keys(); for (let i = 0; i < keys.length - MAX_TILES; i++) await c.delete(keys[i]); }
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  // the page itself: network first so updates arrive, cached copy when offline
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).then((r) => { const cp = r.clone(); caches.open(SHELL).then((c) => c.put('./index.html', cp)); return r; }).catch(() => caches.match('./index.html')));
    return;
  }
  // vector tiles and fonts: cache first (they change rarely), refresh in the background
  if (url.hostname === 'tiles.openfreemap.org' && /\.pbf$/.test(url.pathname)) {
    e.respondWith(caches.open(TILES).then(async (c) => {
      const hit = await c.match(e.request);
      const net = fetch(e.request).then((r) => { if (r.ok) { c.put(e.request, r.clone()); trimTiles(); } return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  // app shell, libraries and the Toronto layer: cache first
  if (url.origin === location.origin || url.hostname === 'cdn.jsdelivr.net') {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => { if (r.ok) { const cp = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, cp)); } return r; })));
  }
});
