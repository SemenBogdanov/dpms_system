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
  created_at: string
  updated_at: string
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
  created_at: string
  updated_at: string
  focus_started_at: string | null
  active_seconds: number
  active_hours: number
  is_focused: boolean
}

/** Задача в очереди с флагами can_pull, locked */
export interface QueueTaskResponse {
  id: string
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
  percent: number
  karma: number
}

export interface TeamMemberSummary {
  id: string
  full_name: string
  league: string
  mpw: number
  earned: number
  percent: number
  karma: number
  in_progress_q: number
  is_at_risk: boolean
  quality_score: number
  has_overdue: boolean
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
