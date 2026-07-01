import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { currentStudentId } from "../api"
import { MasteryOverview } from "../components/MasteryOverview"
import { GrowthCurve } from "../components/GrowthCurve"
import { EffortBoard } from "../components/EffortBoard"
import { WeakRoots } from "../components/WeakRoots"
import { CalibrationCard } from "../components/CalibrationCard"
import { InterleaveCard } from "../components/InterleaveCard"
import { PageHeader } from "../components/ui"

/**
 * 掌握度（底部 tab）：跨学科的"镜子"——薄弱点排序 + 成长曲线 + 努力收益 + 校准 + 交错池。
 * 数据均来自跨学科认知端点。
 */
export function Mastery() {
  const studentId = currentStudentId()
  const [selectedKc, setSelectedKc] = useState<string | undefined>(undefined)
  const navigate = useNavigate()

  if (!studentId) return <div className="p-6 text-sm text-slate-500">请先登录后查看掌握度。</div>

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <PageHeader title="掌握度" subtitle="不替你决定学什么——帮你看清你是怎么学的、在怎样变好。" />

      <div className="grid md:grid-cols-2 gap-5">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">掌握度总览（薄弱在前）</h2>
          <MasteryOverview studentId={studentId} onSelect={setSelectedKc} selectedKc={selectedKc} />
        </div>
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
