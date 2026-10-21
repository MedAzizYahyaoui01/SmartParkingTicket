// Gate kiosk: the screen at the barrier. Drivers talk to the assistant (voice or text, in
// English, French or Arabic) and identify themselves with the QR code from the app.
// The kiosk session lives only in this page's memory and ends after a few minutes.
import { useCallback, useEffect, useState } from 'react'

import Chat from '../components/Chat'
import QrScanner from '../components/QrScanner'
import { Button, Card, inputClass } from '../components/ui'
import { api } from '../lib/api'
import { money } from '../lib/format'
import { useLive, useNow } from '../lib/live'
import { useToast } from '../lib/toast'

const GREETING = 'Hello! · Bonjour ! · مرحبا! Ask me for a free spot, to open the gate, or to reserve.'
const SUGGESTIONS = ['Any free spot?', 'Ouvrez la barrière', 'حل الباب', 'Je pars', 'قداش السوم؟', 'My balance']

function Identify({ onSession }) {
  const [scanning, setScanning] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = useCallback(
    async (value) => {
      setBusy(true)
      setError(null)
      try {
        onSession(await api.identify(value))
        setCode('')
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
        setScanning(false)
      }
    },
    [onSession],
  )

  if (scanning) return <QrScanner onCode={submit} onClose={() => setScanning(false)} />

  return (
    <div className="grid gap-3">
      <Button className="py-3 text-base" onClick={() => setScanning(true)}>
        Scan my QR code
      </Button>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit(code)
        }}
      >
        <input
          className={`${inputClass} font-mono text-lg tracking-widest`}
          inputMode="numeric"
          placeholder="6-digit code"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          aria-label="Access code"
        />
        <Button type="submit" variant="secondary" disabled={busy || code.length !== 6}>
          OK
        </Button>
      </form>
      {error && <p className="text-sm text-occupied">{error}</p>}
      <p className="text-xs text-muted">
        Open the app, Account page: the code is shown as a QR code and as digits.
      </p>
    </div>
  )
}

export default function GatePage() {
  const { summary, barrier } = useLive()
  const toast = useToast()
  const now = useNow()
  const [session, setSession] = useState(null) // {token, expires_at, user}
  const [banner, setBanner] = useState(null)

  const endSession = useCallback(() => setSession(null), [])
  useEffect(() => {
    if (session && now >= session.expires_at) endSession()
  }, [session, now, endSession])

  const refreshUser = useCallback(async () => {
    if (!session) return
    try {
      const user = await api.me(session.token)
      setSession((s) => (s ? { ...s, user } : s))
    } catch {
      endSession()
    }
  }, [session, endSession])

  const showBanner = useCallback((text, tone) => {
    setBanner({ text, tone })
    setTimeout(() => setBanner(null), 6000)
  }, [])

  const onActions = useCallback(
    (actions) => {
      for (const a of actions) {
        if (a.type === 'barrier_opening') {
          showBanner(a.direction === 'exit' ? 'Barrier opening · Goodbye!' : 'Barrier opening · Welcome!', 'ok')
        }
        if (a.type === 'open_top_up') showBanner('Please top up your wallet in the app', 'warn')
      }
      refreshUser()
    },
    [refreshUser, showBanner],
  )

  async function gate(direction) {
    try {
      const d = direction === 'entry' ? await api.gateEnter(session.token) : await api.gateExit(session.token)
      if (d.allowed) {
        onActions([{ type: 'barrier_opening', direction }])
      } else {
        toast(`Refused: ${d.reason.replace('_', ' ')}`, 'error')
        refreshUser()
      }
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const user = session?.user

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
      <div className="grid content-start gap-4">
        <Card>
          <p className="text-sm text-ink-2">Free spots</p>
          <p className="text-5xl font-bold tabular-nums">
            {summary ? summary.free : '–'}
            <span className="text-2xl font-medium text-muted"> / {summary?.total ?? 4}</span>
          </p>
          <p className="mt-1 text-xs text-muted">Barrier: {barrier.state}</p>
        </Card>

        <Card title={user ? 'Identified' : 'Who are you?'}>
          {user ? (
            <div className="grid gap-3">
              <div>
                <p className="text-lg font-semibold">{user.name}</p>
                <p className="font-mono text-xs text-ink-2">{user.uid}</p>
                <p className={`mt-1 text-sm ${user.balance < 0 ? 'text-occupied' : ''}`}>
                  Balance {money(user.balance, user.currency)}
                  {user.reservation && <> · reserved {user.reservation.spot_id}</>}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Button className="py-3" onClick={() => gate('entry')} disabled={Boolean(user.stay)}>
                  Enter
                </Button>
                <Button className="py-3" variant="secondary" onClick={() => gate('exit')} disabled={!user.stay}>
                  Leave
                </Button>
              </div>
              <button type="button" onClick={endSession} className="text-sm text-accent hover:underline">
                End session (next driver)
              </button>
            </div>
          ) : (
            <Identify onSession={setSession} />
          )}
        </Card>
      </div>

      <section className="flex h-[70vh] min-h-[480px] flex-col overflow-hidden rounded-xl border border-line bg-surface">
        {banner && (
          <p
            role="status"
            className={`m-3 mb-0 rounded-lg px-4 py-3 text-center text-lg font-semibold ${
              banner.tone === 'ok' ? 'bg-free/15 text-free' : 'bg-reserved/15 text-reserved'
            }`}
          >
            {banner.text}
          </p>
        )}
        {/* A new key per session: each driver starts a fresh conversation */}
        <Chat
          key={session?.token || 'anonymous'}
          token={session?.token ?? null}
          channel="kiosk"
          defaultLang={user?.language || 'en'}
          greeting={user ? `${GREETING.split('!')[0]} ${user.name}!` : GREETING}
          suggestions={SUGGESTIONS}
          onActions={onActions}
          large
          className="flex-1"
        />
      </section>
    </div>
  )
}
