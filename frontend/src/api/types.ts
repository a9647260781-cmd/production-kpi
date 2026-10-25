export type Id = string;
export type DecimalString = string;

export interface ApiFieldError {
  field: string;
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    field_errors?: ApiFieldError[];
    trace_id?: string;
  };
  submission?: SubmissionAcknowledgement;
}

export interface SubmissionAcknowledgement {
  event_id?: Id;
  inspection_id?: Id;
  status: "REJECTED_TERMINAL" | "UNRESOLVED";
  code?: string;
  message?: string;
  accepted: false;
  terminal: boolean;
  retryable: boolean;
  next_steps: string[];
}

export interface ListResponse<T> {
  items: T[];
  total: number;
  next_cursor?: string | null;
}

export interface User {
  id: Id;
  username: string;
  display_name: string;
  employee_id?: Id | null;
  roles: Array<{ name: string; row_id: Id | null }>;
  scopes: { row_ids: Id[] };
  capabilities: string[];
  csrf_token: string;
}

export interface AuthResponse {
  user: User;
}

export type ShiftApprovalStatus = "DRAFT" | "REVIEW" | "APPROVED" | "REOPENED" | "CLOSED";
export type MaturityState = "INCOMPLETE_DATA" | "PROVISIONAL" | "AWAITING_AUDIT" | "FINAL";

export interface Shift {
  id: Id;
  code: string;
  production_date: string;
  starts_at?: string;
  ends_at?: string;
  status: string;
  approval_status: ShiftApprovalStatus;
  maturity_state: MaturityState;
  demo_business_date?: boolean;
}

export type RowKind = "ASSEMBLY" | "SOLDER" | "QC";

export interface ProductionRow {
  id: Id;
  code: string;
  name: string;
  category: RowKind;
  sort_order: number;
  accepted_operations?: number;
  metrics?: RowMetric;
}

export interface Workstation {
  id: Id;
  code: string;
  name: string;
  row_id: Id;
}

export interface RouteStep {
  id: Id;
  code: string;
  name: string;
  entity_type: string;
  row_id: Id | null;
  sequence: number;
  allows_rework: boolean;
}

export type SampleQr = string;

export interface WorkSession {
  id: Id;
  shift_id: Id;
  row_id: Id;
  workstation_id: Id;
  route_step_id: Id;
  user_id?: Id;
  employee_id?: Id;
  started_at: string;
  ended_at?: string | null;
}

export interface Employee {
  id: Id;
  display_name: string;
  personnel_no: string;
  status: string;
}

export interface Bootstrap {
  active_shift: Shift | null;
  rows: ProductionRow[];
  workstations: Workstation[];
  route_steps: RouteStep[];
  capabilities: string[];
  scopes: { row_ids: Id[] };
  sample_qr: SampleQr[];
  employees?: Employee[];
  version: string;
  updated_at: string;
}

export interface Dashboard {
  shift: { id: Id; code: string };
  rows: ProductionRow[];
  calculation: Calculation;
  row_metrics: RowMetric[];
  synthetic: true;
}

export interface RowMetric {
  row_id: Id;
  row_code: string;
  category: RowKind;
  a_plan: DecimalString | null;
  a_volume: DecimalString | null;
  p: DecimalString | null;
  h_accounted_hours: DecimalString | null;
  q: DecimalString | null;
  kpi_raw: DecimalString | null;
  kpi_official: DecimalString | null;
  reason_flags: string[];
  inputs: Record<string, string | number | boolean | null>;
  trace: Record<string, string | number | boolean | null>;
}

export interface RouteAllowedRow {
  id: Id;
  code: string;
  name: string;
  category: RowKind;
}

export interface RouteVersionStep {
  id: Id;
  code: string;
  name: string;
  sequence: number;
  entity_type: "COMPONENT" | "WIP";
  allowed_rows: RouteAllowedRow[];
  row_scope: "EXACT_ROW" | "ASSEMBLY_CATEGORY" | "UNSCOPED";
  allows_rework: boolean;
}

export interface RouteVersion {
  id: Id;
  model: { id: Id; code: string; name: string } | null;
  version: number;
  status: "DRAFT" | "APPROVED";
  immutable: boolean;
  steps: RouteVersionStep[];
}

export interface ConfiguredEntity {
  id: Id;
  qr_code: string;
  entity_type: "COMPONENT" | "WIP";
  model_id: Id;
  route_version_id: Id;
  status: string;
  final_serial?: string | null;
}

