import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import CheckoutDialog from '../components/CheckoutDialog'
import { Button, Card, StatTile } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { countdown, minutes, money } from '../lib/format'
import { useNow } from '../lib/live'
import { useToast } from '../lib/toast'

const STATUS = {
  ok: { label: 'Ready to park', className: 'text-free' },
  low: { label: 'Top up to enter', className: 'text-reserved' },
  debt: { label: 'Balance due: blocked', className: 'text-occupied' },
}

const REFUSALS = {
  already_inside: 'You are already inside.',
  not_inside: 'You are not parked inside.',
  debt: 'Your balance is negative: top up first.',
  low_balance: 'Not enough credit to enter: top up first.',
  full: 'The parking is full and you have no reservation.',
}

const TX_LABEL = {
  topup: 'Top-up',
  reservation_fee: 'Reservation',
  reservation_refund: 'Refund',
  parking: 'Parking',
}

/** The code the kiosk scans. Renewed automatically when it expires. */
function AccessCode() {
  const [code, setCode] = useState(null)
  const [error, setError] = useState(null)
  const now = useNow()

  const renew = useCallback(async () => {
    try {
      setCode(await api.accessCode())
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    renew()
  }, [renew])
  const left = code ? code.expires_at - now : 0
  useEffect(() => {
    if (code && left <= 0) renew()
  }, [code, left, renew])

  return (
    <Card title="Gate access code">
      {error && <p className="text-sm text-occupied">{error}</p>}
      {code && (
        <div className="grid justify-items-center gap-3">
          <div className="rounded-xl bg-white p-3">
            <QRCodeSVG value={code.qr_payload} size={176} level="M" />
          </div>
          <p className="font-mono text-3xl font-semibold tracking-[0.3em]" aria-label="Code">
            {code.code}
          </p>
          <p className="text-xs text-muted">
            Show it to the kiosk camera, or type the digits. New code in {countdown(left)}.
          </p>
        </div>
      )}
    </Card>
  )
}

export default function AccountPage() {
  const { user, token, loading, refresh, signOut } = useAuth()
  const toast = useToast()
  const [pricing, setPricing] = useState(null)
  const [transactions, setTransactions] = useState([])
  const [checkout, setCheckout] = useState(false)
  const [busy, setBusy] = useState(false)

  const loadTransactions = useCallback(() => {
    api.transactions().then(setTransactions).catch(() => {})
  }, [])

  useEffect(() => {
    api.pricing().then(setPricing).catch(() => {})
  }, [])
  useEffect(() => {
    if (user) loadTransactions()
  }, [user?.balance, loadTransactions]) // reload when the balance moves

  if (!token) return <Navigate to="/login" state={{ from: '/account' }} replace />
  if (loading || !user) return <p className="text-sm text-muted">Loading…</p>

  const status = STATUS[user.status]

  async function gate(direction) {
    setBusy(true)
    try {
      const d = direction === 'entry' ? await api.gateEnter() : await api.gateExit()
      if (d.allowed) {
        toast(
          direction === 'entry'
            ? `Barrier opening${d.spot_hint ? ` · your spot is ${d.spot_hint}` : ''}`
            : `Goodbye! ${minutes(d.minutes)}, ${money(d.fee)} charged`,
          'success',
        )
        if (!d.device_online) toast('The sensors are offline: the barrier may not move', 'error')
      } else {
        toast(REFUSALS[d.reason] || d.reason, 'error')
        if (d.reason === 'debt' || d.reason === 'low_balance') setCheckout(true)
      }
      await refresh()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function cancelReservation() {
    try {
      await api.cancelReservation(user.reservation.id)
      toast('Reservation cancelled, fee refunded', 'info')
      refresh()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{user.name}</h1>
          <p className="text-sm text-ink-2">
            UID <span className="font-mono">{user.uid}</span>
            {user.plate && <> · {user.plate}</>} · {user.email}
          </p>
        </div>
        <Button variant="secondary" onClick={signOut}>
          Sign out
        </Button>
      </div>

      {user.status === 'debt' && (
        <p className="rounded-lg border border-occupied/40 bg-occupied/10 px-4 py-2 text-sm" role="alert">
          You owe {money(-user.balance, user.currency)}. Entry and reservations are blocked until you top up.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Wallet balance"
          value={<span className={user.balance < 0 ? 'text-occupied' : ''}>{money(user.balance, user.currency)}</span>}
          hint={<span className={status.className}>{status.label}</span>}
        />
        <StatTile
          label="Current stay"
          value={user.stay ? minutes(user.stay.minutes) : 'Not parked'}
          hint={user.stay ? `${money(user.stay.fee_so_far)} if you leave now` : 'Open the gate to enter'}
        />
        <StatTile
          label="Reservation"
          value={user.reservation ? user.reservation.spot_id : 'None'}
          hint={
            user.reservation
              ? `until ${new Date(user.reservation.expires_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
              : pricing && `${money(pricing.reservation_fee)} per reservation`
          }
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => setCheckout(true)}>Top up</Button>
        {user.stay ? (
          <Button variant="secondary" onClick={() => gate('exit')} disabled={busy}>
            Leave (open barrier)
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => gate('entry')} disabled={busy}>
            Enter (open barrier)
          </Button>
        )}
        {user.reservation && (
          <Button variant="danger" onClick={cancelReservation}>
            Cancel reservation
          </Button>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-[300px_1fr]">
        <AccessCode />
        <Card title="Wallet statement">
          {transactions.length === 0 ? (
            <p className="text-sm text-muted">No transaction yet.</p>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {transactions.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-2">
                  <div>
                    <p className="font-medium">{TX_LABEL[t.kind]}</p>
                    <p className="text-xs text-muted">
                      {t.description} · {new Date(t.ts).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={`font-semibold tabular-nums ${t.amount < 0 ? 'text-occupied' : 'text-free'}`}>
                      {t.amount > 0 ? '+' : ''}
                      {money(t.amount, user.currency)}
                    </p>
                    <p className="text-xs text-muted tabular-nums">{money(t.balance_after, user.currency)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {pricing && (
        <p className="text-xs text-muted">
          {money(pricing.hourly_rate)} per hour, first {pricing.free_minutes} min free, billed per started{' '}
          {pricing.billing_block_min} min. {money(pricing.min_entry_balance)} of credit needed to enter.
        </p>
      )}

      {checkout && (
        <CheckoutDialog
          pricing={pricing}
          onClose={() => setCheckout(false)}
          onPaid={() => {
            refresh()
            loadTransactions()
          }}
        />
      )}
    </div>
  )
}
