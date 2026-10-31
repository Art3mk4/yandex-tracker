import type {
  DailyTotal,
  Entry,
  Filters,
  IssueDetail,
  IssueListItem,
  Meta,
  MirrorStatus,
  Project,
  TaskTotal,
} from './types'

function qs(filters: Filters): string {
  const p = new URLSearchParams()
  if (filters.date_from) p.set('date_from', filters.date_from)
  if (filters.date_to) p.set('date_to', filters.date_to)
  if (filters.project_id) p.set('project_id', String(filters.project_id))
  if (filters.queue) p.set('queue', filters.queue)
  if (filters.task.trim()) p.set('task', filters.task.trim())
  if (filters.state) p.set('state', filters.state)
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  return (await r.json()) as T
}

export const getMeta = () => get<Meta>('/api/meta')
export const getProjects = () => get<Project[]>('/api/projects')
export const getEntries = (f: Filters) =>
  get<{ entries: Entry[]; count: number; total_hours: number }>(`/api/entries${qs(f)}`)
export const getDaily = (f: Filters) =>
  get<{ days: DailyTotal[]; total_hours: number }>(`/api/totals/daily${qs(f)}`)
export const getTasks = (f: Filters) =>
  get<{ tasks: TaskTotal[]; tasks_total: number; total_hours: number }>(
    `/api/totals/tasks?top=15${qs(f).slice(1) ? '&' + qs(f).slice(1) : ''}`,
  )
export const getIssues = (q: string, queue: string | null) =>
  get<IssueListItem[]>(`/api/issues${q || queue ? '?' : ''}${q ? 'q=' + encodeURIComponent(q) : ''}${q && queue ? '&' : ''}${queue ? 'queue=' + queue : ''}`)

export const getIssue = (key: string) => get<IssueDetail>(`/api/issues/${encodeURIComponent(key)}`)

export const getMirrorStatus = () => get<MirrorStatus>('/api/mirror/status')
