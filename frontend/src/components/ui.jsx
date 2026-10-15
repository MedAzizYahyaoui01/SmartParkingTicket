// Small shared building blocks.

export function Card({ title, action, children, className = '' }) {
  return (
    <section className={`rounded-xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-sm font-semibold text-ink-2">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function StatTile({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-medium text-ink-2">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

const BUTTON = {
  primary: 'bg-accent text-white hover:opacity-90',
  secondary: 'border border-line bg-surface hover:bg-ink/5',
  danger: 'border border-occupied/40 text-occupied hover:bg-occupied/10',
}

export function Button({ variant = 'primary', className = '', ...props }) {
  return (
    <button
      className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${className}`}
      {...props}
    />
  )
}

export const inputClass =
  'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20'

// Spot status -> colour + label. Colour is never the only cue: the label is always shown.
export const STATUS = {
  free: { label: 'Free', text: 'text-free', fill: 'fill-free/12', stroke: 'stroke-free', solid: 'bg-free' },
  occupied: {
    label: 'Occupied',
    text: 'text-occupied',
    fill: 'fill-occupied/12',
    stroke: 'stroke-occupied',
    solid: 'bg-occupied',
  },
  reserved: {
    label: 'Reserved',
    text: 'text-reserved',
    fill: 'fill-reserved/15',
    stroke: 'stroke-reserved',
    solid: 'bg-reserved',
  },
  offline: {
    label: 'No signal',
    text: 'text-offline',
    fill: 'fill-offline/12',
    stroke: 'stroke-offline',
    solid: 'bg-offline',
  },
}

export function StatusLegend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {Object.entries(STATUS).map(([key, s]) => (
        <li key={key} className="flex items-center gap-1.5">
          <span className={`size-2.5 rounded-sm ${s.solid}`} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  )
}
