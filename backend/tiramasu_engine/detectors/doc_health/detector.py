"""Doc Health detector — stale TODOs, FIXMEs, and misleading comments."""
from __future__ import annotations
import re
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Stale markers. We intentionally do NOT include TEMP (matches "temperature"),
# REMOVEME, or NOCOMMIT — they're not widely-used stale-comment conventions and
# TEMP produces many false positives on the word "temp" inside prose.
_STALE_TAGS = r"TODO|FIXME|HACK|XXX|BUG|WORKAROUND"

# Match the marker only when it appears at (or near) the START of a comment,
# optionally after the comment marker and a little whitespace. This avoids
# matching the words "temp"/"bug"/"todo" buried inside explanatory prose like
#   "# Cache the result (updated forecast-based temp/visibility)"
# or user-facing text like "how do I report a bug?".
_STALE_COMMENT_RE = re.compile(
    rf"#\s*({_STALE_TAGS})\b",
    re.IGNORECASE,
)

_JS_STALE_COMMENT_RE = re.compile(
    rf"(?://|/\*+)\s*({_STALE_TAGS})\b",
    re.IGNORECASE,
)

# Path substrings marking generated/build artifacts or legacy backup directories
# that must not be linted for stale comments. Minified bundles contain user-facing
# text; backup copies are not maintained source and will be removed wholesale.
_SKIP_PATH_PARTS = (
    "/_next/", "/dist/", "/build/", "/out/", "/public/",
    "/.turbo/", "/.svelte-kit/",
    "-backup/", "frontend-backup/",  # legacy backup directories
)

# Maximum number of stale comment findings per file (to avoid noise)
_MAX_PER_FILE = 5


class DocHealthDetector(BaseDetector):
    category = DetectionCategory.DOC_HEALTH

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        for file_info in context.files:
            norm = file_info.relative_path.replace("\\", "/")
            # Skip generated/build artifacts entirely
            if any(part in norm for part in _SKIP_PATH_PARTS):
                continue

            lines = file_info.content.splitlines()
            file_findings = 0

            if file_info.language == "python":
                pattern = _STALE_COMMENT_RE
            else:
                pattern = _JS_STALE_COMMENT_RE

            for line_no, line in enumerate(lines, 1):
                if file_findings >= _MAX_PER_FILE:
                    break
                match = pattern.search(line)
                if match:
                    tag = match.group(1).upper()
                    snippet = line.strip()
                    findings.append(Finding(
                        category=DetectionCategory.DOC_HEALTH,
                        title=f"Stale {tag} comment in `{file_info.relative_path}`",
                        description=(
                            f"A `{tag}` comment at line {line_no} of `{file_info.relative_path}` "
                            f"indicates unfinished work or a known issue. "
                            f"Resolve, track in an issue tracker, or remove if no longer relevant."
                        ),
                        evidence=[Evidence(
                            file_path=file_info.relative_path,
                            line_start=line_no,
                            line_end=line_no,
                            snippet=snippet[:200],
                        )],
                        confidence=0.6,
                        risk=RiskLevel.LOW,
                        effort=EffortLevel.MINUTES,
                        benefit="Keeps the codebase clean and ensures known issues are tracked properly.",
                    ))
                    file_findings += 1

        return findings
