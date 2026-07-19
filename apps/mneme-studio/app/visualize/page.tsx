"use client";

// /studio/visualize —— W4 Visualize 模式：数学概念/数据 -> 真实渲染
// （去 Manim）。
//
// FC-5：零 DB，唯一数据通道是 mcp.visualizeConcept()。原有页面零改动，
// 本页是新增独立路由。
//
// 4 种渲染类型，data_source 字段如实标注来源：svg_plot/three/chart 三种
// 由 S0 加固后的真实内核（kernel_to_plot2d/kernel_to_three/solve_sequence）
// 产出；mermaid 是 LLM 直接撰写的声明式图示文本，标"llm_authored"，不伪装
// 成内核数据——页面上也把这个区分做实（图注里写清楚"来自内核计算"还是
// "AI 生成的示意图"，不是只在 API 响应里藏一个字段没人看）。
//
// react-three-fiber 在这个仓库首次真实投用（此前 package.json 里装了但
// 零页面使用）——用 next/dynamic + ssr:false 加载（WebGL 需要浏览器环境，
// 服务端渲染没有意义）。

import { useState } from "react";
import dynamic from "next/dynamic";
import { Line, Bar } from "react-chartjs-2";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { mcp, getToken, redirectToLogin, type VisualizeConceptResult } from "@/lib/mcp";
import { MermaidDiagram } from "@/components/MermaidDiagram";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
);

const ThreePointCloud = dynamic(
  () => import("@/components/ThreePointCloud").then((m) => m.ThreePointCloud),
  { ssr: false, loading: () => <div data-testid="three-loading">正在加载 3D 视图…</div> }
);

const DATA_SOURCE_LABEL: Record<string, string> = {
  kernel_to_plot2d: "来自内核计算（确定性，非 AI 生成）",
  kernel_to_three: "来自内核计算（确定性，非 AI 生成）",
  solve_sequence: "来自内核计算（确定性，非 AI 生成）",
  llm_authored: "AI 生成的示意图（非数值计算结果）",
};

function RenderView({ result }: { result: VisualizeConceptResult }) {
  const sourceLabel = DATA_SOURCE_LABEL[result.data_source ?? ""] ?? "";

  return (
    <div className="space-y-2" data-testid="visualize-render">
      {sourceLabel && (
        <p className="text-xs text-[var(--o-color-fg-muted,#888)]" data-testid="data-source-label">
          {sourceLabel}
        </p>
      )}

      {result.render_type === "svg_plot" && result.svg && (
        <div
          data-testid="svg-plot"
          className="rounded-lg border p-2"
          dangerouslySetInnerHTML={{ __html: result.svg }}
        />
      )}

      {result.render_type === "three" && result.points && (
        <ThreePointCloud points={result.points} />
      )}

      {result.render_type === "chart" && result.labels && result.datasets && (
        <div data-testid="chart-view" className="rounded-lg border p-4">
          {result.chart_type === "bar" ? (
            <Bar
              data={{ labels: result.labels, datasets: result.datasets }}
              options={{ responsive: true }}
            />
          ) : (
            <Line
              data={{ labels: result.labels, datasets: result.datasets }}
              options={{ responsive: true }}
            />
          )}
        </div>
      )}

      {result.render_type === "mermaid" && result.diagram_source && (
        <div className="rounded-lg border p-4">
          <MermaidDiagram source={result.diagram_source} />
        </div>
      )}
    </div>
  );
}

export default function VisualizePage() {
  const [conceptText, setConceptText] = useState("");
  const [result, setResult] = useState<VisualizeConceptResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    const text = conceptText.trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await mcp.visualizeConcept(text);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="visualize-root">
      <h1 className="text-2xl font-bold">善学记 · 图示</h1>
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        描述一个数学概念或数据，系统会选择合适的方式画出来——函数图像、
        三维曲面、图表或示意图。
      </p>

      <OCard>
        <div className="p-4 space-y-3">
          <textarea
            data-testid="concept-input"
            className="w-full rounded-lg border p-3 text-sm"
            rows={3}
            placeholder="例如：画出 y=x^2-4 的图像"
            value={conceptText}
            onChange={(e) => setConceptText(e.target.value)}
          />
          <OButton
            data-testid="submit-concept"
            disabled={loading || !conceptText.trim()}
            onClick={() => void handleSubmit()}
          >
            {loading ? "生成中…" : "画出来"}
          </OButton>
        </div>
      </OCard>

      {error && (
        <OCard>
          <div
            className="p-4 text-sm text-[var(--o-color-danger,#c00)]"
            data-testid="visualize-error"
          >
            出错了：{error}
          </div>
        </OCard>
      )}

      {result && !result.success && (
        <OEmptyState
          title="这个概念暂时画不出来"
          description={result.error || "未知原因"}
        />
      )}

      {result && result.success && (
        <div className="space-y-4">
          {result.restated_concept && (
            <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
              理解到的需求：{result.restated_concept}
            </p>
          )}
          <OCard data-testid="render-card">
            <OCardHeader>
              <OCardTitle>{result.title || "可视化结果"}</OCardTitle>
            </OCardHeader>
            <div className="p-4">
              <RenderView result={result} />
            </div>
          </OCard>
        </div>
      )}
    </main>
  );
}
