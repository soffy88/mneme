// /studio/animate 的例题（参数格式与 /v1/geometry、/v1/chemistry、visualize 内核一致）。
import type { AnimKind } from "@/lib/mcp";

export const ANIM_KIND_LABEL: Record<AnimKind, string> = {
  solid_geometry: "立体几何",
  conic_chord: "圆锥曲线弦",
  equation_balance: "化学配平",
  function_graph: "函数图像",
};

export const ANIM_PRESETS: Record<AnimKind, { label: string; params: object }[]> = {
  solid_geometry: [
    {
      label: "正四棱锥 P-ABCD，底边 2、高 1，E 为 PC 中点，求 BE 与平面 PAC 所成角的正弦",
      params: {
        body: "regular_quad_pyramid",
        dims: { base_edge: 2, height: 1 },
        givens: [{ name: "E", kind: "midpoint", of: ["P", "C"] }],
        query: { type: "line_plane_angle", line: ["B", "E"], plane: ["P", "A", "C"] },
      },
    },
    {
      label: "正方体 ABCD-A₁B₁C₁D₁，棱长 2，求 A₁ 到平面 AB₁D₁ 的距离",
      params: { body: "cube", dims: { edge: 2 }, query: { type: "point_plane_distance", point: ["A1"], plane: ["A", "B1", "D1"] } },
    },
    {
      label: "正四面体 ABCD，棱长 2√2，求二面角 C-AB-D 的余弦",
      params: { body: "regular_tetrahedron", dims: { edge: "2sqrt(2)" }, query: { type: "dihedral_angle", edge: ["A", "B"], faces: ["C", "D"] } },
    },
  ],
  conic_chord: [
    {
      label: "椭圆 x²/4+y²/3=1，过 F(1,0) 的弦 AB，M(-1,0)，MA·MB 的范围",
      params: { conic: { kind: "ellipse", a: 2, b: "sqrt(3)" }, query: { through: [1, 0], target: "dot_product", vertex: [-1, 0] } },
    },
    {
      label: "椭圆 x²/4+y²/3=1，过焦点 F(1,0) 的弦长范围",
      params: { conic: { kind: "ellipse", a: 2, b: "sqrt(3)" }, query: { through: [1, 0], target: "chord_length" } },
    },
    {
      label: "抛物线 y²=4x，过焦点的弦 AB，OA·OB 为定值",
      params: { conic: { kind: "parabola", p: 2 }, query: { through: [1, 0], target: "fixed_value_dot", vertex: [0, 0] } },
    },
    {
      label: "双曲线 x²−y²/3=1，过 F(2,0) 的弦 AB，OA·OB 的范围",
      params: { conic: { kind: "hyperbola", a: 1, b: "sqrt(3)" }, query: { through: [2, 0], target: "dot_product", vertex: [0, 0] } },
    },
  ],
  equation_balance: [
    { label: "KMnO4 + HCl → KCl + MnCl2 + Cl2 + H2O", params: { reactants: ["KMnO4", "HCl"], products: ["KCl", "MnCl2", "Cl2", "H2O"] } },
    { label: "MnO4⁻ + Fe²⁺ + H⁺ → Mn²⁺ + Fe³⁺ + H2O", params: { reactants: ["MnO4^-", "Fe^2+", "H^+"], products: ["Mn^2+", "Fe^3+", "H2O"] } },
    { label: "C3H8 + O2 → CO2 + H2O", params: { reactants: ["C3H8", "O2"], products: ["CO2", "H2O"] } },
    { label: "Cu + HNO3 → Cu(NO3)2 + NO + H2O", params: { reactants: ["Cu", "HNO3"], products: ["Cu(NO3)2", "NO", "H2O"] } },
  ],
  function_graph: [
    { label: "y = x² − 2x − 3", params: { expression: "x**2 - 2*x - 3", x_min: -3, x_max: 5 } },
    { label: "y = sin(x)", params: { expression: "sin(x)", x_min: -7, x_max: 7 } },
    { label: "y = x³ − 3x", params: { expression: "x**3 - 3*x", x_min: -2.5, x_max: 2.5 } },
  ],
};

/** 动画参数 → base64url（/studio/animate?kind=..&params=.. 深链用）。 */
export function encodeAnimParams(params: unknown): string {
  const bytes = new TextEncoder().encode(JSON.stringify(params));
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
