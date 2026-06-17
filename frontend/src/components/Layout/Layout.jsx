import { useState } from 'react'
import HUD from '../HUD'
import Sidebar from './Sidebar'

export default function Layout({ children, fullWidth = false }) {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-screen bg-bg">
      <HUD onMenu={() => setMobileOpen(true)} />
      <div className="flex">
        <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
        <main className={`flex-1 min-w-0 ${fullWidth ? '' : 'px-5 py-8 sm:px-8 lg:px-10 lg:py-12'} overflow-x-hidden`}>
          {children}
        </main>
      </div>
    </div>
  )
}
