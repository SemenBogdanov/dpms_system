/**
 * Типы, зеркало backend schemas.
 */

export type League = 'C' | 'B' | 'A'
export type UserRole = 'executor' | 'teamlead' | 'admin'
export type CatalogCategory = 'widget' | 'etl' | 'api' | 'docs' | 'proactive'
export type Complexity = 'S' | 'M' | 'L' | 'XL'
export type TaskType = 'widget' | 'etl' | 'api' | 'docs' | 'proactive' | 'bugfix'
export type TaskStatus =
  | 'new'
  | 'estimated'
  | 'in_queue'
  | 'in_progress'
  | 'review'
  | 'done'
  | 'cancelled'
export type TaskPriority = 'low' | 'medium' | 'high' | 'critical'
export type KnowledgeStatus = 'draft' | 'published'
export type AbsenceType = 'vacation' | 'sick_leave' | 'day_off' | 'other'
export type FeedbackCategory = 'improvement' | 'disagreement' | 'bug' | 'process' | 'other'
export type FeedbackStatus = 'new' | 'in_review' | 'triage' | 'needs_info' | 'accepted' | 'planned' | 'rejected' | 'done' | 'withdrawn'
export type FeedbackPriority = 'low' | 'medium' | 'high'
export type FeedbackObjectType = 'task' | 'shop' | 'report' | 'rule' | 'kb' | 'other'
export type QuickNoteStatus = 'draft' | 'processed' | 'archived'
export type ContactStatus = 'pending' | 'accepted' | 'rejected'
export type QuickNoteShareStatus = 'active' | 'revoked'
export type PersonalTaskStatus = 'inbox' | 'planned' | 'next' | 'in_progress' | 'waiting' | 'blocked' | 'done' | 'archived'
export type PersonalTaskPriority = 'low' | 'medium' | 'high' | 'critical'
export type PersonalTaskCategory = 'work' | 'meeting' | 'follow_up' | 'research' | 'decision' | 'admin' | 'other'
export type PersonalTaskEventType =
  | 'task_created'
  | 'task_updated'
  | 'status_changed'
  | 'meeting'
  | 'follow_up'
  | 'note'
  | 'checkpoint_created'
  | 'checkpoint_updated'
  | 'checkpoint_done'
  | 'promoted'
export type PersonalTaskCheckpointStatus = 'planned' | 'in_progress' | 'waiting' | 'blocked' | 'done'
export type DeadlineTrackerType = 'subscription' | 'system' | 'password' | 'task' | 'document' | 'payment' | 'other'
export type DeadlineTrackerStatus = 'active' | 'paused' | 'done' | 'archived'
export type WorkTrackReservationStatus = 'draft' | 'sent' | 'reserved' | 'declined' | 'released'

export interface SidebarMenuOrder {
  groups?: Array<string | { id?: string; key?: string; label?: string; item_ids?: string[]; itemIds?: string[] }>
  items?: Record<string, string[]>
  item_labels?: Record<string, string>
  itemLabels?: Record<string, string>
}

export interface User {
  id: string
  full_name: string
  email: string
  league: League
  role: UserRole
  mpw: number
  wip_limit: number
  wallet_main: number
  wallet_karma: number
  quality_score: number
  is_active: boolean
  needs_password_change: boolean
  is_new_employee: boolean
  task_workspace_enabled: boolean
  feedback_enabled: boolean
  audit_enabled: boolean
  competency_development_enabled: boolean
  competency_constructor_enabled: boolean
  plan_started_at: string | null
  onboarding_started_at: string | null
  onboarding_until: string | null
  sidebar_menu_order: SidebarMenuOrder | null
  created_at: string
  updated_at: string
}

export type AuditCaseStatus = 'draft' | 'atomization' | 'ready' | 'archived'
export type AuditWorkflowStage =
  | 'unassigned'
  | 'atomization'
  | 'alpha_review'
  | 'commission_pending'
  | 'fixes_required'
  | 'fixing'
  | 'recommission_pending'
  | 'ready'
export type AuditAtomState = 'draft' | 'ready' | 'excluded'
export type AuditTeamRole = 'leader' | 'member'
export type AuditDocumentKind = 'technical_spec' | 'atom_register' | 'audit_result' | 'protocol' | 'other'

