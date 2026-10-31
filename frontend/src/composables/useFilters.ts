import { reactive } from 'vue'

import type { Filters } from '../types'

const DEFAULTS: Filters = {
  date_from: null,
  date_to: null,
  project_id: null,
  queue: null,
  task: '',
  state: null,
}

export function useFilters() {
  const filters = reactive<Filters>({ ...DEFAULTS })
  const reset = () => Object.assign(filters, DEFAULTS)
  return { filters, reset }
}
