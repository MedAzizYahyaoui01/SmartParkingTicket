import { useEffect, useState } from 'react'
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, StatTile } from '../components/ui'
import { api } from '../lib/api'
import { pct } from '../lib/format'

const HORIZON_MAX = 180 // minutes ahead shown on the forecast
const PAST_HOURS = 3 // recorded history shown before "now"
const REFRESH_MS = 60 * 1000 // the model works on 5-min buckets: no need to poll faster

const axisTick = { fill: 'var(--muted)', fontSize: 12 }
const time = (t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
const spots = (n) => `${n} free spot${n === 1 ? '' : 's'}`
// MAE 0.083 -> "8.3 pts": off by 8.3 points of occupancy on average
const points = (v) => `${(v * 100).toFixed(1)} pts`

function horizonLabel(min) {
  return min < 60 ? `${min} min` : `${min / 60} h`
}

function ForecastTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const item = payload.find((p) => p.value != null)
  if (!item) return null
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-md">
      <p className="font-semibold">{pct(item.value / 100)}</p>
      <p className="text-xs text-ink-2">
        {time(label)} · {item.dataKey === 'recorded' ? 'recorded' : 'predicted'}
      </p>
    </div>
  )
}

/** Recorded rate (solid area) up to "now", then the prediction (dashed line) from it. */
function ForecastChart({ prediction, history }) {
  const now = Date.parse(prediction.based_on)
  const rows = history
    .filter((p) => Date.parse(p.ts) < now)
    .map((p) => ({ t: Date.parse(p.ts), recorded: p.rate * 100 }))
  // The two series meet at "now", so the dashed line starts where the solid one ends
  rows.push({ t: now, recorded: prediction.current.rate * 100, predicted: prediction.current.rate * 100 })
  for (const p of prediction.points) rows.push({ t: Date.parse(p.ts), predicted: p.rate * 100 })

  const start = now - PAST_HOURS * 3600 * 1000
  const end = now + HORIZON_MAX * 60 * 1000
  const ticks = []
  for (let t = Math.ceil(start / 3600000) * 3600000; t <= end; t += 3600000) ticks.push(t)

  return (
    <>
      <ul className="mb-2 flex gap-4 text-xs text-ink-2">
        <li className="flex items-center gap-1.5">
          <span className="h-0.5 w-5 rounded bg-accent" aria-hidden /> Recorded
        </li>
        <li className="flex items-center gap-1.5">
          <span className="w-5 border-t-2 border-dashed border-accent" aria-hidden /> Predicted
        </li>
      </ul>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[start, end]}
            ticks={ticks}
            tickFormatter={time}
            tick={axisTick}
            stroke="var(--grid)"
          />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v) => `${v}%`} tick={axisTick} stroke="var(--grid)" />
          <Tooltip content={<ForecastTooltip />} cursor={{ stroke: 'var(--muted)', strokeWidth: 1 }} />
          <ReferenceLine x={now} stroke="var(--muted)" strokeDasharray="2 3" label={{ value: 'now', position: 'insideTopLeft', fill: 'var(--muted)', fontSize: 12 }} />
          <Area
            type="stepAfter"
            dataKey="recorded"
            stroke="var(--series-1)"
            strokeWidth={2}
            fill="var(--series-1)"
            fillOpacity={0.12}
            connectNulls
            isAnimationActive={false}
            activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="var(--series-1)"
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={{ r: 4, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </>
  )
}

/** Scores per model for one horizon at a time. `compare` is our parking or a benchmark:
 *  both have horizons, results and best_model. */
