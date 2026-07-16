import { redirect } from "next/navigation";

// /studio → /studio/learn（学习主面是默认入口）。
export default function Home() {
  redirect("/learn");
}
