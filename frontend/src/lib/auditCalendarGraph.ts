import type { CalendarFact, CalendarPlan } from '@/api/auditCalendar'

type Meeting = CalendarPlan | CalendarFact
export type CalendarGraphLane = { plans: CalendarPlan[]; facts: CalendarFact[] }
const overlaps = (a: Meeting, b: Meeting) => a.start < b.start + b.duration && b.start < a.start + a.duration

export function graphMeetings(plans: CalendarPlan[], facts: CalendarFact[], hideCancelled: boolean) {
  if (!hideCancelled) return { plans, facts }
  const cancelled = new Set(facts.filter(f => f.outcome === 'cancelled').map(f => f.plan_id))
  return { plans: plans.filter(p => p.status !== 'cancelled' && p.fact_outcome !== 'cancelled' && !cancelled.has(p.id)), facts: facts.filter(f => f.outcome !== 'cancelled') }
}

export function calendarGraphLanes(plans: CalendarPlan[], facts: CalendarFact[], date: string): CalendarGraphLane[] {
  const families = new Map<string, CalendarGraphLane>()
  for (const plan of plans.filter(p => p.date === date)) families.set(plan.id, { plans: [plan], facts: [] })
  for (const fact of facts.filter(f => f.date === date)) {
    const id = fact.plan_id || `fact:${fact.id}`
    const family = families.get(id) || { plans: [], facts: [] }
    family.facts.push(fact)
    families.set(id, family)
  }
  // Keep a plan and its own fact on one lane even when actual time differs.
  const first = (family: CalendarGraphLane) => Math.min(...[...family.plans, ...family.facts].map(r => r.start))
  const lanes: CalendarGraphLane[] = []
  for (const [, family] of [...families].sort(([a, x], [b, y]) => first(x) - first(y) || a.localeCompare(b))) {
    const records = [...family.plans, ...family.facts]
    // Both layers must stay clear of other families to avoid false visual pairs.
    let lane = lanes.find(l => !records.some(record => [...l.plans, ...l.facts].some(other => overlaps(record, other))))
    if (!lane) { lane = { plans: [], facts: [] }; lanes.push(lane) }
    lane.plans.push(...family.plans)
    lane.facts.push(...family.facts)
  }
  return lanes.length ? lanes : [{ plans: [], facts: [] }]
}
