"use client";

// /studio/lab —— 交互实验室：立体几何 / 解析几何（圆锥曲线弦）/ 化学方程式配平。
//
// 三个内核都是确定性 3O 事务（sympy 精确求解 + 独立浮点/整数复核），不经 LLM：
//   POST /v1/geometry/solid/{solve,lesson}
//   POST /v1/geometry/conic/{solve,lesson}
//   POST /v1/chemistry/equation/balance
// 交互课是服务端渲染的自包含 HTML，放进 sandbox iframe（只给 allow-scripts，
// 不给 allow-same-origin，拿不到本页 localStorage 里的登录 token）。

import { useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle } from "@helios/blocks";
import { MathText } from "@/components/MathText";
import { eduPost, eduPostHtml, getToken, redirectToLogin } from "@/lib/mcp";

type Tab = "solid" | "conic" | "chem";

type Step = { title: string; content: string };

type GeometryResult = {
  title: string;
  answer_latex: string;
  answer_label?: string;
  steps: Step[];
};

type ChemResult = {
  equation_text: string;
  equation_latex: string;
  coefficients: number[];
  conservation: { row: string; left: number; right: number; balanced: boolean }[];
  molar_masses: Record<string, number | null>;
  steps: Step[];
};

const SOLID_PRESETS: { label: string; spec: object }[] = [
  {
    label: "正方体 ABCD-A₁B₁C₁D₁，棱长 2，求 A₁ 到平面 AB₁D₁ 的距离",
    spec: { body: "cube", dims: { edge: 2 }, query: { type: "point_plane_distance", point: ["A1"], plane: ["A", "B1", "D1"] } },
  },
  {
    label: "正四棱锥 P-ABCD，底边 2、高 1，E 为 PC 中点，求 BE 与平面 PAC 所成角的正弦",
    spec: {
      body: "regular_quad_pyramid",
      dims: { base_edge: 2, height: 1 },
      givens: [{ name: "E", kind: "midpoint", of: ["P", "C"] }],
      query: { type: "line_plane_angle", line: ["B", "E"], plane: ["P", "A", "C"] },
    },
  },
  {
    label: "正方体棱长 1，求异面直线 A₁C 与 AB 所成角的余弦",
    spec: { body: "cube", dims: { edge: 1 }, query: { type: "line_line_angle", line: ["A1", "C"], line2: ["A", "B"] } },
  },
  {
    label: "正四面体 ABCD，棱长 2√2，求二面角 C-AB-D 的余弦",
    spec: { body: "regular_tetrahedron", dims: { edge: "2sqrt(2)" }, query: { type: "dihedral_angle", edge: ["A", "B"], faces: ["C", "D"] } },
  },
  {
    label: "长方体 3×4×5，M 在 A₁C₁ 上且 A₁M = ¼A₁C₁，求 MC",
    spec: {
      body: "cuboid",
      dims: { length: 3, width: 4, height: 5 },
      givens: [{ name: "M", kind: "on_segment", of: ["A1", "C1"], ratio: "1/4" }],
      query: { type: "segment_length", points: ["M", "C"] },
    },
  },
];

const CONIC_PRESETS: { label: string; spec: object }[] = [
  {
    label: "椭圆 x²/4+y²/3=1，过 F(1,0) 的弦 AB，M(-1,0)，求 MA·MB 的范围",
    spec: { conic: { kind: "ellipse", a: 2, b: "sqrt(3)" }, query: { through: [1, 0], target: "dot_product", vertex: [-1, 0] } },
  },
  {
    label: "椭圆 x²/4+y²/3=1，过焦点 F(1,0) 的弦长范围",
    spec: { conic: { kind: "ellipse", a: 2, b: "sqrt(3)" }, query: { through: [1, 0], target: "chord_length" } },
  },
  {
    label: "椭圆 x²/4+y²/3=1，过 F(1,0) 的弦 AB，求 △OAB 面积范围",
    spec: { conic: { kind: "ellipse", a: 2, b: "sqrt(3)" }, query: { through: [1, 0], target: "triangle_area", vertex: [0, 0] } },
  },
  {
    label: "抛物线 y²=4x，过焦点的弦 AB，证明 OA·OB 为定值",
    spec: { conic: { kind: "parabola", p: 2 }, query: { through: [1, 0], target: "fixed_value_dot", vertex: [0, 0] } },
  },
  {
    label: "双曲线 x²−y²/3=1，过 F(2,0) 的弦 AB，求 OA·OB 的范围",
    spec: { conic: { kind: "hyperbola", a: 1, b: "sqrt(3)" }, query: { through: [2, 0], target: "dot_product", vertex: [0, 0] } },
  },
];