export interface OperationEventBody {
  event_id: Id;
  work_session_id: Id;
  subject_qr: string;
  event_type: "COMPLETE";
  attempt_type: "PRIMARY" | "REWORK";
  occurred_at_device?: string;
}

export interface QcInspectionBody {
  inspection_id: Id;
  work_session_id: Id;
  subject_qr: string;
  decision: "ACCEPT" | "REJECT";
  defect_code: string | null;
  occurred_at_device?: string;
}

export interface QcInspectionRecord {
  event_id: Id;
  decision_id: Id;
  subject_qr: string;
  decision: "ACCEPT" | "REJECT";
  defect_code: string | null;
  defect_label: string | null;
  attempt_type: "PRIMARY" | "REWORK";
  mode: "FIRST_PASS" | "REINSPECTION";
  row: { id: Id; code: string; name: string } | null;
  route_step: { id: Id; code: string; name: string } | null;
  created_at: string;
  corrected?: boolean;
  display_status?: "ACCEPTED" | "CORRECTED";
}

export interface QcInspectionResult {
  inspection_id: Id;
  status: "ACCEPTED" | "NOT_FOUND" | "REJECTED_TERMINAL" | "UNRESOLVED";
  accepted: boolean;
  terminal: boolean;
  retryable: boolean;
  duplicate: boolean;
  server_received_at?: string | null;
  message?: string;
  next_steps?: string[];
  inspection: QcInspectionRecord | null;
}

export interface QcRecentInspection extends QcInspectionRecord {
  inspection_id: Id;
  server_received_at: string;
}

export interface QcShiftActivity {
  shift: { id: Id; code: string; production_date: string } | null;
  context: {
    work_session_id: Id;
    row: { id: Id; code: string; name: string } | null;
    route_step: { id: Id; code: string; name: string } | null;
  } | null;
  checked_count: number;
  accepted_count: number;
  rejected_count: number;
  first_pass_count: number;
  reinspection_count: number;
  recent_inspections: QcRecentInspection[];
  note: string;
}

export interface QcDefectReason {
  code: string;
  label: string;
}

export interface QcDefectReasonCatalog {
  items: QcDefectReason[];
  synthetic: true;
}

export interface ForemanRosterItem {
  assignment_id: Id;
  employee: { id: Id; display_name: string; personnel_no: string; status: string } | null;
  workstation: { id: Id; name: string } | null;
  route_step: { id: Id; name: string } | null;
  assignment_status: string;
  starts_at: string;
  ends_at: string | null;
}

export interface ForemanProblem {
  id: Id;
  kind: "NEEDS_REVIEW" | "SCAN_REJECTED";
  code: string;
  qr: string | null;
  operation: { id: Id; name: string } | null;
  worker: { id: Id; display_name: string } | null;
  occurred_at: string;
  status: string;
  message: string;
  allowed_actions: never[];
}

export interface ForemanRework {
  id: Id;
  qr: string | null;
  reason: string;
  requested_route_step: { id: Id; name: string } | null;
  status: string;
  created_at: string;
  allowed_actions: never[];
}

export interface ForemanShiftSummary {
  shift: { id: Id; code: string };
  row: { id: Id; code: string; name: string; category: RowKind };
  roster: ForemanRosterItem[];
  primary_completed: number;
  rework_completed: number;
  problems: ForemanProblem[];
  reworks: ForemanRework[];
  note: string;
}

export type OperationEventStatus = "ACCEPTED" | "NEEDS_REVIEW" | "CANCELLED" | "PENDING" | "REJECTED_TERMINAL" | "UNRESOLVED";

export interface OperationEventResult {
  id?: Id;
  status: OperationEventStatus | "NOT_FOUND";
  code: string;
  server_received_at?: string | null;
  review_id?: Id | null;
  retryable: boolean;
  duplicate?: boolean;
  accepted?: boolean;
  terminal?: boolean;
  event?: OperationEvent | null;
  entity?: TrackedEntity | null;
  next_steps: string[];
  message?: string;
  original_worker?: Pick<User, "id" | "username" | "display_name"> | null;
  context?: Record<string, string | null>;
}

export interface OperationEvent {
  id: Id;
  event_id: Id;
  subject_qr: string;
  event_type: string;
  attempt_type: string;
  operation_name: string;
  row_name: string;
  workstation_name: string;
  worker_name: string;
  received_at_server: string;
  outcome: string;
  status: string;
}

