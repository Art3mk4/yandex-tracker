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

type Params = Record<string, string | number | null | undefined>

/** URL с query-параметрами; пустые значения пропускаются. */
export function withParams(path: string, params: Params): string {
  const q = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return q ? `${path}?${q}` : path
}

/** Фильтры табеля → query-параметры. */
export function filterParams(f: Filters): Params {
  return {
    date_from: f.date_from,
    date_to: f.date_to,
    project_id: f.project_id,
    queue: f.queue,
    task: f.task.trim() || null,
    state: f.state,
  }
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  return (await r.json()) as T
}

export const getMeta = () => get<Meta>('/api/meta')
export const getProjects = () => get<Project[]>('/api/projects')
export const getEntries = (f: Filters) =>
  get<{ entries: Entry[]; count: number; total_hours: number }>(withParams('/api/entries', filterParams(f)))
export const getDaily = (f: Filters) =>
  get<{ days: DailyTotal[]; total_hours: number }>(withParams('/api/totals/daily', filterParams(f)))
export const getTasks = (f: Filters) =>
  get<{ tasks: TaskTotal[]; tasks_total: number; total_hours: number }>(
    withParams('/api/totals/tasks', { top: 15, ...filterParams(f) }),
  )

// --- Зеркало Яндекс Трекера ---

export const getIssues = (q: string, queue: string | null) =>
  get<IssueListItem[]>(withParams('/api/issues', { q: q.trim() || null, queue }))

export const getIssue = (key: string) => get<IssueDetail>(`/api/issues/${encodeURIComponent(key)}`)

export const getMirrorStatus = () => get<MirrorStatus>('/api/mirror/status')
