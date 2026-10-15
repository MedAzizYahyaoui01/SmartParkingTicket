// Hand-drawn SVG plan of the parking: 4 bays above a road, entry barrier on the left.
// Each bay's colour is bound to its live status; colours fade on change (CSS transition).
import { STATUS } from './ui'

const BAY_W = 112
const BAY_H = 150
const BAY_Y = 24
const BAY_X0 = 150
const BAY_GAP = 12
const ROAD_Y = BAY_Y + BAY_H + 14
const ROAD_H = 96

// Barrier arm angle for each state (0 = down across the road, -90 = raised)
const ARM_ANGLE = { closed: 0, opening: -45, open: -90, closing: -45 }

function Car({ x, y, className }) {
  return (
    <g transform={`translate(${x} ${y})`} className={className}>
      <rect width="52" height="78" rx="12" className="fill-current" />
      <rect x="7" y="12" width="38" height="17" rx="5" className="fill-white/70" />
      <rect x="7" y="54" width="38" height="12" rx="4" className="fill-white/50" />
    </g>
  )
}

function Bay({ id, spot, index, online, onSelect }) {
  const status = !online || !spot || spot.status === 'unknown' ? 'offline' : spot.status
  const s = STATUS[status]
  const x = BAY_X0 + index * (BAY_W + BAY_GAP)
  const clickable = status === 'free' && onSelect
  const label = `${id}: ${s.label}${clickable ? ', click to reserve' : ''}`

  return (
    <g
      role={clickable ? 'button' : 'img'}
      tabIndex={clickable ? 0 : undefined}
      aria-label={label}
      onClick={clickable ? () => onSelect(id) : undefined}
      onKeyDown={clickable ? (e) => (e.key === 'Enter' || e.key === ' ') && onSelect(id) : undefined}
      className={`outline-none ${clickable ? 'cursor-pointer [&:hover>rect:first-child]:stroke-[4] [&:focus-visible>rect:first-child]:stroke-[4]' : ''}`}
    >
      <title>{label}</title>
      <rect
        x={x}
        y={BAY_Y}
        width={BAY_W}
        height={BAY_H}
        rx="8"
        strokeWidth="2.5"
        className={`transition-colors duration-500 ${s.fill} ${s.stroke}`}
      />
      <text x={x + 12} y={BAY_Y + 24} className="fill-ink text-[17px] font-semibold">
        {id}
      </text>
      {status === 'occupied' && <Car x={x + BAY_W / 2 - 26} y={BAY_Y + 34} className={s.text} />}
      <text
        x={x + BAY_W / 2}
        y={BAY_Y + BAY_H - 14}
        textAnchor="middle"
        className={`text-[13px] font-semibold transition-colors duration-500 ${s.text} fill-current`}
      >
        {s.label}
      </text>
    </g>
  )
}

export default function ParkingMap({ spots, online, barrierState, gateCar, onSelectFree }) {
  const ids = ['P1', 'P2', 'P3', 'P4']
  const width = BAY_X0 + ids.length * (BAY_W + BAY_GAP) + 8
  const height = ROAD_Y + ROAD_H + 8
  const pivotX = 112
  const angle = ARM_ANGLE[barrierState] ?? 0

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="group" aria-label="Parking map">
      {/* Road with a dashed centre line */}
      <rect x="0" y={ROAD_Y} width={width} height={ROAD_H} rx="10" fill="var(--road)" />
      <line
        x1="0"
        x2={width}
        y1={ROAD_Y + ROAD_H / 2}
        y2={ROAD_Y + ROAD_H / 2}
        stroke="var(--muted)"
        strokeWidth="2"
        strokeDasharray="14 12"
        opacity="0.5"
      />
      <text x="12" y={ROAD_Y - 8} className="fill-muted text-[12px] font-medium">
        ENTRY
      </text>

      {/* Car waiting at the gate */}
      {gateCar && (
        <g transform={`translate(18 ${ROAD_Y + ROAD_H / 2 + 26}) rotate(-90)`} className="text-accent">
          <title>Car waiting at the gate</title>
          <rect width="52" height="82" rx="11" className="fill-current" />
          <rect x="7" y="12" width="38" height="18" rx="5" className="fill-white/70" />
        </g>
      )}

      {/* Barrier: post + arm that swings up when open */}
      <g aria-label={`Barrier ${barrierState}`} role="img">
        <title>{`Barrier ${barrierState}`}</title>
        <g
          style={{
            transform: `rotate(${angle}deg)`,
            transformOrigin: `${pivotX}px ${ROAD_Y + 6}px`,
            transition: 'transform 600ms ease',
          }}
        >
          <rect x={pivotX - 3} y={ROAD_Y + 6} width="6" height={ROAD_H - 12} rx="3" fill="var(--ink)" />
          {[0, 1, 2, 3].map((i) => (
            <rect key={i} x={pivotX - 3} y={ROAD_Y + 14 + i * 20} width="6" height="9" fill="#d03b3b" />
          ))}
        </g>
        <circle cx={pivotX} cy={ROAD_Y + 6} r="8" fill="var(--ink)" />
      </g>

      {ids.map((id, i) => (
        <Bay key={id} id={id} index={i} spot={spots[id]} online={online} onSelect={onSelectFree} />
      ))}
    </svg>
  )
}
