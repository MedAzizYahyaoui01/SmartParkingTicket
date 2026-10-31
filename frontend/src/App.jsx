import { lazy, Suspense, useEffect, useRef } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'

import ChatWidget from './components/ChatWidget'
import { useAuth } from './lib/auth'
import { money } from './lib/format'
import { useDeviceOnline, useLive } from './lib/live'
import { useToast } from './lib/toast'
import LivePage from './pages/LivePage'
import LoginPage from './pages/LoginPage'
import ReservationsPage from './pages/ReservationsPage'

// Heavy pages (charts, QR code libraries) are only loaded when opened
const StatsPage = lazy(() => import('./pages/StatsPage'))
const PredictionPage = lazy(() => import('./pages/PredictionPage'))
const GatePage = lazy(() => import('./pages/GatePage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))

const loading = <p className="text-sm text-muted">Loading…</p>

const NAV = [
  { to: '/', label: 'Live map' },
  { to: '/reservations', label: 'Reservations' },
  { to: '/stats', label: 'Statistics' },
  { to: '/predictions', label: 'Prediction' },
  { to: '/gate', label: 'Gate kiosk' },
]

function AccountLink() {
  const { user, token } = useAuth()
  if (!token) {
    return (
      <Link to="/login" className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
        Sign in
      </Link>
    )
  }
  return (
    <Link
      to="/account"
      className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-sm hover:bg-ink/5"
    >
      <span className="font-medium">{user?.name || 'Account'}</span>
      {user && (
        <span className={`tabular-nums ${user.balance < 0 ? 'text-occupied' : 'text-ink-2'}`}>
          {money(user.balance, user.currency)}
        </span>
      )}
    </Link>
  )
}

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
          <div className="ml-auto flex items-center gap-2">
            <DeviceBadge />
            <AccountLink />
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
          <Route path="/gate" element={<Suspense fallback={loading}><GatePage /></Suspense>} />
          <Route
            path="/predictions"
            element={
              <Suspense fallback={loading}>
                <PredictionPage />
              </Suspense>
            }
          />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/account" element={<Suspense fallback={loading}><AccountPage /></Suspense>} />
          <Route
            path="/stats"
            element={
              <Suspense fallback={loading}>
                <StatsPage />
              </Suspense>
            }
          />
        </Routes>
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-6 text-xs text-muted">
        Live data source: {source}
      </footer>

      <ChatWidget />
    </div>
  )
}
