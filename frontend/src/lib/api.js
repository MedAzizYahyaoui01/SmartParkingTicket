// REST calls to the FastAPI backend.
const BASE = `${(import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')}/api/v1`

// The signed-in user's token (set by AuthProvider). The kiosk passes its own short-lived
// token per call instead, so a kiosk session never touches the app's sign-in.
let userToken = null
export function setUserToken(token) {
  userToken = token
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { token, ...options } = {}) {
  const bearer = token === undefined ? userToken : token
  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...options.headers,
    },
  })
  if (!res.ok) {
    // FastAPI errors: {"detail": "message"} or {"detail": [{"msg": ...}]} for validation
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      message = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg || message
    } catch {
      /* not JSON: keep the status text */
    }
    throw new ApiError(message, res.status)
  }
  return res.status === 204 ? null : res.json()
}

const post = (path, body, options) => request(path, { method: 'POST', body: JSON.stringify(body), ...options })
const query = (params) => new URLSearchParams(params).toString()

export const api = {
  spots: () => request('/spots'),
  reservations: () => request('/reservations'),
  reserve: (body, token) => post('/reservations', body, { token }),
  cancelReservation: (id, token) => request(`/reservations/${id}`, { method: 'DELETE', token }),
  barrier: (action) => post('/barrier/command', { action }),
  occupancy: (params) => request(`/stats/occupancy?${query(params)}`),
  statsSummary: (params) => request(`/stats/summary?${query(params)}`),

  // Accounts and wallet
  register: (body) => post('/auth/register', body, { token: null }),
  login: (body) => post('/auth/login', body, { token: null }),
  me: (token) => request('/me', { token }),
  updateMe: (body) => request('/me', { method: 'PATCH', body: JSON.stringify(body) }),
  transactions: () => request('/me/transactions'),
  accessCode: () => post('/me/access-code', {}),
  pricing: () => request('/pricing'),
  checkout: (amount) => post('/payments/checkout', { amount }),
  confirmPayment: (id, card) => post(`/payments/${id}/confirm`, card),
  payments: () => request('/payments'),

  // Gate and assistant
  identify: (code) => post('/gate/identify', { code }, { token: null }),
  gateEnter: (token) => post('/gate/enter', {}, { token }),
  gateExit: (token) => post('/gate/exit', {}, { token }),
  chat: (body, token) => post('/chat', body, { token }),
  chatInfo: () => request('/chat/info'),
}