function ModelComparison({ compare, badge = 'In use', children }) {
  const [horizon, setHorizon] = useState(compare.horizons.includes(30) ? 30 : compare.horizons[0])
  const rows = compare.results.filter((r) => r.horizon_min === horizon)
  const bestMae = Math.min(...rows.map((r) => r.mae))

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Horizon">
        <span className="text-xs text-ink-2">Predicting</span>
        {compare.horizons.map((h) => (
          <button
            key={h}
            onClick={() => setHorizon(h)}
            aria-pressed={h === horizon}
            className={`rounded-lg border px-2.5 py-1 text-xs ${
              h === horizon ? 'border-accent bg-accent/10 font-medium text-accent' : 'border-line bg-surface hover:bg-ink/5'
            }`}
          >
            {horizonLabel(h)} ahead
          </button>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm tabular-nums">
          <thead>
            <tr className="text-left text-ink-2">
              <th className="py-1.5 font-medium">Model</th>
              <th className="py-1.5 text-right font-medium" title="Mean absolute error: average miss, in points of occupancy">
                MAE
              </th>
              <th className="py-1.5 text-right font-medium">RMSE</th>
              <th className="py-1.5 text-right font-medium">R²</th>
              <th className="py-1.5 text-right font-medium">Training</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model} className={`border-t border-line ${r.model === compare.best_model ? 'font-medium' : ''}`}>
                <td className="py-1.5">
                  {r.label}
                  {r.model === compare.best_model && (
                    <span className="ml-2 rounded-full bg-accent/10 px-2 py-0.5 text-xs text-accent">{badge}</span>
                  )}
                </td>
                <td className="py-1.5 text-right">
                  {points(r.mae)}
                  {r.mae === bestMae && <span className="sr-only"> (lowest)</span>}
                </td>
                <td className="py-1.5 text-right">{points(r.rmse)}</td>
                <td className="py-1.5 text-right">{r.r2.toFixed(2)}</td>
                <td className="py-1.5 text-right text-ink-2">{r.fit_s < 0.01 ? '–' : `${r.fit_s.toFixed(2)} s`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">{children}</p>
    </div>
  )
}

const shortDate = (d) => new Date(d).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })

function FeatureImportance({ compare }) {
  const models = Object.keys(compare.feature_importance)
  const [model, setModel] = useState(models.includes(compare.best_model) ? compare.best_model : models[0])
  const labels = { rf: 'Random Forest', xgboost: 'XGBoost' }
  const top = (compare.feature_importance[model] ?? []).slice(0, 8).map((f) => ({ ...f, value: f.importance * 100 }))

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Model">
        {models.map((m) => (
          <button
            key={m}
            onClick={() => setModel(m)}
            aria-pressed={m === model}
            className={`rounded-lg border px-2.5 py-1 text-xs ${
              m === model ? 'border-accent bg-accent/10 font-medium text-accent' : 'border-line bg-surface hover:bg-ink/5'
            }`}
          >
            {labels[m] ?? m}
          </button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={top.length * 30 + 10}>
        <BarChart data={top} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 0 }} barCategoryGap={4}>
          <XAxis type="number" hide domain={[0, 'dataMax']} />
          <YAxis type="category" dataKey="label" width={150} tick={{ fill: 'var(--ink-2)', fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'var(--grid)', opacity: 0.5 }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-md">
                  <p className="font-semibold">{payload[0].value.toFixed(1)}%</p>
                  <p className="text-xs text-ink-2">{payload[0].payload.label}</p>
                </div>
              ) : null
            }
          />
          <Bar
            dataKey="value"
            fill="var(--series-1)"
            radius={[0, 4, 4, 0]}
            isAnimationActive={false}
            label={{ position: 'right', fill: 'var(--ink-2)', fontSize: 12, formatter: (v) => `${v.toFixed(0)}%` }}
          />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-muted">Share of the model's decisions that rely on each input, averaged over the horizons.</p>
    </div>
  )
}

