import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * GET /api/scans
 * Proxy to FastAPI backend to fetch the most recent scan result.
 */
export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${BACKEND_URL}/scans/latest`, {
      headers: {
        'Content-Type': 'application/json',
      },
      // Don't cache — always fetch fresh data
      cache: 'no-store',
    })

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend returned ${response.status}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: `Failed to connect to backend: ${message}` },
      { status: 502 }
    )
  }
}

/**
 * POST /api/scans
 * Trigger a new scan via the FastAPI backend.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}))
    const response = await fetch(`${BACKEND_URL}/scans`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    })

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend returned ${response.status}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data, { status: 201 })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: `Failed to trigger scan: ${message}` },
      { status: 502 }
    )
  }
}
