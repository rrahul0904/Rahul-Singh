/**
 * UMA Platform — API Client
 * Connects the React frontend to the FastAPI backend
 */

import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'uma.accessToken'

export const api = axios.create({
  baseURL: `${BASE}/api`,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem(TOKEN_KEY) : null
  if (token) {
    config.headers = config.headers || ({} as any)
    ;(config.headers as any).Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && typeof window !== 'undefined') {
      window.localStorage.removeItem(TOKEN_KEY)
      window.localStorage.removeItem('uma.currentUser')
    }
    return Promise.reject(error)
  }
)

// ── Auth

export const register = (data: any) => api.post('/auth/register', data).then(r => r.data)
export const login = (data: any) => api.post('/auth/login', data).then(r => r.data)
export const me = () => api.get('/auth/me').then(r => r.data)

// ── Connections ──────────────────────────────────────────────

export const getConnections      = ()         => api.get('/connections').then(r => r.data)
export const createConnection    = (data: any) => api.post('/connections', data).then(r => r.data)
export const updateConnection    = (id: string, data: any) => api.put(`/connections/${id}`, data).then(r => r.data)
export const deleteConnection    = (id: string) => api.delete(`/connections/${id}`)
export const testConnection      = (id: string, data: any = {}) => api.post(`/connections/${id}/test`, data).then(r => r.data)

// ── Jobs ─────────────────────────────────────────────────────

export const getJobs             = (params?: any)  => api.get('/jobs', { params }).then(r => r.data)
export const getJob              = (id: string)    => api.get(`/jobs/${id}`).then(r => r.data)
export const createJob           = (data: any)     => api.post('/jobs', data).then(r => r.data)
export const executeJob          = (id: string)    => api.post(`/jobs/${id}/execute`).then(r => r.data)
export const deleteJob           = (id: string)    => api.delete(`/jobs/${id}`)
export const getJobTasks         = (id: string)    => api.get(`/jobs/${id}/tasks`).then(r => r.data)
export const addJobTask          = (id: string, data: any) => api.post(`/jobs/${id}/tasks`, data).then(r => r.data)
export const getJobLogs          = (id: string, params?: any) => api.get(`/jobs/${id}/logs`, { params }).then(r => r.data)
export const getJobStats         = ()             => api.get('/jobs/stats/summary').then(r => r.data)

// ── Tables ───────────────────────────────────────────────────

export const getTables           = (params?: any) => api.get('/tables', { params }).then(r => r.data)
export const getTableStats       = ()             => api.get('/tables/stats').then(r => r.data)
export const getCatalogTables    = (params?: any) => api.get('/catalog/tables', { params }).then(r => r.data)
export const getCatalogSummary   = ()             => api.get('/catalog/tables/summary').then(r => r.data)
export const getCatalogTable     = (id: string)   => api.get(`/catalog/tables/${encodeURIComponent(id)}`).then(r => r.data)
export const getCatalogColumns   = (id: string)   => api.get(`/catalog/tables/${encodeURIComponent(id)}/columns`).then(r => r.data)
export const getCatalogRuns      = (id: string)   => api.get(`/catalog/tables/${encodeURIComponent(id)}/runs`).then(r => r.data)
export const getCatalogLineage   = (id: string)   => api.get(`/catalog/tables/${encodeURIComponent(id)}/lineage`).then(r => r.data)

// ── Validation ───────────────────────────────────────────────

export const getValidationRules  = ()             => api.get('/validation').then(r => r.data)
export const createValidationRule = (data: any)   => api.post('/validation', data).then(r => r.data)
export const runValidationRule   = (id: string)   => api.post(`/validation/${id}/run`).then(r => r.data)

// ── AI ───────────────────────────────────────────────────────

export const aiChat              = (messages: any[]) => api.post('/ai/chat', { messages }).then(r => r.data)
export const generateSQL         = (prompt: string, database?: string, schema?: string) =>
  api.post('/ai/sql-generate', null, { params: { prompt, database, schema } }).then(r => r.data)
