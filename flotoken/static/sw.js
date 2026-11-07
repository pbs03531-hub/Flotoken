/* Flotoken service worker.
   - Pages and data always come from the server (orders must never be stale).
   - CSS, JS, icons and menu photos are cached so the app opens instantly.
   - If the phone is offline, a friendly offline page is shown instead of a browser error. */
const VERSION = 'v1';
const SHELL = 'flotoken-shell-' + VERSION;
const ASSETS = 'flotoken-assets-' + VERSION;
const OFFLINE_URL = '/offline';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll([OFFLINE_URL, '/static/img/icon-192.png'])).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('flotoken-') && k !== SHELL && k !== ASSETS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function trim(cache, max) {
  const keys = await cache.keys();
  if (keys.length > max) await Promise.all(keys.slice(0, keys.length - max).map((k) => cache.delete(k)));
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;          // QR library etc.: let the browser handle it
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;   // live data: never cached

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (url.pathname.startsWith('/static/') || url.pathname.includes('/img/')) {
    // Addresses carry ?v=..., so a cached copy is always the right one. Fall back to the network when missing.
    event.respondWith(
      caches.open(ASSETS).then(async (cache) => {
        const hit = await cache.match(req);
        if (hit) return hit;
        const res = await fetch(req);
        if (res.ok) { cache.put(req, res.clone()); trim(cache, 250); }
        return res;
      })
    );
  }
});
