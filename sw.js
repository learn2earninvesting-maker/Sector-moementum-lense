// Sector Momentum Lens service worker: works offline, always tries the network first
// so a newly published week shows up as soon as it is online.
const CACHE = 'sml-v11';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png',
  'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const cdn = /cdnjs\.cloudflare\.com|fonts\.(googleapis|gstatic)\.com/.test(url.host);
  if (cdn) { // libraries and fonts never change: cache first
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => { const c = res.clone(); caches.open(CACHE).then(k => k.put(req, c)); return res; })));
    return;
  }
  if (url.origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const c = res.clone(); caches.open(CACHE).then(k => k.put(req, c)); }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: true}).then(hit => hit || (req.mode === 'navigate' ? caches.match('index.html') : Response.error()))));
});
