import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ElevatorSummary, RiskLevel } from '../types/elevator'
import RiskBadge from '../components/RiskBadge'
import ScopeTag from '../components/ScopeTag'

const BUILDING_TYPE_LABEL: Record<string, string> = {
  residential: 'Residential',
  commercial: 'Commercial',
  office: 'Office',
  infrastructure: 'Infrastructure',
}

export default function Dashboard() {
  const [elevators, setElevators] = useState<ElevatorSummary[]>([])
  const [filter, setFilter] = useState<RiskLevel | 'all'>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/elevators')
      .then((r) => r.json())
      .then((data) => { setElevators(data); setLoading(false) })
  }, [])

  const high = elevators.filter((e) => e.risk_level === 'high').length
  const medium = elevators.filter((e) => e.risk_level === 'medium').length
  const outOfScope = elevators.filter((e) => !e.in_model_scope).length

  const visible = elevators.filter((e) => {
    if (filter !== 'all' && e.risk_level !== filter) return false
    if (search && !e.building_name.toLowerCase().includes(search.toLowerCase()) &&
        !e.id.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Elevator Maintenance</h1>
            <p className="text-sm text-slate-500">Predictive Maintenance Dashboard</p>
          </div>
          <div className="text-right text-sm text-slate-500">
            <p>Today · {new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
            <p className="font-medium text-slate-700">Morning Review</p>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {/* KPI cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <KpiCard label="Total elevators" value={elevators.length} color="slate" />
          <KpiCard label="High risk (>80%)" value={high} color="red" />
          <KpiCard label="Medium risk (50–80%)" value={medium} color="orange" />
          <KpiCard label="Out of model scope" value={outOfScope} color="gray" note="insufficient sensor data" />
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-4">
          <input
            type="text"
            placeholder="Search building or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-slate-400"
          />
          {(['all', 'high', 'medium', 'low'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                filter === f
                  ? 'bg-slate-800 text-white border-slate-800'
                  : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
              }`}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          <span className="ml-auto text-sm text-slate-500 self-center">{visible.length} shown</span>
        </div>

        {/* Table */}
        {loading ? (
          <div className="text-center py-20 text-slate-400">Loading...</div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-3">ID</th>
                  <th className="text-left px-4 py-3">Building</th>
                  <th className="text-left px-4 py-3 hidden md:table-cell">Type</th>
                  <th className="text-left px-4 py-3 hidden lg:table-cell">Zone</th>
                  <th className="text-left px-4 py-3 hidden lg:table-cell">Last visit</th>
                  <th className="text-left px-4 py-3">Risk</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((e) => (
                  <tr key={e.id} className={`hover:bg-slate-50 transition-colors ${e.risk_level === 'high' ? 'bg-red-50/40' : ''}`}>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{e.id}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{e.building_name}</div>
                      <div className="text-xs text-slate-400">{e.model} · {e.age_years}y · {e.floor_count}F</div>
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell text-slate-500">
                      {BUILDING_TYPE_LABEL[e.building_type]}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell text-slate-500">{e.zone}</td>
                    <td className="px-4 py-3 hidden lg:table-cell text-slate-500">
                      {new Date(e.last_visit_date).toLocaleDateString('en-GB')}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <RiskBadge level={e.risk_level} score={e.risk_score} showScore />
                        <ScopeTag inScope={e.in_model_scope} />
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/elevators/${e.id}`}
                        className="text-slate-600 hover:text-slate-900 text-xs font-medium underline underline-offset-2"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}

function KpiCard({ label, value, color, note }: { label: string; value: number; color: string; note?: string }) {
  const colorMap: Record<string, string> = {
    slate: 'text-slate-800',
    red: 'text-red-600',
    orange: 'text-orange-600',
    gray: 'text-gray-500',
  }
  return (
    <div className="bg-white rounded-xl border border-slate-200 px-4 py-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-3xl font-bold ${colorMap[color]}`}>{value}</p>
      {note && <p className="text-xs text-slate-400 mt-1">{note}</p>}
    </div>
  )
}
