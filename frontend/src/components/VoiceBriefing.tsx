import { useState, useRef } from 'react'
import { getBriefing } from '../services/briefingService'
import type { Briefing } from '../types/elevator'

type State = 'idle' | 'loading' | 'ready' | 'speaking'

interface Props {
  elevatorId: string
}

export default function VoiceBriefing({ elevatorId }: Props) {
  const [state, setState] = useState<State>('idle')
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)

  const hasSpeech = typeof window !== 'undefined' && 'speechSynthesis' in window

  async function handleBriefMe() {
    setState('loading')
    setError(null)
    try {
      const data = await getBriefing(elevatorId)
      setBriefing(data)
      setState('ready')
      if (hasSpeech) {
        speak(data.text)
      }
    } catch {
      setError('Could not load briefing. Please try again.')
      setState('idle')
    }
  }

  function speak(text: string) {
    if (!hasSpeech) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utteranceRef.current = utterance
    utterance.onstart = () => setState('speaking')
    utterance.onend = () => setState('ready')
    utterance.onerror = () => setState('ready')
    window.speechSynthesis.speak(utterance)
  }

  function handleStop() {
    if (hasSpeech) window.speechSynthesis.cancel()
    setState('ready')
  }

  function handleReplay() {
    if (briefing) speak(briefing.text)
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 px-5 py-4" data-testid="voice-briefing">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-700">Pre-visit briefing</h2>
        {briefing?.source === 'fallback' && (
          <span
            className="text-xs text-slate-400 border border-slate-200 rounded px-2 py-0.5"
            data-testid="fallback-marker"
          >
            Generated without AI
          </span>
        )}
      </div>

      {state === 'idle' && (
        <button
          onClick={handleBriefMe}
          className="bg-slate-800 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-700 transition-colors"
          data-testid="brief-me-button"
        >
          Brief me
        </button>
      )}

      {state === 'loading' && (
        <p className="text-sm text-slate-400" data-testid="briefing-loading">
          Generating briefing…
        </p>
      )}

      {(state === 'ready' || state === 'speaking') && briefing && (
        <div className="space-y-3">
          <p className="text-sm text-slate-700 leading-relaxed" data-testid="briefing-text">
            {briefing.text}
          </p>
          <div className="flex gap-2">
            {state === 'speaking' ? (
              <button
                onClick={handleStop}
                className="bg-red-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-500 transition-colors"
                data-testid="stop-button"
              >
                Stop
              </button>
            ) : hasSpeech ? (
              <button
                onClick={handleReplay}
                className="bg-slate-100 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-200 transition-colors"
                data-testid="replay-button"
              >
                Replay
              </button>
            ) : null}
          </div>
        </div>
      )}

      {error && (
        <p className="text-sm text-red-500" data-testid="briefing-error">
          {error}
        </p>
      )}
    </div>
  )
}