export const getCopilotProviders = () => api.get('/copilot/providers').then(r => r.data)
export const getCopilotSnowflakeServices = () => api.get('/copilot/snowflake-services').then(r => r.data)
export const queryCopilotSnowflakeService = (data: any) => api.post('/copilot/snowflake-services/query', data).then(r => r.data)
export const askCopilot          = (data: any) => api.post('/copilot/ask', data).then(r => r.data)
export const previewCopilotAction = (data: any) => api.post('/copilot/actions/preview', data).then(r => r.data)
export const executeCopilotAction = (data: any) => api.post('/copilot/actions/execute', data).then(r => r.data)
export const getOllamaHealth = () => api.get('/ai/providers/ollama/health').then(r => r.data)
export const getAiProviderStatus = (provider = '') => api.get('/ai/providers/status', { params: provider ? { provider } : {} }).then(r => r.data)
export const getRagStatus = () => api.get('/rag/status').then(r => r.data)
export const indexRagRun = (id: string) => api.post(`/rag/index/run/${encodeURIComponent(id)}`).then(r => r.data)
export const searchRag = (params: any) => api.get('/rag/search', { params }).then(r => r.data)
export const getInternalToolRegistryStatus = () => api.get('/internal-tools/status').then(r => r.data)
export const callInternalTool = (data: any) => api.post('/internal-tools/call', data).then(r => r.data)
export const cortexAgent = (message: string, context: any = {}) => api.post('/ai/cortex-agent', { message, context }).then(r => r.data)
export const cortexAgentArchitecture = () => api.get('/ai/cortex-agent/architecture').then(r => r.data)
export const cortexAgentReadiness = () => api.get('/ai/cortex-agent/readiness').then(r => r.data)
export const codeGeneration = (data: any) => api.post('/ai/code-generation', data).then(r => r.data)
export const listCodeGenerationArtifacts = () => api.get('/ai/code-generation/artifacts').then(r => r.data)
export const getCodeGenerationArtifact = (id: string) => api.get(`/ai/code-generation/artifacts/${id}`).then(r => r.data)
export const submitJudgePass = (id: string, data: any) => api.post(`/ai/code-generation/artifacts/${id}/judge-pass`, data).then(r => r.data)
export const reviseCodeGenerationArtifact = (id: string, data: any = {}) => api.post(`/ai/code-generation/artifacts/${id}/revise`, data).then(r => r.data)

// ── Health ───────────────────────────────────────────────────

export const getHealth           = () => api.get('/health').then(r => r.data)

// ── SQL Workspace ───────────────────────────────────────────
export const workspaceConnections = () => api.get('/workspace/connections').then(r => r.data)
export const workspaceDatabases = (id: string) => api.get(`/workspace/${encodeURIComponent(id)}/databases`).then(r => r.data)
export const workspaceSchemas = (id: string, database = '') =>
  api.get(`/workspace/${encodeURIComponent(id)}/schemas`, { params: database ? { database } : {} }).then(r => r.data)
export const workspaceTables = (id: string, database = '', schemaName = '') =>
  api.get(`/workspace/${encodeURIComponent(id)}/tables`, { params: { database, schema_name: schemaName } }).then(r => r.data)
export const workspaceColumns = (id: string, table: string, database = '', schemaName = '') =>
  api.get(`/workspace/${encodeURIComponent(id)}/tables/${encodeURIComponent(table)}/columns`, { params: { database, schema_name: schemaName } }).then(r => r.data)
export const workspacePreview = (id: string, data: any) => api.post(`/workspace/${encodeURIComponent(id)}/preview`, data).then(r => r.data)
export const workspaceQuery = (id: string, data: any) => api.post(`/workspace/${encodeURIComponent(id)}/query`, data).then(r => r.data)
export const createSnowflakeWorkspaceSession = (data: any) => api.post('/snowflake/workspace-session', data).then(r => r.data)
export const closeSnowflakeWorkspaceSession = (id: string) => api.delete(`/snowflake/workspace-session/${encodeURIComponent(id)}`).then(r => r.data)
export const getSnowflakeWorkspaceSessionStatus = (connectionId = '') =>
  api.get('/snowflake/workspace-session/status', { params: connectionId ? { connection_id: connectionId } : {} }).then(r => r.data)
export const aiSQL = (data: any) => api.post('/ai/sql', data).then(r => r.data)

