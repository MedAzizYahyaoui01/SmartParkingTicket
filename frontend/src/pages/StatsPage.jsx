import { useEffect, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, StatTile } from '../components/ui'
import { api } from '../lib/api'
import { hourLabel, minutes, pct, WEEKDAYS } from '../lib/format'

// Period presets: length, bucket size of the occupancy curve, and how to label its x axis
const RANGES = [
  { key: '24h', label: 'Last 24 h', hours: 24, step: 15, tick: { hour: '2-digit', minute: '2-digit' } },
  { key: '7d', label: 'Last 7 days', hours: 24 * 7, step: 60, tick: { weekday: 'short', day: 'numeric' } },
  { key: '30d', label: 'Last 30 days', hours: 24 * 30, step: 360, tick: { day: 'numeric', month: 'short' } },
]

// Sequential blue ramp for the heatmap (light -> dark = low -> high), stepped per theme
const HEAT_STEPS = 7

const axisTick = { fill: 'var(--muted)', fontSize: 12 }

/** Chart points, with a break (null) wherever data is missing, so the line never
 *  invents values across a period without data (e.g. while the sensors were off). */
function withGaps(points, stepMin) {
  const out = []
  const maxGap = stepMin * 60 * 1000 * 1.5
  for (const p of points) {
    const t = new Date(p.ts).getTime()
    const prev = out[out.length - 1]
    if (prev && t - prev.t > maxGap) out.push({ t: prev.t + stepMin * 60 * 1000, value: null })
    out.push({ t, value: p.rate * 100 })
  }
  return out
}

/** X ticks on round local times: every 3 h for a day, every midnight for a week,
 *  every 5 days for a month. */
function timeTicks(start, end, rangeKey) {
  const ticks = []
  const d = new Date(start)
  d.setMinutes(0, 0, 0)
  if (rangeKey === '24h') {
    d.setHours(Math.ceil(d.getHours() / 3) * 3)
    for (; d <= end; d.setHours(d.getHours() + 3)) ticks.push(d.getTime())
  } else {
    d.setHours(24)
    const every = rangeKey === '7d' ? 1 : 5
    for (; d <= end; d.setDate(d.getDate() + every)) ticks.push(d.getTime())
  }
  return ticks
}

function ChartTooltip({ active, payload, label, formatLabel }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-md">
      <p className="font-semibold">{pct(payload[0].value / 100)}</p>
      <p className="text-xs text-ink-2">{formatLabel(label)}</p>
    </div>
  )
}

