/* YT-DLP Media Desk - Service Worker
 * Estratégia:
 *  - Navegações: network-first com fallback para a app shell em cache (offline).
 *  - App shell (HTML/CSS/JS/manifest/ícones): network-first (sempre fresco) com cache de reserva.
 *  - Tudo o resto (API, SSE /events, /downloads/*): passa direto SEM cache.
 */
const VERSION = "v1";
const SHELL_CACHE = `mediadesk-shell-${VERSION}`;
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png"
];

// Rotas dinâmicas que NUNCA devem ser cacheadas.
const BYPASS_PREFIXES = ["/events", "/downloads/", "/get_", "/system_status", "/init_log", "/update_ytdlp"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) =>
      Promise.all(
        SHELL_ASSETS.map((asset) =>
          cache.add(new Request(asset, { cache: "reload" })).catch(() => null)
        )
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Passa direto (sem cache) para API/SSE/media.
  if (BYPASS_PREFIXES.some((p) => url.pathname.startsWith(p))) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put("/index.html", copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match("/index.html").then((r) => r || caches.match("/")))
    );
    return;
  }

  // App shell estático: network-first, cache de reserva.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
