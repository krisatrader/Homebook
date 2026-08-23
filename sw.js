const CACHE_NAME = 'homebook-cache-v11';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './manifest.json',
  './icon.svg',
  './sw.js'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Network-First: online állapotban azonnal lekéri a friss GitHub Pages verziót, offline esetén cache-ből
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // Cloud Run, Render API és külső TTS hívások közvetlen átengedése (ne cache-elje a SW)
  const url = event.request.url;
  if (url.includes('run.app') ||
      url.includes('onrender.com') ||
      url.includes('speech.microsoft.com') ||
      url.includes('translate.google.com') ||
      url.includes('api.mymemory')) {
    return;
  }

  // Navigációs és statikus fájl kérések Network-First logikával
  event.respondWith(
    fetch(event.request, { cache: 'no-cache' })
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && url.startsWith(self.location.origin)) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
