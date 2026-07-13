import type { Feature } from '../types/elevator'

export default function FeatureBar({ features }: { features: Feature[] }) {
  return (
    <div className="space-y-3">
      {features.map((f) => {
        const raises = f.direction === 'increases'
        const arrow = raises ? '↑' : '↓'
        const label = raises ? 'raises risk' : 'lowers risk'
        const barColor = raises ? 'bg-red-500' : 'bg-green-500'
        const accent = raises ? 'text-red-600' : 'text-green-600'
        const explanation = raises
          ? 'This factor is pushing the failure risk up.'
          : 'This factor is pushing the failure risk down (protective).'
        return (
          <div key={f.name}>
            <div className="flex justify-between text-sm mb-1">
              <span className="font-medium text-slate-700">
                {/* Hover overlay: explains whether the factor raises or lowers risk */}
                <span className="relative inline-block group/dir align-baseline">
                  <span
                    className={`${accent} font-semibold mr-1 cursor-help`}
                    role="img"
                    aria-label={label}
                  >
                    {arrow}
                  </span>
                  <span
                    role="tooltip"
                    className="pointer-events-none absolute left-0 bottom-full mb-1.5 z-10 hidden w-52 group-hover/dir:block whitespace-normal rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-normal leading-snug text-white shadow-lg"
                  >
                    <span className="font-semibold">{raises ? 'Increases risk' : 'Decreases risk'}</span>
                    {' — '}
                    {explanation}
                  </span>
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
