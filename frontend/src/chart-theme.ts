// Общие помощники графиков: цвета из CSS-токенов, локаль, ось дат.

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** Перерисовать при смене системной темы (для dark — свои шаги палитры). */
export function onThemeChange(cb: () => void): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

const dayFmt = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
})

/** «пт, 24 сент.» для ISO-даты; неделя в ru-RU начинается с понедельника. */
export function isoDayTitle(iso: string): string {
  return dayFmt.format(new Date(`${iso}T00:00:00`))
}

const numFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

export function fmtHours(h: number): string {
  return numFmt.format(h)
}

/** Непрерывный ряд ISO-дат от from до to включительно (UTC-арифметика, без сдвигов). */
export function isoRange(from: string, to: string): string[] {
  const out: string[] = []
  const end = Date.parse(to)
  for (let ts = Date.parse(from); ts <= end; ts += 86_400_000) {
    out.push(new Date(ts).toISOString().slice(0, 10))
  }
  return out
}
