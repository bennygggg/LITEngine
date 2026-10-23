import { BrowserRouter, Route, Routes } from 'react-router-dom'
import KitPage from '@/features/kit/KitPage'

/** Phase 0 shell: the design kit is the only route until the chat shell lands in Phase 3. */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<KitPage />} />
      </Routes>
    </BrowserRouter>
  )
}
