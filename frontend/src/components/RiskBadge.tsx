import type { RiskLevel } from '../types/elevator'

interface Props {
  level: RiskLevel
  score: number
  showScore?: boolean
}

const CONFIG: Record<RiskLevel, { label: string; classes: string; dot: string }> = {
  high:   { label: 'High',   classes: 'bg-red-100 text-red-800 border border-red-300',       dot: 'bg-red-500' },
  medium: { label: 'Medium', classes: 'bg-orange-100 text-orange-800 border border-orange-300', dot: 'bg-orange-500' },
  low:    { label: 'Low',    classes: 'bg-yellow-50 text-yellow-700 border border-yellow-200',  dot: 'bg-yellow-400' },
}

export default function RiskBadge({ level, score, showScore = false }: Props) {
  const { label, classes, dot } = CONFIG[level]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${classes}`}>
      <span className={`w-2 h-2 rounded-full ${dot}`} />
      {label}
      {showScore && <span className="opacity-70">· {Math.round(score * 100)}%</span>}
    </span>
  )
}
