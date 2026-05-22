import type { RiskLevel } from '../types/elevator'

interface Props {
  level: RiskLevel
  score: number
  showScore?: boolean
}

function getConfig(level: RiskLevel, score: number) {
  if (level === 'low') {
    return { label: 'Low', classes: 'bg-green-100 text-green-800 border border-green-300', dot: 'bg-green-500' }
  }
  if (level === 'medium') {
    return { label: 'Medium', classes: 'bg-yellow-100 text-yellow-800 border border-yellow-300', dot: 'bg-yellow-500' }
  }
  if (score > 0.90) {
    return { label: 'High', classes: 'bg-red-100 text-red-800 border border-red-300', dot: 'bg-red-500' }
  }
  return { label: 'High', classes: 'bg-orange-100 text-orange-800 border border-orange-300', dot: 'bg-orange-500' }
}

export default function RiskBadge({ level, score, showScore = false }: Props) {
  const { label, classes, dot } = getConfig(level, score)
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${classes}`}>
      <span className={`w-2 h-2 rounded-full ${dot}`} />
      {label}
      {showScore && level !== 'low' && <span className="opacity-70">· {Math.round(score * 100)}%</span>}
    </span>
  )
}
