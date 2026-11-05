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

export interface StockRow {
  medicine_id: string;
  name: string;
  composition: string;
  therapeutic_class: string | null;
  pack_size: string | null;
  qty: number | null;
  as_of: string | null;
  reserved: number;
  available: number;
  demand: number;
  unmet: number;
  status: 'in_stock' | 'low' | 'out_of_stock' | 'stale';
}

export interface QueueItem {
  reservation_id: string;
  status: 'reserved' | 'dispensed' | 'released';
  reserved_at: string;
  closed_at: string | null;
  patient_name: string | null;
  medicine_text: string;
  medicine: string;
  pack_size: string | null;
  doctor_name: string | null;
}

export interface Medicine {
  medicine_id: string;
  name: string;
  composition: string;
  manufacturer: string | null;
  pack_size: string | null;
  price_inr: string | number | null;
  therapeutic_class: string | null;
  source: string;
  clinics_available: number;
  clinics_total: number;
}

export interface Prescription {
  rx_id: string;
  medicine_text: string;
  medicine: string | null;
  composition: string | null;
  pack_size: string | null;
  signed_at: string;
  doctor_name: string | null;
  patient_name: string | null;
  reservation_status: 'reserved' | 'dispensed' | 'released' | null;
  clinic_name: string | null;
  rx_status: 'active' | 'stopped';
  stop_reason: string | null;
  stopped_at: string | null;
  replaces: string | null;
}

export interface SignedNote {
  note_id: string;
  version: number;
  signed_at: string;
  soap_json: {
    subjective: string;
    objective: string;
    assessment: string;
    plan: string;
    medicines?: string[];
  };
  edit_history: {
    action: string;
    at?: string;
    fields?: string[];
    reason?: string;
    version?: number;
  }[];
  earlier_versions: {
    version: number;
    signed_at: string;
    soap_json: SignedNote['soap_json'];
  }[];
  mine: boolean | null;
  content_hash: string;
  patient_id: string;
  patient_name: string | null;
  doctor_name: string | null;
  clinic_name: string | null;
  transcript: string | null;
  prescriptions: {
    rx_id: string;
    medicine: string;
    status: string | null;
    clinic: string | null;
    rx_status: 'active' | 'stopped';
    stop_reason: string | null;
    stopped_at: string | null;
    replaces: string | null;
  }[];
}

export interface PatientNotification {
  notification_id: string;
  kind: string;
  body: string;
  created_at: string;
  read_at: string | null;
}

export interface Quality {
  evaluation:
    | (Record<string, unknown> & {
        file: string;
        gates?: Record<string, boolean>;
      })
    | null;
  live: {
    file: string;
    run_at: string;
    passed: number;
    total: number;
    areas: Record<string, { passed: number; total: number }>;
    summary: string[];
  } | null;
}

export interface ContactSettings {
  email: string | null;
  email_verified: boolean;
  email_notifications: boolean;
}

export interface OutboxMessage {
  notification_id: string;
  kind:
    | 'appointment_booked'
    | 'appointment_cancelled'
    | 'appointment_reminder_24h'
    | 'appointment_reminder_2h';
  channel: 'email';
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'cancelled' | 'skipped';
  send_after: string;
  sent_at: string | null;
  recipient: string | null;
  subject: string | null;
  detail: string | null;
  attempts: number;
  created_at: string;
  starts_at: string | null;
  patient_name: string | null;
  doctor_name: string | null;
  on_hold: string | null;
}

export interface StockAdjustment {
  adjustment_id: string;
  medicine_id: string;
  medicine: string;
  kind: 'count' | 'delivery' | 'write_off';
  qty_before: number;
  qty_after: number;
  reason: string;
  made_at: string;
}
