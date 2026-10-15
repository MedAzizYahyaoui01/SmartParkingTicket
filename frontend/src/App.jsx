import { lazy, Suspense, useEffect, useRef } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import { useDeviceOnline, useLive } from './lib/live'
import { useToast } from './lib/toast'
import LivePage from './pages/LivePage'
import ReservationsPage from './pages/ReservationsPage'

// Charts are only loaded when the Statistics page is opened
const StatsPage = lazy(() => import('./pages/StatsPage'))

const NAV = [
  { to: '/', label: 'Live map' },
  { to: '/reservations', label: 'Reservations' },
  { to: '/stats', label: 'Statistics' },
]

function DeviceBadge() {
  const online = useDeviceOnline()
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs font-medium">
      <span className={`size-2 rounded-full ${online ? 'bg-free' : 'bg-offline'}`} aria-hidden />
      Sensors {online ? 'online' : 'offline'}
    </span>
  )
}

/** Shows a toast whenever the barrier starts opening (whoever asked for it). */
function useBarrierToast() {
  const { barrier, ready } = useLive()
  const toast = useToast()
  const previous = useRef(null)
  useEffect(() => {
    if (!ready) return
    // From the closed side to the open side ("opening" can be skipped between two updates)
    const isUp = (state) => state === 'opening' || state === 'open'
    if (previous.current && !isUp(previous.current) && isUp(barrier.state)) {
      toast('Barrier opening', 'success')
    }
    previous.current = barrier.state
  }, [barrier.state, ready, toast])
}

export default function App() {
  const { error, source } = useLive()
  useBarrierToast()

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <span className="flex items-center gap-2 text-lg font-semibold">
            <span className="grid size-7 place-items-center rounded-md bg-accent text-sm font-bold text-white">
              P
            </span>
            Smart Parking
          </span>
          <nav className="order-last flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${
                    isActive ? 'bg-accent/10 font-medium text-accent' : 'text-ink-2 hover:bg-ink/5'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <DeviceBadge />
          </div>
        </div>
      </header>

      {error && (
        <div className="mx-auto mt-4 max-w-6xl px-4">
          <p className="rounded-lg border border-occupied/40 bg-occupied/10 px-4 py-2 text-sm">
            Live data unavailable ({source}): {error}
          </p>
        </div>
      )}

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<LivePage />} />
          <Route path="/reservations" element={<ReservationsPage />} />
          <Route
            path="/stats"
            element={
              <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
                <StatsPage />
              </Suspense>
            }
          />
        </Routes>
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-6 text-xs text-muted">
        Live data source: {source}
      </footer>
    </div>
  )
}
