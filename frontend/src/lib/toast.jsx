// Small toast notifications (barrier opening, reservation made, errors...).
import { createContext, useCallback, useContext, useState } from 'react'

const ToastContext = createContext(() => {})

const TONES = {
  info: 'border-l-accent',
  success: 'border-l-free',
  error: 'border-l-occupied',
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const push = useCallback((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-4 bottom-24 z-50 flex flex-col items-end gap-2"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto max-w-sm rounded-lg border border-l-4 border-line bg-surface px-4 py-3 text-sm shadow-lg ${TONES[t.tone]}`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
