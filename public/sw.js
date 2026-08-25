// アプリの外枠はキャッシュから即座に表示しつつ、裏で新しい版を取りに行く
// （stale-while-revalidate）。次に開いたときには更新が反映される。
// データは常に取りに行き、通信できないときだけ最後に取得した内容を見せる。
const SHELL = 'mr-shell-v49';
const DATA = 'mr-data-v1';
const FILES = ['./', './index.html', './style.css?v=49', './app.js?v=49', './manifest.json'];

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

  // 版の確認用。ここをキャッシュすると更新に気づけなくなるので必ず通信する。
  if (url.pathname.endsWith('/version.json')) {
    e.respondWith(fetch(req).catch(() => new Response('{}', {
      headers: { 'Content-Type': 'application/json' } })));
    return;
  }

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

  // 入口（index.html）だけは通信優先にする。
  // ここをキャッシュ優先にしていたため、更新後の1回目の起動では古い画面が出て、
  // 2回目でようやく新しくなる状態だった。iPhoneのホーム画面から使うと
  // これが分かりにくい不具合になる。通信できないときだけキャッシュを使う。
  const isEntry = req.mode === 'navigate'
    || url.pathname.endsWith('/') || url.pathname.endsWith('/index.html');
  if (isEntry) {
    e.respondWith(
      fetch(req).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(SHELL).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match(req).then(r => r || caches.match('./')))
    );
    return;
  }

  // それ以外（app.js / style.css）は ?v= が付いているので、
  // キャッシュを返しつつ裏で差し替えて構わない。
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
