import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Button, Card, inputClass } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ name: '', email: '', password: '', plate: '', language: 'en' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const next = location.state?.from || '/account'

  if (user) return <Navigate to={next} replace />

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const auth =
        mode === 'login'
          ? await api.login({ email: form.email, password: form.password })
          : await api.register({
              name: form.name.trim(),
              email: form.email,
              password: form.password,
              plate: form.plate.trim() || null,
              language: form.language,
            })
      signIn(auth)
      navigate(next, { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <Card>
        <div className="mb-4 grid grid-cols-2 rounded-lg bg-ink/5 p-1 text-sm" role="tablist">
          {[
            ['login', 'Sign in'],
            ['register', 'Create account'],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={mode === id}
              onClick={() => setMode(id)}
              className={`rounded-md py-1.5 ${mode === id ? 'bg-surface font-medium shadow-sm' : 'text-ink-2'}`}
            >
              {label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="grid gap-3">
          {mode === 'register' && (
            <label className="grid gap-1 text-sm">
              <span className="text-ink-2">Name</span>
              <input className={inputClass} value={form.name} onChange={set('name')} maxLength={40} required />
            </label>
          )}
          <label className="grid gap-1 text-sm">
            <span className="text-ink-2">E-mail</span>
            <input
              className={inputClass}
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={set('email')}
              required
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-ink-2">Password</span>
            <input
              className={inputClass}
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              minLength={mode === 'register' ? 8 : undefined}
              value={form.password}
              onChange={set('password')}
              required
            />
          </label>
          {mode === 'register' && (
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1 text-sm">
                <span className="text-ink-2">Plate (optional)</span>
                <input className={inputClass} value={form.plate} onChange={set('plate')} maxLength={16} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-ink-2">Language</span>
                <select className={inputClass} value={form.language} onChange={set('language')}>
                  <option value="en">English</option>
                  <option value="fr">Français</option>
                  <option value="ar">العربية</option>
                </select>
              </label>
            </div>
          )}
          {error && <p className="text-sm text-occupied">{error}</p>}
          <Button type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
