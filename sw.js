// Throw in the Towel — service worker (network-first, offline shell)
const C = 'ttt-v2';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first for same-origin GETs (fresh when online), cache fallback when offline.
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (new URL(req.url).origin !== location.origin) return; // let cross-origin (worker, fonts, nflverse) pass through
  e.respondWith(
    fetch(req).then(res => {
      if (res && res.status === 200) {
        const clone = res.clone();
        caches.open(C).then(c => c.put(req, clone));
      }
      return res;
    }).catch(() =>
      caches.match(req).then(m => m || (req.mode === 'navigate' ? caches.match('./index.html') : undefined))
    )
  );
});
