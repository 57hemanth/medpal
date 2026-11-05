/** Response shapes of the MedPal API, as the product uses them. */

export interface Appointment {
  appt_id: string;
  patient_id: string;
  patient_name: string | null;
  status: 'booked' | 'cancelled' | 'attended' | 'no_show';
  source: string;
  starts_at: string;
  doctor_name: string;
  specialty: string;
  clinic_name: string;
  city: string;
}

export interface HealthRecord {
  doc_id: string;
  patient_id: string;
  type: string;
  uploaded_at: string;
  phi_status: string;
  status: string | null;
  error: string | null;
}

export interface Consent {
  consent_id: string;
  patient_id: string;
  grantee_user_id: string;
  scope: string[];
  purpose: string;
  expires_at: string;
  revoked_at: string | null;
  patient_name: string | null;
  grantee_name: string | null;
}

export interface Handoff {
  ticket_id: string;
  kind: 'emergency' | 'front_desk' | 'records' | 'review';
  status: 'open' | 'in_progress' | 'closed';
  patient_id: string | null;
  patient_name: string | null;
  reason: string;
  thread_id: string | null;
  created_at: string;
}

export interface Consultation {
  appt_id: string;
  starts_at: string;
  clinic_name: string;
  patient_name: string | null;
  encounter_id: string | null;
  signed: boolean;
}

export interface WorkflowMetric {
  workflow: string;
  runs: number;
  p50_ms: number | null;
  p95_ms: number | null;
  error_rate: number | null;
}

export interface ModelMetric {
  workflow: string;
  model: string;
  calls: number;
  error_rate: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_estimated: boolean;
  cost: string | number | null;
  unpriced_calls: number;
  price_list_date: string | null;
  p95_ms: number | null;
}

export interface Metrics {
  window_hours: number;
  runs: WorkflowMetric[];
  slowest_nodes: {
    workflow: string;
    name: string;
    calls: number;
    p95_ms: number;
  }[];
  models: ModelMetric[];
  cost_per_run: Record<string, number | null>;
  cost_formula: string;
}

export interface AuditEvent {
  event_id: number;
  at: string;
  actor_id: string;
  actor_role: string;
  action: string;
  resource: string;
  record_id: string;
  patient_id: string | null;
  patient_name: string | null;
  purpose: string;
  trace_id: string | null;
}
