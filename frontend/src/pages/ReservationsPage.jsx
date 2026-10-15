import { useState } from 'react'

import ReservationForm from '../components/ReservationForm'
import { Button, Card } from '../components/ui'
import { api } from '../lib/api'
import { countdown, SPOT_IDS } from '../lib/format'
import { useLive, useNow } from '../lib/live'
import { useToast } from '../lib/toast'

function ReservationRow({ reservation, now }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const left = reservation.expires_at - now
  const total = reservation.expires_at - reservation.created_at
  const progress = Math.max(0, Math.min(1, left / total))

  async function cancel() {
    setBusy(true)
    try {
      await api.cancelReservation(reservation.id)
      toast(`Reservation of ${reservation.spot_id} cancelled`, 'info')
    } catch (err) {
      toast(`Cancel failed: ${err.message}`, 'error')
      setBusy(false)
    }
  }

  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-semibold">
            {reservation.spot_id} <span className="font-normal text-ink-2">· {reservation.name}</span>
          </p>
          <p className="text-xs text-muted">
            Until{' '}
            {new Date(reservation.expires_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold tabular-nums" aria-label="Time left">
            {countdown(left)}
          </span>
          <Button variant="danger" onClick={cancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink/5" aria-hidden>
        <div className="h-full rounded-full bg-reserved transition-[width] duration-1000" style={{ width: `${progress * 100}%` }} />
      </div>
    </li>
  )
}

export default function ReservationsPage() {
  const { spots, reservations } = useLive()
  const now = useNow()
  const freeSpots = SPOT_IDS.filter((id) => spots[id]?.status === 'free')
  const list = Object.entries(reservations)
    .map(([id, r]) => ({ id, ...r }))
    .sort((a, b) => a.expires_at - b.expires_at)

  return (
    <div className="grid gap-4 md:grid-cols-[340px_1fr]">
      <Card title="New reservation" className="self-start">
        {freeSpots.length === 0 ? (
          <p className="text-sm text-muted">No free spot right now.</p>
        ) : (
          <ReservationForm freeSpots={freeSpots} />
        )}
        <p className="mt-4 text-xs text-muted">
          Simulated booking: the spot is held (orange on the map) until the driver parks on it or the time runs out.
        </p>
      </Card>

      <Card title={`Active reservations (${list.length})`}>
        {list.length === 0 ? (
          <p className="text-sm text-muted">No active reservation.</p>
        ) : (
          <ul className="divide-y divide-line">
            {list.map((r) => (
              <ReservationRow key={r.id} reservation={r} now={now} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
