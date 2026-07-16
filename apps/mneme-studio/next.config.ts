import type { NextConfig } from "next";

// W2b S1 mneme-studio：独立 app，basePath=/studio，端口 3001（见 package.json dev/start）。
// 零 DB 凭据 —— 所有数据经 HTTP /mcp/*（NEXT_PUBLIC_API_BASE），tool 面是唯一通道。
const nextConfig: NextConfig = {
  basePath: "/studio",
  transpilePackages: ["@helios/blocks"],
  reactStrictMode: true,
  output: "standalone", // 生产：standalone 产物便于容器化（同 mneme-web 部署方式）。
};

export default nextConfig;
