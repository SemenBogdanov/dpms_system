export type UserRole = 'executor' | 'teamlead' | 'admin'
export type League = 'C' | 'B' | 'A'

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
  is_new_employee: boolean
  task_workspace_enabled: boolean
  can_link_queue_tasks_to_projects: boolean
  feedback_enabled: boolean
  audit_enabled: boolean
  competency_development_enabled: boolean
  competency_constructor_enabled: boolean
  plan_started_at: string | null
  onboarding_started_at: string | null
  onboarding_until: string | null
  sidebar_menu_order: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AuthenticatedUser extends User {
  needs_password_change: boolean
}

export interface SetupStatus {
  setup_required: boolean
  catalog_competencies: number
  catalog_questions: number
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
