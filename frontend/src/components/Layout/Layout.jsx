import HUD from '../HUD'
import Sidebar from './Sidebar'

export default function Layout({ children, fullWidth = false }) {
  return (
    <div className="min-h-screen bg-bg">
      <HUD />
      <div className="flex">
        <Sidebar />
        <main className={`flex-1 ${fullWidth ? '' : 'px-10 py-12'} overflow-x-hidden`}>
          {children}
        </main>
      </div>
    </div>
  )
}
