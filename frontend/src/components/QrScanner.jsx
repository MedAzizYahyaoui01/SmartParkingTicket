// Reads the account QR code with the kiosk camera (jsQR decodes the video frames).
import jsQR from 'jsqr'
import { useEffect, useRef, useState } from 'react'

export default function QrScanner({ onCode, onClose }) {
  const video = useRef(null)
  const canvas = useRef(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let stream
    let frame
    let stopped = false

    function scan() {
      if (stopped) return
      const v = video.current
      const c = canvas.current
      if (v && c && v.readyState === v.HAVE_ENOUGH_DATA) {
        c.width = v.videoWidth
        c.height = v.videoHeight
        const ctx = c.getContext('2d', { willReadFrequently: true })
        ctx.drawImage(v, 0, 0, c.width, c.height)
        const image = ctx.getImageData(0, 0, c.width, c.height)
        const found = jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' })
        if (found?.data?.startsWith('SPGATE:')) {
          stopped = true
          onCode(found.data)
          return
        }
      }
      frame = requestAnimationFrame(scan)
    }

    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: 'environment' } })
      .then((s) => {
        stream = s
        if (stopped) return
        video.current.srcObject = s
        video.current.play()
        frame = requestAnimationFrame(scan)
      })
      .catch((err) => setError(err.name === 'NotAllowedError' ? 'Camera access was refused.' : err.message))
    if (!navigator.mediaDevices) setError('No camera available in this browser.')

    return () => {
      stopped = true
      cancelAnimationFrame(frame)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [onCode])

  return (
    <div className="grid gap-3">
      <div className="relative overflow-hidden rounded-xl bg-black">
        <video ref={video} className="aspect-video w-full object-cover" muted playsInline />
        <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden>
          <div className="size-40 rounded-2xl border-4 border-white/80" />
        </div>
      </div>
      <canvas ref={canvas} className="hidden" />
      {error && <p className="text-sm text-occupied">{error}</p>}
      <button type="button" onClick={onClose} className="text-sm text-accent hover:underline">
        Cancel
      </button>
    </div>
  )
}
