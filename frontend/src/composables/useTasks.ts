import { computed, onMounted, reactive, ref, watch } from 'vue'

import { getIssue, getIssues, getMirrorStatus } from '../api'
import type { IssueDetail, IssueListItem, MirrorStatus } from '../types'

export function useTasks() {
  const state = reactive({
    list: [] as IssueListItem[],
    detail: null as IssueDetail | null,
    mirror: null as MirrorStatus | null,
    selected: '' as string,
    loading: false,
    loadingDetail: false,
    error: '' as string | { message: string },
  })
  const filters = reactive({ q: '', queue: null as string | null })
  const queues = computed(() => {
    const set = new Set(state.list.map((i) => i.queue).filter(Boolean))
    if (filters.queue) set.add(filters.queue)
    return [...set].sort()
  })

  async function loadList() {
    state.loading = true
    try {
      state.list = await getIssues(filters.q.trim(), filters.queue)
    } catch (e) {
      state.error = e as string
    } finally {
      state.loading = false
    }
  }

  async function open(key: string) {
    state.selected = key
    state.loadingDetail = true
    try {
      state.detail = await getIssue(key)
    } catch (e) {
      state.detail = null
      state.error = e as string
    } finally {
      state.loadingDetail = false
    }
  }

  onMounted(async () => {
    getMirrorStatus()
      .then((m) => (state.mirror = m))
      .catch(() => {})
    await loadList()
    if (state.list.length) await open(state.list[0].key)
  })

  let timer: ReturnType<typeof setTimeout> | undefined
  watch(filters, () => {
    clearTimeout(timer)
    timer = setTimeout(loadList, 300)
  })

  return { state, filters, queues, open }
}
