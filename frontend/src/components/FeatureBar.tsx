import type { Feature } from '../types/elevator'

interface Props {
  features: Feature[]
}

export default function FeatureBar({ features }: Props) {
  return (
    <div className="space-y-3">
      {features.map((f) => {
        const raises = f.direction === 'increases'
        const arrow = raises ? '↑' : '↓'
        const label = raises ? 'raises risk' : 'lowers risk'
        const barColor = raises ? 'bg-red-500' : 'bg-green-500'
        const accent = raises ? 'text-red-600' : 'text-green-600'
        return (
          <div key={f.name}>
            <div className="flex justify-between text-sm mb-1">
              <span className="font-medium text-slate-700">
                <span className={`${accent} font-semibold mr-1`} title={label} aria-label={label}>
                  {arrow}
                </span>
                {f.name}
              </span>
              <span className="text-slate-500">{f.value}</span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full ${barColor} rounded-full`}
                style={{ width: `${Math.round(f.impact * 100)}%` }}
              />
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              {Math.round(f.impact * 100)}% of prediction weight · {label}
            </p>
          </div>
        )
      })}
    </div>
  )
}