export interface AuditAtom {
  id: string
  case_id: string
  item_code: string
  title: string
  digital_product: string
  work_type: string | null
  object_type: string | null
  source_clause: string | null
  system_url: string | null
  notes: string | null
  state: AuditAtomState
  source_sheet: string | null
  source_row: number | null
  source_fingerprint: string | null
  import_batch_id: string | null
  alpha_result: string | null
  alpha_result_raw: string | null
  alpha_date: string | null
  commission_result: string | null
  commission_result_raw: string | null
  commission_date: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface AuditCaseSummary {
  id: string
  case_number: string
  code: string
  created_by_id: string | null
  responsible_user_id: string | null
  responsible_name: string | null
  responsible_email: string | null
  title: string
  digital_product: string
  contract_reference_mask: string | null
  contract_date: string | null
  status: AuditCaseStatus
  workflow_stage: AuditWorkflowStage
  notes: string | null
  atoms_count: number
  ready_atoms_count: number
  draft_atoms_count: number
  excluded_atoms_count: number
  alpha_passed_count: number
  commission_passed_count: number
  documents_count: number
  created_at: string
  updated_at: string
}

export interface AuditCaseDetail extends AuditCaseSummary {
  atoms: AuditAtom[]
}

export interface AuditEvent {
  id: string
  case_id: string
  atom_id: string | null
  import_batch_id: string | null
  actor_id: string | null
  actor_name: string | null
  event_type: string
  message: string
  payload_json: Record<string, unknown> | null
  created_at: string
}

export interface AuditCaseCreate {
  title: string
  digital_product: string
  contract_reference?: string | null
  contract_date?: string | null
  status?: AuditCaseStatus
  workflow_stage?: AuditWorkflowStage
  notes?: string | null
}

export type AuditCaseUpdate = Partial<AuditCaseCreate>

export interface AuditAtomCreate {
  item_code?: string | null
  title: string
  digital_product: string
  work_type?: string | null
  object_type?: string | null
  source_clause?: string | null
  system_url?: string | null
  notes?: string | null
  state?: AuditAtomState
  alpha_result_raw?: string | null
  commission_result_raw?: string | null
}

export type AuditAtomUpdate = Partial<AuditAtomCreate>

export interface AuditImportIssue {
  row_number: number
  field: string
  message: string
  severity: 'error' | 'warning'
}

export interface AuditImportPreviewRow {
  group_id: string
  row_number: number
  item_code: string
  contract_reference_mask: string | null
  contract_date: string | null
  title: string | null
  digital_product: string | null
  work_type: string | null
  object_type: string | null
  source_clause: string | null
  system_url_mask: string | null
  state: AuditAtomState
  source_sheet: string | null
  source_row: number | null
  alpha_result: string | null
  alpha_result_raw: string | null
  alpha_date: string | null
  commission_result: string | null
  commission_result_raw: string | null
  commission_date: string | null
  issues: AuditImportIssue[]
}

export interface AuditImportPreviewGroup {
  group_id: string
  contract_reference_mask: string
  total_rows: number
  valid_rows: number
  error_rows: number
  warning_rows: number
  digital_products: string[]
}

export interface AuditImportPreview {
  sha256: string
  source_sheet: string
  total_rows: number
  valid_rows: number
  error_rows: number
  warning_rows: number
  has_errors: boolean
  grouped_counts: AuditImportPreviewGroup[]
  rows: AuditImportPreviewRow[]
}

export interface AuditTeamMember {
  id: string
  user_id: string
  full_name: string
  email: string
  role: AuditTeamRole
  is_active: boolean
  audit_enabled: boolean
  added_by_id: string | null
  created_at: string
}

export interface AuditTeamCandidate {
  user_id: string
  full_name: string
  email: string
  is_active: boolean
  audit_enabled: boolean
}

export interface AuditDocument {
  id: string
  case_id: string
  uploaded_by_id: string | null
  uploaded_by_name: string | null
  kind: AuditDocumentKind
  display_name: string
  content_type: string
  size_bytes: number
  sha256: string
  created_at: string
}

export interface AuditDocumentUploadItem {
  case: AuditCaseDetail
  document: AuditDocument
}

export interface AuditDocumentBatchResponse {
  items: AuditDocumentUploadItem[]
}

export interface AuditAtomizationSkillVersion {
  id: string
  skill_id: string
  slug: string
  name: string
  description: string | null
  version: string
  schema_version: string
  content_sha256: string
  source_filename: string
  is_enabled: boolean
  is_active: boolean
  created_at: string
  activated_at: string | null
}

export interface AuditAtomizationSkillList {
  items: AuditAtomizationSkillVersion[]
}

export interface AuditAssignment {
  id: string
  case_id: string
  case_number: string
  case_title: string
  digital_product: string
  case_status: AuditCaseStatus
  workflow_stage: AuditWorkflowStage
  atoms_count: number
  assignee_id: string
  assignee_name: string
  scheduled_date: string
  assigned_by_id: string | null
  created_at: string
  updated_at: string
}

export interface AuditAssignmentList {
  date_from: string
  date_to: string
  items: AuditAssignment[]
}

export interface AuditAISourceRef {
  source_unit_id: string
  locator: string
  excerpt: string
}

export interface AuditAIAtomDraft {
  id: string
  title: string
  digital_product: string
  work_type: string | null
  object_type: string | null
  source_clause: string
  notes: string | null
  confidence_percent: number | null
  review_status: 'pending' | 'accepted' | 'rejected' | 'committed'
  sort_order: number
  source_refs: AuditAISourceRef[]
}

export interface AuditAIAtomizationAttempt {
  id: string
  case_id: string
  document_id: string
  skill_version_id: string
  skill_name: string
  skill_version: string
  status: 'running' | 'draft_ready' | 'failed' | 'committed'
  config_version: number
  model_name: string
  document_sha256: string
  skill_sha256: string
  coverage_summary: Record<string, number>
  warnings: string[]
  error_code: string | null
  drafts: AuditAIAtomDraft[]
  created_at: string
  committed_at: string | null
}

export interface AuditAIAtomizationCommitResult {
  attempt_id: string
  case_id: string
  atoms_created: number
  atom_ids: string[]
  already_committed: boolean
}

export interface QuickNote {
  id: string
  owner_id: string
  title: string
  body: string
  context: string | null
  status: QuickNoteStatus
  tags: string[]
  created_at: string
  updated_at: string
}

export interface QuickNoteCreate {
  title?: string | null
  body: string
  context?: string | null
  tags: string[]
}

export interface QuickNoteUpdate {
  title?: string | null
  body?: string
  context?: string | null
  status?: QuickNoteStatus
  tags?: string[]
}

export interface Contact {
  id: string
  requester_id: string
  recipient_id: string
  requester_name: string
  requester_email: string
  recipient_name: string
  recipient_email: string
  status: ContactStatus
  direction: 'incoming' | 'outgoing'
  created_at: string
  updated_at: string
}

export interface QuickNoteShare {
  id: string
  note_id: string
  owner_id: string
  owner_name: string
  owner_email: string
  recipient_id: string
  recipient_name: string
  recipient_email: string
  status: QuickNoteShareStatus
  created_at: string
  updated_at: string
}

export interface SharedQuickNote {
  share: QuickNoteShare
  note: QuickNote
}

export interface QuickNoteAttachment {
  id: string
  note_id: string
  original_filename: string
  content_type: string
  size_bytes: number
  uploaded_by_id: string
  created_at: string
}

export interface QuickNoteComment {
  id: string
  note_id: string
  author_id: string
  author_name: string
  author_email: string
  parent_id: string | null
  body: string
  created_at: string
}

export interface PersonalTask {
  id: string
  task_number: number
  task_key: string
  owner_id: string
  title: string
  description: string | null
  notes: string | null
  status: PersonalTaskStatus
  priority: PersonalTaskPriority
  category: PersonalTaskCategory
  project: string | null
  context: string | null
  responsible: string | null
  tags: string[]
  acceptance_criteria: string | null
  next_step: string | null
  next_step_at: string | null
  start_at: string
  due_at: string | null
  waiting_for: string | null
  blocked_reason: string | null
  impact: number | null
  effort: number | null
  linked_task_id: string | null
  source_quick_note_id: string | null
  promoted_task_id: string | null
  promoted_at: string | null
  created_at: string
  updated_at: string
}

export interface PersonalTaskCreate {
  title: string
  description?: string | null
  notes?: string | null
  status?: PersonalTaskStatus
  priority?: PersonalTaskPriority
  category?: PersonalTaskCategory
  project?: string | null
  context?: string | null
  responsible?: string | null
  tags?: string[]
  acceptance_criteria?: string | null
  next_step?: string | null
  next_step_at?: string | null
  start_at?: string | null
  due_at?: string | null
  waiting_for?: string | null
  blocked_reason?: string | null
  impact?: number | null
  effort?: number | null
  linked_task_id?: string | null
  source_quick_note_id?: string | null
}

export interface PersonalTaskUpdate {
  title?: string
  description?: string | null
  notes?: string | null
  status?: PersonalTaskStatus
  priority?: PersonalTaskPriority
  category?: PersonalTaskCategory
  project?: string | null
  context?: string | null
  responsible?: string | null
  tags?: string[]
  acceptance_criteria?: string | null
  next_step?: string | null
  next_step_at?: string | null
  start_at?: string | null
  due_at?: string | null
  waiting_for?: string | null
  blocked_reason?: string | null
  impact?: number | null
  effort?: number | null
  linked_task_id?: string | null
  source_quick_note_id?: string | null
}

export interface PersonalTaskPromoteRequest {
  task_type: TaskType
  complexity: Complexity
  estimated_q: number
  priority: TaskPriority
  min_league: League
  due_date?: string | null
  tags?: string[] | null
}

export interface PersonalTaskEvent {
  id: string
  task_id: string
  actor_id: string | null
  event_type: PersonalTaskEventType
  title: string | null
  body: string | null
  from_status: string | null
  to_status: string | null
  next_step: string | null
  waiting_for: string | null
  due_at: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export interface PersonalTaskEventCreate {
  event_type: PersonalTaskEventType
  title?: string | null
  body?: string | null
  next_step?: string | null
  waiting_for?: string | null
  due_at?: string | null
  metadata_json?: Record<string, unknown> | null
}

export interface PersonalTaskCheckpoint {
  id: string
  task_id: string
  title: string
  status: PersonalTaskCheckpointStatus
  next_step: string | null
  waiting_for: string | null
  notes: string | null
  due_at: string | null
  completed_at: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface PersonalTaskCheckpointCreate {
  title: string
  status?: PersonalTaskCheckpointStatus
  next_step?: string | null
  waiting_for?: string | null
  notes?: string | null
  due_at?: string | null
  sort_order?: number
}

export interface PersonalTaskCheckpointUpdate {
  title?: string
  status?: PersonalTaskCheckpointStatus
  next_step?: string | null
  waiting_for?: string | null
  notes?: string | null
  due_at?: string | null
  sort_order?: number
}

export interface PersonalTaskDeadline {
  item_type: 'task' | 'checkpoint'
  item_id: string
  task_id: string
  task_key: string
  task_title: string
  title: string
  status: string
  due_at: string
  start_at: string
  responsible: string | null
  waiting_for: string | null
  project: string | null
}

export interface DeadlineTracker {
  id: string
  owner_id: string
  title: string
  description: string | null
  tracker_type: DeadlineTrackerType
  status: DeadlineTrackerStatus
  starts_at: string
  due_at: string
  pause_started_at: string | null
  paused_seconds: number
  shifted_due_at: string | null
  total_pause_seconds: number
  next_action: string | null
  responsible: string | null
  tags: string[]
  personal_task_id: string | null
  linked_task_id: string | null
  personal_task_key: string | null
  personal_task_title: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface DeadlineTrackerCreate {
  title: string
  description?: string | null
  tracker_type?: DeadlineTrackerType
  status?: DeadlineTrackerStatus
  starts_at: string
  due_at: string
  next_action?: string | null
  responsible?: string | null
  tags?: string[]
  personal_task_id?: string | null
  linked_task_id?: string | null
}

export interface DeadlineTrackerUpdate {
  title?: string
  description?: string | null
  tracker_type?: DeadlineTrackerType
  status?: DeadlineTrackerStatus
  starts_at?: string
  due_at?: string
  next_action?: string | null
  responsible?: string | null
  tags?: string[]
  personal_task_id?: string | null
  linked_task_id?: string | null
}

export type WorkTrackStatus = 'draft' | 'active' | 'paused' | 'done' | 'archived'
export type WorkTrackItemType = 'task' | 'personal_task' | 'manual' | 'cube'
export type WorkTrackItemStatus = 'active' | 'waiting' | 'blocked' | 'done' | 'skipped'

export interface WorkMethodology {
  id: string
  created_by_id: string | null
  title: string
  description: string | null
  schema_version: number | null
  methodology_version: string | null
  display_version: string | null
  release_kind: string | null
  source_kind: string
  fingerprint: string
  stages_count: number
  cubes_count: number
  routes_count: number
  products_count: number
  is_active: boolean
  activated_at: string | null
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WorkMethodologyImport {
  payload: Record<string, unknown>
  source_kind?: string
}

export interface WorkTrackApplyMethodologyRequest {
  methodology_id: string
  route_key?: string | null
  product_key?: string | null
  replace_existing_cubes?: boolean
}

export interface WorkTrackActivationIssue {
  item_id: string | null
  item_title: string | null
  code: string
  message: string
}

export interface WorkTrackReadiness {
  can_activate: boolean
  issues: WorkTrackActivationIssue[]
}

export interface WorkTrackItem {
  id: string
  track_id: string
  item_type: WorkTrackItemType
  task_id: string | null
  personal_task_id: string | null
  methodology_id: string | null
  methodology_node_type: string | null
  methodology_node_id: string | null
  methodology_stage_id: string | null
  methodology_snapshot: Record<string, unknown> | null
  checklist_snapshot: unknown[] | Record<string, unknown> | null
  proposed_executor_email: string | null
  proposed_executor_name: string | null
  reservation_status: WorkTrackReservationStatus
  title: string | null
  description: string | null
  status: WorkTrackItemStatus
  position: number
  starts_at: string | null
  due_at: string | null
  notes: string | null
  linked_title: string | null
  linked_number: number | null
  linked_status: string | null
  linked_due_at: string | null
  effective_title: string
  effective_due_at: string | null
  is_done: boolean
  source_available: boolean
  created_at: string
  updated_at: string
}

export interface WorkTrack {
  id: string
  owner_id: string
  title: string
  description: string | null
  status: WorkTrackStatus
  start_at: string | null
  due_at: string | null
  color: string
  methodology_id: string | null
  methodology_title: string | null
  methodology_version: string | null
  product_key: string | null
  route_key: string | null
  route_name: string | null
  methodology_snapshot: Record<string, unknown> | null
  route_snapshot: Record<string, unknown> | null
  items_count: number
  done_count: number
  progress_percent: number
  next_due_at: string | null
  items: WorkTrackItem[]
  created_at: string
  updated_at: string
}

export interface WorkTrackCreate {
  title: string
  description?: string | null
  status?: WorkTrackStatus
  start_at?: string | null
  due_at?: string | null
  color?: string
  methodology_id?: string | null
  product_key?: string | null
  route_key?: string | null
}

export interface WorkTrackUpdate {
  title?: string
  description?: string | null
  status?: WorkTrackStatus
  start_at?: string | null
  due_at?: string | null
  color?: string
  methodology_id?: string | null
  product_key?: string | null
  route_key?: string | null
}

export interface WorkTrackItemCreate {
  item_type: WorkTrackItemType
  task_id?: string | null
  personal_task_id?: string | null
  methodology_id?: string | null
  methodology_node_type?: string | null
  methodology_node_id?: string | null
  methodology_stage_id?: string | null
  methodology_snapshot?: Record<string, unknown> | null
  checklist_snapshot?: unknown[] | Record<string, unknown> | null
  proposed_executor_email?: string | null
  proposed_executor_name?: string | null
  reservation_status?: WorkTrackReservationStatus
  title?: string | null
  description?: string | null
  status?: WorkTrackItemStatus
  position?: number | null
  starts_at?: string | null
  due_at?: string | null
  notes?: string | null
}

export interface WorkTrackAssignedItem {
  track_id: string
  track_title: string
  track_owner_id: string
  item: WorkTrackItem
}

export interface WorkTrackItemUpdate {
  title?: string | null
  description?: string | null
  status?: WorkTrackItemStatus
  position?: number
  starts_at?: string | null
  due_at?: string | null
  notes?: string | null
  checklist_snapshot?: unknown[] | Record<string, unknown> | null
  proposed_executor_email?: string | null
  proposed_executor_name?: string | null
  reservation_status?: WorkTrackReservationStatus
}

export interface CatalogItem {
  id: string
  category: CatalogCategory
  name: string
  complexity: Complexity
  base_cost_q: number
  description: string | null
  min_league: League
  sort_order?: number
  is_active: boolean
  created_at: string
}

export interface Task {
  id: string
  task_number: number
  title: string
  description: string | null
  task_type: TaskType
  complexity: Complexity
  estimated_q: number
  priority: TaskPriority
  status: TaskStatus
  min_league: League
  assignee_id: string | null
  estimator_id: string
  validator_id: string | null
  estimation_details: Record<string, unknown> | null
  result_url: string | null
  result_comment: string | null
  brief_rating: number | null
  brief_feedback: string | null
  rejection_comment: string | null
  started_at: string | null
  completed_at: string | null
  validated_at: string | null
   /** SLA / дедлайны */
  due_date: string | null
  sla_hours: number | null
  is_overdue: boolean
  parent_task_id: string | null
  deadline_zone: 'green' | 'yellow' | 'red' | null
  tags: string[]
  rejection_count: number
  created_at: string
  updated_at: string
  focus_started_at: string | null
  active_seconds: number
  active_hours: number
  is_focused: boolean
}

export type TaskReviewEventType = 'submitted' | 'returned' | 'accepted'

export interface TaskReviewEvent {
  id: string
  task_id: string
  actor_id: string | null
  actor_name: string | null
  actor_email: string | null
  event_type: TaskReviewEventType
  comment: string | null
  result_url: string | null
  result_comment: string | null
  brief_rating: number | null
  brief_feedback: string | null
  created_at: string
}

export interface TaskAttachment {
  id: string
  task_id: string
  original_filename: string
  content_type: string
  size_bytes: number
  uploaded_by_id: string
  created_at: string
}

export interface TaskTagSuggestion {
  tag: string
  count: number
}

export interface TaskImportIssue {
  row_number: number
  field: string
  message: string
}

export interface TaskImportPreviewRow {
  row_number: number
  title: string
  catalog_item_id: string | null
  catalog_item_name: string | null
  quantity: number | null
  priority: TaskPriority
  due_date: string | null
  tags: string[]
  task_type: TaskType | null
  complexity: Complexity | null
  estimated_q: number | null
  min_league: League | null
  errors: TaskImportIssue[]
}

export interface TaskImportPreview {
  batch_id: string
  total_rows: number
  valid_rows: number
  error_rows: number
  has_errors: boolean
  warnings: string[]
  rows: TaskImportPreviewRow[]
}

export interface TaskImportCommitResponse {
  batch_id: string
  created_count: number
  tasks: Task[]
}

export interface KnowledgeArticle {
  id: string
  slug: string
  title: string
  summary: string
  section: string
  body: string
  status: KnowledgeStatus
  sort_order: number
  created_by_id: string | null
  updated_by_id: string | null
  created_at: string
  updated_at: string
  published_at: string | null
}

export interface KnowledgeArticleCreate {
  slug?: string | null
  title: string
  summary: string
  section: string
  body: string
  status: KnowledgeStatus
  sort_order: number
}

export interface KnowledgeArticleUpdate {
  slug?: string
  title?: string
  summary?: string
  section?: string
  body?: string
  status?: KnowledgeStatus
  sort_order?: number
}

export interface UserAbsence {
  id: string
  user_id: string
  user_name: string
  user_email: string
  start_date: string
  end_date: string
  type: AbsenceType
  affects_plan: boolean
  comment: string | null
  source: string
  working_days: number
  created_by_id: string | null
  created_at: string
  updated_at: string
}

export interface AbsencePayload {
  user_id: string
  start_date: string
  end_date: string
  type: AbsenceType
  affects_plan: boolean
  comment?: string | null
}

export interface GlobalHoliday {
  id: string
  date: string
  name: string
  affects_plan: boolean
  created_by_id: string | null
  created_at: string
  updated_at: string
}

export interface HolidayPayload {
  date: string
  name: string
}

export interface FeedbackRequest {
  id: string
  feedback_number: number
  feedback_code: string
  author_id: string
  author_name: string
  reviewer_id: string | null
  reviewer_name: string | null
  decided_by_id: string | null
  decided_by_name: string | null
  category: FeedbackCategory
  status: FeedbackStatus
  priority: FeedbackPriority
  title: string
  description: string
  object_type: FeedbackObjectType
  object_ref: string | null
  expected_result: string | null
  impact: string | null
  evidence_links: string[]
  resolution: string | null
  decision_summary: string | null
  decision_reason: string | null
  next_action: string | null
  target_release: string | null
  created_at: string
  updated_at: string
  reviewed_at: string | null
  closed_at: string | null
  decided_at: string | null
}

export interface FeedbackRequestCreate {
  category: FeedbackCategory
  priority: FeedbackPriority
  title: string
  description: string
  object_type: FeedbackObjectType
  object_ref?: string | null
  expected_result?: string | null
  impact?: string | null
  evidence_links: string[]
}

export interface FeedbackRequestUpdate {
  status?: FeedbackStatus
  reviewer_id?: string | null
  priority?: FeedbackPriority
  resolution?: string | null
  object_type?: FeedbackObjectType
  object_ref?: string | null
  expected_result?: string | null
  impact?: string | null
  evidence_links?: string[] | null
  decision_summary?: string | null
  decision_reason?: string | null
  next_action?: string | null
  target_release?: string | null
}

export interface FeedbackRequestListResponse {
  items: FeedbackRequest[]
  total: number
  limit: number
}

export interface CompetencyAccess {
  development_enabled: boolean
  constructor_enabled: boolean
  is_admin: boolean
}

export interface CompetencySummary {
  id: string
  title: string
  description: string | null
  source: 'builtin' | 'custom' | string
  department?: string | null
  visibility?: 'assigned' | 'all' | string
  created_by_id?: string | null
  questions_count: number
  status: string
  is_required_builtin?: boolean
  assigned_count?: number
  attempts_count?: number
  completed_count?: number
  can_edit_content?: boolean
  active_attempt_id: string | null
  latest_attempt_id: string | null
  score_ib: number | null
  score_ich: number | null
  is_overused: boolean
  completed_at: string | null
  retake_allowed_at: string | null
}

export interface CompetencyListResponse {
  competencies: CompetencySummary[]
}

export interface CompetencyChoiceRead {
  id: string
  text: string
}

export interface CompetencyQuestionRead {
  id: string
  text: string
  question_type: string
  position: number
  choices: CompetencyChoiceRead[]
}

export interface CompetencyAttemptStartResponse {
  attempt_id: string
  competency_id: string
  competency_title: string
  competency_description: string | null
  status: string
  questions: CompetencyQuestionRead[]
}

export interface CompetencyResultResponse {
  attempt_id: string
  competency_id: string
  competency_title: string
  status: string
  score_ib: number | null
  score_ich: number | null
  is_overused: boolean
  interpretation_text: string | null
  avg_time_per_question: number | null
  completed_at: string | null
  retake_allowed_at: string | null
}

export type DevelopmentPlanStatus = 'planned' | 'in_progress' | 'done' | 'cancelled'

export interface DevelopmentPlanItem {
  id: string
  competency_id: string | null
  source_attempt_id: string | null
  competency_title: string | null
  goal: string
  action_text: string
  expected_result: string | null
  due_at: string | null
  status: DevelopmentPlanStatus
  created_at: string
  updated_at: string
}

export interface DevelopmentPlanItemCreate {
  competency_id?: string | null
  source_attempt_id?: string | null
  goal: string
  action_text: string
  expected_result?: string | null
  due_at?: string | null
}

export interface DevelopmentPlanPromptResponse {
  prompt: string
  completed_assessments_count: number
  generated_at: string
}

export interface DevelopmentPlanImportResponse {
  imported_count: number
  skipped_count: number
  warnings: string[]
  items: DevelopmentPlanItem[]
}

export interface DevelopmentPlanReportAssessment {
  attempt_id: string
  competency_id: string
  competency_title: string
  source: string
  score_ib: number | null
  score_ich: number | null
  is_overused: boolean
  interpretation_text: string | null
  completed_at: string | null
  retake_allowed_at: string | null
}

export interface DevelopmentPlanRoadmapPoint {
  id: string | null
  title: string
  description: string | null
  status: string
  due_at: string | null
  completed_at: string | null
}

export interface DevelopmentPlanReportResponse {
  user_id: string
  full_name: string
  email: string
  completed_assessments_count: number
  plan_total: number
  plan_planned: number
  plan_in_progress: number
  plan_done: number
  plan_cancelled: number
  progress_percent: number
  assessments: DevelopmentPlanReportAssessment[]
  roadmap: DevelopmentPlanRoadmapPoint[]
}

export interface DevelopmentPlanAdminSummaryUser {
  user_id: string
  full_name: string
  email: string
  completed_assessments_count: number
  plan_total: number
  plan_done: number
  plan_in_progress: number
  progress_percent: number
  last_activity_at: string | null
}

export interface DevelopmentPlanAdminSummaryResponse {
  total_enabled_users: number
  users_with_completed_assessments: number
  completed_assessments_count: number
  users_with_plan: number
  plan_total: number
  plan_planned: number
  plan_in_progress: number
  plan_done: number
  plan_cancelled: number
  users: DevelopmentPlanAdminSummaryUser[]
}

export interface ConstructorChoiceCreate {
  text: string
  value: number
}

export interface ConstructorQuestionCreate {
  text: string
  question_type: string
  choices: ConstructorChoiceCreate[]
}

export interface ConstructorCompetencyCreate {
  title: string
  description?: string | null
  department?: string | null
  visibility?: 'assigned' | 'all'
  questions: ConstructorQuestionCreate[]
  interpretations: Array<{
    min_score_ib: number
    max_score_ib: number
    text: string
    overuse_modifier_text?: string | null
    recommendation_text?: string | null
  }>
}

export interface ConstructorCompetencyUpdate {
  title?: string | null
  description?: string | null
  department?: string | null
  visibility?: 'assigned' | 'all' | null
  questions?: ConstructorQuestionCreate[] | null
  interpretations?: ConstructorCompetencyCreate['interpretations'] | null
}

export interface ConstructorChoiceRead {
  id: string
  text: string
  value: number
  position: number
}

export interface ConstructorQuestionRead {
  id: string
  text: string
  question_type: string
  position: number
  choices: ConstructorChoiceRead[]
}

export interface ConstructorInterpretationRead {
  id: string
  min_score_ib: number
  max_score_ib: number
  text: string
  overuse_modifier_text: string | null
  recommendation_text: string | null
}

export interface ConstructorCompetencyDetail extends CompetencySummary {
  questions: ConstructorQuestionRead[]
  interpretations: ConstructorInterpretationRead[]
}

export interface ConstructorAssignmentSet {
  target_user_ids: string[]
  visibility?: 'assigned' | 'all' | null
}

export interface ConstructorAssignmentRead {
  id: string
  competency_id: string
  target_user_id: string
  status: string
  link: string
  due_at: string | null
  created_at: string
}

export interface ConstructorReportRow {
  user_id: string
  full_name: string
  email: string
  assignment_status: string | null
  attempt_status: string
  score_ib: number | null
  score_ich: number | null
  is_overused: boolean
  completed_at: string | null
  retake_allowed_at: string | null
  attention_points: string[]
  interpretation_text: string | null
}

export interface ConstructorReportResponse {
  competency_id: string
  title: string
  visibility: string
  assigned_count: number
  completed_count: number
  rows: ConstructorReportRow[]
}

/** Задача в очереди с флагами can_pull, locked */
export interface QueueTaskResponse {
  id: string
  task_number: number
  title: string
  description: string | null
  task_type: string
  complexity: string
  estimated_q: number
  priority: string
  min_league: string
  created_at: string
  estimator_name: string | null
  due_date: string | null
  deadline_zone: 'green' | 'yellow' | 'red' | null
  can_pull: boolean
  locked: boolean
  lock_reason: string | null
  is_proactive?: boolean
  tags?: string[]
  is_stale?: boolean
  hours_in_queue?: number
  can_assign?: boolean
  recommended?: boolean
  assigned_by_name?: string | null
}

/** Кандидат для назначения задачи */
export interface AssignCandidate {
  id: string
  full_name: string
  role: UserRole
  league: string
  wip_current: number
  wip_limit: number
  is_available: boolean
}

export interface CapacityGauge {
  capacity: number
  load: number
  utilization: number
  status: 'green' | 'yellow' | 'red'
}

export interface CapacityHistoryPoint {
  week: string
  earned: number
  capacity: number
  percent: number
}

export interface CapacityHistoryResponse {
  weeks: CapacityHistoryPoint[]
  total_capacity: number
}

export interface UserProgress {
  earned: number
  target: number
  full_target: number
  percent: number
  karma: number
  is_new_employee: boolean
  onboarding_active: boolean
  onboarding_until: string | null
  plan_started_at: string | null
  absence_working_days: number
  absent_today: boolean
  adjustment_reasons: string[]
}

export interface TeamMemberSummary {
  id: string
  full_name: string
  league: string
  mpw: number
  effective_mpw: number
  earned: number
  percent: number
  karma: number
  in_progress_q: number
  is_at_risk: boolean
  quality_score: number
  has_overdue: boolean
  is_new_employee: boolean
  onboarding_active: boolean
  onboarding_until: string | null
  absence_working_days: number
  absent_today: boolean
  adjustment_reasons: string[]
}

export interface TeamSummary {
  by_league: Record<string, TeamMemberSummary[]>
  total_capacity: number
  total_load: number
  total_earned: number
  utilization: number
}

export interface PeriodStats {
  period: string
  tasks_created: number
  tasks_completed: number
  total_q_earned: number
  avg_completion_time_hours: number | null
}

export interface BurndownPoint {
  day: string
  ideal: number
  actual: number | null
}

export interface BurndownData {
  period: string
  total_capacity: number
  working_days: number
  points: BurndownPoint[]
}

export interface CalibrationItem {
  catalog_item_id: string
  name: string
  category: string
  complexity: string
  base_cost_q: number
  tasks_count: number
  avg_estimated_q: number
  avg_actual_hours: number | null
  deviation_percent: number | null
  recommendation: string
}

export interface CalibrationReport {
  period: string
  items: CalibrationItem[]
  total_tasks_analyzed: number
  overall_accuracy_percent: number
}

/** Новый формат калибровки: по задачам, оценщикам, популярность операций */
export interface TaskCalibration {
  task_id: string
  title: string
  task_type: string
  complexity: string
  estimated_q: number
  actual_hours: number
  deviation_pct: number
  assignee_name: string
  estimator_name: string
  tags: string[]
}

export interface EstimatorCalibration {
  estimator_name: string
  tasks_count: number
  avg_deviation_pct: number
  accuracy_pct: number
  bias: 'точно' | 'завышает' | 'занижает'
  overestimates: number
  underestimates: number
}

export interface WidgetPopularityItem {
  name: string
  tasks_count: number
  usage_percent: number
}

export interface CalibrationReportNew {
  period: string
  total_tasks_analyzed: number
  overall_accuracy_pct: number
  avg_deviation_pct: number
  task_calibrations: TaskCalibration[]
  estimator_calibrations: EstimatorCalibration[]
  widget_popularity: WidgetPopularityItem[]
  total_tasks_with_breakdown: number
}

export interface FocusStatusItem {
  user_id: string
  full_name: string
  league: string
  focused_task_id: string | null
  focused_task_title: string | null
  focus_duration_minutes: number
  status: 'focused' | 'idle' | 'paused'
}

export interface TeamleadAccuracy {
  user_id: string
  full_name: string
  tasks_evaluated: number
  accuracy_percent: number
  bias: 'neutral' | 'overestimates' | 'underestimates'
  bias_percent: number
  trend: 'improving' | 'stable' | 'declining'
  trend_delta: number
}

export interface LeagueEvaluation {
  user_id: string
  full_name: string
  current_league: string
  suggested_league: string
  reason: string
  eligible: boolean
  history: Array<{ period: string; percent: number }>
}

export interface CriteriaPeriod {
  period: string
  value: number | null
  met: boolean
  current?: boolean
}

export interface LeagueCriterion {
  name: string
  description: string
  required: number
  completed: number
  met: boolean
  progress_percent: number
  details: CriteriaPeriod[]
}

export interface LeagueProgress {
  user_id: string
  current_league: string
  next_league: string | null
  at_max: boolean
  criteria: LeagueCriterion[]
  overall_progress: number
  message: string
}

export interface LeagueChange {
  user_id: string
  full_name: string
  old_league: string
  new_league: string
  reason: string
}

export interface NotificationRead {
  id: string
  user_id: string
  type: string
  title: string
  message: string
  is_read: boolean
  link: string | null
  created_at: string
}

export interface PerformerSummary {
  full_name: string
  league: string
  percent: number
  tasks_completed: number
}

export interface TasksOverview {
  total_created: number
  total_completed: number
  avg_time_hours: number | null
  by_category: Record<string, number>
}

export interface ShopActivity {
  total_purchases: number
  total_karma_spent: number
  popular_items: Array<{ shop_item_id?: string; name?: string; count?: number }>
}

export interface CalibrationSummary {
  accurate_count: number
  overestimated_count: number
  underestimated_count: number
}

export interface PeriodReport {
  period: string
  generated_at: string
  team_members: PerformerSummary[]
  top_performers: PerformerSummary[]
  underperformers: PerformerSummary[]
  tasks_overview: TasksOverview
  shop_activity: ShopActivity
  calibration_summary: CalibrationSummary
  total_capacity: number
  total_earned: number
  utilization_percent: number
}

export interface EmployeeScorecardRow {
  rank: number
  user_id: string
  full_name: string
  role: UserRole
  league: League
  plan_q: number
  completed_q: number
  efficiency_percent: number
  completed_tasks_count: number
  first_pass_tasks_count: number
  first_pass_rate: number
  rejection_events_count: number
  active_overdue_count: number
  completed_late_count: number
  high_priority_completed_count: number
  critical_completed_count: number
  focus_hours: number
  focus_start_count: number
  focus_pause_count: number
  avg_pauses_per_task: number
  focus_task_coverage_percent: number
  quality_score: number
  efficiency_score: number
  acceptance_score: number
  reliability_score: number
  focus_score: number
  score: number
}

export interface EmployeeScorecardResponse {
  start_date: string
  end_date: string
  generated_at: string
  weights: Record<string, number>
  rows: EmployeeScorecardRow[]
}

export interface ActivityEvent {
  id: string
  actor_id: string
  actor_name: string
  event_type: string
  task_id: string | null
  task_number: number | null
  task_title: string | null
  metadata: Record<string, unknown> | null
  occurred_at: string
}

export interface ActivityEventListResponse {
  items: ActivityEvent[]
  total: number
  limit: number
}

export interface FocusActivitySummary {
  total_focus_seconds: number
  total_focus_hours: number
  focus_start_count: number
  focus_pause_count: number
  focus_auto_pause_count: number
  focused_tasks_count: number
  avg_pauses_per_task: number
}

export interface EmployeeSummaryTask {
  id: string
  task_number: number
  title: string
  status: TaskStatus
  priority: TaskPriority
  task_type: TaskType
  estimated_q: number
  started_at: string | null
  completed_at: string | null
  validated_at: string | null
  active_seconds: number
  focus_sessions: number
  pause_count: number
  auto_pause_count: number
  result_url: string | null
}

export interface EmployeePeriodSummary {
  user_id: string
  full_name: string
  role: UserRole
  league: League
  start_date: string
  end_date: string
  plan_q: number
  completed_q: number
  efficiency_percent: number
  completed_tasks_count: number
  in_progress_tasks_count: number
  review_tasks_count: number
  rejected_tasks_count: number
  absence_working_days: number
  focus: FocusActivitySummary
  completed_tasks: EmployeeSummaryTask[]
  in_progress_tasks: EmployeeSummaryTask[]
  review_tasks: EmployeeSummaryTask[]
  rejected_tasks: EmployeeSummaryTask[]
  recent_activity: ActivityEvent[]
}

export interface TaskExportRow {
  title: string
  category: string
  complexity: string
  estimated_q: number
  assignee_name: string
  started_at: string | null
  completed_at: string | null
  duration_hours: number | null
  validator_name: string | null
  status: string
}

export interface TasksExport {
  period: string
  rows: TaskExportRow[]
  total_tasks: number
  total_q: number
}

export interface ShopItem {
  id: string
  name: string
  description: string
  cost_q: number
  category: string
  icon: string
  is_active: boolean
  max_per_month: number
  requires_approval?: boolean
  created_at: string
}

export interface Purchase {
  id: string
  user_id: string
  shop_item_id: string
  cost_q: number
  status: string
  created_at: string
  approved_at: string | null
  approved_by: string | null
  item_name: string | null
  user_name?: string | null
  user_email?: string | null
}

export interface RolloverResponse {
  period: string
  users_processed: number
  total_main_reset: number
  total_karma_burned: number
}

export interface PeriodHistoryItem {
  period: string
  closed_at: string | null
  status: 'closed' | 'cancelled' | string
  mode: 'manual' | 'auto' | 'legacy' | string
  cancelled_at: string | null
  users_count: number
  total_main_reset: number
  total_karma_burned: number
}

export interface QTransactionRead {
  id: string
  user_id: string
  amount: number
  wallet_type: 'main' | 'karma'
  reason: string
  task_id: string | null
  created_at: string
}

export type RunRateStatus = 'on_track' | 'slightly_behind' | 'at_risk' | 'critical'

export interface RunRate {
  rate_daily: number
  projected: number
  mpw: number
  full_mpw: number
  run_rate_percent: number
  required_rate: number | null
  status: RunRateStatus
  days_elapsed: number
  days_total: number
  days_remaining: number
  earned: number
  is_new_employee: boolean
  onboarding_active: boolean
  onboarding_until: string | null
  absence_working_days: number
  absent_today: boolean
}

/** Позиция в запросе калькулятора */
export interface CalcItemInput {
  catalog_id: string
  quantity: number
}

export interface EstimateBreakdownItem {
  catalog_id: string
  name: string
  category: string
  complexity: string
  base_cost_q: number
  quantity: number
  subtotal_q: number
}

export interface EstimateResponse {
  total_q: number
  min_league: string
  breakdown: EstimateBreakdownItem[]
}

/** Запрос создания задачи из калькулятора */
export interface CreateTaskFromCalcRequest {
  title: string
  description: string
  priority: string
  estimator_id: string
  items: CalcItemInput[]
  tags?: string[]
}

export interface AuditSynologyConnection {
  configured: boolean
  id: string | null
  display_name: string | null
  base_url: string | null
  account_name: string | null
  root_path: string | null
  enabled: boolean
  is_active: boolean
  credential_saved: boolean
  config_version: number | null
  last_tested_at: string | null
  last_test_status: 'ok' | 'error' | null
  last_verified_config_version: number | null
  ready_for_use: boolean
  last_error_code: string | null
  allowed_origins_configured: boolean
  encryption_key_configured: boolean
  updated_at: string | null
}

export interface AuditSynologyConnectionList {
  items: AuditSynologyConnection[]
  allowed_origins_configured: boolean
  encryption_key_configured: boolean
}

export interface AuditSynologyConnectResponse {
  session_token: string
  expires_at: string
  connection: AuditSynologyConnection
}

export interface AuditSynologyFile {
  item_id: string
  path_token: string
  name: string
  is_dir: boolean
  size_bytes: number
  modified_at: number
  extension: string
  selectable: boolean
  already_imported: boolean
  disabled_reason: string | null
}

export interface AuditSynologyBrowser {
  current_folder_name: string
  root_folder_name: string
  parent_token: string | null
  offset: number
  total: number
  items: AuditSynologyFile[]
}

export interface AuditSynologyPreview {
  preview_token: string
  expires_in_seconds: number
  file_count: number
  total_size_bytes: number
  items: Array<{
    file_token: string
    name: string
    size_bytes: number
    modified_at: number
    extension: string
  }>
}

export interface AuditSynologyImportResult {
  imported_count: number
  total_size_bytes: number
  items: Array<{
    case_id: string
    case_number: string
    document_id: string
    file_name: string
    size_bytes: number
  }>
}

export interface AIProviderConfig {
  configured: boolean
  id: string | null
  provider_kind: 'openai_compatible'
  display_name: string | null
  base_url: string | null
  model_name: string | null
  enabled: boolean
  api_key_configured: boolean
  config_version: number | null
  last_tested_at: string | null
  last_test_status: 'ok' | 'error' | null
  last_verified_config_version: number | null
  ready_for_use: boolean
  last_error_code: string | null
  allowed_origins_configured: boolean
  encryption_key_configured: boolean
  updated_at: string | null
}

export interface AIProviderTestResult {
  ok: boolean
  model_name: string
  message: string
  tested_at: string
}
