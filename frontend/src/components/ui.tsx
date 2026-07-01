import type { ButtonHTMLAttributes, ReactNode } from "react"

type Variant = "primary" | "secondary" | "ghost"
const VARIANT: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800 shadow-sm",
  secondary: "bg-slate-100 text-slate-700 hover:bg-slate-200",
  ghost: "text-slate-500 hover:text-slate-800 hover:bg-slate-100",
}

/** 统一按钮：variant(primary/secondary/ghost) + size(sm/md)。 */
export function Button(
  { variant = "primary", size = "md", className = "", ...props }:
    ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" },
) {
  const sz = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2.5 text-sm"
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50 ${VARIANT[variant]} ${sz} ${className}`}
    />
  )
}

/** 小标签。 */
export function Badge({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${className || "bg-slate-100 text-slate-500"}`}>{children}</span>
}

/** 统一页头：标题 + 副标题（+ 可选右侧操作）。 */
export function PageHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 mt-1">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

/** 统一空状态。 */
export function EmptyState({ icon, children }: { icon?: string; children: ReactNode }) {
  return (
    <div className="py-12 text-center text-sm text-slate-400">
      {icon && <div className="text-3xl mb-2 opacity-80">{icon}</div>}
      {children}
    </div>
  )
}

/** 统一加载态。 */
export function Loading({ label = "加载中…" }: { label?: string }) {
  return <div className="py-12 text-center text-sm text-slate-400 animate-pulse">{label}</div>
}
