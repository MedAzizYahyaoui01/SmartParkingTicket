// One live subscription for the whole app, shared through a React context.
// Firebase pushes every change (onValue, no polling). Without Firebase configured,
// the same data is polled from the API every 2 s, so the dashboard still works.
import { onValue, ref } from 'firebase/database'
import { createContext, useContext, useEffect, useState } from 'react'

import { api } from './api'
import { db } from './firebase'

// The API marks the device offline after 15 s; this covers the case where the API itself
// is down (Firebase would then keep saying "online" forever).
const STALE_AFTER_S = 20

const initial = {
  source: db ? 'Firebase (live)' : 'API (polling)',
  ready: false,
  error: null,
  spots: {}, // {P1: {status, distance_cm, updated_at}}
  summary: null, // {free, occupied, reserved, total}
  device: { online: false, last_seen: null },
  barrier: { state: 'closed', command: null },
  gateCar: false,
  reservations: {}, // {id: {spot_id, name, created_at, expires_at}}
}

function subscribeFirebase(setState) {
  const fail = (err) => setState((s) => ({ ...s, error: err.message }))
  const unsubscribers = [
    onValue(
      ref(db, 'parking'),
      (snap) => {
        const p = snap.val() || {}
        setState((s) => ({
          ...s,
          ready: true,
          error: null,
          spots: p.spots || {},
          summary: p.summary || null,
          device: p.device || initial.device,
          gateCar: Boolean(p.gate_car_detected),
        }))
      },
      fail,
    ),
    onValue(
      ref(db, 'barrier'),
      (snap) => {
        const b = snap.val() || {}
        setState((s) => ({ ...s, barrier: { state: b.state || 'closed', command: b.command || null } }))
      },
      fail,
    ),
    onValue(ref(db, 'reservations'), (snap) => setState((s) => ({ ...s, reservations: snap.val() || {} })), fail),
  ]
  return () => unsubscribers.forEach((off) => off())
}

function pollApi(setState) {
  let stopped = false
  async function tick() {
    try {
      const [parking, reservations] = await Promise.all([api.spots(), api.reservations()])
      if (stopped) return
      setState((s) => ({
        ...s,
        ready: true,
        error: null,
        spots: Object.fromEntries(parking.spots.map((spot) => [spot.spot_id, spot])),
        summary: parking.summary,
        device: parking.device,
        gateCar: parking.gate_car_detected,
        barrier: { ...s.barrier, state: parking.barrier_state },
        reservations: Object.fromEntries(reservations.map((r) => [r.id, r])),
      }))
    } catch (err) {
      if (!stopped) setState((s) => ({ ...s, error: err.message }))
    }
  }
  tick()
  const timer = setInterval(tick, 2000)
  return () => {
    stopped = true
    clearInterval(timer)
  }
}

const LiveContext = createContext(initial)

export function LiveProvider({ children }) {
  const [state, setState] = useState(initial)
  useEffect(() => (db ? subscribeFirebase(setState) : pollApi(setState)), [])
  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>
}

export function useLive() {
  return useContext(LiveContext)
}

/** Current time in seconds, refreshed every `intervalMs` (for countdowns and staleness). */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

export function useDeviceOnline() {
  const { device } = useLive()
  const now = useNow()
  return Boolean(device.online && device.last_seen && now - device.last_seen < STALE_AFTER_S)
}
