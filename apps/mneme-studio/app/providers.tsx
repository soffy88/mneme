"use client";

import { ThemeProvider, OToastProvider } from "@helios/blocks";

// 儿童可用：mneme-friendly 主题，light 模式（无暗黑模式强制）。attachToRoot 写根元素。
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme="mneme-friendly" mode="light" attachToRoot>
      <OToastProvider>{children}</OToastProvider>
    </ThemeProvider>
  );
}
