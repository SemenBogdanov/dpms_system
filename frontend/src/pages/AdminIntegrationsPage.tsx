import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  BrainCircuit,
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  File,
  FileJson2,
  Folder,
  HardDrive,
  Loader2,
  LogOut,
  Plus,
  PlugZap,
  Power,
  RefreshCw,
  Server,
  ShieldCheck,
  UploadCloud,
  Users,
  X,
} from 'lucide-react'

import { ApiError, api } from '@/api/client'
import type {
  AIProviderConfig,
  AIProviderTestResult,
  AuditAtomizationSkillList,
  AuditAtomizationSkillVersion,
  AuditSynologyBrowser,
  AuditSynologyConnectResponse,
  AuditSynologyConnection,
  AuditSynologyConnectionList,
  AuditSynologyFile,
  AuditSynologyImportResult,
  AuditSynologyPreview,
} from '@/api/types'
import { cn } from '@/lib/utils'


type IntegrationTab = 'synology' | 'ai'
const SYNOLOGY_PAGE_SIZE = 100
const SYNOLOGY_SESSION_ERROR_CODES = new Set([
  'session_expired',
  'session_interrupted',
  'session_missing',
  'profile_changed',
])

function formatBytes(value: number) {
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

function formatTimestamp(value: number) {
  if (!value) return 'Дата не указана'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value * 1000))
}

function IntegrationStatus({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div className={cn(
      'flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm',
      ok
        ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200'
        : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200'
    )}>
      {ok ? <Check className="h-4 w-4 shrink-0" /> : <ShieldCheck className="h-4 w-4 shrink-0" />}
      <span>{children}</span>
    </div>
  )
}

function ProtectedDialog({
  title,
  children,
  onClose,
}: {
  title: string
  children: React.ReactNode
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const frame = requestAnimationFrame(() => dialogRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      previousFocus?.focus()
    }
  }, [])

  function handleKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      return
    }
    if (event.key !== 'Tab' || !dialogRef.current) return
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
    ))
    if (focusable.length === 0) {
      event.preventDefault()
      dialogRef.current.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement
    if (event.shiftKey && active === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3" role="presentation">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="integration-dialog-title"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-lg border border-border bg-background shadow-xl"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background px-4 py-3">
          <h2 id="integration-dialog-title" className="text-base font-semibold text-foreground">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>
        {children}
      </section>
    </div>
  )
}

