import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const here = path.dirname(fileURLToPath(import.meta.url));

// W2b S1 mneme-studio：独立 app，basePath=/studio，端口 3001（见 package.json dev/start）。
// 零 DB 凭据 —— 所有数据经 HTTP /mcp/*（NEXT_PUBLIC_API_BASE），tool 面是唯一通道。
//
// turbopack.root：这个 worktree 的 node_modules 是软链到主仓
// （/data/soffy/projects/mneme/apps/mneme-studio/node_modules，git 不跟踪），
// Turbopack 只编译"workspace root 之内"的文件，软链逃逸会直接 panic
// （"Symlink node_modules is invalid, it points out of the filesystem root"）。
// 把 root 抬到两个仓库的公共父目录，软链目标就落在 root 之内，构建恢复正常。
const nextConfig: NextConfig = {
  basePath: "/studio",
  transpilePackages: ["@helios/blocks"],
  reactStrictMode: true,
  output: "standalone", // 生产：standalone 产物便于容器化（同 mneme-web 部署方式）。
};

export default nextConfig;
