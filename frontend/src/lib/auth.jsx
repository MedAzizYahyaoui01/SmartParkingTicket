// The signed-in user, shared through a React context. The token is kept in localStorage
// so a reload keeps you signed in (wrapped in try/catch: storage can be blocked).
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, setUserToken } from './api'

const KEY = 'smart-parking.token'

function readToken() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

function writeToken(token) {
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    /* private mode: the session lasts until the tab is closed */
  }
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => {
    const t = readToken()
    setUserToken(t)
    return t
  })
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(token))

  const signIn = useCallback((auth) => {
    setUserToken(auth.token)
    writeToken(auth.token)
    setToken(auth.token)
    setUser(auth.user)
  }, [])

  const signOut = useCallback(() => {
    setUserToken(null)
    writeToken(null)
    setToken(null)
    setUser(null)
  }, [])

  const refresh = useCallback(async () => {
    if (!token) return null
    try {
      const me = await api.me()
      setUser(me)
      return me
    } catch (err) {
      if (err.status === 401) signOut()
      return null
    } finally {
      setLoading(false)
    }
  }, [token, signOut])

  // Load the profile on start, then keep the balance and stay fresh
  useEffect(() => {
    if (!token) return undefined
    refresh()
    const timer = setInterval(refresh, 15000)
    return () => clearInterval(timer)
  }, [token, refresh])

  const value = useMemo(
    () => ({ token, user, loading, signIn, signOut, refresh }),
    [token, user, loading, signIn, signOut, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
