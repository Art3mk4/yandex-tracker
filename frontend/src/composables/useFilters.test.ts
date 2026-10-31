import { describe, expect, it } from 'vitest'

import { useFilters } from './useFilters'

describe('useFilters', () => {
  it('дефолты: без дат, без проекта, пустой поиск', () => {
    const { filters } = useFilters()
    expect(filters.date_from).toBeNull()
    expect(filters.queue).toBeNull()
    expect(filters.task).toBe('')
    expect(filters.state).toBeNull()
  })

  it('объект реактивный: изменения видны', () => {
    const { filters } = useFilters()
    filters.task = '507'
    filters.queue = 'BACKEND'
    expect(filters.task).toBe('507')
    expect(filters.queue).toBe('BACKEND')
  })

  it('reset() возвращает дефолты', () => {
    const { filters, reset } = useFilters()
    filters.task = '507'
    filters.project_id = 2
    filters.state = 'synced'
    reset()
    expect(filters.task).toBe('')
    expect(filters.project_id).toBeNull()
    expect(filters.state).toBeNull()
  })
})
