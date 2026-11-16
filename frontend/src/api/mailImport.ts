import { api } from '@/api/client'

export type MailDeviceStatus = 'pending' | 'active' | 'expired' | 'revoked'
export type MailSourceState = 'cached' | 'online' | 'offline'
export type ImportedMailKind = 'mail' | 'meeting'

export interface MailImportDevice {
  id: string
  name: string
  status: MailDeviceStatus
  include_body: boolean
  include_attachments: boolean
  mailbox_label: string | null
  created_at: string
  last_sync_at: string | null
  last_scan_complete: boolean | null
  last_skipped_items: number
  source_state: MailSourceState | null
  expires_at: string | null
}

export interface MailPairing {
  device: MailImportDevice
  pairing_code: string
  expires_at: string
}

export interface ImportedMailAttachment {
  id: string
  filename: string
  content_type: string
  byte_length: number
  sha256: string
  is_inline: boolean
  content_id: string | null
}

export interface ImportedMailItem {
  id: string
  source_id: string
  kind: ImportedMailKind
  source_modified_at: string
  received_at: string
  subject: string
  sender_name: string
  sender_address: string
  to_recipients: string
  cc_recipients: string
  body_text: string | null
  body_html: string | null
  attachments: ImportedMailAttachment[]
  source_is_read: boolean
  meeting_status: 'invited' | 'updated' | 'cancelled' | 'response' | null
  starts_at: string | null
  ends_at: string | null
  all_day: boolean
  location: string
  meeting_key: string | null
  is_recurring: boolean
  mailbox_label: string
  is_read: boolean
  created_at: string
  updated_at: string
}

export interface ImportedMailList {
  items: ImportedMailItem[]
  total: number
  unread_count: number
}

export const mailImport = {
  devices: () => api.get<MailImportDevice[]>('/api/mail-import/devices'),
  createDevice: (name: string, includeBody: boolean, includeAttachments: boolean) =>
    api.post<MailPairing>('/api/mail-import/devices', { name, include_body: includeBody, include_attachments: includeAttachments }),
  revokeDevice: (id: string) =>
    api.post<MailImportDevice>(`/api/mail-import/devices/${encodeURIComponent(id)}/revoke`, {}),
  items: (options: { kind?: ImportedMailKind; unreadOnly?: boolean; limit?: number; offset?: number } = {}) =>
    api.get<ImportedMailList>('/api/mail-import/items', {
      ...(options.kind ? { kind: options.kind } : {}),
      unread_only: String(options.unreadOnly ?? false),
      limit: String(options.limit ?? 50),
      offset: String(options.offset ?? 0),
    }),
  item: (id: string) => api.get<ImportedMailItem>(`/api/mail-import/items/${encodeURIComponent(id)}`),
  attachment: (id: string, attachmentId: string) =>
    api.blob(`/api/mail-import/items/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}`),
  setRead: (id: string, isRead: boolean) =>
    api.post<ImportedMailItem>(`/api/mail-import/items/${encodeURIComponent(id)}/read`, { is_read: isRead }),
}