const CHEM_EXAMPLES = [
  "KMnO4 + HCl -> KCl + MnCl2 + Cl2 + H2O",
  "Fe2O3 + CO -> Fe + CO2",
  "C3H8 + O2 -> CO2 + H2O",
  "Cu + HNO3 -> Cu(NO3)2 + NO + H2O",
  "MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O",
];

/** 服务端步骤是带 $..$ 的 HTML；只取纯文本再交给 KaTeX，不把 HTML 插进 DOM。 */
function htmlToText(html: string): string {
  if (typeof window === "undefined") return html;
  const doc = new DOMParser().parseFromString(html.replace(/<br\s*\/?>/gi, "\n"), "text/html");
  return doc.body.textContent ?? "";
}

function parseEquation(text: string): { reactants: string[]; products: string[] } | null {
  const parts = text.split(/\s*(?:->|→|⟶|=)\s*/);
  if (parts.length !== 2) return null;
  const side = (s: string) => s.split(/\s+\+\s+/).map((x) => x.trim()).filter(Boolean);
  const reactants = side(parts[0]);
  const products = side(parts[1]);
  if (!reactants.length || !products.length) return null;
  return { reactants, products };
}

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="space-y-3 text-sm">
      {steps.map((s, i) => (
        <li key={i} data-testid="lab-step">
          <div className="font-medium">
            {i + 1}. {s.title}
          </div>
          <div className="whitespace-pre-wrap">
            <MathText text={htmlToText(s.content)} />
          </div>
        </li>
      ))}
    </ol>
  );
}

