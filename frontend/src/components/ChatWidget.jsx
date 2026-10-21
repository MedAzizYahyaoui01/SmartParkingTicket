// Floating assistant on every app page (the kiosk page has its own, full-size one).
import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import Chat from './Chat'
import CheckoutDialog from './CheckoutDialog'

export default function ChatWidget() {
  const { user, refresh } = useAuth()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [needsLogin, setNeedsLogin] = useState(false)
  const [topUp, setTopUp] = useState(null) // {amount} while the checkout is open
  const [pricing, setPricing] = useState(null)

  useEffect(() => {
    if (user) setNeedsLogin(false)
  }, [user])

  const onActions = useCallback(
    (actions) => {
      for (const a of actions) {
        if (a.type === 'login_required') setNeedsLogin(true)
        if (a.type === 'open_top_up') {
          api.pricing().then(setPricing).catch(() => {})
          setTopUp({ amount: a.amount })
        }
      }
      refresh()
    },
    [refresh],
  )

  if (location.pathname === '/gate') return null

  return (
    <>
      {open && (
        <section
          className="fixed inset-x-4 bottom-20 z-40 flex h-[min(560px,70vh)] flex-col overflow-hidden rounded-xl border border-line bg-page shadow-2xl sm:left-auto sm:w-96"
          aria-label="Parking assistant"
        >
          <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-2.5">
            <div>
              <p className="text-sm font-semibold">Parking assistant</p>
              <p className="text-xs text-muted">English · Français · العربية</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md px-2 py-1 text-ink-2 hover:bg-ink/5"
              aria-label="Close assistant"
            >
              ✕
            </button>
          </header>
          {needsLogin && !user && (
            <p className="border-b border-line bg-reserved/10 px-4 py-2 text-xs">
              <Link to="/login" className="font-medium text-accent hover:underline" onClick={() => setOpen(false)}>
                Sign in
              </Link>{' '}
              to reserve, open the gate or check your balance.
            </p>
          )}
          <Chat
            key={user?.uid || 'anonymous'}
            defaultLang={user?.language || 'en'}
            greeting={`Hi${user ? ` ${user.name}` : ''}! How can I help? · Comment puis-je aider ? · كيف نجم نعاونك؟`}
            suggestions={['Free spots?', 'Réserver 30 min', 'رصيدي', 'Busy hours?']}
            onActions={onActions}
            className="flex-1"
          />
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-4 right-4 z-40 grid size-14 place-items-center rounded-full bg-accent text-white shadow-lg hover:opacity-90"
        aria-label={open ? 'Close assistant' : 'Open assistant'}
        aria-expanded={open}
      >
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M4 5h16v11H8l-4 4z" strokeLinejoin="round" />
        </svg>
      </button>

      {topUp && user && (
        <CheckoutDialog
          initialAmount={topUp.amount}
          pricing={pricing}
          onClose={() => setTopUp(null)}
          onPaid={() => refresh()}
        />
      )}
    </>
  )
}
