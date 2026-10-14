"use client";

// 注册 app shell service worker。只在生产注册（dev 下 SW 会缓存半成品页面，越调越乱），
// 且只在支持时注册。新版本就绪时只刷新一次（updatefound → waiting → 让新 SW 接管并 reload），
// 不让学生在做题中途被反复 reload 打断。

import { useEffect } from "react";

export function RegisterSW() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    if (!window.isSecureContext) return; // http（非 localhost）下 SW 直接拒绝，别报错

    let refreshing = false;
    // 新 SW 接手后刷新一次；用 controllerchange 保证只刷一次。
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });

    void navigator.serviceWorker
      .register("/studio/sw.js", { scope: "/studio/" })
      .then((reg) => {
        // 有 waiting 中的新版本 → 让它跳过等待直接接管。
        reg.waiting?.postMessage({ type: "SKIP_WAITING" });
        reg.addEventListener("updatefound", () => {
          const nw = reg.installing;
          if (!nw) return;
          nw.addEventListener("statechange", () => {
            if (nw.state === "installed" && navigator.serviceWorker.controller) {
              nw.postMessage({ type: "SKIP_WAITING" });
            }
          });
        });
      })
      .catch(() => {
        /* 注册失败不打扰学生：页面照常能用（只是没离线壳） */
      });
  }, []);

  return null;
}
