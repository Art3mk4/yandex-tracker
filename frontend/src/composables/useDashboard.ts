import { onMounted, reactive, watch } from 'vue'

import { getDaily, getEntries, getMeta, getProjects, getTasks } from '../api'
import type { DailyTotal, Entry, Filters, Meta, Project, TaskTotal } from '../types'

export function useDashboard(filters: Filters) {
  const state = reactive({
    meta: null as Meta | null,
    projects: [] as Project[],
    entries: [] as Entry[],
    daily: [] as DailyTotal[],
    tasks: [] as TaskTotal[],
    tasksTotal: 0,
    totalHours: 0,
    loading: false,
  })

  // один срез для плиток, графиков и таблицы — числа всегда согласованы
  async function load() {
    state.loading = true
    try {
      const [entries, daily, tasks] = await Promise.all([
        getEntries(filters),
        getDaily(filters),
        getTasks(filters),
      ])
      state.entries = entries.entries
      state.totalHours = entries.total_hours
      state.daily = daily.days
      state.tasks = tasks.tasks
      state.tasksTotal = tasks.tasks_total
    } finally {
      state.loading = false
    }
  }

  onMounted(async () => {
    const [meta, projects] = await Promise.all([getMeta(), getProjects()])
    state.meta = meta
    state.projects = projects
    await load()
  })

  let timer: ReturnType<typeof setTimeout> | undefined
  watch(
    () => ({ ...filters }),
    () => {
      clearTimeout(timer)
      timer = setTimeout(load, 300)
    },
    { deep: false },
  )

  return { state }
}