function GeometryLab({ kind }: { kind: "solid" | "conic" }) {
  const presets = kind === "solid" ? SOLID_PRESETS : CONIC_PRESETS;
  const base = kind === "solid" ? "/v1/geometry/solid" : "/v1/geometry/conic";
  const [specText, setSpecText] = useState(JSON.stringify(presets[0].spec, null, 2));
  const [result, setResult] = useState<GeometryResult | null>(null);
  const [lessonHtml, setLessonHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    let spec: unknown;
    try {
      spec = JSON.parse(specText);
    } catch {
      setError("题目参数不是合法的 JSON");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setLessonHtml(null);
    try {
      const [r, html] = await Promise.all([
        eduPost<GeometryResult>(`${base}/solve`, spec),
        eduPostHtml(`${base}/lesson`, spec),
      ]);
      setResult(r);
      setLessonHtml(html);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <OCard>
        <div className="p-4 space-y-3">
          <label className="block text-sm font-medium" htmlFor={`${kind}-preset`}>
            例题
          </label>
          <select
            id={`${kind}-preset`}
            data-testid={`${kind}-preset`}
            className="w-full rounded-lg border p-2 text-sm"
            onChange={(e) => setSpecText(JSON.stringify(presets[Number(e.target.value)].spec, null, 2))}
          >
            {presets.map((p, i) => (
              <option key={i} value={i}>
                {p.label}
              </option>
            ))}
          </select>
          <details>
            <summary className="cursor-pointer text-sm">改题目参数</summary>
            <textarea
              data-testid={`${kind}-spec`}
              className="mt-2 w-full rounded-lg border p-3 font-mono text-xs"
              rows={8}
              value={specText}
              onChange={(e) => setSpecText(e.target.value)}
            />
          </details>
          <OButton data-testid={`${kind}-run`} disabled={loading} onClick={() => void run()}>
            {loading ? "求解中…" : "求解并生成交互课"}
          </OButton>
        </div>
      </OCard>

      {error && (
        <OCard>
          <div className="p-4 text-sm text-[var(--o-color-danger,#c00)]" data-testid="lab-error">
            出错了：{error}
          </div>
        </OCard>
      )}

      {result && (
        <OCard data-testid="lab-answer">
          <OCardHeader>
            <OCardTitle>{result.title}</OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-3">
            <div className="font-medium">
              答案：<MathText text={`$${result.answer_latex}$`} />
            </div>
            <Steps steps={result.steps} />
          </div>
        </OCard>
      )}

      {lessonHtml && (
        <OCard>
          <OCardHeader>
            <OCardTitle>交互课（可拖动旋转、逐步播放）</OCardTitle>
          </OCardHeader>
          <iframe
            data-testid="lab-lesson"
            title="交互课"
            className="h-[720px] w-full rounded-b-lg border-0"
            sandbox="allow-scripts"
            srcDoc={lessonHtml}
          />
        </OCard>
      )}
    </div>
  );
}

function ChemLab() {
  const [text, setText] = useState(CHEM_EXAMPLES[0]);
  const [result, setResult] = useState<ChemResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    const parsed = parseEquation(text.trim());
    if (!parsed) {
      setError("格式：反应物 + 反应物 -> 生成物 + 生成物（加号两边留空格）");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await eduPost<ChemResult>("/v1/chemistry/equation/balance", parsed));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <OCard>
        <div className="p-4 space-y-3">
          <input
            data-testid="chem-input"
            className="w-full rounded-lg border p-3 font-mono text-sm"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex flex-wrap gap-2 text-xs">
            {CHEM_EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="rounded border px-2 py-1" onClick={() => setText(ex)}>
                {ex}
              </button>
            ))}
          </div>
          <OButton data-testid="chem-run" disabled={loading || !text.trim()} onClick={() => void run()}>
            {loading ? "配平中…" : "配平"}
          </OButton>
        </div>
      </OCard>

      {error && (
        <OCard>
          <div className="p-4 text-sm text-[var(--o-color-danger,#c00)]" data-testid="lab-error">
            出错了：{error}
          </div>
        </OCard>
      )}

      {result && (
        <OCard data-testid="chem-answer">
          <OCardHeader>
            <OCardTitle>配平结果</OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-4">
            <div className="text-lg">
              <MathText text={`$${result.equation_latex}$`} />
            </div>
            <table className="text-sm">
              <thead>
                <tr>
                  <th className="pr-6 text-left">元素 / 电荷</th>
                  <th className="pr-6 text-right">左边</th>
                  <th className="text-right">右边</th>
                </tr>
              </thead>
              <tbody>
                {result.conservation.map((row) => (
                  <tr key={row.row}>
                    <td className="pr-6">{row.row === "charge" ? "电荷" : row.row}</td>
                    <td className="pr-6 text-right">{row.left}</td>
                    <td className="text-right">{row.right}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Steps steps={result.steps} />
          </div>
        </OCard>
      )}
    </div>
  );
}

export default function LabPage() {
  const [tab, setTab] = useState<Tab>("solid");
  const tabs: { id: Tab; label: string }[] = [
    { id: "solid", label: "立体几何" },
    { id: "conic", label: "解析几何" },
    { id: "chem", label: "化学配平" },
  ];
  return (
    <main className="mx-auto max-w-4xl p-6 space-y-4" data-testid="lab-root">
      <h1 className="text-2xl font-bold">善学记 · 交互实验室</h1>
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        答案由确定性内核精确计算，并经独立复核；对不上就不出结果，不会给出错误答案。
      </p>
      <div className="flex gap-2" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            data-testid={`lab-tab-${t.id}`}
            className={`rounded-lg border px-3 py-1 text-sm ${tab === t.id ? "font-semibold bg-black/5" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "solid" && <GeometryLab key="solid" kind="solid" />}
      {tab === "conic" && <GeometryLab key="conic" kind="conic" />}
      {tab === "chem" && <ChemLab />}
    </main>
  );
}
