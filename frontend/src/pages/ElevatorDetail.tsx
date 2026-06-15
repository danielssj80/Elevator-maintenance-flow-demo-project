import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import type { ElevatorDetail as ElevatorDetailType } from '../types/elevator'
import RiskBadge from '../components/RiskBadge'
import FeatureBar from '../components/FeatureBar'
import ScopeTag from '../components/ScopeTag'
import VoiceBriefing from '../components/VoiceBriefing'

const DAYS = ['5d ago', '4d ago', '3d ago', '2d ago', 'Yesterday', 'Today']

export default function ElevatorDetail() {
  const { id } = useParams<{ id: string }>()
  const [elevator, setElevator] = useState<ElevatorDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [dispatched, setDispatched] = useState(false)

  useEffect(() => {
    fetch(`/api/elevators/${id}`)
      .then((r) => r.json())
      .then((data) => { setElevator(data); setLoading(false) })
  }, [id])

  if (loading) return <div className="min-h-screen flex items-center justify-center text-slate-400">Loading...</div>
  if (!elevator) return <div className="min-h-screen flex items-center justify-center text-red-500">Elevator not found</div>

  const trendData = elevator.trend.map((val, i) => ({
    day: DAYS[i] ?? `Day ${i + 1}`,
    probability: Math.round(val * 100),
  }))

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-800 mb-2 inline-block">
            ← Back to Dashboard
          </Link>
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-xl font-bold text-slate-900">{elevator.building_name}</h1>
              <p className="text-sm text-slate-500">{elevator.id} · {elevator.model} · {elevator.age_years} years old · {elevator.floor_count} floors</p>
            </div>
            <div className="flex items-center gap-3">
              {elevator.in_model_scope && (
                <RiskBadge level={elevator.risk_level} score={elevator.risk_score} showScore />
              )}
              <ScopeTag inScope={elevator.in_model_scope} />
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {elevator.in_model_scope ? (
          <>
            <section className={`rounded-xl border px-5 py-4 ${
              elevator.risk_level === 'high'
                ? 'bg-red-50 border-red-200'
                : elevator.risk_level === 'medium'
                ? 'bg-orange-50 border-orange-200'
                : 'bg-green-50 border-green-200'
            }`}>
              <p className="text-sm font-semibold text-slate-700 mb-1">Model explanation</p>
              <p className="text-slate-800">{elevator.nl_explanation}</p>
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
                <h2 className="text-sm font-semibold text-slate-700 mb-4">Prediction drivers</h2>
                <FeatureBar features={elevator.features} />
              </div>

              <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
                <h2 className="text-sm font-semibold text-slate-700 mb-1">Failure probability trend</h2>
                <p className="text-xs text-slate-400 mb-4">Last 6 days · 48h horizon</p>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={trendData}>
                    <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} width={36} />
                    <Tooltip formatter={(v) => [`${v}%`, 'Failure probability']} />
                    <ReferenceLine y={80} stroke="#ef4444" strokeDasharray="4 4" label={{ value: '80%', fontSize: 10, fill: '#ef4444' }} />
                    <ReferenceLine y={50} stroke="#f97316" strokeDasharray="4 4" label={{ value: '50%', fontSize: 10, fill: '#f97316' }} />
                    <Line type="monotone" dataKey="probability" stroke="#475569" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        ) : (
          <section className="rounded-xl border border-slate-200 px-5 py-4 bg-slate-50">
            <p className="text-sm font-semibold text-slate-600 mb-1">Outside model scope</p>
            <p className="text-sm text-slate-500">Insufficient sensor data to generate a prediction for this elevator. Refer to last visit notes below.</p>
          </section>
        )}

        {elevator.in_model_scope && id && (
          <VoiceBriefing elevatorId={id} />
        )}

        <div className="bg-white rounded-xl border border-slate-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Last visit</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-slate-400 text-xs">Date</p>
              <p className="font-medium">{new Date(elevator.last_visit_date).toLocaleDateString('en-GB')}</p>
            </div>
            <div>
              <p className="text-slate-400 text-xs">Technician</p>
              <p className="font-medium">{elevator.last_visit_technician}</p>
            </div>
            <div>
              <p className="text-slate-400 text-xs">Avg. trips / hour</p>
              <p className="font-medium">{elevator.hourly_trips_avg}</p>
            </div>
            <div className="col-span-2 md:col-span-3">
              <p className="text-slate-400 text-xs mb-1">Notes</p>
              <p className="text-slate-700">{elevator.last_visit_notes}</p>
            </div>
          </div>
        </div>

        <div className="flex gap-3 flex-wrap">
          {!dispatched ? (
            <button
              onClick={() => setDispatched(true)}
              className="bg-slate-800 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-slate-700 transition-colors"
            >
              Dispatch technician
            </button>
          ) : (
            <div className="bg-green-50 border border-green-200 text-green-800 px-5 py-2.5 rounded-lg text-sm font-medium">
              ✓ Technician dispatched
            </div>
          )}
          <Link
            to={`/elevators/${elevator.id}/report`}
            className="bg-white border border-slate-300 text-slate-700 px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
          >
            Submit post-visit report
          </Link>
        </div>
      </main>
    </div>
  )
}