// ── Schedule ─────────────────────────────────────────────────
export const updateJobSchedule = (id: string, schedule_cron: string | null) =>
  api.put(`/jobs/${id}/schedule`, { schedule_cron }).then(r => r.data)

// ── Files ────────────────────────────────────────────────────
export const uploadFile = (formData: FormData) =>
  api.post('/files/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(r => r.data)


export const impersonateUser = (id: string) => api.post(`/auth/impersonate/${id}`).then(r => r.data)
export const getSettings = () => api.get('/settings').then(r => r.data)
export const saveSettings = (data: any) => api.put('/settings', data).then(r => r.data)
export const getSettingsHistory = () => api.get('/settings/history').then(r => r.data)
export const testEmail = () => api.post('/settings/test-email').then(r => r.data)
export const testSlack = () => api.post('/settings/test-slack').then(r => r.data)
export const getSyncProfiles = () => api.get('/syncs/profiles').then(r => r.data)
export const createSyncProfile = (data: any) => api.post('/syncs/profiles', data).then(r => r.data)
export const runSyncProfile = (id: string) => api.post(`/syncs/profiles/${id}/run`).then(r => r.data)
export const getSyncRuns = (id: string) => api.get(`/syncs/profiles/${id}/runs`).then(r => r.data)
export const getReplicationOverview = () => api.get('/replication/overview').then(r => r.data)
export const getReplicationConnections = () => api.get('/replication/connections').then(r => r.data)
export const createReplicationConnection = (data: any) => api.post('/replication/connections', data).then(r => r.data)
export const testReplicationConnection = (id: string) => api.post(`/replication/connections/${id}/test`).then(r => r.data)
export const getReplicationSources = () => api.get('/replication/sources').then(r => r.data)
export const discoverReplicationSource = (data: any) => api.post('/replication/sources/discover', data).then(r => r.data)
export const getReplicationJobs = () => api.get('/replication/jobs').then(r => r.data)
export const createReplicationJob = (data: any) => api.post('/replication/jobs', data).then(r => r.data)
export const getReplicationJob = (id: string) => api.get(`/replication/jobs/${id}`).then(r => r.data)
export const startReplicationJob = (id: string, data: any = {}) => api.post(`/replication/jobs/${id}/start`, data).then(r => r.data)
export const pauseReplicationJob = (id: string) => api.post(`/replication/jobs/${id}/pause`).then(r => r.data)
export const resumeReplicationJob = (id: string) => api.post(`/replication/jobs/${id}/resume`).then(r => r.data)
export const cancelReplicationJob = (id: string) => api.post(`/replication/jobs/${id}/cancel`).then(r => r.data)
export const retryReplicationJob = (id: string) => api.post(`/replication/jobs/${id}/retry`).then(r => r.data)
export const getReplicationJobTables = (id: string) => api.get(`/replication/jobs/${id}/tables`).then(r => r.data)
export const updateReplicationJobTables = (id: string, data: any) => api.put(`/replication/jobs/${id}/tables`, data).then(r => r.data)
export const getReplicationJobPlan = (id: string) => api.get(`/replication/jobs/${id}/plan`).then(r => r.data)
export const createReplicationJobPlan = (id: string) => api.post(`/replication/jobs/${id}/plan`).then(r => r.data)
export const getReplicationJobMapping = (id: string) => api.get(`/replication/jobs/${id}/mapping`).then(r => r.data)
export const getReplicationJobEvents = (id: string) => api.get(`/replication/jobs/${id}/events`).then(r => r.data)
export const getReplicationJobErrors = (id: string) => api.get(`/replication/jobs/${id}/errors`).then(r => r.data)
export const getReplicationRuns = () => api.get('/replication/runs').then(r => r.data)
export const getReplicationRun = (id: string) => api.get(`/replication/runs/${id}`).then(r => r.data)
export const getReplicationRunEvents = (id: string) => api.get(`/replication/runs/${id}/events`).then(r => r.data)
export const getReplicationRunTables = (id: string) => api.get(`/replication/runs/${id}/tables`).then(r => r.data)
export const getReplicationSnowflakeReadiness = () => api.get('/replication/snowflake/readiness').then(r => r.data)
export const checkReplicationSnowflakePermissions = (data: any) => api.post('/replication/snowflake/check-permissions', data).then(r => r.data)
export const navDatabases = (id: string, auth: any = {}) => api.post(`/snowflake/navigator/${id}/databases`, auth).then(r => r.data)
export const navSchemas = (id: string, db: string, auth: any = {}) => api.post(`/snowflake/navigator/${id}/schemas/${encodeURIComponent(db)}`, auth).then(r => r.data)
export const navTables = (id: string, db: string, schema: string, auth: any = {}) => api.post(`/snowflake/navigator/${id}/tables/${encodeURIComponent(db)}/${encodeURIComponent(schema)}`, auth).then(r => r.data)
export const navDescribe = (id: string, db: string, schema: string, table: string, auth: any = {}) => api.post(`/snowflake/navigator/${id}/describe/${encodeURIComponent(db)}/${encodeURIComponent(schema)}/${encodeURIComponent(table)}`, auth).then(r => r.data)
export const navPreview = (id: string, db: string, schema: string, table: string, limit = 50, auth: any = {}) => api.post(`/snowflake/navigator/${id}/preview/${encodeURIComponent(db)}/${encodeURIComponent(schema)}/${encodeURIComponent(table)}?limit=${limit}`, auth).then(r => r.data)
export const snowflakeReadiness = (data: any) => api.post('/snowflake/readiness', data).then(r => r.data)

// ── Agentic migration orchestrator ──────────────────────────
export const getAgentRuns = () => api.get('/agent-runs').then(r => r.data)
export const startAgentRun = (data: any) => api.post('/agent-runs/start', data).then(r => r.data)
export const getAgentRun = (id: string) => api.get(`/agent-runs/${id}`).then(r => r.data)
export const getAgentSteps = (id: string) => api.get(`/agent-runs/${id}/steps`).then(r => r.data)
export const getAgentToolCalls = (id: string) => api.get(`/agent-runs/${id}/tool-calls`).then(r => r.data)
export const approveAgentRun = (id: string, data: any = { approved: true }) => api.post(`/agent-runs/${id}/approve`, data).then(r => r.data)
export const retryAgentRun = (id: string) => api.post(`/agent-runs/${id}/retry`).then(r => r.data)

// ── Migration Intelligence ─────────────────────────────────
export const uploadIntelligenceArtifact = (formData: FormData) =>
  api.post('/intelligence/artifacts/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(r => r.data)

export const listIntelligenceArtifacts = () => api.get('/intelligence/artifacts').then(r => r.data)
export const getIntelligenceArtifact = (id: string) => api.get(`/intelligence/artifacts/${encodeURIComponent(id)}`).then(r => r.data)
export const createIntelligenceRun = (data: any) => api.post('/intelligence/runs', data).then(r => r.data)
export const listIntelligenceRuns = () => api.get('/intelligence/runs').then(r => r.data)
export const getIntelligenceRun = (id: string) => api.get(`/intelligence/runs/${encodeURIComponent(id)}`).then(r => r.data)
export const getIntelligenceRunSteps = (id: string) => api.get(`/intelligence/runs/${encodeURIComponent(id)}/steps`).then(r => r.data)
export const getIntelligenceRunFindings = (id: string) => api.get(`/intelligence/runs/${encodeURIComponent(id)}/findings`).then(r => r.data)
export const getIntelligenceReport = (id: string) => api.get(`/intelligence/reports/${encodeURIComponent(id)}`).then(r => r.data)
export const previewIntelligenceReport = (id: string) => api.get(`/intelligence/reports/${encodeURIComponent(id)}/preview`).then(r => r.data)

export const downloadIntelligenceReport = async (reportId: string, format: 'md' | 'pdf' | 'docx') => {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem(TOKEN_KEY) : null
  const response = await api.get(`/intelligence/reports/${encodeURIComponent(reportId)}/download.${format}`, {
    responseType: 'blob',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  const disposition = response.headers['content-disposition'] || ''
  const fileNameMatch = disposition.match(/filename=\"?([^"]+)\"?/)
  const fileName = fileNameMatch?.[1] || `${reportId}.${format}`
  const href = window.URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(href)
  return fileName
}

// ── Migration Control Plane ─────────────────────────────────
export const uploadControlPlaneArtifact = (formData: FormData) =>
  api.post('/artifacts/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(r => r.data)

export const listControlPlaneArtifacts = () => api.get('/artifacts').then(r => r.data)
export const getControlPlaneRuns = () => api.get('/control-plane/runs').then(r => r.data)
export const getControlPlaneRun = (id: string) => api.get(`/control-plane/runs/${encodeURIComponent(id)}`).then(r => r.data)
export const getControlPlaneRunDetail = (id: string) => api.get(`/control-plane/runs/${encodeURIComponent(id)}/detail`).then(r => r.data)
export const getControlPlaneRunJobs = (id: string) => api.get(`/control-plane/runs/${encodeURIComponent(id)}/jobs`).then(r => r.data)
export const getControlPlaneRunArtifacts = (id: string) => api.get(`/control-plane/runs/${encodeURIComponent(id)}/artifacts`).then(r => r.data)
export const getDialectCapabilities = () => api.get('/control-plane/dialect-capabilities').then(r => r.data)
export const linkReplicationToRun = (id: string, data: any) => api.post(`/control-plane/runs/${encodeURIComponent(id)}/link-replication`, data).then(r => r.data)
export const linkScopeToRun = (id: string, data: any) => api.post(`/control-plane/runs/${encodeURIComponent(id)}/link-scope`, data).then(r => r.data)
export const previewControlPlaneArtifact = (id: string) => api.get(`/artifacts/${encodeURIComponent(id)}/preview`).then(r => r.data)
export const downloadControlPlaneArtifact = async (id: string, fallbackName = 'artifact') => {
  const response = await api.get(`/artifacts/${encodeURIComponent(id)}/download`, { responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const fileNameMatch = disposition.match(/filename=\"?([^"]+)\"?/)
  const fileName = fileNameMatch?.[1] || fallbackName
  const href = window.URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(href)
  return fileName
}

export const createSqlConversionRun = (data: any) => api.post('/sql-conversion/runs', data).then(r => r.data)
export const analyzeSqlConversionRun = (id: string, data: any = {}) => api.post(`/sql-conversion/runs/${encodeURIComponent(id)}/analyze`, data).then(r => r.data)
export const translateSqlConversionRun = (id: string, data: any = {}) => api.post(`/sql-conversion/runs/${encodeURIComponent(id)}/translate`, data).then(r => r.data)
export const listSqlConversionRuns = () => api.get('/sql-conversion/runs').then(r => r.data)
export const getSqlConversionMessages = (id: string) => api.get(`/sql-conversion/runs/${encodeURIComponent(id)}/messages`).then(r => r.data)
export const getSqlConversionArtifacts = (id: string) => api.get(`/sql-conversion/runs/${encodeURIComponent(id)}/artifacts`).then(r => r.data)
export const getSqlConversionReport = (id: string) => api.get(`/sql-conversion/runs/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createMigrationControlRun = (data: any) => api.post('/migration-intelligence/runs', data).then(r => r.data)
export const executeMigrationControlRun = (id: string, data: any = {}) => api.post(`/migration-intelligence/runs/${encodeURIComponent(id)}/execute`, data).then(r => r.data)
export const listMigrationControlRuns = () => api.get('/migration-intelligence/runs').then(r => r.data)
export const getMigrationControlReport = (id: string) => api.get(`/migration-intelligence/runs/${encodeURIComponent(id)}/report`).then(r => r.data)
export const getMigrationHumanReview = (id: string) => api.get(`/migration-intelligence/runs/${encodeURIComponent(id)}/human-review`).then(r => r.data)
export const listBrainReviewItems = () => api.get('/brain-review/items').then(r => r.data)
export const getBrainReviewItemComparison = (id: string) => api.get(`/brain-review/items/${encodeURIComponent(id)}/comparison`).then(r => r.data)
export const updateBrainReviewItem = (id: string, data: any) => api.patch(`/brain-review/items/${encodeURIComponent(id)}`, data).then(r => r.data)

export const createAnalyzerRun = (data: any) => api.post('/analyzer/runs', data).then(r => r.data)
export const scanAnalyzerRun = (id: string, data: any = {}) => api.post(`/analyzer/runs/${encodeURIComponent(id)}/scan`, data).then(r => r.data)
export const listAnalyzerRuns = () => api.get('/analyzer/runs').then(r => r.data)
export const getAnalyzerComponents = (id: string) => api.get(`/analyzer/runs/${encodeURIComponent(id)}/components`).then(r => r.data)
export const getAnalyzerDependencies = (id: string) => api.get(`/analyzer/runs/${encodeURIComponent(id)}/dependencies`).then(r => r.data)
export const getAnalyzerReport = (id: string) => api.get(`/analyzer/runs/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createAdvisorScan = (data: any) => api.post('/advisor/scans', data).then(r => r.data)
export const runAdvisorScan = (id: string) => api.post(`/advisor/scans/${encodeURIComponent(id)}/run`).then(r => r.data)
export const listAdvisorScans = () => api.get('/advisor/scans').then(r => r.data)
export const getAdvisorChecks = (id: string) => api.get(`/advisor/scans/${encodeURIComponent(id)}/checks`).then(r => r.data)
export const getAdvisorReport = (id: string) => api.get(`/advisor/scans/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createProvisionRun = (data: any) => api.post('/provision/runs', data).then(r => r.data)
export const planProvisionLocal = (id: string) => api.post(`/provision/runs/${encodeURIComponent(id)}/plan-local`).then(r => r.data)
export const planProvisionConnected = (id: string) => api.post(`/provision/runs/${encodeURIComponent(id)}/plan-connected`).then(r => r.data)
export const approveProvisionRun = (id: string, approved: boolean) => api.post(`/provision/runs/${encodeURIComponent(id)}/approve`, { approved }).then(r => r.data)
export const applyProvisionRun = (id: string) => api.post(`/provision/runs/${encodeURIComponent(id)}/apply`).then(r => r.data)
export const listProvisionRuns = () => api.get('/provision/runs').then(r => r.data)
export const getProvisionPlan = (id: string) => api.get(`/provision/runs/${encodeURIComponent(id)}/plan`).then(r => r.data)

export const createValidationControlRun = (data: any) => api.post('/validation-center/runs', data).then(r => r.data)
export const planValidationControlRun = (id: string) => api.post(`/validation-center/runs/${encodeURIComponent(id)}/plan`).then(r => r.data)
export const executeValidationControlRun = (id: string) => api.post(`/validation-center/runs/${encodeURIComponent(id)}/execute`).then(r => r.data)
export const listValidationControlRuns = () => api.get('/validation-center/runs').then(r => r.data)
export const getValidationControlReport = (id: string) => api.get(`/validation-center/runs/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createDbtConversionRun = (data: any) => api.post('/dbt-conversion/runs', data).then(r => r.data)
export const analyzeDbtConversionRun = (id: string, data: any = {}) => api.post(`/dbt-conversion/runs/${encodeURIComponent(id)}/analyze`, data).then(r => r.data)
export const generateDbtConversionRun = (id: string) => api.post(`/dbt-conversion/runs/${encodeURIComponent(id)}/generate`).then(r => r.data)
export const listDbtConversionRuns = () => api.get('/dbt-conversion/runs').then(r => r.data)
export const getDbtConversionRun = (id: string) => api.get(`/dbt-conversion/runs/${encodeURIComponent(id)}`).then(r => r.data)
export const getDbtConversionArtifacts = (id: string) => api.get(`/dbt-conversion/runs/${encodeURIComponent(id)}/artifacts`).then(r => r.data)
export const getDbtConversionReport = (id: string) => api.get(`/dbt-conversion/runs/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createConversionJob = (data: any) => api.post('/conversion/jobs', data).then(r => r.data)
export const uploadConversionJobArtifact = (id: string, formData: FormData) =>
  api.post(`/conversion/jobs/${encodeURIComponent(id)}/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
export const analyzeConversionJob = (id: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/analyze`, data).then(r => r.data)
export const convertConversionJob = (id: string) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/convert`).then(r => r.data)
export const agenticConvertConversionJob = (id: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/agentic-convert`, data).then(r => r.data)
export const aiReviewConversionJob = (id: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/ai-review`, data).then(r => r.data)
export const getConversionAiProviderStatus = (provider = '') => api.get('/conversion/providers', { params: provider ? { provider } : {} }).then(r => r.data)
export const proposeConversionAiPatch = (id: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/ai-patch`, data).then(r => r.data)
export const applyConversionAiPatch = (id: string, patchId: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/patches/${encodeURIComponent(patchId)}/apply`, data).then(r => r.data)
export const chatConversionJobCopilot = (id: string, message: string) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/copilot/chat`, { message }).then(r => r.data)
export const listConversionJobs = () => api.get('/conversion/jobs').then(r => r.data)
export const getConversionJob = (id: string) => api.get(`/conversion/jobs/${encodeURIComponent(id)}`).then(r => r.data)
export const getConversionJobReport = (id: string) => api.get(`/conversion/jobs/${encodeURIComponent(id)}/report`).then(r => r.data)
export const validateConversionJob = (id: string, data: any = {}) => api.post(`/conversion/jobs/${encodeURIComponent(id)}/validate`, data).then(r => r.data)
export const downloadConversionJob = async (id: string, fallbackName = 'converted-snowflake-output.zip') => {
  const response = await api.get(`/conversion/jobs/${encodeURIComponent(id)}/download`, { responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const fileNameMatch = disposition.match(/filename=\"?([^"]+)\"?/)
  const fileName = fileNameMatch?.[1] || fallbackName
  const href = window.URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(href)
  return fileName
}

export const uploadDbtProject = (formData: FormData) =>
  api.post('/dbt/projects/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
export const analyzeDbtProject = (id: string) => api.post(`/dbt/projects/${encodeURIComponent(id)}/analyze`).then(r => r.data)
export const listDbtProjects = () => api.get('/dbt/projects').then(r => r.data)
export const getDbtProject = (id: string) => api.get(`/dbt/projects/${encodeURIComponent(id)}`).then(r => r.data)
export const getDbtProjectModels = (id: string) => api.get(`/dbt/projects/${encodeURIComponent(id)}/models`).then(r => r.data)
export const getDbtProjectLineage = (id: string) => api.get(`/dbt/projects/${encodeURIComponent(id)}/lineage`).then(r => r.data)
export const getDbtProjectReport = (id: string) => api.get(`/dbt/projects/${encodeURIComponent(id)}/report`).then(r => r.data)

export const createArtifactFactoryDbtModels = (data: any) => api.post('/artifact-factory/dbt/models', data).then(r => r.data)
export const createArtifactFactoryDbtProject = (data: any) => api.post('/artifact-factory/dbt/project', data).then(r => r.data)
export const listArtifactFactoryRuns = () => api.get('/artifact-factory/runs').then(r => r.data)
export const getArtifactFactoryRun = (id: string) => api.get(`/artifact-factory/runs/${encodeURIComponent(id)}`).then(r => r.data)
export const getArtifactFactoryRunArtifacts = (id: string) => api.get(`/artifact-factory/runs/${encodeURIComponent(id)}/artifacts`).then(r => r.data)

export const createCodegenRun = (data: any) => api.post('/codegen/runs', data).then(r => r.data)
export const generateCodegenRun = (id: string) => api.post(`/codegen/runs/${encodeURIComponent(id)}/generate`).then(r => r.data)
export const listCodegenRuns = () => api.get('/codegen/runs').then(r => r.data)
export const getCodegenTemplates = () => api.get('/codegen/templates').then(r => r.data)

export const listUnifiedReports = () => api.get('/reports').then(r => r.data)
export const previewUnifiedReport = (id: string) => api.get(`/reports/${encodeURIComponent(id)}/preview`).then(r => r.data)
export const downloadUnifiedReport = async (runId: string) => {
  const response = await api.get(`/reports/${encodeURIComponent(runId)}/download.json`, { responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const fileNameMatch = disposition.match(/filename=\"?([^"]+)\"?/)
  const fileName = fileNameMatch?.[1] || `${runId}-report.json`
  const href = window.URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(href)
  return fileName
}
