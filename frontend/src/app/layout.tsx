import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Tiramasu — Repository Health Intelligence',
  description: 'Detect dead code, duplicates, architectural drift, and more.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">
        <nav className="border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-500 to-amber-400 flex items-center justify-center text-sm font-bold text-white">
                T
              </div>
              <span className="font-semibold text-gray-100 tracking-tight">tiramasu</span>
            </div>
            <span className="text-gray-600 text-sm hidden sm:block">|</span>
            <span className="text-gray-500 text-sm hidden sm:block">Repository Health Intelligence</span>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
      </body>
    </html>
  )
}