function Heatmap({ cells }) {
  const [hover, setHover] = useState(null)
  const byKey = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c.rate]))

  return (
    <div>
      <p className="mb-2 h-5 text-sm text-ink-2" aria-live="polite">
        {hover
          ? `${WEEKDAYS[hover.weekday]} ${hourLabel(hover.hour)}: ${hover.rate == null ? 'no data' : pct(hover.rate)} occupied`
          : 'Hover a cell for its value'}
      </p>
      <div className="overflow-x-auto">
        <div className="grid min-w-[480px] grid-cols-[36px_repeat(24,minmax(0,1fr))] gap-[2px] text-[11px] text-muted">
          <span />
          {Array.from({ length: 24 }, (_, h) => (
            <span key={h} className="text-center">
              {h % 3 === 0 ? h : ''}
            </span>
          ))}
          {WEEKDAYS.map((day, wd) => (
            <div key={day} className="contents">
              <span className="self-center">{day}</span>
              {Array.from({ length: 24 }, (_, h) => {
                const rate = byKey.get(`${wd}-${h}`)
                const step = rate == null ? null : Math.min(HEAT_STEPS - 1, Math.floor(rate * HEAT_STEPS))
                return (
                  <span
                    key={h}
                    tabIndex={0}
                    aria-label={`${day} ${hourLabel(h)}: ${rate == null ? 'no data' : pct(rate)}`}
                    onMouseEnter={() => setHover({ weekday: wd, hour: h, rate })}
                    onFocus={() => setHover({ weekday: wd, hour: h, rate })}
                    onMouseLeave={() => setHover(null)}
                    className="aspect-square rounded-[3px] outline-none hover:ring-2 hover:ring-ink focus-visible:ring-2 focus-visible:ring-ink"
                    style={{ background: step == null ? 'var(--grid)' : `var(--heat-${step})` }}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-muted">
        <span>0%</span>
        <span className="flex">
          {Array.from({ length: HEAT_STEPS }, (_, i) => (
            <span key={i} className="h-2.5 w-6" style={{ background: `var(--heat-${i})` }} />
          ))}
        </span>
        <span>100% occupied</span>
      </div>
    </div>
  )
}

export default function StatsPage() {
  const [rangeKey, setRangeKey] = useState('7d')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const range = RANGES.find((r) => r.key === rangeKey)

  useEffect(() => {
    let cancelled = false
    const to = new Date()
    const from = new Date(to.getTime() - range.hours * 3600 * 1000)
    const period = { from: from.toISOString(), to: to.toISOString() }
    setLoading(true)
    Promise.all([api.occupancy({ ...period, step: range.step }), api.statsSummary(period)])
      .then(([occupancy, summary]) => {
        if (cancelled) return
        setData({ occupancy, summary })
        setError(null)
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [range])

  const points = data ? withGaps(data.occupancy.points, data.occupancy.step_min) : []
  const ticks = data ? timeTicks(new Date(data.occupancy.start), new Date(data.occupancy.end), rangeKey) : []
  const byHour = (data?.summary.by_hour ?? []).map((h) => ({ hour: h.hour, value: h.rate * 100 }))
  const s = data?.summary
  const formatTime = (t) => new Date(t).toLocaleString([], range.tick)
  const formatFull = (t) =>
    new Date(t).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

  return (
    <div className="grid gap-4">
      {/* One filter row, above everything it scopes */}
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Period">
        {RANGES.map((r) => (
          <button
            key={r.key}
            onClick={() => setRangeKey(r.key)}
            aria-pressed={r.key === rangeKey}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              r.key === rangeKey ? 'border-accent bg-accent/10 font-medium text-accent' : 'border-line bg-surface hover:bg-ink/5'
            }`}
          >
            {r.label}
          </button>
        ))}
        {s && <span className="text-xs text-muted">Times in {s.timezone}</span>}
      </div>

      {error && <p className="rounded-lg border border-occupied/40 bg-occupied/10 px-4 py-2 text-sm">Statistics unavailable: {error}</p>}

      {/* Refetch keeps the previous render, dimmed, instead of flashing */}
      <div className={`grid gap-4 transition-opacity ${loading && data ? 'opacity-50' : ''}`}>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Average occupancy" value={pct(s?.avg_rate)} hint={s ? `${s.samples.toLocaleString()} minute samples` : null} />
          <StatTile label="Entries" value={s ? s.entries.toLocaleString() : '–'} hint="Cars that parked" />
          <StatTile label="Average parking time" value={minutes(s?.avg_duration_min)} />
          <StatTile
            label="Peak hour"
            value={s?.peak_hours[0] ? hourLabel(s.peak_hours[0].hour) : '–'}
            hint={s?.peak_hours.length ? `Busiest: ${s.peak_hours.map((h) => `${hourLabel(h.hour)} (${pct(h.rate)})`).join(', ')}` : null}
          />
        </div>

        <Card title="Occupancy rate over time">
          {points.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted">{loading ? 'Loading…' : 'No data for this period.'}</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={data ? [Date.parse(data.occupancy.start), Date.parse(data.occupancy.end)] : ['dataMin', 'dataMax']}
                  ticks={ticks}
                  tickFormatter={formatTime}
                  tick={axisTick}
                  stroke="var(--grid)"
                />
                <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v) => `${v}%`} tick={axisTick} stroke="var(--grid)" />
                <Tooltip content={<ChartTooltip formatLabel={formatFull} />} cursor={{ stroke: 'var(--muted)', strokeWidth: 1 }} />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="var(--series-1)"
                  strokeWidth={2}
                  fill="var(--series-1)"
                  fillOpacity={0.12}
                  isAnimationActive={false}
                  activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <div className="grid gap-4 xl:grid-cols-[2fr_3fr]">
          <Card title="Average occupancy by hour of the day">
            {byHour.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted">No data for this period.</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={byHour} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap={2}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="hour" tick={axisTick} stroke="var(--grid)" interval={2} />
                  <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tickFormatter={(v) => `${v}%`} tick={axisTick} stroke="var(--grid)" />
                  <Tooltip content={<ChartTooltip formatLabel={hourLabel} />} cursor={{ fill: 'var(--grid)', opacity: 0.5 }} />
                  <Bar dataKey="value" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card title="Weekly pattern (average occupancy)">
            <Heatmap cells={s?.heatmap ?? []} />
          </Card>
        </div>

        {byHour.length > 0 && (
          <details className="rounded-xl border border-line bg-surface p-4 text-sm">
            <summary className="cursor-pointer text-ink-2">Show the hourly values as a table</summary>
            <table className="mt-3 w-full max-w-sm tabular-nums">
              <thead>
                <tr className="text-left text-ink-2">
                  <th className="py-1 font-medium">Hour</th>
                  <th className="py-1 text-right font-medium">Average occupancy</th>
                </tr>
              </thead>
              <tbody>
                {byHour.map((h) => (
                  <tr key={h.hour} className="border-t border-line">
                    <td className="py-1">{hourLabel(h.hour)}</td>
                    <td className="py-1 text-right">{pct(h.value / 100, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>
    </div>
  )
}
