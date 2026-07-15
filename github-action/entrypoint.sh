#!/bin/bash
set -e

# ── Configuration from environment variables ────────────────────────────────
ENGINES="${ENGINES:-all}"
MIN_CONFIDENCE="${MIN_CONFIDENCE:-0.6}"
FAIL_BELOW="${FAIL_BELOW:-70}"
FORMAT="${FORMAT:-terminal}"
REPO_PATH="${GITHUB_WORKSPACE:-/repo}"
REPORT_PATH="/tmp/ghostlint-report.json"

# ── Build CLI arguments ──────────────────────────────────────────────────────
ARGS=("${REPO_PATH}")
ARGS+=("--min-confidence" "${MIN_CONFIDENCE}")

if [ "${ENGINES}" != "all" ]; then
  # Convert comma-separated list to repeated -e flags
  IFS=',' read -ra ENGINE_LIST <<< "${ENGINES}"
  for engine in "${ENGINE_LIST[@]}"; do
    engine=$(echo "${engine}" | xargs)  # trim whitespace
    ARGS+=("-e" "${engine}")
  done
fi

# ── Run scan ─────────────────────────────────────────────────────────────────
echo "::group::ghostlint Repository Health Scan"
echo "Scanning: ${REPO_PATH}"
echo "Engines: ${ENGINES}"
echo "Min confidence: ${MIN_CONFIDENCE}"
echo "Format: ${FORMAT}"
echo ""

if [ "${FORMAT}" = "json" ]; then
  ghostlint scan "${ARGS[@]}" --format json 2>&1 | tee "${REPORT_PATH}" || SCAN_EXIT=$?
else
  ghostlint scan "${ARGS[@]}" 2>&1 || SCAN_EXIT=$?
fi

echo "::endgroup::"

# ── Parse results and set outputs ────────────────────────────────────────────
if [ "${FORMAT}" = "json" ] && [ -f "${REPORT_PATH}" ]; then
  HEALTH_SCORE=$(python3 -c "import json; d=json.load(open('${REPORT_PATH}')); print(d.get('health_score', 0))" 2>/dev/null || echo "0")
  FINDINGS_COUNT=$(python3 -c "import json; d=json.load(open('${REPORT_PATH}')); print(d.get('findings_count', 0))" 2>/dev/null || echo "0")
else
  # Parse from terminal output or default
  HEALTH_SCORE="0"
  FINDINGS_COUNT="0"
fi

# Write to GitHub Actions output file
if [ -n "${GITHUB_OUTPUT}" ]; then
  echo "health_score=${HEALTH_SCORE}" >> "${GITHUB_OUTPUT}"
  echo "findings_count=${FINDINGS_COUNT}" >> "${GITHUB_OUTPUT}"
  if [ "${FORMAT}" = "json" ] && [ -f "${REPORT_PATH}" ]; then
    echo "report_path=${REPORT_PATH}" >> "${GITHUB_OUTPUT}"
  fi
fi

# ── Emit GitHub Actions summary ───────────────────────────────────────────────
if [ -n "${GITHUB_STEP_SUMMARY}" ]; then
  cat >> "${GITHUB_STEP_SUMMARY}" << EOF
## ghostlint Repository Health

| Metric | Value |
|--------|-------|
| Health Score | ${HEALTH_SCORE}/100 |
| Findings | ${FINDINGS_COUNT} |
| Threshold | ${FAIL_BELOW}/100 |

EOF
fi

# ── Fail check ────────────────────────────────────────────────────────────────
if [ -n "${HEALTH_SCORE}" ] && [ "${HEALTH_SCORE}" != "0" ]; then
  SCORE_INT=$(python3 -c "print(int(float('${HEALTH_SCORE}')))" 2>/dev/null || echo "0")
  THRESHOLD_INT=$(python3 -c "print(int(float('${FAIL_BELOW}')))" 2>/dev/null || echo "70")
  if [ "${SCORE_INT}" -lt "${THRESHOLD_INT}" ]; then
    echo "::error::Health score ${HEALTH_SCORE} is below threshold ${FAIL_BELOW}"
    exit 1
  fi
fi

echo "Health score: ${HEALTH_SCORE}/100"
echo "Findings: ${FINDINGS_COUNT}"
exit 0