export interface WorkerShiftActivityEvent {
  id: Id;
  event_id: Id;
  subject_qr: string;
  attempt_type: "PRIMARY" | "REWORK";
  status: string;
  display_status: string;
  corrected: boolean;
  server_received_at: string;
  row: { id: Id; name: string } | null;
  route_step: { id: Id; name: string } | null;
}

export interface WorkerShiftActivity {
  shift: { id: Id; code: string } | null;
  context: {
    work_session_id: Id;
    row: { id: Id; name: string };
    route_step: { id: Id; name: string };
  } | null;
  primary_completed: number;
  rework_completed: number;
  corrected_primary: number;
  recent_events: WorkerShiftActivityEvent[];
}

export interface TrackedEntity {
  id: Id;
  qr_code: string;
  entity_type: "COMPONENT" | "WIP" | "FINAL";
  status: string;
  final_serial?: string | null;
}

export interface TimelineItem {
  id: Id;
  kind: "route" | "genealogy" | "quality";
  at: string;
  status?: string;
  code?: string;
  action?: string;
  decision?: string;
  defect_code?: string | null;
}

export interface EntityTimeline {
  entity: TrackedEntity;
  items: TimelineItem[];
  total: number;
  next_cursor?: string | null;
}

export interface Assignment {
  id: Id;
  shift_id: Id;
  employee_id: Id;
  row_id: Id;
  workstation_id: Id;
  route_step_id: Id;
  starts_at: string;
  ends_at?: string | null;
  status: string;
}

export type TimeCategory = "PRIMARY" | "REWORK" | "WAITING" | "SETUP" | "SUPPORT" | "UNAVAILABLE";

export interface TimeEntry {
  id: Id;
  assignment_id: Id;
  category: TimeCategory;
  hours: DecimalString;
  source: string;
  approval_status: string;
  version: number;
}

export interface QualityDecision {
  id: Id;
  request_id: Id;
  entity_id: Id;
  shift_id: Id;
  operation_event_id: Id;
  inspector_user_id: Id;
  decision: "ACCEPT" | "REJECT";
  defect_code?: string | null;
  note?: string | null;
  created_at: string;
}

export interface QualityAudit {
  id: Id;
  request_id: Id;
  decision_id: Id;
  result: "CONFIRMED" | "OVERTURNED";
  auditor_user_id: Id;
  created_at: string;
  note?: string | null;
}

export interface ReworkOrder {
  id: Id;
  entity_id: Id;
  quality_decision_id: Id;
  reason: string;
  requested_route_step_id: Id;
  status: "OPEN" | "READY_FOR_QC" | "REINSPECTED" | "CANCELLED";
  created_at: string;
}

export interface PlanLine {
  id: Id;
  key: string;
  model_id: Id;
  route_step_id: Id;
  row_id?: Id | null;
  planned_qty: number;
  norm_minutes: DecimalString | null;
}

export interface ProductionPlan {
  id: Id;
  shift_id: Id;
  version: number;
  status: "DRAFT" | "APPROVED";
  approved_at?: string | null;
  lines: PlanLine[];
}

export interface StandardValue {
  route_step_id: Id;
  norm_minutes: DecimalString;
}

export interface StandardSet {
  id: Id;
  model_id: Id;
  version: number;
  status: "DRAFT" | "APPROVED";
  effective_from: string;
  effective_to?: string | null;
  values: StandardValue[];
}

export interface Calculation {
  shift_id: Id;
  approval_status: ShiftApprovalStatus;
  maturity_state: MaturityState;
  reason_flags: string[];
  a_plan: DecimalString | null;
  a_volume: DecimalString | null;
  p: DecimalString | null;
  q: DecimalString | null;
  kpi_raw: DecimalString | null;
  kpi_official: DecimalString | null;
  inputs: Record<string, string | number | boolean | null>;
  trace: Record<string, string | number | boolean | null>;
  production: Record<string, unknown>;
  otk: Record<string, unknown>;
  version: number;
  calculated_at: string;
}

export interface ReportRow {
  id: Id;
  label: string;
  scope: string;
  a_plan: string | null;
  a_volume: string | null;
  p: string | null;
  q: string | null;
  kpi_official: string | null;
  status: string;
}

export interface Report {
  shift_id: Id;
  snapshot_id?: Id | null;
  frozen: boolean;
  calculation: Calculation;
  synthetic: boolean;
}

export interface AuditEvent {
  id: Id;
  created_at: string;
  actor_user_id: Id;
  action: string;
  object_type: string;
  object_id: Id;
  reason?: string | null;
  trace_id?: string | null;
}

