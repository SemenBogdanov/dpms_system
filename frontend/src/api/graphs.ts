import { api } from './client'

export type GraphPayload = Record<string, unknown> & {
  id: string
  title: string
}

export type GraphMetadata = {
  client_id: string
  title: string
  revision: number
  payload_bytes: number
  node_count: number
  edge_count: number
  created_at: string
  updated_at: string
}

export type GraphDocument = GraphMetadata & {
  id: string
  payload: GraphPayload
}

const graphPath = (clientId: string) => `/api/graphs/${encodeURIComponent(clientId)}`

export const graphsApi = {
  list: () => api.get<GraphMetadata[]>('/api/graphs'),
  get: (clientId: string) => api.get<GraphDocument>(graphPath(clientId)),
  put: (clientId: string, baseRevision: number | null, payload: GraphPayload) =>
    api.put<GraphDocument>(graphPath(clientId), {
      base_revision: baseRevision,
      payload,
    }),
  delete: (clientId: string, baseRevision: number) =>
    api.delete<{ deleted: true; client_id: string }>(
      `${graphPath(clientId)}?base_revision=${baseRevision}`
    ),
}
