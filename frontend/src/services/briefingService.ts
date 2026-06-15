import type { Briefing } from '../types/elevator'

export async function getBriefing(id: string): Promise<Briefing> {
  const response = await fetch(`/api/elevators/${id}/briefing`)
  if (!response.ok) {
    throw new Error(`Failed to fetch briefing: ${response.status}`)
  }
  return response.json() as Promise<Briefing>
}
