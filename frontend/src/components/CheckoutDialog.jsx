// Wallet top-up through the (simulated) card gateway: amount -> card -> receipt.
import { useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { money } from '../lib/format'
import { Button, inputClass } from './ui'

const PRESETS = [10000, 20000, 50000]
const TEST_CARDS = [
  ['4242 4242 4242 4242', 'success'],
  ['4000 0000 0000 0002', 'declined'],
  ['4000 0000 0000 9995', 'insufficient funds'],
]
const REASONS = {
  card_declined: 'Your card was declined.',
  insufficient_funds: 'Insufficient funds on the card.',
  expired_card: 'This card has expired.',
  invalid_number: 'The card number is not valid.',
}

function formatCardNumber(value) {
  return value
    .replace(/\D/g, '')
    .slice(0, 19)
    .replace(/(.{4})/g, '$1 ')
    .trim()
}

export default function CheckoutDialog({ initialAmount, pricing, onClose, onPaid }) {
  const min = pricing?.topup_min ?? 5000
  const max = pricing?.topup_max ?? 500000
  const [amount, setAmount] = useState(initialAmount || 20000)
  const [card, setCard] = useState({ number: '', expiry: '', cvc: '', holder: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [receipt, setReceipt] = useState(null)
  const dialog = useRef(null)

  useEffect(() => {
    dialog.current?.querySelector('input')?.focus()
  }, [])

  async function pay(e) {
    e.preventDefault()
    setError(null)
    const [month, year] = card.expiry.split('/').map((p) => parseInt(p, 10))
    if (!month || !year || month > 12) {
      setError('Expiry must be MM/YY.')
      return
    }
    setBusy(true)
    try {
      const checkout = await api.checkout(amount)
      const result = await api.confirmPayment(checkout.id, {
        number: card.number,
        exp_month: month,
        exp_year: year < 100 ? 2000 + year : year,
        cvc: card.cvc,
        holder: card.holder.trim(),
      })
      if (result.status === 'succeeded') {
        setReceipt(result)
        onPaid?.(result)
      } else {
        setError(REASONS[result.failure_reason] || 'Payment failed.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const amountValid = amount >= min && amount <= max

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
      onKeyDown={(e) => e.key === 'Escape' && !busy && onClose()}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="checkout-title"
        className="max-h-full w-full max-w-sm overflow-y-auto rounded-xl bg-surface p-5 shadow-xl"
      >
        {receipt ? (
          <div className="grid gap-3 text-center">
            <div className="mx-auto grid size-12 place-items-center rounded-full bg-free/15 text-2xl text-free" aria-hidden>
              ✓
            </div>
            <h2 id="checkout-title" className="text-lg font-semibold">
              Payment successful
            </h2>
            <dl className="grid grid-cols-2 gap-y-1 rounded-lg border border-line p-3 text-left text-sm">
              <dt className="text-ink-2">Amount</dt>
              <dd className="text-right font-medium">{money(receipt.amount, receipt.currency)}</dd>
              <dt className="text-ink-2">Card</dt>
              <dd className="text-right">
                {receipt.card_brand} •••• {receipt.card_last4}
              </dd>
              <dt className="text-ink-2">Receipt</dt>
              <dd className="text-right font-mono text-xs">{receipt.receipt_no}</dd>
              <dt className="text-ink-2">New balance</dt>
              <dd className="text-right font-semibold">{money(receipt.balance_after, receipt.currency)}</dd>
            </dl>
            <Button onClick={onClose}>Done</Button>
          </div>
        ) : (
          <form onSubmit={pay} className="grid gap-3">
            <h2 id="checkout-title" className="text-lg font-semibold">
              Top up your wallet
            </h2>

            <div className="grid grid-cols-3 gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setAmount(p)}
                  className={`rounded-lg border px-2 py-2 text-sm ${
                    amount === p ? 'border-accent bg-accent/10 font-medium text-accent' : 'border-line hover:bg-ink/5'
                  }`}
                >
                  {money(p)}
                </button>
              ))}
            </div>
            <label className="grid gap-1 text-sm">
              <span className="text-ink-2">Amount (TND)</span>
              <input
                className={inputClass}
                type="number"
                min={min / 1000}
                max={max / 1000}
                step="0.5"
                value={amount / 1000}
                onChange={(e) => setAmount(Math.round(Number(e.target.value) * 1000))}
                required
              />
            </label>

            <label className="grid gap-1 text-sm">
              <span className="text-ink-2">Card number</span>
              <input
                className={`${inputClass} font-mono`}
                inputMode="numeric"
                autoComplete="cc-number"
                placeholder="4242 4242 4242 4242"
                value={card.number}
                onChange={(e) => setCard({ ...card, number: formatCardNumber(e.target.value) })}
                required
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1 text-sm">
                <span className="text-ink-2">Expiry</span>
                <input
                  className={inputClass}
                  autoComplete="cc-exp"
                  placeholder="MM/YY"
                  value={card.expiry}
                  onChange={(e) => {
                    const digits = e.target.value.replace(/\D/g, '').slice(0, 4)
                    setCard({ ...card, expiry: digits.length > 2 ? `${digits.slice(0, 2)}/${digits.slice(2)}` : digits })
                  }}
                  required
                />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-ink-2">CVC</span>
                <input
                  className={inputClass}
                  inputMode="numeric"
                  autoComplete="cc-csc"
                  placeholder="123"
                  value={card.cvc}
                  onChange={(e) => setCard({ ...card, cvc: e.target.value.replace(/\D/g, '').slice(0, 4) })}
                  required
                />
              </label>
            </div>
            <label className="grid gap-1 text-sm">
              <span className="text-ink-2">Name on card</span>
              <input
                className={inputClass}
                autoComplete="cc-name"
                value={card.holder}
                onChange={(e) => setCard({ ...card, holder: e.target.value })}
                maxLength={60}
                required
              />
            </label>

            {error && (
              <p className="rounded-lg border border-occupied/40 bg-occupied/10 px-3 py-2 text-sm" role="alert">
                {error}
              </p>
            )}
            {!amountValid && (
              <p className="text-sm text-occupied">
                Between {money(min)} and {money(max)}.
              </p>
            )}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !amountValid}>
                {busy ? 'Processing…' : `Pay ${money(amount)}`}
              </Button>
            </div>

            <details className="text-xs text-muted">
              <summary className="cursor-pointer">Test cards (simulated gateway)</summary>
              <ul className="mt-1 grid gap-0.5">
                {TEST_CARDS.map(([n, label]) => (
                  <li key={n}>
                    <button
                      type="button"
                      className="font-mono text-accent hover:underline"
                      onClick={() => setCard({ ...card, number: n })}
                    >
                      {n}
                    </button>{' '}
                    – {label}
                  </li>
                ))}
                <li>Any future expiry, any CVC.</li>
              </ul>
            </details>
          </form>
        )}
      </div>
    </div>
  )
}
