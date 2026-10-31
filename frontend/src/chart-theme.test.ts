import { describe, expect, it } from 'vitest'

import { fmtHours, isoDayTitle, isoRange } from './chart-theme'

describe('isoRange', () => {
  it('даёт непрерывный ряд дат', () => {
    const days = isoRange('2026-09-28', '2026-10-02')
    expect(days).toEqual(['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02'])
  })

  it('переходит через границу месяца и года', () => {
    expect(isoRange('2026-12-30', '2027-01-02')).toEqual([
      '2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02',
    ])
  })

  it('from == to даёт один день', () => {
    expect(isoRange('2026-10-05', '2026-10-05')).toEqual(['2026-10-05'])
  })
})

describe('fmtHours', () => {
  it('форматирует по-русски: запятая, без лишних нулей', () => {
    expect(fmtHours(213.5)).toBe('213,5')
    expect(fmtHours(8)).toBe('8')
    expect(fmtHours(4.25)).toBe('4,25')
  })
})

describe('isoDayTitle', () => {
  it('русская локаль: день недели и дата', () => {
    const title = isoDayTitle('2026-09-24') // четверг
    expect(title.toLowerCase()).toContain('чт')
    expect(title).toContain('24')
  })
})
