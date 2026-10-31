import { describe, expect, it } from 'vitest'

import { filterParams, withParams } from './api'
import type { Filters } from './types'

const EMPTY_FILTERS: Filters = {
  date_from: null,
  date_to: null,
  project_id: null,
  queue: null,
  task: '',
  state: null,
}

describe('withParams', () => {
  it('без непустых параметров — без вопросительного знака', () => {
    expect(withParams('/api/entries', { a: null, b: '', c: undefined })).toBe('/api/entries')
  })

  it('пропускает пустые значения и собирает остальные', () => {
    expect(withParams('/api/entries', { queue: 'BACKEND', task: null, top: 15 })).toBe(
      '/api/entries?queue=BACKEND&top=15',
    )
  })

  it('кодирует кириллицу', () => {
    const url = withParams('/api/issues', { q: 'рол' })
    expect(url).toBe(`/api/issues?q=${encodeURIComponent('рол')}`)
  })
})

describe('filterParams', () => {
  it('пустые фильтры → все значения отфильтруются', () => {
    const params = filterParams(EMPTY_FILTERS)
    expect(Object.values(params).every((v) => !v)).toBe(true)
  })

  it('заполненные фильтры передаются как есть, пробелы задачи обрезаются', () => {
    const params = filterParams({
      ...EMPTY_FILTERS,
      date_from: '2026-09-24',
      queue: 'BACKEND',
      task: '  507 ',
      state: 'synced',
    })
    expect(params).toEqual({
      date_from: '2026-09-24',
      date_to: null,
      project_id: null,
      queue: 'BACKEND',
      task: '507',
      state: 'synced',
    })
  })
})
