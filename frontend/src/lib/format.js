export const SPOT_IDS = ['P1', 'P2', 'P3', 'P4']
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const pct = (rate, digits = 0) => (rate == null ? '–' : `${(rate * 100).toFixed(digits)}%`)

export const hourLabel = (h) => `${String(h).padStart(2, '0')}:00`

export function countdown(seconds) {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function minutes(value) {
  if (value == null) return '–'
  if (value < 60) return `${Math.round(value)} min`
  return `${Math.floor(value / 60)} h ${String(Math.round(value % 60)).padStart(2, '0')}`
}
