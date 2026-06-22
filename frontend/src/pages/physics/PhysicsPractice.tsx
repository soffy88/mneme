import { useSearchParams, Link } from "react-router-dom"

export function PhysicsPractice() {
  const [params] = useSearchParams()
  const kuId = params.get("ku")

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center gap-2 mb-6 text-sm text-gray-500">
        <Link to="/subjects/physics" className="hover:text-blue-600">物理</Link>
        <span>›</span>
        <span>练习</span>
      </div>

      <h1 className="text-xl font-bold text-gray-900 mb-2">物理练习</h1>
      {kuId && (
        <p className="text-sm text-gray-500 mb-6">知识点：{kuId.split("-ku-")[1] ?? kuId}</p>
      )}

      {/* 受力分析入口（已有工具） */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 mb-4">
        <div className="flex items-start gap-3">
          <div className="text-2xl">⚡</div>
          <div>
            <h2 className="font-semibold text-blue-900 mb-1">受力分析苏格拉底引导</h2>
            <p className="text-sm text-blue-700 mb-3">
              力学综合练习，AI 一步步引导你找到所有力，不直接给答案。
            </p>
            <Link
              to="/subjects/physics/force-analysis"
              className="inline-block px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
            >
              开始受力分析
            </Link>
          </div>
        </div>
      </div>

      {/* 题库建设中提示 */}
      <div className="bg-gray-50 border border-dashed border-gray-300 rounded-xl p-6 text-center">
        <div className="text-3xl mb-3">🔬</div>
        <h2 className="font-semibold text-gray-700 mb-2">物理题库建设中</h2>
        <p className="text-sm text-gray-500 leading-relaxed">
          当前物理题库暂未导入。
          <br />
          已有数学题库 20,000+ 题可参考练习形式。
          <br />
          <span className="text-xs text-gray-400 mt-1 block">物理题库上线后，将支持按知识点自动出题和变式练习。</span>
        </p>
        <div className="mt-4 flex justify-center gap-3">
          <Link
            to="/subjects/physics/lesson"
            className="px-4 py-2 text-sm bg-white border border-gray-300 rounded-lg text-gray-600 hover:border-gray-400"
          >
            返回知识体系
          </Link>
        </div>
      </div>
    </div>
  )
}
