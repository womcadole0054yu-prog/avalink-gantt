/* 制作ガント PWA サービスワーカー
   ネットワーク優先（常に最新を取りに行き、オフライン時だけキャッシュで開く）。
   キャッシュ固定による「古いアプリが出続ける」事故を避ける方針。 */
const CACHE = "gantt-shell-v1";

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // Firebase等の外部通信には触らない

  e.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match("./") : undefined))
      )
  );
});
