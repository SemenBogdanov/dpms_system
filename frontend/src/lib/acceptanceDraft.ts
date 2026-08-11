export type AcceptanceEvidence = Record<string, { comment: string; url: string }>
export type AcceptanceReviewComments = Record<string, string>

export interface StoredAcceptanceDraft {
  savedAt: number
  acceptanceRevision: number
  selected: string[]
  evidence: AcceptanceEvidence
  reviewComments: AcceptanceReviewComments
  revisionCriterionId: string | null
  revisionComments: AcceptanceReviewComments
  criterionTitles: Record<string, string>
}

const DRAFT_TTL_MS = 8 * 60 * 60 * 1000

function acceptanceDraftKey(taskId: string) {
  return `dpms:acceptance-draft:${taskId}`
}

export function readAcceptanceDraft(
  taskId: string,
): StoredAcceptanceDraft | null {
  try {
    const raw = window.sessionStorage.getItem(acceptanceDraftKey(taskId))
    if (!raw) return null
    const draft = JSON.parse(raw) as StoredAcceptanceDraft
    if (
      !draft
      || typeof draft.savedAt !== 'number'
      || Date.now() - draft.savedAt > DRAFT_TTL_MS
    ) {
      window.sessionStorage.removeItem(acceptanceDraftKey(taskId))
      return null
    }
    return { ...draft, criterionTitles: draft.criterionTitles ?? {} }
  } catch {
    return null
  }
}

export function writeAcceptanceDraft(taskId: string, draft: StoredAcceptanceDraft) {
  try {
    window.sessionStorage.setItem(acceptanceDraftKey(taskId), JSON.stringify(draft))
  } catch {
    // The in-memory draft remains protected when storage is unavailable.
  }
}

export function clearTaskAcceptanceDraft(taskId: string) {
  try {
    window.sessionStorage.removeItem(acceptanceDraftKey(taskId))
  } catch {
    // Session storage may be unavailable in restrictive browser modes.
  }
}
