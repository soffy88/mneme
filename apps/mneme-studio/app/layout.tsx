import type { Metadata, Viewport } from "next";
import "@helios/blocks/styles.css";
import "./globals.css";
import { Providers } from "./providers";
import { RegisterSW } from "@/components/pwa/RegisterSW";

export const metadata: Metadata = {
  title: "善学记 · 学习",
  description: "善学记学习工作区",
  manifest: "/studio/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "善学记",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/studio/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/studio/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/studio/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

// 手机优先（390x844）：允许等比放大（学生可能想看清题面），但不允许初始缩放错位。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#25304a",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <RegisterSW />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