export function AdminIntegrationsPage() {
  const otpInputRef = useRef<HTMLInputElement>(null)
  const importInFlightRef = useRef(false)
  const skillFileInputRef = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<IntegrationTab>('synology')
  const [loading, setLoading] = useState(true)

  const [synologyConnections, setSynologyConnections] = useState<AuditSynologyConnection[]>([])
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null)
  const [synologyAllowlistReady, setSynologyAllowlistReady] = useState(false)
  const [synologyEncryptionReady, setSynologyEncryptionReady] = useState(false)
  const [synologyName, setSynologyName] = useState('')
  const [synologyUrl, setSynologyUrl] = useState('')
  const [synologyAccount, setSynologyAccount] = useState('')
  const [synologyPassword, setSynologyPassword] = useState('')
  const [synologyOtp, setSynologyOtp] = useState('')
  const [synologyRoot, setSynologyRoot] = useState('/')
  const [showSynologyPassword, setShowSynologyPassword] = useState(false)
  const [synologyBusy, setSynologyBusy] = useState(false)
  const [sessionToken, setSessionToken] = useState<string | null>(null)
  const [sessionConnectionId, setSessionConnectionId] = useState<string | null>(null)
  const [browser, setBrowser] = useState<AuditSynologyBrowser | null>(null)
  const [currentFolderToken, setCurrentFolderToken] = useState<string | null>(null)
  const [folderBusy, setFolderBusy] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<Map<string, AuditSynologyFile>>(new Map())
  const [preview, setPreview] = useState<AuditSynologyPreview | null>(null)
  const [previewRequestId, setPreviewRequestId] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [digitalProduct, setDigitalProduct] = useState('')
  const [importResult, setImportResult] = useState<AuditSynologyImportResult | null>(null)

  const [aiConfig, setAiConfig] = useState<AIProviderConfig | null>(null)
  const [aiDisplayName, setAiDisplayName] = useState('ИИ-провайдер')
  const [aiUrl, setAiUrl] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [aiKey, setAiKey] = useState('')
  const [aiEnabled, setAiEnabled] = useState(true)
  const [showAiKey, setShowAiKey] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const [auditSkills, setAuditSkills] = useState<AuditAtomizationSkillVersion[]>([])
  const [skillFile, setSkillFile] = useState<File | null>(null)
  const [skillBusy, setSkillBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([
      api.get<AuditSynologyConnectionList>('/api/audit/synology/connections'),
      api.get<AIProviderConfig>('/api/admin/integrations/ai'),
      api.get<AuditAtomizationSkillList>('/api/admin/integrations/ai/skills'),
    ])
      .then(([synologyResult, aiResult, skillsResult]) => {
        if (cancelled) return
        if (synologyResult.status === 'fulfilled') {
          const synology = synologyResult.value
          setSynologyConnections(synology.items)
          setSynologyAllowlistReady(synology.allowed_origins_configured)
          setSynologyEncryptionReady(synology.encryption_key_configured)
          const initialProfile = synology.items.find((item) => item.is_active) ?? synology.items[0]
          if (initialProfile?.id) {
            setSelectedConnectionId(initialProfile.id)
            setSynologyName(initialProfile.display_name ?? '')
            setSynologyUrl(initialProfile.base_url ?? '')
            setSynologyAccount(initialProfile.account_name ?? '')
            setSynologyRoot(initialProfile.root_path ?? '/')
          }
        } else {
          toast.error(synologyResult.reason instanceof Error ? synologyResult.reason.message : 'Не удалось загрузить Synology')
        }
        if (aiResult.status === 'fulfilled') {
          const ai = aiResult.value
          setAiConfig(ai)
          setAiDisplayName(ai.display_name ?? 'ИИ-провайдер')
          setAiUrl(ai.base_url ?? '')
          setAiModel(ai.model_name ?? '')
          setAiEnabled(ai.configured ? ai.enabled : true)
        } else {
          toast.error(aiResult.reason instanceof Error ? aiResult.reason.message : 'Не удалось загрузить ИИ-провайдера')
        }
        if (skillsResult.status === 'fulfilled') {
          setAuditSkills(skillsResult.value.items)
        } else {
          toast.error(skillsResult.reason instanceof Error ? skillsResult.reason.message : 'Не удалось загрузить skills атомизации')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const selectedSize = useMemo(
    () => Array.from(selectedFiles.values()).reduce((sum, item) => sum + item.size_bytes, 0),
    [selectedFiles]
  )
  const selectedConnection = useMemo(
    () => synologyConnections.find((item) => item.id === selectedConnectionId) ?? null,
    [selectedConnectionId, synologyConnections]
  )
  const activeSessionToken = (
    sessionToken
    && selectedConnection?.id
    && sessionConnectionId === selectedConnection.id
    && selectedConnection.is_active
  ) ? sessionToken : null

  function clearSynologySession() {
    setSessionToken(null)
    setSessionConnectionId(null)
    setBrowser(null)
    setCurrentFolderToken(null)
    setSelectedFiles(new Map())
    closePreview()
  }

  function populateSynologyForm(connection: AuditSynologyConnection) {
    if (!connection.id) return
    setSelectedConnectionId(connection.id)
    setSynologyName(connection.display_name ?? '')
    setSynologyUrl(connection.base_url ?? '')
    setSynologyAccount(connection.account_name ?? '')
    setSynologyRoot(connection.root_path ?? '/')
    setSynologyPassword('')
    setSynologyOtp('')
  }

  function updateSynologyConnection(connection: AuditSynologyConnection) {
    if (!connection.id) return
    setSynologyConnections((current) => {
      const updated = current.some((item) => item.id === connection.id)
        ? current.map((item) => item.id === connection.id ? connection : item)
        : [...current, connection]
      return updated
        .sort((left, right) => Number(right.is_active) - Number(left.is_active) || (left.display_name ?? '').localeCompare(right.display_name ?? '', 'ru'))
    })
  }

  async function closeServerSession() {
    if (!sessionToken) return
    try {
      await api.post<null>('/api/audit/synology/disconnect', { session_token: sessionToken })
    } catch {
      // Expired remote sessions are cleared locally as well.
    }
  }

  async function selectSynologyProfile(connection: AuditSynologyConnection) {
    if (!connection.id) return
    if (connection.id === selectedConnectionId) return
    if (sessionToken) await closeServerSession()
    clearSynologySession()
    populateSynologyForm(connection)
    setImportResult(null)
  }

  async function startNewSynologyProfile() {
    if (sessionToken) await closeServerSession()
    clearSynologySession()
    setSelectedConnectionId(null)
    setSynologyName('')
    setSynologyUrl('')
    setSynologyAccount('')
    setSynologyPassword('')
    setSynologyOtp('')
    setSynologyRoot('/')
    setImportResult(null)
  }

  function closePreview() {
    setPreview(null)
    setPreviewRequestId(null)
    setDigitalProduct('')
  }

  function handleSynologyError(error: unknown, fallback: string) {
    if (error instanceof ApiError && error.code && SYNOLOGY_SESSION_ERROR_CODES.has(error.code)) {
      clearSynologySession()
    }
    toast.error(error instanceof Error ? error.message : fallback)
  }

  async function loadFolder(token: string, folderToken: string | null, offset = 0) {
    setFolderBusy(true)
    try {
      const next = await api.post<AuditSynologyBrowser>('/api/audit/synology/files/list', {
        session_token: token,
        folder_token: folderToken,
        offset,
        limit: SYNOLOGY_PAGE_SIZE,
      })
      setBrowser(next)
      setCurrentFolderToken(folderToken)
    } catch (error) {
      handleSynologyError(error, 'Не удалось открыть папку')
    } finally {
      setFolderBusy(false)
    }
  }

  async function handleSynologySave(event: React.FormEvent) {
    event.preventDefault()
    setSynologyBusy(true)
    setImportResult(null)
    try {
      const payload = {
        display_name: synologyName,
        base_url: synologyUrl,
        account_name: synologyAccount,
        password: synologyPassword || null,
        otp_code: synologyOtp || null,
        root_path: synologyRoot || '/',
        expected_config_version: selectedConnectionId ? selectedConnection?.config_version : null,
      }
      const result = selectedConnectionId
        ? await api.put<AuditSynologyConnectResponse>(`/api/audit/synology/connections/${selectedConnectionId}`, payload)
        : await api.post<AuditSynologyConnectResponse>('/api/audit/synology/connections', payload)
      updateSynologyConnection(result.connection)
      populateSynologyForm(result.connection)
      setSessionToken(result.session_token)
      setSessionConnectionId(result.connection.id)
      setSynologyPassword('')
      setSynologyOtp('')
      setSelectedFiles(new Map())
      closePreview()
      if (result.connection.is_active) {
        await loadFolder(result.session_token, null)
      } else {
        setBrowser(null)
      }
      toast.success('Профиль проверен и сохранен')
    } catch (error) {
      if (error instanceof ApiError && ['two_factor_required', 'two_factor_failed'].includes(error.code ?? '')) {
        requestAnimationFrame(() => otpInputRef.current?.focus())
      }
      try {
        const current = await api.get<AuditSynologyConnectionList>('/api/audit/synology/connections')
        setSynologyConnections(current.items)
        if (error instanceof ApiError && error.code === 'profile_changed') {
          clearSynologySession()
          const refreshed = current.items.find((item) => item.id === selectedConnectionId)
          if (refreshed) populateSynologyForm(refreshed)
        }
      } catch {
        // Keep the connection error as the actionable message.
      }
      handleSynologyError(error, 'Не удалось подключить Synology')
    } finally {
      setSynologyBusy(false)
    }
  }

  async function handleActivateSynology() {
    if (!selectedConnectionId || !selectedConnection?.config_version) return
    setSynologyBusy(true)
    setImportResult(null)
    try {
      const result = await api.post<AuditSynologyConnectResponse>(`/api/audit/synology/connections/${selectedConnectionId}/activate`, {
        expected_config_version: selectedConnection.config_version,
        session_token: sessionConnectionId === selectedConnectionId ? sessionToken : null,
        otp_code: synologyOtp || null,
      })
      const current = await api.get<AuditSynologyConnectionList>('/api/audit/synology/connections')
      setSynologyConnections(current.items)
      populateSynologyForm(
        current.items.find((item) => item.id === result.connection.id) ?? result.connection
      )
      setSessionToken(result.session_token)
      setSessionConnectionId(result.connection.id)
      setSynologyOtp('')
      setSelectedFiles(new Map())
      closePreview()
      await loadFolder(result.session_token, null)
      toast.success(`Активен профиль «${result.connection.display_name}»`)
    } catch (error) {
      if (error instanceof ApiError && ['two_factor_required', 'two_factor_failed'].includes(error.code ?? '')) {
        requestAnimationFrame(() => otpInputRef.current?.focus())
      }
      if (error instanceof ApiError && error.code === 'profile_changed') {
        clearSynologySession()
        try {
          const current = await api.get<AuditSynologyConnectionList>('/api/audit/synology/connections')
          setSynologyConnections(current.items)
          const refreshed = current.items.find((item) => item.id === selectedConnectionId)
          if (refreshed) populateSynologyForm(refreshed)
        } catch {
          // Keep the original conflict as the actionable error.
        }
      }
      handleSynologyError(error, 'Не удалось активировать профиль Synology')
    } finally {
      setSynologyBusy(false)
    }
  }

  async function handleDisconnect() {
    if (!sessionToken) return
    setSynologyBusy(true)
    try {
      await api.post<null>('/api/audit/synology/disconnect', { session_token: sessionToken })
    } catch {
      // The server may already have expired the session; local state still must be cleared.
    } finally {
      clearSynologySession()
      setSynologyBusy(false)
    }
  }

  function toggleFile(item: AuditSynologyFile) {
    if (!item.selectable) return
    setSelectedFiles((current) => {
      const next = new Map(current)
      if (next.has(item.item_id)) {
        next.delete(item.item_id)
      } else if (next.size < 20) {
        next.set(item.item_id, item)
      } else {
        toast.error('За один раз можно выбрать не более 20 документов')
      }
      return next
    })
  }

  async function handlePreview() {
    if (!sessionToken || selectedFiles.size === 0) return
    setPreviewBusy(true)
    try {
      const result = await api.post<AuditSynologyPreview>('/api/audit/synology/imports/preview', {
        session_token: sessionToken,
        file_tokens: Array.from(selectedFiles.values()).map((item) => item.path_token),
      })
      setPreview(result)
      setPreviewRequestId(window.crypto.randomUUID())
    } catch (error) {
      handleSynologyError(error, 'Не удалось проверить выбранные документы')
    } finally {
      setPreviewBusy(false)
    }
  }

  async function handleImport() {
    if (!sessionToken || !preview || !previewRequestId || importInFlightRef.current) return
    importInFlightRef.current = true
    setPreviewBusy(true)
    try {
      const result = await api.post<AuditSynologyImportResult>('/api/audit/synology/imports/commit', {
        session_token: sessionToken,
        request_id: previewRequestId,
        preview_token: preview.preview_token,
        file_tokens: preview.items.map((item) => item.file_token),
        digital_product: digitalProduct.trim() || null,
      })
      setImportResult(result)
      closePreview()
      setSelectedFiles(new Map())
      await loadFolder(sessionToken, null)
      toast.success(`Создано черновиков: ${result.imported_count}`)
    } catch (error) {
      handleSynologyError(error, 'Не удалось импортировать документы')
    } finally {
      importInFlightRef.current = false
      setPreviewBusy(false)
    }
  }

  async function handleSaveAi(event: React.FormEvent) {
    event.preventDefault()
    setAiBusy(true)
    try {
      const result = await api.put<AIProviderConfig>('/api/admin/integrations/ai', {
        display_name: aiDisplayName,
        base_url: aiUrl,
        model_name: aiModel,
        api_key: aiKey || null,
        enabled: aiEnabled,
        expected_config_version: aiConfig?.config_version ?? null,
      })
      setAiConfig(result)
      setAiKey('')
      toast.success('Профиль ИИ проверен и сохранен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить ИИ-провайдера')
    } finally {
      setAiBusy(false)
    }
  }

  async function handleTestAi() {
    setAiBusy(true)
    try {
      const result = await api.post<AIProviderTestResult>('/api/admin/integrations/ai/test', {})
      setAiConfig((current) => current ? {
        ...current,
        last_test_status: 'ok',
        last_tested_at: result.tested_at,
        last_verified_config_version: current.config_version,
        ready_for_use: current.enabled,
        last_error_code: null,
      } : current)
      toast.success(result.message)
    } catch (error) {
      try {
        setAiConfig(await api.get<AIProviderConfig>('/api/admin/integrations/ai'))
      } catch {
        // Keep the original provider error as the actionable message.
      }
      toast.error(error instanceof Error ? error.message : 'Проверка ИИ-провайдера завершилась ошибкой')
    } finally {
      setAiBusy(false)
    }
  }

  async function reloadAuditSkills() {
    const result = await api.get<AuditAtomizationSkillList>('/api/admin/integrations/ai/skills')
    setAuditSkills(result.items)
  }

  async function handleImportAuditSkill() {
    if (!skillFile || skillBusy) return
    setSkillBusy(true)
    try {
      const body = new FormData()
      body.append('file', skillFile)
      const result = await api.upload<AuditAtomizationSkillVersion>('/api/admin/integrations/ai/skills/import', body)
      await reloadAuditSkills()
      setSkillFile(null)
      if (skillFileInputRef.current) skillFileInputRef.current.value = ''
      toast.success(`${result.name}: версия ${result.version} установлена`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось установить skill')
    } finally {
      setSkillBusy(false)
    }
  }

  async function handleActivateAuditSkill(version: AuditAtomizationSkillVersion) {
    if (skillBusy || version.is_active) return
    setSkillBusy(true)
    try {
      await api.post<AuditAtomizationSkillVersion>(`/api/admin/integrations/ai/skills/${version.id}/activate`, {})
      await reloadAuditSkills()
      toast.success(`${version.name}: версия ${version.version} активирована`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось активировать версию skill')
    } finally {
      setSkillBusy(false)
    }
  }

  if (loading) {
    return <div className="flex min-h-52 items-center justify-center text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Загрузка интеграций</div>
  }

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5">
      <header className="flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">Администрирование</p>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">Интеграции</h1>
        </div>
        <nav className="grid w-full grid-cols-2 items-center rounded-md border border-border bg-background p-1 sm:flex sm:w-auto" aria-label="Разделы администрирования">
          <Link to="/admin/users" className="inline-flex min-h-10 min-w-0 items-center justify-center gap-2 rounded px-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground sm:px-3">
            <Users className="h-4 w-4" />Сотрудники
          </Link>
          <span className="inline-flex min-h-10 min-w-0 items-center justify-center gap-2 rounded bg-primary px-2 text-sm font-medium text-primary-foreground sm:px-3">
            <PlugZap className="h-4 w-4" />Интеграции
          </span>
        </nav>
      </header>

      <div className="flex w-full gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Интеграции">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'synology'}
          onClick={() => setTab('synology')}
          className={cn('inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-4 text-sm font-medium', tab === 'synology' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground')}
        >
          <HardDrive className="h-4 w-4" />Synology
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'ai'}
          onClick={() => setTab('ai')}
          className={cn('inline-flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-4 text-sm font-medium', tab === 'ai' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground')}
        >
          <BrainCircuit className="h-4 w-4" />ИИ
        </button>
      </div>

      {tab === 'synology' && (
        <div className="grid gap-4 xl:grid-cols-[260px_360px_minmax(0,1fr)]">
          <aside className="self-start rounded-lg border border-border bg-background shadow-sm">
            <header className="flex min-h-14 items-center justify-between gap-2 border-b border-border px-3">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Профили Synology</h2>
                <p className="text-xs text-muted-foreground">{synologyConnections.length} сохранено</p>
              </div>
              <button type="button" onClick={startNewSynologyProfile} className="inline-flex h-10 w-10 items-center justify-center rounded-md text-primary hover:bg-muted" aria-label="Новый профиль Synology" title="Новый профиль">
                <Plus className="h-5 w-5" />
              </button>
            </header>
            <div className="space-y-1 p-2">
              {synologyConnections.length === 0 ? (
                <div className="px-3 py-8 text-center text-sm text-muted-foreground">Создайте первое подключение</div>
              ) : synologyConnections.map((connection) => (
                <button
                  key={connection.id ?? `${connection.base_url}-${connection.display_name}`}
                  type="button"
                  onClick={() => selectSynologyProfile(connection)}
                  className={cn(
                    'w-full rounded-md border px-3 py-2.5 text-left transition-colors',
                    selectedConnectionId === connection.id
                      ? 'border-primary/40 bg-primary/5'
                      : 'border-transparent hover:bg-muted/70'
                  )}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium text-foreground">{connection.display_name}</span>
                    {connection.is_active ? (
                      <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">Активен</span>
                    ) : connection.last_test_status === 'ok' ? (
                      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">OK</span>
                    ) : connection.last_test_status === 'error' ? (
                      <span className="shrink-0 rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-950 dark:text-red-200">Ошибка</span>
                    ) : (
                      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">Не проверен</span>
                    )}
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">{connection.base_url}</span>
                </button>
              ))}
            </div>
            <div className="space-y-2 border-t border-border p-3">
              <IntegrationStatus ok={synologyAllowlistReady}>HTTPS allowlist {synologyAllowlistReady ? 'настроен' : 'не настроен'}</IntegrationStatus>
              <IntegrationStatus ok={synologyEncryptionReady}>Шифрование {synologyEncryptionReady ? 'настроено' : 'не настроено'}</IntegrationStatus>
            </div>
          </aside>

          <form onSubmit={handleSynologySave} className="self-start space-y-4 rounded-lg border border-border bg-background p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Server className="h-5 w-5 text-primary" />
                <h2 className="font-semibold text-foreground">{selectedConnection ? 'Параметры профиля' : 'Новый профиль'}</h2>
              </div>
              {selectedConnection?.last_test_status && (
                <span className={cn('rounded px-2 py-1 text-xs font-medium', selectedConnection.last_test_status === 'ok' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200')}>
                  {selectedConnection.last_test_status === 'ok' ? 'OK' : 'Ошибка'}
                </span>
              )}
            </div>
            <label className="block text-sm font-medium text-foreground">Название профиля
              <input name="synology_profile_name" value={synologyName} onChange={(event) => setSynologyName(event.target.value)} placeholder="Основное хранилище" autoComplete="off" className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" required />
            </label>
            <label className="block text-sm font-medium text-foreground">URL
              <input name="synology_url" type="url" value={synologyUrl} onChange={(event) => setSynologyUrl(event.target.value)} placeholder="https://nas.example.org:5001" autoCapitalize="none" autoComplete="off" spellCheck={false} className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" required />
              <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">Полный HTTPS-адрес с портом, без пути к File Station.</span>
            </label>
            <label className="block text-sm font-medium text-foreground">Имя пользователя
              <input name="synology_account" value={synologyAccount} onChange={(event) => setSynologyAccount(event.target.value)} autoCapitalize="none" spellCheck={false} autoComplete="off" className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" required />
            </label>
            <label className="block text-sm font-medium text-foreground">Пароль
              <span className="relative mt-1 block">
                <input name="synology_password" type={showSynologyPassword ? 'text' : 'password'} value={synologyPassword} onChange={(event) => setSynologyPassword(event.target.value)} placeholder={selectedConnection?.credential_saved ? 'Сохранен; оставьте пустым без изменений' : ''} autoComplete="new-password" className="h-11 w-full rounded-md border border-input bg-background px-3 pr-12 text-base sm:text-sm" required={!selectedConnection?.credential_saved} />
                <button type="button" onPointerDown={() => setShowSynologyPassword(true)} onPointerUp={() => setShowSynologyPassword(false)} onPointerCancel={() => setShowSynologyPassword(false)} onPointerLeave={() => setShowSynologyPassword(false)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setShowSynologyPassword(true) }} onKeyUp={() => setShowSynologyPassword(false)} onBlur={() => setShowSynologyPassword(false)} className="absolute right-1 top-1 inline-flex h-9 w-9 items-center justify-center rounded text-muted-foreground hover:bg-muted" aria-label="Показать пароль во время удерживания">
                  {showSynologyPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </span>
            </label>
            <label className="block text-sm font-medium text-foreground">2FA-код
              <input ref={otpInputRef} name="synology_otp" value={synologyOtp} onChange={(event) => setSynologyOtp(event.target.value.replace(/\s/g, ''))} inputMode="numeric" autoComplete="one-time-code" className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" />
            </label>
            <label className="block text-sm font-medium text-foreground">Корневая папка
              <input name="synology_root" value={synologyRoot} onChange={(event) => setSynologyRoot(event.target.value)} placeholder="/" autoComplete="off" className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 font-mono text-base sm:text-sm" required />
            </label>
            <p className="text-xs leading-5 text-muted-foreground">Пароль сохраняется зашифрованно. 2FA-код одноразовый и не сохраняется. Сессия закрывается после 30 минут бездействия.</p>
            <div className="space-y-2 border-t border-border pt-4">
              <button type="submit" disabled={synologyBusy} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-primary/30 px-4 text-sm font-medium text-primary hover:bg-primary/5 disabled:opacity-50">
                {synologyBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                Проверить и сохранить
              </button>
              {selectedConnection && (
                <div className="flex gap-2">
                  <button type="button" onClick={handleActivateSynology} disabled={synologyBusy || !selectedConnection.id || !selectedConnection.credential_saved} className={cn('inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:opacity-50', selectedConnection.is_active ? 'border border-emerald-300 text-emerald-800 hover:bg-emerald-50 dark:border-emerald-800 dark:text-emerald-200 dark:hover:bg-emerald-950/30' : 'bg-primary text-primary-foreground')}>
                    {synologyBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
                    {selectedConnection.is_active ? 'Подключить активный' : 'Активировать'}
                  </button>
                  {sessionToken && sessionConnectionId === selectedConnection.id && (
                    <button type="button" onClick={handleDisconnect} className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Завершить сессию Synology" title="Завершить сессию">
                      <LogOut className="h-4 w-4" />
                    </button>
                  )}
                </div>
              )}
            </div>
          </form>

          <section className="min-w-0 rounded-lg border border-border bg-background shadow-sm">
            <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate font-semibold text-foreground">{browser?.current_folder_name ?? 'Каталоги Synology'}</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {activeSessionToken
                    ? `${browser?.total ?? 0} элементов · выбрано ${selectedFiles.size} (${formatBytes(selectedSize)})`
                    : selectedConnection?.is_active
                      ? 'Подключите активный профиль, чтобы открыть дерево каталогов'
                      : selectedConnection?.last_test_status === 'ok'
                        ? 'Профиль проверен. Активируйте его для работы с файлами'
                        : 'Проверьте и активируйте профиль для работы с файлами'}
                </p>
              </div>
              {activeSessionToken && <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">Сессия активна</span>}
            </header>

            {!activeSessionToken ? (
              <div className="flex min-h-[420px] flex-col items-center justify-center px-6 text-center text-muted-foreground">
                <HardDrive className="h-9 w-9" />
                <p className="mt-3 text-sm">
                  {selectedConnection?.last_test_status === 'ok' && !selectedConnection.is_active
                    ? 'Подключение проверено. Нажмите «Активировать».'
                    : 'Нет активного подключения'}
                </p>
              </div>
            ) : (
              <>
                <div className="flex min-h-12 items-center gap-2 border-b border-border px-3">
                  <button type="button" disabled={!browser?.parent_token || folderBusy} onClick={() => browser?.parent_token && loadFolder(activeSessionToken, browser.parent_token)} className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted disabled:opacity-30" aria-label="На уровень выше" title="На уровень выше">
                    <ChevronLeft className="h-5 w-5" />
                  </button>
                  <button type="button" disabled={folderBusy} onClick={() => loadFolder(activeSessionToken, currentFolderToken, browser?.offset ?? 0)} className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted disabled:opacity-50" aria-label="Обновить список" title="Обновить">
                    <RefreshCw className={cn('h-4 w-4', folderBusy && 'animate-spin')} />
                  </button>
                  <span className="truncate text-sm text-muted-foreground">{browser?.root_folder_name}</span>
                </div>
                <div className="max-h-[520px] min-h-[360px] overflow-y-auto">
                  {folderBusy && !browser ? (
                    <div className="flex min-h-56 items-center justify-center text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Открываем каталог</div>
                  ) : browser?.items.length ? (
                    <ul className="divide-y divide-border">
                      {browser.items.map((item) => {
                        const checked = selectedFiles.has(item.item_id)
                        return (
                          <li key={item.item_id}>
                            {item.is_dir ? (
                              <button type="button" onClick={() => loadFolder(activeSessionToken, item.path_token)} className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left hover:bg-muted/60">
                                <Folder className="h-5 w-5 shrink-0 text-amber-500" />
                                <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{item.name}</span>
                              </button>
                            ) : (
                              <label className={cn('flex min-h-16 items-center gap-3 px-4 py-2', item.selectable ? 'cursor-pointer hover:bg-muted/60' : 'opacity-55')}>
                                <input type="checkbox" checked={checked} disabled={!item.selectable} onChange={() => toggleFile(item)} className="h-5 w-5 rounded border-input text-primary focus:ring-primary" />
                                <File className="h-5 w-5 shrink-0 text-muted-foreground" />
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-sm font-medium text-foreground">{item.name}</span>
                                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">{item.disabled_reason ?? `${formatBytes(item.size_bytes)} · ${formatTimestamp(item.modified_at)}`}</span>
                                </span>
                              </label>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  ) : (
                    <div className="flex min-h-56 items-center justify-center text-sm text-muted-foreground">Папка пуста</div>
                  )}
                </div>
                {browser && browser.total > SYNOLOGY_PAGE_SIZE && (
                  <div className="flex min-h-12 items-center justify-between gap-3 border-t border-border px-3 text-xs text-muted-foreground">
                    <span>
                      {browser.total === 0 ? 0 : browser.offset + 1}-{Math.min(browser.offset + browser.items.length, browser.total)} из {browser.total}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        disabled={folderBusy || browser.offset === 0}
                        onClick={() => loadFolder(activeSessionToken, currentFolderToken, Math.max(0, browser.offset - SYNOLOGY_PAGE_SIZE))}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted disabled:opacity-30"
                        aria-label="Предыдущая страница"
                        title="Предыдущая страница"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        disabled={folderBusy || browser.offset + browser.items.length >= browser.total}
                        onClick={() => loadFolder(activeSessionToken, currentFolderToken, browser.offset + browser.items.length)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted disabled:opacity-30"
                        aria-label="Следующая страница"
                        title="Следующая страница"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                )}
                <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
                  <button type="button" onClick={() => setSelectedFiles(new Map())} disabled={selectedFiles.size === 0} className="min-h-10 px-2 text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-40">Очистить выбор</button>
                  <button type="button" onClick={handlePreview} disabled={previewBusy || selectedFiles.size === 0 || selectedSize > 100 * 1024 * 1024} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                    {previewBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                    Проверить выбор
                  </button>
                </footer>
              </>
            )}
          </section>

          {importResult && (
            <section className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100 xl:col-start-3">
              <h3 className="font-semibold">Импорт завершен</h3>
              <p className="mt-1 text-sm">Создано черновиков: {importResult.imported_count}. Общий объем: {formatBytes(importResult.total_size_bytes)}.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {importResult.items.map((item) => <span key={item.case_id} className="rounded border border-emerald-300 px-2 py-1 text-xs font-medium dark:border-emerald-800">{item.case_number}</span>)}
              </div>
            </section>
          )}
        </div>
      )}

      {tab === 'ai' && (
        <div className="max-w-4xl space-y-5">
        <form onSubmit={handleSaveAi} className="space-y-5 rounded-lg border border-border bg-background p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <BrainCircuit className="h-5 w-5 text-primary" />
              <h2 className="font-semibold text-foreground">OpenAI-compatible API</h2>
            </div>
            {aiConfig?.configured && (
              <span className={cn(
                'rounded px-2 py-1 text-xs font-medium',
                aiConfig.ready_for_use
                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                  : aiConfig.last_test_status === 'error'
                    ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200'
                    : 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100'
              )}>
                {aiConfig.ready_for_use
                  ? 'OK · активно'
                  : aiConfig.last_test_status === 'error'
                    ? 'Ошибка проверки'
                    : aiConfig.last_test_status === 'ok' && !aiConfig.enabled
                      ? 'OK · отключено'
                      : 'Требуется проверка'}
              </span>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-foreground">Название
              <input value={aiDisplayName} onChange={(event) => setAiDisplayName(event.target.value)} className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" required />
            </label>
            <label className="block text-sm font-medium text-foreground">Модель
              <input value={aiModel} onChange={(event) => setAiModel(event.target.value)} placeholder="model-id" autoCapitalize="none" spellCheck={false} className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 font-mono text-base sm:text-sm" required />
            </label>
          </div>
          <label className="block text-sm font-medium text-foreground">API URL
            <input value={aiUrl} onChange={(event) => setAiUrl(event.target.value)} placeholder="https://provider.example/v1" autoCapitalize="none" spellCheck={false} className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 font-mono text-base sm:text-sm" required />
          </label>
          <label className="block text-sm font-medium text-foreground">API key
            <span className="relative mt-1 block">
              <input type={showAiKey ? 'text' : 'password'} value={aiKey} onChange={(event) => setAiKey(event.target.value)} placeholder={aiConfig?.api_key_configured ? 'Ключ сохранен; оставьте пустым без изменений' : ''} autoComplete="new-password" className="h-11 w-full rounded-md border border-input bg-background px-3 pr-12 text-base sm:text-sm" required={!aiConfig?.api_key_configured} />
              <button type="button" onPointerDown={() => setShowAiKey(true)} onPointerUp={() => setShowAiKey(false)} onPointerCancel={() => setShowAiKey(false)} onPointerLeave={() => setShowAiKey(false)} className="absolute right-1 top-1 inline-flex h-9 w-9 items-center justify-center rounded text-muted-foreground hover:bg-muted" aria-label="Показать API key во время удерживания">
                {showAiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </span>
          </label>
          <label className="flex min-h-11 items-center gap-3 text-sm font-medium text-foreground">
            <input type="checkbox" checked={aiEnabled} onChange={(event) => setAiEnabled(event.target.checked)} className="h-5 w-5 rounded border-input text-primary focus:ring-primary" />
            Подключение активно
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <IntegrationStatus ok={Boolean(aiConfig?.allowed_origins_configured)}>HTTPS allowlist {aiConfig?.allowed_origins_configured ? 'настроен' : 'не настроен на backend'}</IntegrationStatus>
            <IntegrationStatus ok={Boolean(aiConfig?.encryption_key_configured)}>Ключ интеграций {aiConfig?.encryption_key_configured ? 'настроен' : 'не настроен на backend'}</IntegrationStatus>
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <button type="button" onClick={handleTestAi} disabled={aiBusy || !aiConfig?.configured} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">
              {aiBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Повторить проверку
            </button>
            <button type="submit" disabled={aiBusy} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {aiBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Проверить и сохранить
            </button>
          </div>
        </form>

        <section className="rounded-lg border border-border bg-background shadow-sm" aria-labelledby="audit-skills-title">
          <header className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
            <div className="flex min-w-0 items-start gap-3">
              <FileJson2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div>
                <h2 id="audit-skills-title" className="font-semibold text-foreground">Skills атомизации аудита</h2>
                <p className="mt-1 text-sm text-muted-foreground">Декларативные правила разбора ТЗ. Skill не исполняет программный код.</p>
              </div>
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">JSON · schema 1.0</span>
          </header>

          <div className="space-y-4 px-4 py-4 sm:px-5">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <label className="block text-sm font-medium text-foreground">
                Новая версия skill
                <input
                  ref={skillFileInputRef}
                  type="file"
                  accept=".json,application/json"
                  onChange={(event) => setSkillFile(event.target.files?.[0] ?? null)}
                  className="mt-1 min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-base text-foreground file:mr-3 file:border-0 file:bg-muted file:px-3 file:py-2 file:text-sm file:font-medium sm:text-sm"
                />
              </label>
              <button
                type="button"
                onClick={() => void handleImportAuditSkill()}
                disabled={!skillFile || skillBusy}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {skillBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                Установить версию
              </button>
            </div>

            {auditSkills.length === 0 ? (
              <div className="border-l-2 border-amber-500 bg-amber-500/5 px-4 py-3 text-sm text-muted-foreground">
                Skills пока не установлены. Без активной версии запуск ИИ-атомизации недоступен.
              </div>
            ) : (
              <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                {auditSkills.map((version) => (
                  <div key={version.id} className="grid gap-3 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-foreground">{version.name}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">v{version.version}</span>
                        {version.is_active ? (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">Активна</span>
                        ) : null}
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground" title={version.description ?? version.source_filename}>
                        {version.description || version.source_filename} · SHA {version.content_sha256.slice(0, 12)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleActivateAuditSkill(version)}
                      disabled={skillBusy || version.is_active || !version.is_enabled}
                      className={cn(
                        'inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:opacity-50',
                        version.is_active
                          ? 'border border-emerald-300 text-emerald-800 dark:border-emerald-800 dark:text-emerald-200'
                          : 'border border-border text-foreground hover:bg-muted'
                      )}
                    >
                      <Power className="h-4 w-4" />
                      {version.is_active ? 'Используется' : 'Активировать'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
        </div>
      )}

      {preview && (
        <ProtectedDialog title="Подтверждение импорта" onClose={() => {
          if (!previewBusy) {
            closePreview()
          }
        }}>
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-border bg-muted/40 p-3"><div className="text-xs text-muted-foreground">Документов</div><div className="mt-1 text-xl font-semibold text-foreground">{preview.file_count}</div></div>
              <div className="rounded-md border border-border bg-muted/40 p-3"><div className="text-xs text-muted-foreground">Общий объем</div><div className="mt-1 text-xl font-semibold text-foreground">{formatBytes(preview.total_size_bytes)}</div></div>
            </div>
            <label className="block text-sm font-medium text-foreground">Цифровой продукт
              <input value={digitalProduct} onChange={(event) => setDigitalProduct(event.target.value)} placeholder="Можно заполнить позднее" className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm" />
            </label>
            <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
              {preview.items.map((item) => (
                <li key={item.file_token} className="flex items-center gap-3 px-3 py-2">
                  <File className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate text-sm text-foreground">{item.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(item.size_bytes)}</span>
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <button type="button" onClick={() => {
                closePreview()
              }} disabled={previewBusy} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">Отмена</button>
              <button type="button" onClick={handleImport} disabled={previewBusy} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {previewBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                Импортировать
              </button>
            </div>
          </div>
        </ProtectedDialog>
      )}
    </div>
  )
}
