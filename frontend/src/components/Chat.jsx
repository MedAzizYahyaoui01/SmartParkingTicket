// Conversation with the parking assistant: typed or spoken (browser speech recognition),
// with the replies read aloud. Used in the app's chat widget and on the gate kiosk.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import { inputClass } from './ui'

const VOICES = [
  { id: 'en', label: 'English', speech: 'en-US' },
  { id: 'fr', label: 'Français', speech: 'fr-FR' },
  { id: 'ar', label: 'العربية', speech: 'ar-TN' },
]
const speechCode = (lang) => VOICES.find((v) => v.id === lang)?.speech || 'en-US'

const Recognition = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

function speak(text, lang) {
  if (!canSpeak) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = speechCode(lang)
  // Prefer a voice of that language when the system has one (Arabic voices are often missing)
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang?.toLowerCase().startsWith(lang))
  if (voice) utterance.voice = voice
  window.speechSynthesis.speak(utterance)
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
    </svg>
  )
}

function Bubble({ message }) {
  const mine = message.role === 'user'
  return (
    <li className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <p
        dir="auto"
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
          mine ? 'rounded-br-sm bg-accent text-white' : 'rounded-bl-sm border border-line bg-surface'
        } ${message.error ? 'border-occupied/40 text-occupied' : ''}`}
      >
        {message.text}
      </p>
    </li>
  )
}

export default function Chat({
  token, // undefined: the app's signed-in user; a string: a kiosk session; null: anonymous
  channel = 'app',
  defaultLang = 'en',
  greeting,
  suggestions = [],
  onActions,
  large = false,
  className = '',
}) {
  const [messages, setMessages] = useState(() => (greeting ? [{ role: 'assistant', text: greeting }] : []))
  const [conversationId, setConversationId] = useState(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [voiceLang, setVoiceLang] = useState(defaultLang)
  const [listening, setListening] = useState(false)
  const [readAloud, setReadAloud] = useState(channel === 'kiosk')
  const recognition = useRef(null)
  const list = useRef(null)

  useEffect(() => setVoiceLang(defaultLang), [defaultLang])
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])
  // A new person at the kiosk starts a new conversation
  useEffect(() => setConversationId(null), [token])
  useEffect(() => () => recognition.current?.abort(), [])

  const send = useCallback(
    async (text) => {
      const message = text.trim()
      if (!message || busy) return
      setDraft('')
      setMessages((m) => [...m, { role: 'user', text: message }])
      setBusy(true)
      try {
        const res = await api.chat({ message, conversation_id: conversationId, channel }, token)
        setConversationId(res.conversation_id)
        setMessages((m) => [...m, { role: 'assistant', text: res.reply, lang: res.language }])
        if (readAloud) speak(res.reply, res.language)
        if (res.actions?.length) onActions?.(res.actions)
      } catch (err) {
        setMessages((m) => [...m, { role: 'assistant', text: `⚠ ${err.message}`, error: true }])
      } finally {
        setBusy(false)
      }
    },
    [busy, conversationId, channel, token, readAloud, onActions],
  )

  function toggleListening() {
    if (listening) {
      recognition.current?.stop()
      return
    }
    const rec = new Recognition()
    rec.lang = speechCode(voiceLang)
    rec.interimResults = true
    rec.maxAlternatives = 1
    let finalText = ''
    rec.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((r) => r[0].transcript)
        .join('')
      setDraft(transcript)
      if (event.results[event.results.length - 1].isFinal) finalText = transcript
    }
    rec.onerror = (event) => {
      if (event.error !== 'aborted' && event.error !== 'no-speech') {
        setMessages((m) => [...m, { role: 'assistant', text: `⚠ Microphone: ${event.error}`, error: true }])
      }
    }
    rec.onend = () => {
      setListening(false)
      if (finalText) send(finalText) // spoken requests are sent straight away
    }
    window.speechSynthesis?.cancel()
    recognition.current = rec
    setListening(true)
    rec.start()
  }

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      <ul ref={list} className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3" aria-live="polite">
        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}
        {busy && (
          <li className="flex justify-start">
            <span className="rounded-2xl rounded-bl-sm border border-line bg-surface px-3.5 py-2 text-sm text-muted">
              …
            </span>
          </li>
        )}
      </ul>

      {suggestions.length > 0 && (
        <div className="flex gap-2 overflow-x-auto px-3 pb-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              dir="auto"
              onClick={() => send(s)}
              disabled={busy}
              className={`whitespace-nowrap rounded-full border border-line px-3 py-1 hover:bg-ink/5 disabled:opacity-50 ${
                large ? 'text-base' : 'text-xs'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="flex items-center gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        {Recognition && (
          <button
            type="button"
            onClick={toggleListening}
            className={`grid shrink-0 place-items-center rounded-full ${large ? 'size-14' : 'size-10'} ${
              listening ? 'animate-pulse bg-occupied text-white' : 'bg-accent/10 text-accent hover:bg-accent/20'
            }`}
            aria-label={listening ? 'Stop listening' : 'Speak'}
            title={listening ? 'Stop' : 'Speak'}
          >
            <MicIcon />
          </button>
        )}
        <input
          dir="auto"
          className={`${inputClass} ${large ? 'py-3 text-base' : ''}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={listening ? 'Listening…' : 'Message · Message · رسالة'}
          maxLength={1000}
          aria-label="Message"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className={`shrink-0 rounded-lg bg-accent px-4 font-medium text-white hover:opacity-90 disabled:opacity-50 ${
            large ? 'py-3 text-base' : 'py-2 text-sm'
          }`}
        >
          Send
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pb-3 text-xs text-ink-2">
        {Recognition ? (
          <label className="flex items-center gap-1.5">
            Voice
            <select
              className="rounded border border-line bg-surface px-1.5 py-0.5"
              value={voiceLang}
              onChange={(e) => setVoiceLang(e.target.value)}
            >
              {VOICES.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="text-muted">Voice input needs Chrome or Edge</span>
        )}
        {canSpeak && (
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={readAloud} onChange={(e) => setReadAloud(e.target.checked)} />
            Read replies aloud
          </label>
        )}
      </div>
    </div>
  )
}
