import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { currentStudentId } from "../../api"
import { MasteryOverview } from "../../components/MasteryOverview"
import { GrowthCurve } from "../../components/GrowthCurve"
import { EffortBoard } from "../../components/EffortBoard"
import { WeakRoots } from "../../components/WeakRoots"
import { CalibrationCard } from "../../components/CalibrationCard"
import { InterleaveCard } from "../../components/InterleaveCard"
import { PageHeader } from "../../components/ui"

/**
 * 成长档案（"镜子"）：左侧薄弱点排序，选中后右侧显示该知识点的成长曲线。
 * 全部数据来自已就绪的认知端点；这是产品的核心差异化呈现。
 */
export function MathDashboard() {
  const studentId = currentStudentId()
  const [selectedKc, setSelectedKc] = useState<string | undefined>(undefined)
  const navigate = useNavigate()

  if (!studentId)
    return <div className="p-6 text-sm text-slate-500">请先登录后查看成长档案。</div>

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <PageHeader title="数学成长档案" subtitle="不替你决定学什么——帮你看清你是怎么学的、在怎样变好。" />

      <div className="grid md:grid-cols-2 gap-5">
        {/* 薄弱点排序 */}
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">掌握度总览（薄弱在前）</h2>
          <MasteryOverview studentId={studentId} onSelect={setSelectedKc} selectedKc={selectedKc} />
        </div>

        {/* 成长曲线 */}
        <div className="card p-4">
          {selectedKc ? (
            <GrowthCurve key={selectedKc} studentId={studentId} kcId={selectedKc} kcName={selectedKc} />
          ) : (
            <div className="text-sm text-slate-400 py-16 text-center">
              ← 点击左侧任一知识点，查看它的掌握度成长曲线
            </div>
          )}
        </div>
      </div>

      {/* 前置断点 + 努力收益 */}
      <div className="grid md:grid-cols-2 gap-5 mt-5">
        <div className="card p-4">
          <WeakRoots
            studentId={studentId}
            onPractice={(kuId, name) =>
              navigate(`/subjects/math/socratic?ku=${encodeURIComponent(kuId)}&name=${encodeURIComponent(name)}`)
            }
          />
        </div>
        <div className="card p-4">
          <EffortBoard studentId={studentId} />
        </div>
      </div>

      {/* 判断准度（JOL 校准）+ 交错复习池（M-B） */}
      <div className="grid md:grid-cols-2 gap-5 mt-5">
        <div className="card p-4">
          <CalibrationCard studentId={studentId} />
        </div>
        <div className="card p-4">
          <InterleaveCard studentId={studentId} />
        </div>
      </div>
    </div>
  )
}
