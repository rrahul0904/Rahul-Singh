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
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
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
export const testConnection      = (id: string) => api.post(`/connections/${id}/test`).then(r => r.data)

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

// ── Validation ───────────────────────────────────────────────

export const getValidationRules  = ()             => api.get('/validation').then(r => r.data)
export const createValidationRule = (data: any)   => api.post('/validation', data).then(r => r.data)
export const runValidationRule   = (id: string)   => api.post(`/validation/${id}/run`).then(r => r.data)

// ── AI ───────────────────────────────────────────────────────

export const aiChat              = (messages: any[]) => api.post('/ai/chat', { messages }).then(r => r.data)
export const generateSQL         = (prompt: string, database?: string, schema?: string) =>
  api.post('/ai/sql-generate', null, { params: { prompt, database, schema } }).then(r => r.data)

// ── Health ───────────────────────────────────────────────────

export const getHealth           = () => api.get('/health').then(r => r.data)

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
export const navDatabases = (id: string) => api.get(`/snowflake/navigator/${id}/databases`).then(r => r.data)
export const navSchemas = (id: string, db: string) => api.get(`/snowflake/navigator/${id}/schemas/${encodeURIComponent(db)}`).then(r => r.data)
export const navTables = (id: string, db: string, schema: string) => api.get(`/snowflake/navigator/${id}/tables/${encodeURIComponent(db)}/${encodeURIComponent(schema)}`).then(r => r.data)
export const navDescribe = (id: string, db: string, schema: string, table: string) => api.get(`/snowflake/navigator/${id}/describe/${encodeURIComponent(db)}/${encodeURIComponent(schema)}/${encodeURIComponent(table)}`).then(r => r.data)
export const navPreview = (id: string, db: string, schema: string, table: string, limit = 50) => api.get(`/snowflake/navigator/${id}/preview/${encodeURIComponent(db)}/${encodeURIComponent(schema)}/${encodeURIComponent(table)}?limit=${limit}`).then(r => r.data)
