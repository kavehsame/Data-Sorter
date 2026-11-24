const CACHE_PREFIX = "data-sorter:" + self.registration.scope + ":";
const CACHE = CACHE_PREFIX + "@@VERSION@@";
const ENTRY = new URL("index.html", self.registration.scope).href;
const ROOT = self.registration.scope;

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const app = await fetch(ENTRY, { cache: "reload" });
    if (!app.ok || !(app.headers.get("content-type") || "").includes("text/html")) {
      throw new Error("The offline page could not be cached.");
    }
    const bytes = await app.clone().arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (hash !== "@@DIGEST@@") throw new Error("The downloaded page and cache version differ.");
    const cache = await caches.open(CACHE);
    await cache.put(ENTRY, app);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith(CACHE_PREFIX) && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin + url.pathname !== ROOT && url.origin + url.pathname !== ENTRY) return;
  event.respondWith(caches.open(CACHE).then(async (cache) => await cache.match(ENTRY) || fetch(request)));
});
