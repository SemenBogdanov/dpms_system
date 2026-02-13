/**
 * Типы, зеркало backend schemas.
 */

export type League = 'C' | 'B' | 'A'
export type UserRole = 'executor' | 'teamlead' | 'admin'
export type CatalogCategory = 'widget' | 'etl' | 'api' | 'docs'
export type Complexity = 'S' | 'M' | 'L' | 'XL'
export type TaskType = 'widget' | 'etl' | 'api' | 'docs'
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
  created_at: string
  updated_at: string
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
  can_pull: boolean
  locked: boolean
  lock_reason: string | null
}

export interface CapacityGauge {
  capacity: number
  load: number
  utilization: number
  status: 'green' | 'yellow' | 'red'
}

export interface UserProgress {
  earned: number
  target: number
  percent: number
  karma: number
}

export interface TeamMemberSummary {
  user_id: string
  full_name: string
  league: League
  earned: number
  target: number
  percent: number
  karma: number
}

export interface TeamSummary {
  by_league: Record<string, TeamMemberSummary[]>
  capacity: number
  total_earned: number
  total_load: number
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
  complexity_multiplier: number
  urgency_multiplier: number
  breakdown: EstimateBreakdownItem[]
}

/** Запрос создания задачи из калькулятора */
export interface CreateTaskFromCalcRequest {
  title: string
  description: string
  priority: string
  estimator_id: string
  items: CalcItemInput[]
  complexity_multiplier: number
  urgency_multiplier: number
}
