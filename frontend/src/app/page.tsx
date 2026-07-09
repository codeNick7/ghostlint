'use client'

import { useEffect, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Finding {
  id: string
  category: string
  title: string
  file: string
  line: number
  confidence: number
  risk: 'low' | 'medium' | 'high'
}

interface ScanData {
  id: string
  repo_path: string
  health_score: number
  files_scanned: number
  symbols_found: number
  findings_count: number
  findings: Finding[]
  scanned_at?: string
}

// ── Mock data (used when API is offline) ─────────────────────────────────────

const MOCK_DATA: ScanData = {
  id: 'mock-scan-001',
  repo_path: '/workspace/my-project',
  health_score: 82.5,
  files_scanned: 147,
  symbols_found: 842,
  findings_count: 14,
  scanned_at: new Date().toISOString(),
  findings: [
    { id: '1', category: 'dead_code', title: 'Unused function: `processLegacyData`', file: 'src/utils/legacy.py', line: 45, confidence: 0.92, risk: 'low' },
    { id: '2', category: 'dead_code', title: 'Unused class: `OldAuthHandler`', file: 'src/auth/handlers.py', line: 112, confidence: 0.88, risk: 'medium' },
    { id: '3', category: 'duplicate_logic', title: 'Duplicate logic: `formatDate` and `formatTimestamp`', file: 'src/utils/date.py', line: 23, confidence: 0.85, risk: 'low' },
    { id: '4', category: 'doc_health', title: 'Stale TODO comment in `api/routes.py`', file: 'src/api/routes.py', line: 78, confidence: 0.6, risk: 'low' },
    { id: '5', category: 'dependency_health', title: 'Potentially unused dependency: `pyyaml`', file: 'requirements.txt', line: 1, confidence: 0.7, risk: 'low' },
    { id: '6', category: 'arch_drift', title: 'Layer violation: Data/Models imports from API/Routes', file: 'src/models/user.py', line: 5, confidence: 0.7, risk: 'high' },
    { id: '7', category: 'naming', title: 'Near-duplicate names: `UserSchema` vs `UserModel`', file: 'src/schemas/user.py', line: 15, confidence: 0.7, risk: 'low' },
    { id: '8', category: 'refactor', title: 'Coexisting old/new: `validate` and `validateNew`', file: 'src/services/validation.py', line: 34, confidence: 0.65, risk: 'medium' },
    { id: '9', category: 'test_health', title: 'Orphan test call: `deleteUser` not found', file: 'tests/test_users.py', line: 88, confidence: 0.8, risk: 'medium' },
    { id: '10', category: 'config_health', title: 'Secret key `STRIPE_SECRET` missing from example config', file: '.env', line: 1, confidence: 0.75, risk: 'medium' },
    { id: '11', category: 'dead_code', title: 'Unused function: `_computeHash`', file: 'src/crypto/utils.py', line: 67, confidence: 0.80, risk: 'low' },
    { id: '12', category: 'doc_health', title: 'Stale FIXME comment in `database.py`', file: 'src/db/database.py', line: 210, confidence: 0.6, risk: 'low' },
    { id: '13', category: 'duplicate_logic', title: 'Duplicate logic: `sendEmail` and `dispatchEmail`', file: 'src/notifications/email.py', line: 12, confidence: 0.75, risk: 'low' },
    { id: '14', category: 'arch_drift', title: 'Circular import detected (3 files)', file: 'src/services/auth.py', line: 1, confidence: 0.9, risk: 'high' },
  ],
}

// ── Category config ───────────────────────────────────────────────────────────

const CATEGORY_META: Record<string, { label: string; color: string; bg: string }> = {
  dead_code:          { label: 'Dead Code',       color: 'text-red-400',    bg: 'bg-red-950/50 border-red-800/50' },
  duplicate_logic:    { label: 'Duplicate Logic', color: 'text-orange-400', bg: 'bg-orange-950/50 border-orange-800/50' },
  refactor:           { label: 'Refactor',        color: 'text-yellow-400', bg: 'bg-yellow-950/50 border-yellow-800/50' },
  arch_drift:         { label: 'Arch Drift',      color: 'text-purple-400', bg: 'bg-purple-950/50 border-purple-800/50' },
  config_health:      { label: 'Config Health',   color: 'text-blue-400',   bg: 'bg-blue-950/50 border-blue-800/50' },
  doc_health:         { label: 'Doc Health',      color: 'text-gray-400',   bg: 'bg-gray-800/50 border-gray-700/50' },
  dependency_health:  { label: 'Dependencies',    color: 'text-cyan-400',   bg: 'bg-cyan-950/50 border-cyan-800/50' },
  test_health:        { label: 'Test Health',     color: 'text-green-400',  bg: 'bg-green-950/50 border-green-800/50' },
  naming:             { label: 'Naming',          color: 'text-pink-400',   bg: 'bg-pink-950/50 border-pink-800/50' },
}

const RISK_BADGE: Record<string, string> = {
  low:    'bg-green-900/60 text-green-300 border border-green-700/50',
  medium: 'bg-yellow-900/60 text-yellow-300 border border-yellow-700/50',
  high:   'bg-red-900/60 text-red-300 border border-red-700/50',
}

// ── Score gauge ───────────────────────────────────────────────────────────────

function ScoreGauge({ score }: { score: number }) {
  const clampedScore = Math.min(100, Math.max(0, score))
  const angle = (clampedScore / 100) * 180 // 0-180 degrees
  const color =
    clampedScore >= 85 ? '#22c55e' :
    clampedScore >= 65 ? '#f59e0b' :
    '#ef4444'

  // SVG arc path
  const r = 70
  const cx = 90
  const cy = 90
  const start = { x: cx - r, y: cy }
  const angleRad = ((angle - 180) * Math.PI) / 180
  const end = {
    x: cx + r * Math.cos(angleRad),
    y: cy + r * Math.sin(angleRad),
  }
  const largeArc = angle > 180 ? 1 : 0

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="180" height="100" viewBox="0 0 180 100" className="overflow-visible">
        {/* Background arc */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke="#1f2937"
          strokeWidth="14"
          strokeLinecap="round"
        />
        {/* Score arc */}
        {clampedScore > 0 && (
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`}
            fill="none"
            stroke={color}
            strokeWidth="14"
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.8s ease' }}
          />
        )}
        {/* Score text */}
        <text x={cx} y={cy - 8} textAnchor="middle" fill={color} fontSize="28" fontWeight="700">
          {clampedScore.toFixed(1)}
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill="#6b7280" fontSize="11">
          / 100
        </text>
      </svg>
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
      <div className="text-2xl font-bold text-gray-100">{value}</div>
      <div className="text-sm text-gray-400 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-600 mt-1">{sub}</div>}
    </div>
  )
}

// ── Category breakdown ────────────────────────────────────────────────────────

function CategoryBreakdown({ findings }: { findings: Finding[] }) {
  const counts: Record<string, number> = {}
  for (const f of findings) {
    counts[f.category] = (counts[f.category] || 0) + 1
  }
  const sorted = Object.entries(counts).sort(([, a], [, b]) => b - a)

  if (sorted.length === 0) return null

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
        Findings by Category
      </h3>
      <div className="space-y-3">
        {sorted.map(([cat, count]) => {
          const meta = CATEGORY_META[cat] || { label: cat, color: 'text-gray-400', bg: '' }
          const pct = Math.round((count / findings.length) * 100)
          return (
            <div key={cat}>
              <div className="flex justify-between text-sm mb-1">
                <span className={meta.color}>{meta.label}</span>
                <span className="text-gray-400">{count}</span>
              </div>
              <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: meta.color.replace('text-', '').replace('-400', '') === 'gray' ? '#4b5563' : undefined, backgroundColor: meta.color.includes('red') ? '#f87171' : meta.color.includes('orange') ? '#fb923c' : meta.color.includes('yellow') ? '#fbbf24' : meta.color.includes('green') ? '#4ade80' : meta.color.includes('blue') ? '#60a5fa' : meta.color.includes('purple') ? '#c084fc' : meta.color.includes('cyan') ? '#22d3ee' : meta.color.includes('pink') ? '#f472b6' : '#9ca3af' }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Findings table ────────────────────────────────────────────────────────────

function FindingsTable({
  findings,
  filter,
  onFilterChange,
}: {
  findings: Finding[]
  filter: string
  onFilterChange: (v: string) => void
}) {
  const filtered = filter
    ? findings.filter((f) => f.category === filter)
    : findings

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Findings
          <span className="ml-2 text-gray-600 font-normal normal-case">
            {filtered.length} of {findings.length}
          </span>
        </h3>
        <select
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="text-sm bg-gray-800 border border-gray-700 text-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-500"
        >
          <option value="">All categories</option>
          {Object.entries(CATEGORY_META).map(([key, meta]) => (
            <option key={key} value={key}>{meta.label}</option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="px-5 py-12 text-center text-gray-600">
          No findings match the selected filter.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-5 py-3 text-gray-500 font-medium">Category</th>
                <th className="text-left px-5 py-3 text-gray-500 font-medium">Title</th>
                <th className="text-left px-5 py-3 text-gray-500 font-medium hidden md:table-cell">File</th>
                <th className="text-center px-5 py-3 text-gray-500 font-medium hidden lg:table-cell">Conf.</th>
                <th className="text-center px-5 py-3 text-gray-500 font-medium">Risk</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((f, i) => {
                const meta = CATEGORY_META[f.category] || { label: f.category, color: 'text-gray-400', bg: '' }
                return (
                  <tr
                    key={f.id}
                    className={`border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors ${i % 2 === 0 ? '' : 'bg-gray-900/30'}`}
                  >
                    <td className="px-5 py-3 whitespace-nowrap">
                      <span className={`text-xs font-medium ${meta.color}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-gray-200 line-clamp-1">{f.title}</span>
                    </td>
                    <td className="px-5 py-3 hidden md:table-cell">
                      <code className="text-xs text-gray-500 font-mono">
                        {f.file}:{f.line}
                      </code>
                    </td>
                    <td className="px-5 py-3 text-center hidden lg:table-cell">
                      <span className="text-gray-400 text-xs font-mono">
                        {(f.confidence * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-5 py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${RISK_BADGE[f.risk] || ''}`}>
                        {f.risk}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const USE_MOCK_DATA = true  // set to false when FastAPI backend is running

export default function DashboardPage() {
  const [data, setData] = useState<ScanData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    async function fetchData() {
      if (USE_MOCK_DATA) {
        await new Promise((r) => setTimeout(r, 400)) // simulate loading
        setData(MOCK_DATA)
        setLoading(false)
        return
      }
      try {
        const res = await fetch('/api/scans')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        setData(json)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load scan data')
        // Fallback to mock data on error
        setData(MOCK_DATA)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] gap-3">
        <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-gray-500">Loading scan data…</span>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="text-4xl mb-4">📭</div>
          <p className="text-gray-400">No scan data available.</p>
          <p className="text-gray-600 text-sm mt-2">Run <code className="font-mono text-orange-400">tiramasu scan</code> to get started.</p>
        </div>
      </div>
    )
  }

  const scoreColor =
    data.health_score >= 85 ? 'text-green-400' :
    data.health_score >= 65 ? 'text-yellow-400' :
    'text-red-400'

  const lastScanned = data.scanned_at
    ? new Date(data.scanned_at).toLocaleString()
    : 'Unknown'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Repository Health</h1>
          <p className="text-gray-500 text-sm mt-0.5 font-mono truncate">
            {data.repo_path}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-600">Last scanned</div>
          <div className="text-sm text-gray-400">{lastScanned}</div>
        </div>
      </div>

      {error && (
        <div className="bg-yellow-950/50 border border-yellow-800/50 rounded-lg px-4 py-3 text-sm text-yellow-300">
          API offline — showing mock data. ({error})
        </div>
      )}

      {/* Top row: score + stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Health Score */}
        <div className="md:col-span-1 bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col items-center">
          <div className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Health Score
          </div>
          <ScoreGauge score={data.health_score} />
          <div className={`text-sm font-medium mt-1 ${scoreColor}`}>
            {data.health_score >= 85 ? 'Excellent' :
             data.health_score >= 70 ? 'Good' :
             data.health_score >= 50 ? 'Needs Attention' :
             'Critical'}
          </div>
        </div>

        {/* Stat cards */}
        <div className="md:col-span-3 grid grid-cols-3 gap-4">
          <StatCard label="Files Scanned" value={data.files_scanned.toLocaleString()} />
          <StatCard label="Symbols Found" value={data.symbols_found.toLocaleString()} />
          <StatCard
            label="Findings"
            value={data.findings_count}
            sub={data.findings_count === 0 ? 'Clean!' : `${data.findings.filter(f => f.risk === 'high').length} high risk`}
          />
        </div>
      </div>

      {/* Middle row: category breakdown + quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-1">
          <CategoryBreakdown findings={data.findings} />
        </div>
        <div className="md:col-span-2">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 h-full">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
              Quick Actions
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Scan Current Repo', cmd: 'tiramasu scan .' },
                { label: 'Changed Files Only', cmd: 'tiramasu scan --changed' },
                { label: 'Dead Code Only', cmd: 'tiramasu scan -e dead_code' },
                { label: 'Fast Pre-commit', cmd: 'tiramasu scan --quick' },
                { label: 'JSON Report', cmd: 'tiramasu scan --format json' },
                { label: 'All Engines', cmd: 'tiramasu scan' },
              ].map(({ label, cmd }) => (
                <div
                  key={cmd}
                  className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3 hover:bg-gray-800 cursor-pointer transition-colors"
                  onClick={() => navigator.clipboard?.writeText(cmd).catch(() => {})}
                  title={`Click to copy: ${cmd}`}
                >
                  <div className="text-xs text-gray-400 mb-1">{label}</div>
                  <code className="text-xs text-orange-400 font-mono">{cmd}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Findings table */}
      {data.findings.length > 0 ? (
        <FindingsTable
          findings={data.findings}
          filter={filter}
          onFilterChange={setFilter}
        />
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-12 text-center">
          <div className="text-4xl mb-4">✨</div>
          <p className="text-gray-300 font-medium">No findings — your repository is healthy!</p>
          <p className="text-gray-600 text-sm mt-2">All detectors passed with no issues.</p>
        </div>
      )}
    </div>
  )
}
