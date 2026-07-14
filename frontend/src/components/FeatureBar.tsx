import { useState } from 'react'
import type { Feature } from '../types/elevator'

export default function FeatureBar({ features }: { features: Feature[] }) {
  // Which feature's explanation overlay is open. Works on touch (tap) and desktop (hover).
  const [openName, setOpenName] = useState<string | null>(null)

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
        const open = openName === f.name
        return (
          <div key={f.name}>
            <div className="flex justify-between text-sm mb-1">
              <span className="font-medium text-slate-700">
                {/* Tap (mobile) or hover (desktop) the icon for a fuller explanation. */}
                <span className="relative inline-block align-baseline">
                  <button
                    type="button"
                    className={`${accent} font-semibold mr-1 cursor-pointer`}
                    aria-label={label}
                    aria-expanded={open}
                    onClick={() => setOpenName(open ? null : f.name)}
                    onMouseEnter={() => setOpenName(f.name)}
                    onMouseLeave={() => setOpenName(null)}
                  >
                    {arrow}
                  </button>
                  {open && (
                    <span
                      role="tooltip"
                      className="absolute left-0 bottom-full mb-1.5 z-10 block w-52 whitespace-normal rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-normal leading-snug text-white shadow-lg"
                    >
                      <span className="font-semibold">{raises ? 'Increases risk' : 'Decreases risk'}</span>
                      {' — '}
                      {explanation}
                    </span>
                  )}
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
