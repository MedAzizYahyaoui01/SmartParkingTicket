// Booking form, used on the Reservations page and in the dialog opened from the map.
// Reserving needs an account: the fee is paid from the wallet.
import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { money, SPOT_IDS } from '../lib/format'
import { useToast } from '../lib/toast'
import { Button, inputClass } from './ui'

const DURATIONS = [5, 10, 15, 30, 45, 60]

export default function ReservationForm({ freeSpots, initialSpot, onDone, onCancel }) {
  const toast = useToast()
  const { user, refresh } = useAuth()
  const location = useLocation()
  const [spot, setSpot] = useState(initialSpot || freeSpots[0] || '')
  const [duration, setDuration] = useState(15)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Keep the selected spot valid when the live state changes
  const spotIsFree = freeSpots.includes(spot)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api.reserve({ spot_id: spot, duration_min: duration })
      toast(`${res.spot_id} reserved for ${duration} min`, 'success')
      refresh()
      onDone?.(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!user) {
    return (
      <div className="grid gap-3 text-sm">
        <p className="text-ink-2">Sign in to reserve a spot. The fee is paid from your wallet.</p>
        <div className="flex justify-end gap-2">
          {onCancel && (
            <Button type="button" variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Link
            to="/login"
            state={{ from: location.pathname }}
            className="rounded-lg bg-accent px-4 py-2 font-medium text-white hover:opacity-90"
          >
            Sign in
          </Link>
        </div>
      </div>
    )
  }

  if (user.reservation) {
    return <p className="text-sm text-ink-2">You already have a reservation on {user.reservation.spot_id}.</p>
  }

  return (
    <form onSubmit={submit} className="grid gap-3">
      <p className="text-sm text-ink-2">
        For <span className="font-medium text-ink">{user.name}</span> · balance {money(user.balance, user.currency)}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <label className="grid gap-1 text-sm">
          <span className="text-ink-2">Spot</span>
          <select className={inputClass} value={spot} onChange={(e) => setSpot(e.target.value)} required>
            {!spotIsFree && <option value="">Choose…</option>}
            {SPOT_IDS.map((id) => (
              <option key={id} value={id} disabled={!freeSpots.includes(id)}>
                {id}
                {freeSpots.includes(id) ? '' : ' (not free)'}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-ink-2">Duration</span>
          <select className={inputClass} value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
            {DURATIONS.map((d) => (
              <option key={d} value={d}>
                {d} min
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p className="text-sm text-occupied">{error}</p>}
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={busy || !spotIsFree}>
          {busy ? 'Reserving…' : 'Reserve'}
        </Button>
      </div>
    </form>
  )
}

export function ReserveDialog({ spotId, freeSpots, onClose }) {
  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-labelledby="reserve-title" className="w-full max-w-sm rounded-xl bg-surface p-5 shadow-xl">
        <h2 id="reserve-title" className="mb-4 text-lg font-semibold">
          Reserve {spotId}
        </h2>
        <ReservationForm freeSpots={freeSpots} initialSpot={spotId} onDone={onClose} onCancel={onClose} />
      </div>
    </div>
  )
}
