import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'

const COMMON_COMPONENTS = [
  'Door seal', 'Motor brushes', 'Drive belt', 'Safety gear',
  'Buffer', 'Guide shoes', 'Rope', 'Control board', 'Door operator',
]

const COMMON_PARAMETERS = [
  'Door open/close timing', 'Motor current calibration', 'Vibration dampers adjusted',
  'Speed governor tested', 'Landing level adjusted', 'Lubrication applied',
]

export default function PostVisitReport() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    technician_name: '',
    visit_date: new Date().toISOString().split('T')[0],
    failure_found: false,
    components_replaced: [] as string[],
    parameters_corrected: [] as string[],
    notes: '',
  })
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)

  const toggle = (field: 'components_replaced' | 'parameters_corrected', value: string) => {
    setForm((f) => ({
      ...f,
      [field]: f[field].includes(value)
        ? f[field].filter((v) => v !== value)
        : [...f[field], value],
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    await fetch(`/api/elevators/${id}/report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setLoading(false)
    setSubmitted(true)
    setTimeout(() => navigate(`/elevators/${id}`), 2000)
  }

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="bg-white rounded-xl border border-green-200 px-8 py-10 text-center max-w-md">
          <p className="text-4xl mb-4">✓</p>
          <h2 className="text-lg font-bold text-slate-800 mb-2">Report submitted</h2>
          <p className="text-sm text-slate-500">Data queued for model retraining. Redirecting...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="max-w-2xl mx-auto">
          <Link to={`/elevators/${id}`} className="text-sm text-slate-500 hover:text-slate-800 mb-2 inline-block">
            ← Back to elevator
          </Link>
          <h1 className="text-xl font-bold text-slate-900">Post-visit report</h1>
          <p className="text-sm text-slate-500">{id}</p>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-6">
        <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-slate-200 px-6 py-6 space-y-6">

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Technician name</label>
              <input
                required
                type="text"
                value={form.technician_name}
                onChange={(e) => setForm((f) => ({ ...f, technician_name: e.target.value }))}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
                placeholder="Full name"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Visit date</label>
              <input
                type="date"
                value={form.visit_date}
                onChange={(e) => setForm((f) => ({ ...f, visit_date: e.target.value }))}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Failure found?</label>
            <div className="flex gap-3">
              {[true, false].map((v) => (
                <button
                  key={String(v)}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, failure_found: v }))}
                  className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    form.failure_found === v
                      ? v ? 'bg-red-100 border-red-400 text-red-800' : 'bg-green-100 border-green-400 text-green-800'
                      : 'bg-white border-slate-300 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {v ? 'Yes — failure confirmed' : 'No — preventive visit'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Components replaced</label>
            <div className="flex flex-wrap gap-2">
              {COMMON_COMPONENTS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggle('components_replaced', c)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                    form.components_replaced.includes(c)
                      ? 'bg-slate-700 text-white border-slate-700'
                      : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">Parameters corrected</label>
            <div className="flex flex-wrap gap-2">
              {COMMON_PARAMETERS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => toggle('parameters_corrected', p)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                    form.parameters_corrected.includes(p)
                      ? 'bg-slate-700 text-white border-slate-700'
                      : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Notes</label>
            <textarea
              rows={4}
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              placeholder="Describe findings, observations, or any follow-up recommended..."
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 resize-none"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-slate-800 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {loading ? 'Submitting...' : 'Submit report'}
          </button>
        </form>
      </main>
    </div>
  )
}