export default function PredictionPage() {
  const [prediction, setPrediction] = useState(null)
  const [history, setHistory] = useState([])
  const [compare, setCompare] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.modelsCompare().then(setCompare).catch(() => setCompare(null))
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = () => {
      const to = new Date()
      const from = new Date(to.getTime() - PAST_HOURS * 3600 * 1000)
      Promise.all([
        api.predictions({ horizon: HORIZON_MAX }),
        api.occupancy({ from: from.toISOString(), to: to.toISOString(), step: 5 }),
      ])
        .then(([p, h]) => {
          if (cancelled) return
          setPrediction(p)
          setHistory(h.points)
          setError(null)
        })
        .catch((err) => !cancelled && setError(err))
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const at = (min) => prediction?.points.find((p) => p.horizon_min === min)
  const in30 = at(30)
  const in60 = at(60)
  const best = prediction?.best

  return (
    <div className="grid gap-4">
      {error && (
        <p className="rounded-lg border border-occupied/40 bg-occupied/10 px-4 py-2 text-sm">
          {error.status === 503 ? error.message : `Prediction unavailable: ${error.message}`}
        </p>
      )}
      {prediction?.stale && (
        <p className="rounded-lg border border-reserved/50 bg-reserved/10 px-4 py-2 text-sm">
          No recent sensor data: this prediction starts from {time(prediction.based_on)}, the last time the sensors reported.
        </p>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          label="Now"
          value={pct(prediction?.current.rate)}
          hint={prediction ? `${spots(prediction.current.free_spots)} of ${prediction.total_spots}` : null}
        />
        <StatTile
          label="In 30 min"
          value={in30 ? `about ${in30.free_spots} free` : '–'}
          hint={in30 ? `${pct(in30.rate)} full` : null}
        />
        <StatTile label="In 1 hour" value={in60 ? `about ${in60.free_spots} free` : '–'} hint={in60 ? `${pct(in60.rate)} full` : null} />
        <StatTile
          label="Best time to come"
          value={best ? (best.horizon_min === 0 ? 'Now' : time(best.ts)) : '–'}
          hint={best ? `${pct(best.rate)} full, about ${spots(best.free_spots)} (next ${HORIZON_MAX / 60} h)` : null}
        />
      </div>

      <Card title={`Occupancy forecast, next ${HORIZON_MAX / 60} hours`}>
        {prediction ? (
          <ForecastChart prediction={prediction} history={history} />
        ) : (
          <p className="py-12 text-center text-sm text-muted">{error ? 'No forecast to show.' : 'Loading…'}</p>
        )}
        {prediction && (
          <p className="mt-2 text-xs text-muted">
            {prediction.label} · trained {new Date(prediction.trained_at).toLocaleDateString([], { day: 'numeric', month: 'short' })}
          </p>
        )}
      </Card>

      {compare && (
        <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
          <Card title="Model comparison (test period)">
            <ModelComparison compare={compare}>
              MAE = how far off the prediction is on average: 8 pts means it says 50% when the parking is 42% or 58% full. In use:
              the model with the lowest MAE over all horizons. Trained on {compare.data.source},{' '}
              {compare.data.points.toLocaleString()} points of 5 min; scored on the data after {shortDate(compare.data.train_until)}{' '}
              that it never saw (time-based split).
            </ModelComparison>
          </Card>
          <Card title="What the model looks at">
            <FeatureImportance compare={compare} />
          </Card>
        </div>
      )}

      {compare?.benchmarks.map((b) => (
        <Card key={b.name} title={`Same comparison on real data: ${b.title}`}>
          <ModelComparison compare={b} badge="Best">
            Our parking's history is synthetic, so the same features, models and time-based split are also run on{' '}
            <a href={b.url} target="_blank" rel="noreferrer" className="underline hover:text-ink-2">
              {b.source}
            </a>
            , {shortDate(b.data.start)} – {shortDate(b.data.end)}; scored after {shortDate(b.data.train_until)}. Steps of{' '}
            {b.step_min} min, so there are no 5 and 15 min lags. R² is high mostly because the car parks differ a lot from each
            other: MAE is the fairer measure. These models are only scored, never used for the live forecast.
          </ModelComparison>
        </Card>
      ))}
    </div>
  )
}
