// Firebase Realtime Database, read-only (the security rules forbid browser writes).
// Public read needs only the database URL: no API key, no sign-in.
import { initializeApp } from 'firebase/app'
import { getDatabase } from 'firebase/database'

const url = import.meta.env.VITE_FIREBASE_DATABASE_URL
const configured = Boolean(url) && !url.includes('<')

export const db = configured ? getDatabase(initializeApp({ databaseURL: url })) : null
