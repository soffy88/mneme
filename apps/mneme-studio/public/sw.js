// 善学记 app shell 缓存（student-first：弱网/地铁里也能打开页面）。
//
// 策略：
//   - 导航请求（HTML）：network-first，失败回落缓存 → 学生永远看到"能用的页面"而非白屏
//   - /studio/_next/static/*：cache-first（文件名带 hash，内容不可变）
//   - 图标 / manifest：cache-first
//   - **绝不缓存** /v1、/v2、/mcp（题目/掌握度/复习调度等服务端数据，缓存等于给学生看旧答案）
//     也不缓存 /v1/questions/records/*/image 这类带 token 的私有图片。
//
// 版本号改了要同步 SW_VERSION（见 components/pwa/RegisterSW.tsx 的轮询提示）：
// 旧 cache 在 activate 时整份删除，绝不留半新半旧的壳。

const CACHE = "mneme-studio-shell-v1";
const SHELL_URLS = [
  "/studio/ask",
  "/studio/review",
  "/studio/history",
  "/studio/learn",
  "/studio/manifest.webmanifest",
  "/studio/icon-192.png",
  "/studio/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // 单个 shell 写入失败不该让整个 SW 装不上：逐个 add 并吞掉错误。
      .then((cache) =>
        Promise.all(
          SHELL_URLS.map((url) => cache.add(new Request(url, { cache: "reload" })).catch(() => undefined))
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// RegisterSW 在新版本就绪时发这个消息：跳过等待，立刻接管并在客户端 reload。
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }

  // API 一律放过：不读缓存、不写缓存（数据必须来自服务端）。
  const p = url.pathname;
  if (p.startsWith("/v1") || p.startsWith("/v2") || p.startsWith("/mcp")) return;

  // 导航（页面切换）：network-first + 缓存兜底。
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
          return res;
        })
        .catch(() =>
          caches
            .match(req)
            .then((hit) => hit || caches.match("/studio/learn"))
            .then((hit) => hit || new Response("离线中，请检查网络", { status: 503 }))
        )
    );
    return;
  }

  // 静态资源（Next 产物、图标）：cache-first。
  if (p.includes("/_next/static/") || p.endsWith(".png") || p.endsWith(".svg") || p.endsWith(".ico")) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
            }
            return res;
          })
      )
    );
  }
});
