export interface Project {
  id: number
  code: string
  since: string
}

export type TrackerState = 'synced' | 'excluded' | 'pending'

export interface Entry {
  id: number
  work_date: string
  task_key: string | null
  label: string | null
  hours: number
  description: string
  estimate_source: string
  tracker_state: TrackerState
  project: { id: number; code: string } | null
}

export interface DailyTotal {
  work_date: string
  hours: number
  entries: number
}

export interface TaskTotal {
  task: string
  queue: string | null
  hours: number
  entries: number
}

export interface Meta {
  min_date: string | null
  max_date: string | null
  total_hours: number | null
  entries_count: number
  days_count: number
  queues: string[]
  tracker_states: Partial<Record<TrackerState, number>>
}

export interface Filters {
  date_from: string | null
  date_to: string | null
  project_id: number | null
  queue: string | null
  task: string
  state: TrackerState | null
}

// --- Зеркало Яндекс Трекера ---

export interface IssueListItem {
  key: string
  summary: string
  queue: string
  status_key: string | null
  status_name: string | null
  assignee_name: string | null
  updated_at: string
  comments_count: number
  attachments_count: number
  timesheet_hours: number | null
}

export interface IssueComment {
  id: number
  author_name: string | null
  text: string
  created_at: string
  updated_at: string
}

export interface IssueAttachment {
  id: number
  name: string
  size: number
  file_path: string | null
  downloaded_at: string | null
  url: string | null
}

export interface ChangelogEntry {
  updated_at: string
  author_name: string | null
  changes: { field: string; from: string; to: string }[]
}

export interface IssueDetail {
  issue: {
    key: string
    summary: string
    description: string
    queue: string
    queue_name: string
    status_name: string | null
    type_name: string | null
    priority_name: string | null
    assignee_name: string | null
    created_by_name: string | null
    tags: string[]
    created_at: string
    updated_at: string
    aliases: string[]
  }
  comments: IssueComment[]
  attachments: IssueAttachment[]
  changelog: ChangelogEntry[]
}

export interface MirrorStatus {
  configured: boolean
  issues?: number
  comments?: number
  attachments?: number
  bytes?: number
  last_run_at?: string | null
  last_mode?: string | null
  last_duration_sec?: number | null
  stats?: Record<string, number>
  errors?: unknown[]
}
