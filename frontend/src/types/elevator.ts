export type RiskLevel = 'high' | 'medium' | 'low'

export interface Feature {
  name: string
  impact: number
  value: string
}

export interface ElevatorSummary {
  id: string
  building_name: string
  building_type: string
  floor_count: number
  model: string
  age_years: number
  risk_score: number
  risk_level: RiskLevel
  last_visit_date: string
  last_visit_technician: string
  in_model_scope: boolean
  zone: string
}

export interface ElevatorDetail extends ElevatorSummary {
  brand: string
  trend: number[]
  last_visit_notes: string
  nl_explanation: string
  features: Feature[]
  hourly_trips_avg: number
}

export interface PostVisitReport {
  technician_name: string
  visit_date: string
  failure_found: boolean
  components_replaced: string[]
  parameters_corrected: string[]
  notes: string
}
