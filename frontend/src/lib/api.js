// REST calls to the FastAPI backend.
const BASE = `${(import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')}/api/v1`

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
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
    throw new Error(message)
  }
  return res.status === 204 ? null : res.json()
}

const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) })
const query = (params) => new URLSearchParams(params).toString()

export const api = {
  spots: () => request('/spots'),
  reservations: () => request('/reservations'),
  reserve: (body) => post('/reservations', body),
  cancelReservation: (id) => request(`/reservations/${id}`, { method: 'DELETE' }),
  barrier: (action) => post('/barrier/command', { action }),
  occupancy: (params) => request(`/stats/occupancy?${query(params)}`),
  statsSummary: (params) => request(`/stats/summary?${query(params)}`),
}
