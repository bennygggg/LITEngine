import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import AppShell from './AppShell'
import ChatPage from '@/features/chat/ChatPage'
const DemoPage = lazy(() => import('@/features/demo/DemoPage'))

const KitPage = lazy(() => import('@/features/kit/KitPage'))
const CardsGallery = lazy(() => import('@/features/kit/CardsGallery'))

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<ChatPage key="new" />} />
          <Route path="c/:id" element={<ChatPage />} />
          <Route path="demo" element={<Suspense fallback={null}><DemoPage /></Suspense>} />
          {import.meta.env.DEV && <Route path="__cards" element={<Suspense fallback={null}><div className="h-full min-w-0 flex-1 overflow-y-auto"><CardsGallery /></div></Suspense>} />}
          <Route path="__kit" element={<Suspense fallback={null}><div className="h-full min-w-0 flex-1 overflow-y-auto"><KitPage /></div></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
