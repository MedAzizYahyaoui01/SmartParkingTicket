import { useState } from 'react'
import { Link } from 'react-router-dom'

import ParkingMap from '../components/ParkingMap'
import { ReserveDialog } from '../components/ReservationForm'
import { Button, Card, StatusLegend } from '../components/ui'
import { api } from '../lib/api'
import { countdown, SPOT_IDS } from '../lib/format'
import { useDeviceOnline, useLive, useNow } from '../lib/live'
import { useToast } from '../lib/toast'

const BARRIER_LABEL = { closed: 'Closed', opening: 'Opening…', open: 'Open', closing: 'Closing…' }

function BarrierPanel({ barrier, gateCar, online }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  async function send(action) {
    setBusy(true)
    try {
      await api.barrier(action)
      toast(`"${action}" sent: the ESP32 applies it with its next report (≤ 2 s)`, 'info')
    } catch (err) {
      toast(`Barrier command failed: ${err.message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  const command = barrier.command
  return (
    <Card title="Entry barrier">
      <p className="text-2xl font-semibold">{BARRIER_LABEL[barrier.state] ?? barrier.state}</p>
      <p className="mt-1 text-sm text-ink-2">{gateCar ? 'A car is waiting at the gate' : 'No car at the gate'}</p>
      {command && (
        <p className="mt-1 text-xs text-muted">
          Last manual command: {command.action} ({command.status})
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button onClick={() => send('open')} disabled={busy || !online}>
          Open
        </Button>
        <Button variant="secondary" onClick={() => send('close')} disabled={busy || !online}>
          Close
        </Button>
      </div>
      {!online && <p className="mt-2 text-xs text-muted">Commands need the sensors online.</p>}
    </Card>
  )
}

function ActiveReservations({ reservations }) {
  const now = useNow()
  const list = Object.entries(reservations)
    .map(([id, r]) => ({ id, ...r }))
    .sort((a, b) => a.expires_at - b.expires_at)

  return (
    <Card
      title="Active reservations"
      action={
        <Link to="/reservations" className="text-sm text-accent hover:underline">
          Manage
        </Link>
      }
    >
      {list.length === 0 ? (
        <p className="text-sm text-muted">None. Click a free spot on the map to reserve it.</p>
      ) : (
        <ul className="divide-y divide-line text-sm">
          {list.map((r) => (
            <li key={r.id} className="flex justify-between py-2">
              <span>
                <strong className="font-semibold">{r.spot_id}</strong> · {r.name}
              </span>
              <span className="tabular-nums text-ink-2">{countdown(r.expires_at - now)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function LivePage() {
  const { spots, summary, barrier, gateCar, reservations, ready } = useLive()
  const online = useDeviceOnline()
  const [reserving, setReserving] = useState(null)
  const freeSpots = SPOT_IDS.filter((id) => spots[id]?.status === 'free')

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <Card>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-ink-2">Available now</p>
            <p className="text-4xl font-semibold">
              {ready && summary ? (
                <>
                  {summary.free} <span className="text-2xl text-muted">/ {summary.total} free</span>
                </>
              ) : (
                '–'
              )}
            </p>
            {summary && (
              <p className="mt-1 text-sm text-ink-2">
                {summary.occupied} occupied · {summary.reserved} reserved
              </p>
            )}
          </div>
          <StatusLegend />
        </div>
        <ParkingMap
          spots={spots}
          online={online}
          barrierState={barrier.state}
          gateCar={gateCar && online}
          onSelectFree={setReserving}
        />
        <p className="mt-3 text-xs text-muted">Click a free spot to reserve it.</p>
      </Card>

      <div className="grid content-start gap-4">
        <BarrierPanel barrier={barrier} gateCar={gateCar} online={online} />
        <ActiveReservations reservations={reservations} />
      </div>

      {reserving && <ReserveDialog spotId={reserving} freeSpots={freeSpots} onClose={() => setReserving(null)} />}
    </div>
  )
}
