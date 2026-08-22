// アプリの外枠はキャッシュから即座に表示しつつ、裏で新しい版を取りに行く
// （stale-while-revalidate）。次に開いたときには更新が反映される。
// データは常に取りに行き、通信できないときだけ最後に取得した内容を見せる。
const SHELL = 'mr-shell-v36';
const DATA = 'mr-data-v1';
const FILES = ['./', './index.html', './style.css?v=36', './app.js?v=36', './manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // データ: 通信優先。取得できたらキャッシュも更新する。
  if (url.pathname.includes('/data/')) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(DATA).then(c => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req).then(r => r || Promise.reject(new Error('offline'))))
    );
    return;
  }

  // 外枠: キャッシュを返しつつ、裏で最新版を取得してキャッシュを差し替える。
  e.respondWith(
    caches.match(req).then(cached => {
      const network = fetch(req).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(SHELL).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
