import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '@/app/App'
import { initTheme } from '@/lib/theme'
import { useCases } from '@/lib/store/cases'
import { useChat } from '@/lib/store/chat'
import { useEngine } from '@/lib/store/engine'
import '@/design/tokens.css'
import '@/design/base.css'

initTheme()
// Load what's on this device, and ping the server (which also wakes a sleeping Space) without blocking first paint.
void useCases.getState().load()
void useChat.getState().load()
void useEngine.getState().check()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
